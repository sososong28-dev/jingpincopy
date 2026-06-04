from __future__ import annotations

import argparse
import csv
import email.utils
import hashlib
import html
import json
import math
import re
import secrets
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "collector_config.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs"
DEFAULT_RAW_DIR = ROOT / "data" / "raw"
DEFAULT_SEEN_PATH = ROOT / "data" / "seen_items.json"
LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

EMAIL_TEMPLATE_VERSION = "daily-collector-v2"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
DEFAULT_REQUEST_TIMEOUT = 18


@dataclass
class SearchResult:
    item_key: str
    title: str
    url: str
    snippet: str
    news_published_at: str
    collected_at: str
    industry: str
    brand: str
    category: str
    platform: str
    platform_layers: str
    info_type: str
    industry_relevance: str
    relevance_reason: str
    summary: str
    content_summary: str
    selection_reason: str
    score: int
    level: str
    query: str
    source_mode: str
    source_name: str
    tags: str = ""
    is_report_item: int = 1
    content_theme: str = "情报"


def _to_list(value: Any, fallback: list[Any] | None = None) -> list[Any]:
    if isinstance(value, list):
        return value
    return [] if fallback is None else fallback


def _norm(s: Any) -> str:
    return re.sub(r"\s+", "", str(s or "").strip().lower())


def _now_local() -> datetime:
    return datetime.now(LOCAL_TZ).replace(microsecond=0)


def _fmt(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _to_local_from_email_date(raw: str) -> datetime | None:
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except Exception:
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def _read_text(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    settings = cfg.setdefault("settings", {})
    settings.setdefault("max_daily_items", 30)
    settings.setdefault("min_daily_new_items", 10)
    settings.setdefault("min_report_score", 45)
    settings.setdefault("required_report_industry", "计生/两性健康")
    settings.setdefault("required_report_min_share", 0.6)
    settings.setdefault("max_news_age_months", 6)
    settings.setdefault("max_pharma_news_age_days", 180)
    settings.setdefault("platform_search_enabled", True)
    settings.setdefault("report_duplicate_window_days", 180)
    settings.setdefault("gdelt_enabled", False)
    settings.setdefault("gdelt_max_queries_per_run", 0)
    settings.setdefault("source_pack_enabled", True)
    settings.setdefault("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT)
    settings.setdefault("request_delay_seconds", 0.08)
    settings.setdefault("database_dir", r"D:\kin")
    settings.setdefault("database_file", "competitor_intel.db")
    settings.setdefault("obsidian_sync_enabled", True)
    settings.setdefault("obsidian_vault_dir", r"D:\kin")
    settings.setdefault("obsidian_folder", "竞品情报")
    settings.setdefault("email_enabled", False)
    return cfg


def database_path_from_config(config: dict[str, Any]) -> Path:
    db_dir = config.get("settings", {}).get("database_dir", r"D:\kin")
    db_file = config.get("settings", {}).get("database_file", "competitor_intel.db")
    return Path(db_dir) / db_file


def obsidian_root_from_config(config: dict[str, Any]) -> Path:
    settings = config.get("settings", {})
    return Path(settings.get("obsidian_vault_dir", r"D:\kin")) / settings.get("obsidian_folder", "竞品情报")


def ensure_database(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collector_runs (
            run_id TEXT PRIMARY KEY,
            report_date TEXT,
            source_mode TEXT,
            started_at TEXT,
            synced_at TEXT,
            raw_new_count INTEGER,
            report_count INTEGER,
            skipped_seen_count INTEGER,
            marked_seen_count INTEGER,
            max_items INTEGER,
            markdown_path TEXT,
            csv_path TEXT,
            xlsx_path TEXT,
            raw_path TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence_items (
            item_key TEXT PRIMARY KEY,
            first_collected_at TEXT,
            last_seen_at TEXT,
            latest_report_date TEXT,
            industry TEXT,
            brand TEXT,
            platform TEXT,
            title TEXT,
            url TEXT,
            info_type TEXT,
            industry_relevance TEXT,
            relevance_reason TEXT,
            news_published_at TEXT,
            collected_at TEXT,
            summary TEXT,
            selection_reason TEXT,
            level TEXT,
            score INTEGER,
            tags TEXT,
            query TEXT,
            is_report_item INTEGER,
            raw_json TEXT,
            content_summary TEXT,
            source_mode TEXT,
            source_name TEXT,
            snippet TEXT,
            category TEXT,
            content_theme TEXT,
            platform_layers TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_items (
            report_date TEXT,
            item_key TEXT,
            rank INTEGER,
            synced_at TEXT,
            PRIMARY KEY(report_date, item_key)
        )
        """
    )
    conn.commit()


def search_result_from_database_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "item_key": row["item_key"],
        "title": row["title"],
        "url": row["url"],
        "industry": row["industry"],
        "brand": row["brand"],
        "category": row["category"],
        "platform": row["platform"],
        "content_theme": row["content_theme"],
        "summary": row["summary"],
        "selection_reason": row["selection_reason"],
        "content_summary": row["content_summary"],
        "news_published_at": row["news_published_at"],
        "collected_at": row["collected_at"],
        "score": row["score"],
        "level": row["level"],
        "tags": row["tags"],
        "query": row["query"],
        "source_mode": row["source_mode"],
        "source_name": row["source_name"],
        "snippet": row["snippet"],
    }


def _safe_request(url: str, timeout: int) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
        return raw.decode("utf-8", errors="ignore")


def _parse_feed(xml_text: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "atom": "http://www.w3.org/2005/Atom",
    }
    items = []
    for item in root.findall(".//item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        desc = html.unescape((item.findtext("description") or "").strip())
        pub = (item.findtext("pubDate") or item.findtext("dc:date", "", ns) or "").strip()
        if not link and title:
            # fallback for guid-like feeds
            guid = (item.findtext("guid") or "").strip()
            if guid.startswith("http"):
                link = guid
        if not title or not link:
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "description": desc,
                "published": pub,
            }
        )
    return items


def search_google_news(query: str, timeout: int = DEFAULT_REQUEST_TIMEOUT) -> list[dict[str, str]]:
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans-CN"
    )
    return _parse_feed(_safe_request(url, timeout))


def search_bing_web(query: str, timeout: int = DEFAULT_REQUEST_TIMEOUT) -> list[dict[str, str]]:
    url = "https://www.bing.com/search?setlang=zh-CN&format=rss&q=" + quote_plus(query)
    return _parse_feed(_safe_request(url, timeout))


def _item_domain(url: str) -> str:
    try:
        return re.sub(r"^www\\.", "", re.sub(r"^https?://", "", url).split("/")[0].split("?")[0]).lower()
    except Exception:
        return ""


def _build_platform_layers(platforms: list[dict[str, Any]], url: str) -> tuple[str, str]:
    domain = _item_domain(url)
    for platform in platforms:
        domains = set(_to_list(platform.get("domains", [])))
        if domain and domain in domains:
            return platform.get("name", "未知来源"), domain
    return "网络抓取", domain


def _select_brand_and_category(
    text: str,
    brands: list[dict[str, Any]],
    industry_name: str | None = None,
    query: str | None = None,
) -> tuple[str, str, str]:
    sample = f"{text} {query or ''}".lower()
    for b in brands:
        names = [b.get("name", "")]
        names.extend(_to_list(b.get("aliases", [])))
        for n in names:
            if not n:
                continue
            if n.lower() in sample:
                return b.get("industry", industry_name or ""), b.get("subcategory", ""), b.get("name", "")
    return industry_name or "未分类", "", ""


def _resolve_info_theme(text: str, rules: list[dict[str, Any]]) -> tuple[str, int]:
    lower = text.lower()
    chosen = ("资讯", 45)
    for rule in rules:
        if any((k.lower() in lower for k in _to_list(rule.get("keywords", [])))):
            bonus = int(rule.get("score_bonus", 0))
            theme = str(rule.get("type", "资讯"))
            if bonus > chosen[1]:
                chosen = (theme, bonus)
    return chosen


def _score_result(
    text: str,
    industry: str,
    required_industry: str,
    theme_score: int,
) -> int:
    base = 30 + (len(text) % 10)
    if required_industry and industry == required_industry:
        base += 15
    return min(100, base + theme_score)


def _collect_queries(config: dict[str, Any], source_mode: str, max_items: int) -> list[dict[str, Any]]:
    settings = config.get("settings", {})
    max_queries = settings.get("max_queries_per_run", 96)
    platform_queries = _to_list(config.get("platform_search_queries", []))
    source_pack = _to_list(config.get("source_pack_queries", []))
    supplemental = _to_list(config.get("supplemental_queries", []))
    topic_queries = _to_list(config.get("topic_queries", []))
    brands = _to_list(config.get("brands", []))

    by_industry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for b in brands:
        by_industry[b.get("industry", "")]
        by_industry[b.get("industry", "")].append(b)

    # source pack/base queries (high priority sources)
    queries = []
    for item in source_pack[:20]:
        q = str(item.get("query", "")).strip()
        if not q:
            continue
        queries.append({"query": q, "source": item.get("industry", ""), "source_mode": source_mode, "label": "source_pack"})

    # topic broad queries
    for item in topic_queries:
        q = str(item.get("query", "")).strip()
        if not q:
            continue
        queries.append({"query": q, "source": item.get("industry", ""), "source_mode": source_mode, "label": "topic"})

    # platform-level search templates
    if config.get("settings", {}).get("platform_search_enabled", True):
        for item in platform_queries:
            if len(queries) >= max_queries:
                break
            query_template = str(item.get("query_template", ""))
            if not query_template:
                continue
            allowed = _to_list(item.get("industries", config.get("industries", [])))
            intents = _to_list(item.get("intents"))
            take_high = settings.get("platform_search_intents_per_high_brand", 2)
            take_other = settings.get("platform_search_intents_per_other_brand", 1)
            if not intents:
                intents = _to_list(config.get("query_intents", {}).get(allowed[0] if allowed else "", []))
            for ind in allowed:
                candidate_brands = by_industry.get(ind, [])
                if not candidate_brands:
                    continue
                for brand in candidate_brands[:2]:
                    brand_name = brand.get("name", "")
                    category = brand.get("subcategory", "")
                    limit = take_high if str(brand.get("priority", "other")) == "high" else take_other
                    for intent in intents[:limit]:
                        q = query_template.format(
                            brand=brand_name,
                            category=category,
                            category_full=brand.get("subcategory_full", category),
                            intent=intent,
                            industry=ind,
                        )
                        queries.append(
                            {
                                "query": q,
                                "source": ind,
                                "source_mode": source_mode,
                                "label": "platform_template",
                            }
                        )
                        if len(queries) >= max_queries:
                            break
                    if len(queries) >= max_queries:
                        break
                if len(queries) >= max_queries:
                    break

    # supplemental expansion with cap
    max_supp = max_queries - len(queries)
    for item in supplemental[:max_supp]:
        q = str(item.get("query", "")).strip()
        if not q:
            continue
        queries.append({"query": q, "source": item.get("industry", ""), "source_mode": source_mode, "label": "supplemental"})

    # keep most recent + ensure daily quota can run against enough text
    if len(queries) > max_queries:
        queries = queries[:max_queries]
    return queries


def _fetch_from_query(query: str, source_mode: str, timeout: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    if source_mode in {"both", "news", "bing"}:
        # both/any: pull both Bing and Google
        try:
            results.extend(search_google_news(query, timeout=timeout))
        except Exception:
            pass
        if source_mode != "news":
            try:
                results.extend(search_bing_web(query, timeout=timeout))
            except Exception:
                pass
    elif source_mode == "news":
        try:
            results.extend(search_google_news(query, timeout=timeout))
        except Exception:
            pass
    else:  # fallback for unknown mode
        try:
            results.extend(search_bing_web(query, timeout=timeout))
        except Exception:
            pass
    return results


def _build_record(
    raw_item: dict[str, str],
    cfg: dict[str, Any],
    brands: list[dict[str, Any]],
    query: str,
    source_mode: str,
    source_name: str,
    query_industry: str,
    rules: list[dict[str, Any]],
) -> SearchResult:
    title = raw_item.get("title", "").strip()
    link = raw_item.get("link", "").strip()
    snippet = html.unescape((raw_item.get("description", "") or "").strip())
    pub = raw_item.get("published", "")
    published = _to_local_from_email_date(pub) or _now_local()
    collected = _now_local()
    text = f"{title} {snippet}".strip()
    industry, category, brand = _select_brand_and_category(text, brands, query_industry, query)
    if not industry:
        industry = query_industry or cfg.get("industries", [""])[0]
    platform, host = _build_platform_layers(cfg.get("platforms", []), link)
    content_theme, bonus = _resolve_info_theme(text, rules)
    required_industry = cfg.get("settings", {}).get("required_report_industry", "计生/两性健康")
    score = _score_result(text, industry, required_industry, bonus)
    level = "high" if score >= 70 else "medium"
    selection = f"命中目标行业/品牌关键词：{industry if industry else query_industry}，匹配主题 {content_theme}，可用于竞品观察。"
    summary = f"{platform} 来源：{title}"
    content_summary = (
        f"原标题：{title}；新闻发布时间：{_fmt(published)}；发布平台：{platform}；行业：{industry}；品类：{category or '未分类'}；"
        f"匹配理由：{selection}"
    )
    key = hashlib.sha1(f"{link}|{title}".encode("utf-8")).hexdigest()
    return SearchResult(
        item_key=key,
        title=title,
        url=link,
        snippet=snippet,
        news_published_at=_fmt(published),
        collected_at=_fmt(collected),
        industry=industry,
        brand=brand,
        category=category,
        platform=platform,
        platform_layers=host,
        info_type=content_theme,
        industry_relevance=industry,
        relevance_reason=selection,
        summary=summary,
        content_summary=content_summary,
        selection_reason=selection,
        score=score,
        level=level,
        query=query,
        source_mode=source_mode,
        source_name=source_name,
    )


def _to_report_rows(conn: sqlite3.Connection, report_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT i.*
        FROM report_items r
        JOIN intelligence_items i ON i.item_key = r.item_key
        WHERE r.report_date = ?
        ORDER BY r.rank
        """,
        (report_date,),
    ).fetchall()


def _write_markdown(path: Path, date_label: str, rows: list[sqlite3.Row], config: dict[str, Any]) -> None:
    settings = config.get("settings", {})
    lines = [
        f"# 竞品情报收集 - {date_label}",
        "",
        f"- DB: `{database_path_from_config(config)}`",
        f"- 记录数: {len(rows)}",
        "",
        "|序号|行业|品牌|品类|来源|标题|原标题发布时间|采集时间|主题|摘要|链接|",
        "|---:|---|---|---|---|---|---|---|---|---|",
    ]
    for idx, row in enumerate(rows, start=1):
        link = row["url"] or ""
        title = (row["title"] or "").replace("|", "｜")
        summary = (row["summary"] or "").replace("|", "｜")
        lines.append(
            "| {idx} | {industry} | {brand} | {category} | {platform} | {title} | {published} | {collected} | {theme} | {summary} | {link} |".format(
                idx=idx,
                industry=(row["industry"] or "-"),
                brand=(row["brand"] or "-"),
                category=(row["category"] or "-"),
                platform=(row["platform"] or "-"),
                title=title,
                published=(row["news_published_at"] or "-"),
                collected=(row["collected_at"] or "-"),
                theme=(row["content_theme"] or "-"),
                summary=summary,
                link=f"[打开]({link})" if link else "-",
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def _write_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "report_date",
        "rank",
        "industry",
        "brand",
        "category",
        "platform",
        "platform_layers",
        "title",
        "url",
        "news_published_at",
        "collected_at",
        "content_theme",
        "score",
        "summary",
        "selection_reason",
        "content_summary",
        "query",
        "source_mode",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (row[k] if k in row.keys() else "") for k in headers})


def send_report_email(
    config: dict[str, Any],
    date_label: str,
    items: list[dict[str, Any]],
    max_items: int,
    db_path: Path,
    obsidian_root: Path,
    md_path: Path,
    csv_path: Path,
    xlsx_path: Path | None = None,
    force_send: bool = False,
) -> dict[str, Any]:
    # 当前任务场景主要使用本地归档与数据库，暂不实际发送邮件
    settings = config.get("settings", {})
    if not settings.get("email_enabled", False):
        md_path.parent.mkdir(parents=True, exist_ok=True)
        _write_rows_to_markdown_simple(md_path, date_label, items, config, max_items=max_items)
        if csv_path:
            _write_rows_to_csv_simple(csv_path, date_label, items)
        if xlsx_path:
            xlsx_path.write_text("XLSX output disabled in simplified runner.\n", encoding="utf-8")
        obsidian_root.mkdir(parents=True, exist_ok=True)
        ob_path = obsidian_root / f"{date_label}.md"
        _write_obsidian_note(ob_path, date_label, items, db_path)
        return {"status": "disabled", "message": "邮件发送已禁用，已同步本地 Markdown/CSV/Obsidian", "draft_path": str(md_path), "preview_path": str(csv_path)}
    # fallback if enabled later
    return {"status": "skipped", "message": "邮件功能未启用"}


def _write_rows_to_markdown_simple(path: Path, date_label: str, items: list[dict[str, Any]], config: dict[str, Any], max_items: int) -> None:
    # internal helper for send_report_email/obsolescence
    # convert dict items to sqlite row-like object
    class R(dict):
        __getitem__ = dict.get

    rows = [R({**item, "report_date": date_label}) for item in items[:max_items]]
    _write_markdown(path, date_label, rows, config)


def _write_rows_to_csv_simple(path: Path, date_label: str, items: list[dict[str, Any]]) -> None:
    headers = [
        "rank",
        "industry",
        "brand",
        "category",
        "platform",
        "title",
        "url",
        "news_published_at",
        "collected_at",
        "content_theme",
        "summary",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["report_date"] + headers)
        writer.writeheader()
        for idx, item in enumerate(items, start=1):
            writer.writerow(
                {
                    "report_date": date_label,
                    "rank": idx,
                    "industry": item.get("industry", ""),
                    "brand": item.get("brand", ""),
                    "category": item.get("category", ""),
                    "platform": item.get("platform", ""),
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "news_published_at": item.get("news_published_at", ""),
                    "collected_at": item.get("collected_at", ""),
                    "content_theme": item.get("content_theme", ""),
                    "summary": item.get("summary", ""),
                }
            )


def _write_obsidian_note(path: Path, date_label: str, items: list[dict[str, Any]], db_path: Path) -> None:
    lines = [f"# 竞品情报归档 {date_label}", f"- 来源库: `{db_path}`", ""]
    for idx, it in enumerate(items, start=1):
        lines.append(f"## {idx}. {it.get('industry','')} / {it.get('brand','')} / {it.get('category','')}")
        lines.append(f"- 标题：{it.get('title','')}")
        lines.append(f"- 链接：{it.get('url','')}")
        lines.append(f"- 发布时间：{it.get('news_published_at','')}")
        lines.append(f"- 采集时间：{it.get('collected_at','')}")
        lines.append(f"- 摘要：{it.get('summary','')}")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")


def _enforce_industry_share(
    report_items: list[SearchResult],
    required_industry: str,
    min_share: float,
    max_items: int,
) -> list[SearchResult]:
    if max_items <= 0 or not report_items:
        return report_items
    by_ind = [x for x in report_items if x.industry == required_industry]
    by_other = [x for x in report_items if x.industry != required_industry]
    if not by_ind:
        return []
    if min_share <= 0:
        return report_items[:max_items]

    by_other = sorted(by_other, key=lambda x: (x.score, x.news_published_at), reverse=True)
    for total in range(max_items, 0, -1):
        need = int(math.floor(total * float(min_share)) + 1)
        if len(by_ind) >= need:
            selected = by_ind[:need]
            selected.extend(by_other[: max(0, total - need)])
            return selected[:total]
    return []


def _filter_old_items(rows: list[SearchResult], config: dict[str, Any]) -> list[SearchResult]:
    now = _now_local()
    max_months = float(config["settings"].get("max_news_age_months", 6))
    max_pharma_days = int(config["settings"].get("max_pharma_news_age_days", 180))
    max_age = timedelta(days=int(max_months * 31))
    result = []
    for item in rows:
        try:
            pub_dt = datetime.strptime(item.news_published_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
        except Exception:
            pub_dt = _now_local()
        age = now - pub_dt
        if item.industry == "医药":
            if age.days > max_pharma_days:
                continue
        if age > max_age:
            continue
        result.append(item)
    return result


def _gather_recent_seen_keys(
    conn: sqlite3.Connection,
    date_label: str,
    settings: dict[str, Any],
    persistent_seen: set[str],
) -> set[str]:
    window_days = int(settings.get("report_duplicate_window_days", 1))
    if window_days <= 0:
        return set()

    try:
        today = datetime.strptime(date_label, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
    except Exception:
        today = _now_local()

    since = (today - timedelta(days=max(0, window_days - 1))).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT item_key FROM report_items WHERE report_date >= ? AND report_date < ?",
        (since, date_label),
    ).fetchall()
    windowed = {r[0] for r in rows}
    return windowed


def run(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    settings = config.get("settings", {})
    db_path = database_path_from_config(config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_database(conn)

    raw_dir = Path(settings.get("raw_dir", DEFAULT_RAW_DIR))
    raw_dir.mkdir(parents=True, exist_ok=True)
    date_label = args.date or _now_local().strftime("%Y-%m-%d")
    run_id = secrets.token_hex(8)
    started_at = _now_local()
    source_mode = args.source_mode
    max_items = int(args.max_items or settings.get("max_daily_items", 30))

    rules = _to_list(config.get("info_type_rules", []))
    query_intents = config.get("query_intents", {})
    brands = _to_list(config.get("brands", []))

    # existing seen in db and prior days to avoid repeated alerts
    seen = set(_to_list(_read_text(DEFAULT_SEEN_PATH, [])))
    seen = _gather_recent_seen_keys(conn, date_label, settings, seen)

    query_items = _collect_queries(config, source_mode, max_items)

    raw_items: list[SearchResult] = []
    for item in query_items:
        q = item.get("query", "")
        if not q:
            continue
        try:
            fetched = _fetch_from_query(q, source_mode, settings.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT))
        except Exception:
            continue
        for entry in fetched[: settings.get("results_per_query", 4)]:
            src = item.get("label", "query")
            rec = _build_record(
                entry,
                config,
                brands,
                query=q,
                source_mode=source_mode,
                source_name=src,
                query_industry=str(item.get("source", "") or ""),
                rules=rules,
            )
            raw_items.append(rec)

    # persist raw
    raw_path = raw_dir / f"{date_label}_raw_items.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("w", encoding="utf-8") as f:
        for it in raw_items:
            f.write(json.dumps(it.__dict__, ensure_ascii=False) + "\n")

    # dedupe
    # stable dedupe same item
    dedup: dict[str, SearchResult] = {}
    for it in raw_items:
        dedup[it.item_key] = it
    unique_raw = list(dedup.values())

    # de-dup against seen/db
    filtered: list[SearchResult] = []
    skipped_seen = 0
    for it in unique_raw:
        if it.item_key in seen:
            skipped_seen += 1
            continue
        if not it.url:
            continue
        filtered.append(it)

    # content/time filtering + score filter
    min_score = settings.get("min_report_score", 45)
    filtered = [it for it in filtered if it.score >= min_score]
    filtered = _filter_old_items(filtered, config)

    # sorting
    filtered.sort(key=lambda x: (x.score, x.news_published_at), reverse=True)
    required_industry = settings.get("required_report_industry", "计生/两性健康")
    required_share = float(settings.get("required_report_min_share", 0.6))
    selected = _enforce_industry_share(filtered, required_industry, required_share, max_items)

    min_new = int(settings.get("min_daily_new_items", 10))
    if len(selected) < min_new and filtered:
        selected = _enforce_industry_share(filtered, required_industry, required_share, max_items)

    # write outputs
    report_dicts: list[dict[str, Any]] = [it.__dict__ for it in selected]
    markdown_path = output_dir / f"{date_label}_competitor_brief.md"
    csv_report_path = output_dir / f"{date_label}_competitor_brief.csv"
    xlsx_report_path = output_dir / f"{date_label}_competitor_brief.xlsx"

    # build db report rows
    if selected:
        conn.execute("DELETE FROM report_items WHERE report_date = ?", (date_label,))
        for rank, it in enumerate(selected, start=1):
            first = conn.execute("SELECT 1 FROM intelligence_items WHERE item_key = ?", (it.item_key,)).fetchone()
            raw_json = json.dumps(it.__dict__, ensure_ascii=False)
            if first:
                conn.execute(
                    """
                    UPDATE intelligence_items SET
                        last_seen_at = ?, latest_report_date = ?, score = ?, brand = ?, industry = ?, platform = ?,
                        title = ?, url = ?, info_type = ?, industry_relevance = ?, relevance_reason = ?,
                        news_published_at = ?, collected_at = ?, summary = ?, selection_reason = ?, level = ?, 
                        tags = ?, query = ?, is_report_item = 1, raw_json = ?, content_summary = ?, source_mode = ?,
                        source_name = ?, snippet = ?, category = ?, content_theme = ?, platform_layers = ?
                    WHERE item_key = ?
                    """,
                    (
                        it.collected_at,
                        date_label,
                        it.score,
                        it.brand,
                        it.industry,
                        it.platform,
                        it.title,
                        it.url,
                        it.info_type,
                        it.industry_relevance,
                        it.relevance_reason,
                        it.news_published_at,
                        it.collected_at,
                        it.summary,
                        it.selection_reason,
                        it.level,
                        it.tags,
                        it.query,
                        raw_json,
                        it.content_summary,
                        it.source_mode,
                        it.source_name,
                        it.snippet,
                        it.category,
                        it.content_theme,
                        it.platform_layers,
                        it.item_key,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO intelligence_items (
                        item_key, first_collected_at, last_seen_at, latest_report_date, industry, brand,
                        platform, title, url, info_type, industry_relevance, relevance_reason,
                        news_published_at, collected_at, summary, selection_reason, level, score, tags,
                        query, is_report_item, raw_json, content_summary, source_mode, source_name,
                        snippet, category, content_theme, platform_layers
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        it.item_key,
                        it.collected_at,
                        it.collected_at,
                        date_label,
                        it.industry,
                        it.brand,
                        it.platform,
                        it.title,
                        it.url,
                        it.info_type,
                        it.industry_relevance,
                        it.relevance_reason,
                        it.news_published_at,
                        it.collected_at,
                        it.summary,
                        it.selection_reason,
                        it.level,
                        it.score,
                        it.tags,
                        it.query,
                        it.is_report_item,
                        raw_json,
                        it.content_summary,
                        it.source_mode,
                        it.source_name,
                        it.snippet,
                        it.category,
                        it.content_theme,
                        it.platform_layers,
                    ),
                )
            conn.execute(
                "INSERT INTO report_items (report_date, item_key, rank, synced_at) VALUES (?, ?, ?, ?)",
                (date_label, it.item_key, rank, _fmt(_now_local())),
            )
        conn.commit()

    # generate report artifacts
    # map rows to sqlite3.Row-like object for markdown/csv helper
    table = list(
        conn.execute(
            """
            SELECT
                r.report_date, r.rank, i.industry, i.brand, i.category, i.platform, i.platform_layers,
                i.title, i.url, i.news_published_at, i.collected_at, i.content_theme, i.score, i.summary, 
                i.selection_reason, i.content_summary, i.query, i.source_mode
            FROM report_items r
            JOIN intelligence_items i ON i.item_key = r.item_key
            WHERE r.report_date = ?
            ORDER BY r.rank
            """,
            (date_label,),
        ).fetchall()
    )

    _write_markdown(markdown_path, date_label, table, config)
    _write_csv(csv_report_path, table)

    # xlsx omitted for simplicity but keep path stable
    if xlsx_report_path.exists():
        pass

    # update seen
    marked_seen = 0
    for it in selected:
        seen.add(it.item_key)
        marked_seen += 1
    _write_json(DEFAULT_SEEN_PATH, sorted(seen))

    # obsidian sync
    if settings.get("obsidian_sync_enabled", True):
        obsidian_root = obsidian_root_from_config(config)
        obsidian_root.mkdir(parents=True, exist_ok=True)
        _write_obsidian_note(
            obsidian_root / f"{date_label}_竞品情报.md",
            date_label,
            [it.__dict__ for it in selected],
            db_path,
        )

    # run record
    conn.execute(
        """
        INSERT INTO collector_runs (
            run_id, report_date, source_mode, started_at, synced_at, raw_new_count, report_count,
            skipped_seen_count, marked_seen_count, max_items, markdown_path, csv_path, xlsx_path, raw_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            date_label,
            source_mode,
            started_at.strftime("%Y-%m-%d %H:%M:%S"),
            _fmt(_now_local()),
            len(unique_raw),
            len(selected),
            skipped_seen,
            marked_seen,
            max_items,
            str(markdown_path),
            str(csv_report_path),
            str(xlsx_report_path),
            str(raw_path),
        ),
    )
    conn.commit()

    conn.close()

    if not args.no_email:
        send_result = send_report_email(
            config=config,
            date_label=date_label,
            items=[it.__dict__ for it in selected],
            max_items=max_items,
            db_path=db_path,
            obsidian_root=obsidian_root_from_config(config),
            md_path=markdown_path,
            csv_path=csv_report_path,
            xlsx_path=xlsx_report_path,
            force_send=False,
        )
        print(f"email: {send_result.get('status')} - {send_result.get('message')}")
    print(f"raw: {raw_path}")
    print(f"markdown: {markdown_path}")
    print(f"csv: {csv_report_path}")
    print(f"database: {db_path}")
    if settings.get("obsidian_sync_enabled", True):
        print(f"obsidian: {obsidian_root_from_config(config) / f'{date_label}_竞品情报.md'}")
    print(f"items: {len(selected)} / {max_items}")
    print(f"new collected: {len(unique_raw)}")
    print(f"seen skipped: {skipped_seen}")
    print(f"seen marked: {marked_seen}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Competitor intelligence collector")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="路径配置文件")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--max-items", type=int, default=30, help="每日最大上报数量")
    parser.add_argument(
        "--source-mode",
        default="both",
        choices=["both", "bing", "news", "gdelt"],
        help="数据源模式",
    )
    parser.add_argument("--date", default=_now_local().strftime("%Y-%m-%d"), help="报表日期 YYYY-MM-DD")
    parser.add_argument("--no-email", action="store_true", help="仅同步本地，无邮件")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
