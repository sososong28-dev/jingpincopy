import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function argValue(name, fallback = null) {
  const idx = process.argv.indexOf(name);
  if (idx >= 0 && idx + 1 < process.argv.length) return process.argv[idx + 1];
  return fallback;
}

function hasArg(name) {
  return process.argv.includes(name);
}

function today() {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const values = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function nowText() {
  const now = new Date();
  const date = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(now);
  return `${date} ${time}`;
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function safeName(text, limit = 80) {
  return String(text || "")
    .replace(/[<>:"/\\|?*\x00-\x1F]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit)
    .trim() || "untitled";
}

function queryList(config, onlyQueries) {
  if (onlyQueries) {
    return onlyQueries
      .split(/\s*[,，]\s*/)
      .map((q) => q.trim())
      .filter(Boolean)
      .map((query) => ({ group: "manual", priority: "P0", query }));
  }
  const result = [];
  for (const group of config.query_groups || []) {
    for (const query of group.queries || []) {
      result.push({ group: group.group || "default", priority: group.priority || "", query });
    }
  }
  return result;
}

async function launchContext(profileDir, headless, channel) {
  const options = {
    headless,
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
  };
  for (const candidate of [channel, "msedge", "chrome", undefined]) {
    try {
      const merged = candidate ? { ...options, channel: candidate } : options;
      return await chromium.launchPersistentContext(profileDir, merged);
    } catch (err) {
      if (!candidate) throw err;
    }
  }
}

async function scrollPage(page, rounds, waitMs) {
  for (let i = 0; i < rounds; i += 1) {
    await page.mouse.wheel(0, 1200);
    await page.waitForTimeout(waitMs);
  }
}

async function extractCards(page, platform, itemUrlPatterns, limit) {
  return page.evaluate(
    ({ platform, itemUrlPatterns, limit }) => {
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 8 && rect.height > 8 && style.visibility !== "hidden" && style.display !== "none";
      };
      const normalize = (text) => String(text || "").replace(/\s+/g, " ").trim();
      const abs = (href) => {
        try {
          return new URL(href, location.href).href.split("#")[0];
        } catch {
          return "";
        }
      };
      const metricPattern = /(\d+(?:\.\d+)?\s*[万千wWkK]?)(赞|点赞|收藏|评论|分享|观看|播放)/g;
      const rows = [];
      const seen = new Set();
      const anchors = Array.from(document.querySelectorAll("a[href]"));
      for (const a of anchors) {
        if (!visible(a)) continue;
        const url = abs(a.getAttribute("href"));
        if (!url || seen.has(url)) continue;
        if (itemUrlPatterns?.length && !itemUrlPatterns.some((p) => url.includes(p))) continue;
        const card = a.closest("article, section, li, div") || a;
        const rawText = normalize(card.innerText || a.innerText || a.getAttribute("title") || a.getAttribute("aria-label"));
        const title = normalize(a.innerText || a.getAttribute("title") || rawText.split(" ").slice(0, 24).join(" "));
        if (!title || title.length < 4) continue;
        seen.add(url);
        const metrics = Array.from(rawText.matchAll(metricPattern)).map((m) => m[0]).join(" ");
        rows.push({
          platform,
          title: title.slice(0, 180),
          url,
          snippet: rawText.slice(0, 520),
          metrics_text: metrics,
        });
        if (rows.length >= limit) break;
      }
      return rows;
    },
    { platform, itemUrlPatterns, limit },
  );
}

async function detectPageStatus(page) {
  const text = await page
    .locator("body")
    .innerText({ timeout: 3000 })
    .catch(() => "");
  if (/登录后|扫码登录|手机号登录|验证码登录|登录即可|请登录/.test(text)) return "login_required";
  if (/验证码|安全验证|拖动滑块|环境异常/.test(text)) return "verification_required";
  return "ok";
}

async function loginOnly(context, platforms, waitSeconds) {
  for (const [key, platform] of Object.entries(platforms)) {
    const page = await context.newPage();
    await page.goto(platform.home_url, { waitUntil: "domcontentloaded", timeout: 60000 });
    console.log(`[login] opened ${key}: ${platform.home_url}`);
  }
  console.log(`[login] 请在打开的浏览器里完成小红书/抖音登录或授权。${waitSeconds} 秒后脚本会自动退出。`);
  await new Promise((resolve) => setTimeout(resolve, waitSeconds * 1000));
}

async function main() {
  const configPath = path.resolve(ROOT, argValue("--config", "configs/social_browser_config.json"));
  const config = readJson(configPath);
  const settings = config.settings || {};
  const dateLabel = argValue("--date", today());
  const onlyPlatforms = (argValue("--platforms", "") || "")
    .split(/\s*,\s*/)
    .map((x) => x.trim())
    .filter(Boolean);
  const platforms = Object.fromEntries(
    Object.entries(config.platforms || {}).filter(([key]) => onlyPlatforms.length === 0 || onlyPlatforms.includes(key)),
  );
  if (Object.keys(platforms).length === 0) throw new Error("No platforms selected.");

  const profileDir = path.resolve(ROOT, argValue("--profile-dir", settings.profile_dir || "data/browser-profile/social-intel"));
  const outputDir = path.resolve(ROOT, argValue("--output-dir", settings.output_dir || "data/social"));
  const screenshotDir = path.resolve(ROOT, argValue("--screenshot-dir", settings.screenshot_dir || "outputs/social_screenshots"));
  ensureDir(profileDir);
  ensureDir(outputDir);
  ensureDir(screenshotDir);

  const headless = hasArg("--headless") ? true : Boolean(settings.headless);
  const limitPerQuery = Number(argValue("--limit-per-query", settings.limit_per_query || 8));
  const scrollRounds = Number(argValue("--scroll-rounds", settings.scroll_rounds || 4));
  const pageWaitMs = Number(argValue("--page-wait-ms", settings.page_wait_ms || 4500));
  const loginWaitSeconds = Number(argValue("--login-wait-seconds", settings.login_wait_seconds || 240));
  const outputPath = path.resolve(outputDir, argValue("--output", `${dateLabel}_social_raw.jsonl`));
  const queries = queryList(config, argValue("--queries"));

  const context = await launchContext(profileDir, headless, settings.browser_channel || "msedge");
  try {
    if (hasArg("--login-only")) {
      await loginOnly(context, platforms, loginWaitSeconds);
      return;
    }

    const out = fs.createWriteStream(outputPath, { flags: "w", encoding: "utf8" });
    const allSeen = new Set();
    let written = 0;
    for (const [platformKey, platform] of Object.entries(platforms)) {
      for (const q of queries) {
        const encoded = encodeURIComponent(q.query);
        const url = platform.search_url.replace("{query}", encoded);
        const page = await context.newPage();
        const collectedAt = nowText();
        let status = "ok";
        try {
          await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
          await page.waitForTimeout(pageWaitMs);
          await scrollPage(page, scrollRounds, Math.max(900, Math.floor(pageWaitMs / 2)));
          const screenshotPath = path.join(
            screenshotDir,
            `${dateLabel}_${platformKey}_${safeName(q.query, 36)}.png`,
          );
          await page.screenshot({ path: screenshotPath, fullPage: false }).catch(() => {});
          const rows = await extractCards(page, platform.name || platformKey, platform.item_url_patterns || [], limitPerQuery);
          status = rows.length > 0 ? "ok" : await detectPageStatus(page);
          for (const [idx, row] of rows.entries()) {
            const key = `${platformKey}|${row.url}|${row.title}`;
            if (allSeen.has(key)) continue;
            allSeen.add(key);
            out.write(
              JSON.stringify(
                {
                  date: dateLabel,
                  collected_at: collectedAt,
                  platform_key: platformKey,
                  platform: platform.name || platformKey,
                  query: q.query,
                  query_group: q.group,
                  priority: q.priority,
                  rank: idx + 1,
                  search_url: url,
                  screenshot_path: screenshotPath,
                  status,
                  ...row,
                },
                null,
                0,
              ) + "\n",
            );
            written += 1;
          }
          if (rows.length === 0) {
            out.write(
              JSON.stringify({
                date: dateLabel,
                collected_at: collectedAt,
                platform_key: platformKey,
                platform: platform.name || platformKey,
                query: q.query,
                query_group: q.group,
                priority: q.priority,
                rank: 0,
                search_url: url,
                screenshot_path: screenshotPath,
                status,
                title: "",
                url: "",
                snippet: "",
              }) + "\n",
            );
          }
          console.log(`[collect] ${platformKey} | ${q.query} | ${rows.length} rows`);
        } catch (err) {
          status = `error: ${err.message}`;
          out.write(
            JSON.stringify({
              date: dateLabel,
              collected_at: nowText(),
              platform_key: platformKey,
              platform: platform.name || platformKey,
              query: q.query,
              query_group: q.group,
              priority: q.priority,
              search_url: url,
              status,
              title: "",
              url: "",
              snippet: "",
            }) + "\n",
          );
          console.warn(`[warn] ${platformKey} | ${q.query} | ${status}`);
        } finally {
          await page.close().catch(() => {});
        }
      }
    }
    out.end();
    console.log(`output: ${outputPath}`);
    console.log(`items: ${written}`);
  } finally {
    await context.close();
  }
}

main().catch((err) => {
  console.error(err.stack || err.message || String(err));
  process.exit(1);
});
