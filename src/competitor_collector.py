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
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit
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

VISIBLE_INDUSTRY_KEYWORDS = {
    "美妆": [
        "美妆",
        "护肤",
        "彩妆",
        "化妆品",
        "面膜",
        "精华",
        "防晒",
        "口红",
        "敏感肌",
        "功效",
    ],
    "医药": [
        "医药",
        "药品",
        "药企",
        "临床",
        "获批",
        "上市申请",
        "cde",
        "nmpa",
        "医保",
        "集采",
        "适应症",
        "fda",
    ],
    "计生/两性健康": [
        "计生",
        "两性",
        "生殖健康",
        "避孕",
        "避孕套",
        "安全套",
        "润滑剂",
        "情趣",
        "成人用品",
        "验孕",
        "排卵",
        "避孕药",
    ],
}

LOW_VALUE_DOMAINS = {
    "baike.baidu.com",
    "hanyuguoxue.com",
    "www.hanyuguoxue.com",
    "hgcha.com",
    "www.hgcha.com",
    "tv.yandex.com",
}

LOW_VALUE_TITLE_KEYWORDS = [
    "百度百科",
    "拼音",
    "笔顺",
    "部首",
    "汉语",
    "字典",
    "意思",
    "组词",
    "搜索引擎",
    "found ",
    "查询词：",
    "怎么画",
    "怎么修",
    "跳过一句话",
    "一次性看完",
    "秒变",
    "史上最全",
    "看这篇就够了",
]

REPORT_ACTION_KEYWORDS = [
    "新品",
    "上新",
    "发布",
    "测评",
    "推荐",
    "价格",
    "便宜",
    "涨价",
    "降价",
    "优惠",
    "销量",
    "评价",
    "热卖",
    "榜",
    "投诉",
    "差评",
    "副作用",
    "区别",
    "对比",
    "体验",
    "使用",
    "解说",
    "热门款",
    "获批",
    "审批",
    "临床",
    "适应症",
    "医保",
    "集采",
    "中选",
    "处罚",
    "召回",
    "旗舰店",
    "自营",
    "直播",
    "投放",
]


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
    ai_summary: str
    ai_summary_method: str
    ai_summary_updated_at: str
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


def _plain_text(s: Any) -> str:
    text = html.unescape(str(s or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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
    settings.setdefault("source_pack_max_queries", 60)
    settings.setdefault("source_registry_enabled", True)
    settings.setdefault("source_registry_max_queries", 60)
    settings.setdefault("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT)
    settings.setdefault("request_delay_seconds", 0.08)
    settings.setdefault("database_dir", r"D:\kin")
    settings.setdefault("database_file", "competitor_intel.db")
    settings.setdefault("obsidian_sync_enabled", True)
    settings.setdefault("obsidian_vault_dir", r"D:\kin")
    settings.setdefault("obsidian_folder", "竞品情报")
    settings.setdefault("ob_database_sync_enabled", True)
    settings.setdefault("ob_database_dir", r"D:\kin\OB数据库")
    settings.setdefault("ob_competitor_project_folder", r"08 项目\竞品情报收集")
    settings.setdefault("email_enabled", False)
    return cfg


def database_path_from_config(config: dict[str, Any]) -> Path:
    db_dir = config.get("settings", {}).get("database_dir", r"D:\kin")
    db_file = config.get("settings", {}).get("database_file", "competitor_intel.db")
    return Path(db_dir) / db_file


def obsidian_root_from_config(config: dict[str, Any]) -> Path:
    settings = config.get("settings", {})
    return Path(settings.get("obsidian_vault_dir", r"D:\kin")) / settings.get("obsidian_folder", "竞品情报")


def ob_database_project_root_from_config(config: dict[str, Any]) -> Path:
    settings = config.get("settings", {})
    return Path(settings.get("ob_database_dir", r"D:\kin\OB数据库")) / settings.get(
        "ob_competitor_project_folder",
        r"08 项目\竞品情报收集",
    )


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


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
            ai_summary TEXT,
            ai_summary_method TEXT,
            ai_summary_updated_at TEXT,
            source_mode TEXT,
            source_name TEXT,
            snippet TEXT,
            category TEXT,
            content_theme TEXT,
            platform_layers TEXT
        )
        """
    )
    _ensure_columns(
        conn,
        "intelligence_items",
        {
            "ai_summary": "TEXT",
            "ai_summary_method": "TEXT",
            "ai_summary_updated_at": "TEXT",
        },
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
        "ai_summary": row["ai_summary"],
        "ai_summary_method": row["ai_summary_method"],
        "ai_summary_updated_at": row["ai_summary_updated_at"],
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


def _canonical_item_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except Exception:
        return text
    if not parts.scheme or not parts.netloc:
        return text
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() != "has_native"],
        doseq=True,
    )
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", query, ""))


def _build_platform_layers(platforms: list[dict[str, Any]], url: str) -> tuple[str, str]:
    domain = _item_domain(url)
    for platform in platforms:
        domains = set(_to_list(platform.get("domains", [])))
        if domain and domain in domains:
            return platform.get("name", "未知来源"), domain
    return "网络抓取", domain


def _iter_brand_names(brands: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for brand in brands:
        for name in [brand.get("name", ""), *_to_list(brand.get("aliases", []))]:
            name = str(name or "").strip()
            if name:
                names.append(name)
    return names


def _contains_visible_brand(text: str, brands: list[dict[str, Any]]) -> bool:
    lower = text.lower()
    compact = _norm(text)
    for name in _iter_brand_names(brands):
        # Avoid short ASCII aliases such as KY matching unrelated text fragments.
        if name.isascii() and len(name) <= 2:
            continue
        if name.lower() in lower or _norm(name) in compact:
            return True
    return False


def _select_brand_and_category(
    text: str,
    brands: list[dict[str, Any]],
    industry_name: str | None = None,
    query: str | None = None,
) -> tuple[str, str, str]:
    sample = text.lower()
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


def _contains_industry_keyword(text: str, industry: str) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in VISIBLE_INDUSTRY_KEYWORDS.get(industry, []))


def _contains_report_action(text: str) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in REPORT_ACTION_KEYWORDS)


def _is_low_value_result(item: SearchResult) -> bool:
    title = item.title.strip().lower()
    domain = item.platform_layers.lower()
    if domain in LOW_VALUE_DOMAINS:
        return True
    if any(keyword.lower() in title for keyword in LOW_VALUE_TITLE_KEYWORDS):
        return True
    if "/search" in item.url.lower() and ("yandex." in item.url.lower() or "baidu." in item.url.lower()):
        return True
    return False


def _passes_visible_relevance_gate(item: SearchResult, config: dict[str, Any]) -> bool:
    if not item.title.strip() or not item.url.strip():
        return False
    if _is_low_value_result(item):
        return False

    visible_text = f"{item.title} {item.snippet}".strip()
    brands = _to_list(config.get("brands", []))
    has_brand = _contains_visible_brand(visible_text, brands)
    has_industry = _contains_industry_keyword(visible_text, item.industry)
    has_action = _contains_report_action(visible_text)

    required_industry = config.get("settings", {}).get("required_report_industry", "计生/两性健康")
    if item.industry != required_industry and not has_brand:
        return False
    return (has_brand or has_industry) and has_action


def _summary_signal(text: str) -> str:
    lower = text.lower()
    checks = [
        ("监管/审批", ["获批", "审批", "临床", "适应症", "fda", "nmpa", "cde", "批准通知书"]),
        ("价格/渠道", ["价格", "便宜", "旗舰店", "自营", "优惠", "销量", "热卖", "榜"]),
        ("测评/口碑", ["测评", "推荐", "体验", "区别", "对比", "避坑", "解说", "热门款"]),
        ("风险/投诉", ["投诉", "差评", "副作用", "召回", "处罚", "破损", "过敏"]),
        ("新品/投放", ["新品", "上新", "发布", "首发", "独家", "新形态", "直播", "投放", "达人"]),
    ]
    for label, keywords in checks:
        if any(keyword.lower() in lower for keyword in keywords):
            return label
    return "情报线索"


def _industry_action_hint(industry: str) -> str:
    if industry == "计生/两性健康":
        return "关注安全套、润滑剂、情趣器具和避孕相关产品的价格带、卖点话术、用户体验和渠道变化。"
    if industry == "美妆":
        return "关注品牌渠道、功效卖点、价格体系和内容平台上的对比口碑。"
    if industry == "医药":
        return "关注审批进展、临床阶段、准入政策和药企管线变化对竞争格局的影响。"
    return "关注其对产品、渠道、价格或用户反馈的可复用信息。"


def _build_ai_summary_fields(
    title: str,
    snippet: str,
    industry: str,
    brand: str,
    category: str,
    platform: str,
    news_published_at: str,
) -> tuple[str, str, str]:
    visible_text = _plain_text(f"{title} {snippet}")
    signal = _summary_signal(visible_text)
    subject = brand or category or industry or "该条信息"
    source = platform or "公开来源"
    published = news_published_at or "发布时间未知"
    clean_title = title.strip()
    hint = _industry_action_hint(industry)
    summary = (
        f"{signal}：{clean_title}。"
        f"这条信息来自{source}，发布时间为{published}，核心对象是{subject}。"
        f"{hint}"
    )
    return summary, "codex-local-structured-summary", _fmt(_now_local())


def _build_ai_summary(item: SearchResult) -> tuple[str, str, str]:
    return _build_ai_summary_fields(
        item.title,
        item.snippet,
        item.industry,
        item.brand,
        item.category,
        item.platform,
        item.news_published_at,
    )


def _safe_filename(value: str, limit: int = 72) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", " ", value)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text[:limit].strip() or "untitled")


def _short_item_key(item_key: str) -> str:
    key = str(item_key or "")
    if re.fullmatch(r"[a-f0-9]{40}", key):
        return key[:8]
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def _yaml_quote(value: Any) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _collect_queries(config: dict[str, Any], source_mode: str, max_items: int) -> list[dict[str, Any]]:
    settings = config.get("settings", {})
    max_queries = settings.get("max_queries_per_run", 96)
    platform_queries = _to_list(config.get("platform_search_queries", []))
    source_registry = _to_list(config.get("source_registry", []))
    source_pack = _to_list(config.get("source_pack_queries", []))
    supplemental = _to_list(config.get("supplemental_queries", []))
    topic_queries = _to_list(config.get("topic_queries", []))
    brands = _to_list(config.get("brands", []))

    by_industry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for b in brands:
        by_industry[b.get("industry", "")]
        by_industry[b.get("industry", "")].append(b)

    queries = []
    seen_queries: set[str] = set()

    def add_query(query: str, source: str, label: str) -> bool:
        q = re.sub(r"\s+", " ", str(query or "")).strip()
        if not q or len(queries) >= max_queries:
            return False
        key = q.casefold()
        if key in seen_queries:
            return False
        seen_queries.add(key)
        queries.append({"query": q, "source": source, "source_mode": source_mode, "label": label})
        return True

    # Structured source registry: high-signal fixed domains and source-specific templates.
    if settings.get("source_registry_enabled", True):
        registry_budget = int(settings.get("source_registry_max_queries", 60))
        registry_added = 0
        for source in source_registry:
            if registry_added >= registry_budget or len(queries) >= max_queries:
                break
            industry = str(source.get("industry", "") or "")
            source_name = str(source.get("source_name", source.get("name", "source_registry")))
            source_budget = int(source.get("max_queries", registry_budget))
            if source_budget <= 0:
                continue
            source_added = 0
            domains = _to_list(source.get("domains", []))
            templates = _to_list(source.get("query_templates", []))
            direct_queries = _to_list(source.get("queries", []))

            for query in direct_queries:
                q = str(query or "").strip()
                if not q:
                    continue
                if add_query(q, industry, source_name):
                    registry_added += 1
                    source_added += 1
                if source_added >= source_budget or registry_added >= registry_budget or len(queries) >= max_queries:
                    break
            if registry_added >= registry_budget or len(queries) >= max_queries:
                break
            if source_added >= source_budget:
                continue

            if not templates:
                continue
            candidate_brands = by_industry.get(industry, []) if industry else brands
            brand_limit = int(source.get("brand_limit", 3))
            intents = _to_list(source.get("intents", [])) or ["新品", "价格", "测评"]
            domain_expr = " OR ".join(f"site:{domain}" for domain in domains)
            for brand in candidate_brands[:brand_limit]:
                brand_name = brand.get("name", "")
                category = brand.get("subcategory", "")
                for intent in intents:
                    for template in templates:
                        q = str(template).format(
                            brand=brand_name,
                            category=category,
                            category_full=brand.get("subcategory_full", category),
                            intent=intent,
                            industry=industry,
                            domains=domain_expr,
                        ).strip()
                        if add_query(q, industry, source_name):
                            registry_added += 1
                            source_added += 1
                        if source_added >= source_budget or registry_added >= registry_budget or len(queries) >= max_queries:
                            break
                    if source_added >= source_budget or registry_added >= registry_budget or len(queries) >= max_queries:
                        break
                if source_added >= source_budget or registry_added >= registry_budget or len(queries) >= max_queries:
                    break

    # source pack/base queries (high priority sources)
    source_pack_budget = int(settings.get("source_pack_max_queries", len(source_pack)))
    for item in source_pack[:source_pack_budget]:
        if len(queries) >= max_queries:
            break
        q = str(item.get("query", "")).strip()
        if not q:
            continue
        add_query(q, item.get("industry", ""), "source_pack")

    # topic broad queries
    for item in topic_queries:
        q = str(item.get("query", "")).strip()
        if not q:
            continue
        add_query(q, item.get("industry", ""), "topic")

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
                        add_query(q, ind, "platform_template")
                        if len(queries) >= max_queries:
                            break
                    if len(queries) >= max_queries:
                        break
                if len(queries) >= max_queries:
                    break

    # supplemental expansion with cap
    for item in supplemental:
        if len(queries) >= max_queries:
            break
        q = str(item.get("query", "")).strip()
        if not q:
            continue
        add_query(q, item.get("industry", ""), "supplemental")

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
    canonical_link = _canonical_item_url(link)
    snippet = _plain_text(raw_item.get("description", ""))
    pub = raw_item.get("published", "")
    published = _to_local_from_email_date(pub) or _now_local()
    collected = _now_local()
    text = f"{title} {snippet}".strip()
    industry, category, brand = _select_brand_and_category(text, brands, query_industry, query)
    if not industry:
        industry = query_industry or cfg.get("industries", [""])[0]
    platform, host = _build_platform_layers(cfg.get("platforms", []), canonical_link or link)
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
    key = hashlib.sha1(f"{canonical_link or link}|{title}".encode("utf-8")).hexdigest()
    record = SearchResult(
        item_key=key,
        title=title,
        url=canonical_link or link,
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
        ai_summary="",
        ai_summary_method="",
        ai_summary_updated_at="",
        selection_reason=selection,
        score=score,
        level=level,
        query=query,
        source_mode=source_mode,
        source_name=source_name,
    )
    record.ai_summary, record.ai_summary_method, record.ai_summary_updated_at = _build_ai_summary(record)
    return record


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
        "|序号|行业|品牌|品类|来源|标题|原标题发布时间|采集时间|主题|AI总结|链接|",
        "|---:|---|---|---|---|---|---|---|---|---|---|",
    ]
    for idx, row in enumerate(rows, start=1):
        link = row["url"] or ""
        title = (row["title"] or "").replace("|", "｜")
        ai_summary = (
            row["ai_summary"] if "ai_summary" in row.keys() and row["ai_summary"] else row["content_summary"] or row["summary"] or ""
        ).replace("|", "｜")
        lines.append(
            "| {idx} | {industry} | {brand} | {category} | {platform} | {title} | {published} | {collected} | {theme} | {ai_summary} | {link} |".format(
                idx=idx,
                industry=(row["industry"] or "-"),
                brand=(row["brand"] or "-"),
                category=(row["category"] or "-"),
                platform=(row["platform"] or "-"),
                title=title,
                published=(row["news_published_at"] or "-"),
                collected=(row["collected_at"] or "-"),
                theme=(row["content_theme"] or "-"),
                ai_summary=ai_summary,
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
        "ai_summary",
        "ai_summary_method",
        "ai_summary_updated_at",
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
        lines.append(f"- AI总结：{it.get('ai_summary') or it.get('content_summary') or it.get('summary','')}")
        lines.append(f"- 摘要：{it.get('summary','')}")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")


def _write_ob_database_competitor_notes(
    project_root: Path,
    date_label: str,
    items: list[dict[str, Any]],
    db_path: Path,
) -> None:
    daily_dir = project_root / "每日运行"
    item_dir = project_root / "情报条目"
    daily_dir.mkdir(parents=True, exist_ok=True)
    item_dir.mkdir(parents=True, exist_ok=True)

    industry_counts = Counter(str(it.get("industry") or "未分类") for it in items)
    created_at = _fmt(_now_local())
    source_db = str(db_path).replace("\\", "/")
    daily_lines = [
        "---",
        "ob_db_type: 'competitor_daily_run'",
        f"run_date: '{date_label}'",
        f"created_at: '{created_at}'",
        f"source_db: '{source_db}'",
        "tags:",
        "  - 'OB数据库'",
        "  - '竞品情报'",
        "  - '每日运行'",
        "---",
        "",
        f"# {date_label} 竞品情报收集",
        "",
        "## 总结",
        f"今日入库日报条目 {len(items)} 条；行业分布："
        + "；".join(f"{industry} {count} 条" for industry, count in industry_counts.items())
        + "。",
        "",
        "## 条目",
    ]

    for idx, it in enumerate(items, start=1):
        title = str(it.get("title") or "未命名情报")
        item_name = f"{date_label}-{idx:02d} {_safe_filename(title)}.md"
        item_path = item_dir / item_name
        item_rel = f"OB数据库/08 项目/竞品情报收集/情报条目/{item_name[:-3]}"
        daily_lines.append(f"- [[{item_rel}|{idx}. {title}]]")

        item_lines = [
            "---",
            "ob_db_type: 'competitor_intelligence_item'",
            f"run_date: '{date_label}'",
            f"rank: {idx}",
            f"industry: {_yaml_quote(it.get('industry'))}",
            f"brand: {_yaml_quote(it.get('brand'))}",
            f"category: {_yaml_quote(it.get('category'))}",
            f"platform: {_yaml_quote(it.get('platform'))}",
            f"news_published_at: '{it.get('news_published_at') or ''}'",
            f"collected_at: '{it.get('collected_at') or ''}'",
            f"score: {int(it.get('score') or 0)}",
            "tags:",
            "  - 'OB数据库'",
            "  - '竞品情报'",
            "  - '情报条目'",
            "---",
            "",
            f"# {title}",
            "",
            f"- 行业：{it.get('industry') or '-'}",
            f"- 品牌：{it.get('brand') or '-'}",
            f"- 品类：{it.get('category') or '-'}",
            f"- 来源：{it.get('platform') or '-'}",
            f"- 原标题发布时间：{it.get('news_published_at') or '-'}",
            f"- 收录时间：{it.get('collected_at') or '-'}",
            f"- 链接：{it.get('url') or '-'}",
            "",
            "## AI总结",
            str(it.get("ai_summary") or it.get("content_summary") or it.get("summary") or ""),
            "",
            "## 选取原因",
            str(it.get("selection_reason") or ""),
            "",
            "## 检索上下文",
            f"- 搜索词：{it.get('query') or '-'}",
            f"- 抓取渠道：{it.get('source_name') or '-'} / {it.get('source_mode') or '-'}",
            f"- 页面片段：{it.get('snippet') or '-'}",
        ]
        item_path.write_text("\n".join(item_lines).strip() + "\n", encoding="utf-8-sig")

    (daily_dir / f"{date_label} 竞品情报收集.md").write_text(
        "\n".join(daily_lines).strip() + "\n",
        encoding="utf-8-sig",
    )


def _report_item_dicts_for_date(conn: sqlite3.Connection, date_label: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            r.report_date, r.rank, i.industry, i.brand, i.category, i.platform, i.platform_layers,
            i.title, i.url, i.news_published_at, i.collected_at, i.content_theme, i.score, i.summary,
            i.selection_reason, i.content_summary, i.ai_summary, i.ai_summary_method,
            i.ai_summary_updated_at, i.query, i.source_mode, i.source_name, i.snippet
        FROM report_items r
        JOIN intelligence_items i ON i.item_key = r.item_key
        WHERE r.report_date = ?
        ORDER BY r.rank
        """,
        (date_label,),
    ).fetchall()
    return [dict(row) for row in rows]


def _write_ob_database_from_db(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    db_path: Path,
    dates: list[str] | None = None,
) -> int:
    if dates is None:
        dates = [
            row[0]
            for row in conn.execute("SELECT DISTINCT report_date FROM report_items ORDER BY report_date").fetchall()
        ]
    project_root = ob_database_project_root_from_config(config)
    written = 0
    for date_label in dates:
        items = _report_item_dicts_for_date(conn, date_label)
        _write_ob_database_competitor_notes(project_root, date_label, items, db_path)
        written += len(items)
    return written


def _existing_competitor_item_paths(item_dir: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not item_dir.exists():
        return result
    for path in item_dir.glob("*.md"):
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        except Exception:
            continue
        in_frontmatter = False
        for line in lines[:80]:
            if line.strip() == "---":
                if in_frontmatter:
                    break
                in_frontmatter = True
                continue
            if not in_frontmatter:
                continue
            if line.startswith("item_key:"):
                key = line.split(":", 1)[1].strip().strip('"').strip("'")
                if key:
                    result[key] = path
                break
    return result


def _competitor_item_filename(item: dict[str, Any]) -> str:
    date_text = str(item.get("news_published_at") or item.get("collected_at") or item.get("first_collected_at") or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", date_text)
    date_label = match.group(0) if match else _now_local().strftime("%Y-%m-%d")
    title = _safe_filename(str(item.get("title") or "未命名情报"), limit=92)
    return f"{date_label} {title} {_short_item_key(str(item.get('item_key') or ''))}.md"


def _write_competitor_item_note(path: Path, item: dict[str, Any]) -> None:
    title = str(item.get("title") or "未命名情报")
    ai_summary = str(item.get("ai_summary") or item.get("content_summary") or item.get("summary") or "")
    raw_json = str(item.get("raw_json") or "").strip()
    lines = [
        "---",
        "type: competitor_intel",
        f"industry: {_yaml_quote(item.get('industry'))}",
        f"brand: {_yaml_quote(item.get('brand'))}",
        f"category: {_yaml_quote(item.get('category'))}",
        f"platform: {_yaml_quote(item.get('platform'))}",
        f"content_theme: {_yaml_quote(item.get('content_theme'))}",
        f"platform_layers: {_yaml_quote(item.get('platform_layers'))}",
        f"source_mode: {_yaml_quote(item.get('source_mode'))}",
        f"source_name: {_yaml_quote(item.get('source_name'))}",
        f"info_type: {_yaml_quote(item.get('info_type'))}",
        f"industry_relevance: {_yaml_quote(item.get('industry_relevance'))}",
        f"level: {_yaml_quote(item.get('level'))}",
        f"score: {int(item.get('score') or 0)}",
        f"news_published_at: {_yaml_quote(item.get('news_published_at'))}",
        f"collected_at: {_yaml_quote(item.get('collected_at'))}",
        f"first_collected_at: {_yaml_quote(item.get('first_collected_at'))}",
        f"last_seen_at: {_yaml_quote(item.get('last_seen_at'))}",
        f"latest_report_date: {_yaml_quote(item.get('latest_report_date'))}",
        f"source_url: {_yaml_quote(item.get('url'))}",
        f"item_key: {_yaml_quote(item.get('item_key'))}",
        f"has_ai_summary: {'true' if ai_summary else 'false'}",
        "tags:",
        "  - 竞品情报",
        "  - 情报条目",
        "---",
        "",
        f"# {title}",
        "",
        f"[原文链接]({item.get('url') or ''})",
        "",
        f"- **行业**：{item.get('industry') or '-'}",
        f"- **品牌/公司**：{item.get('brand') or '-'}",
        f"- **品类**：{item.get('category') or '-'}",
        f"- **平台/来源**：{item.get('platform') or '-'}",
        f"- **抓取渠道**：{item.get('source_name') or '-'} / {item.get('source_mode') or '-'}",
        f"- **信息类型**：{item.get('info_type') or item.get('content_theme') or '-'}",
        f"- **新闻发布时间**：{item.get('news_published_at') or '-'}",
        f"- **收录时间**：{item.get('collected_at') or '-'}",
        f"- **首次收录时间**：{item.get('first_collected_at') or '-'}",
        f"- **最近发现时间**：{item.get('last_seen_at') or '-'}",
        f"- **是否进入日报**：{'是' if item.get('latest_report_date') else '否'}",
        "",
        "## AI总结",
        ai_summary,
        "",
        "## 选取原因",
        str(item.get("selection_reason") or item.get("relevance_reason") or ""),
        "",
        "## 检索上下文",
        f"- 搜索词：{item.get('query') or '-'}",
        f"- 页面片段：{item.get('snippet') or '-'}",
    ]
    if raw_json:
        lines.extend(["", "## 原始收录详情", "", "```json", raw_json, "```"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")


def _write_competitor_daily_brief(root: Path, date_label: str, items: list[dict[str, Any]], db_path: Path) -> Path:
    daily_dir = root / "每日简报"
    daily_dir.mkdir(parents=True, exist_ok=True)
    required = sum(1 for it in items if it.get("industry") == "计生/两性健康")
    high = sum(1 for it in items if str(it.get("level") or "").lower() == "high" or int(it.get("score") or 0) >= 70)
    lines = [
        "---",
        "type: competitor_daily_brief",
        f"date: {_yaml_quote(date_label)}",
        f"sqlite_db: {_yaml_quote(db_path)}",
        "---",
        "",
        f"# 行业竞品信息简报 {date_label}",
        "",
        f"- 实际输出：{len(items)} 条",
        f"- 计生/两性健康占比：{required}/{len(items) if items else 0}",
        "- 规则：保留原标题和可跳转链接；每条附 AI 总结和选取原因。",
        "",
        "## 今日重点",
        f"高优先级 {high} 条，建议优先查看监管、风险、价格/销售、新品/投放和测评信息。",
        "",
        "| # | 行业 | 品牌/公司 | 品类 | 平台/来源 | 主题 | 发布时间 | 收录时间 | 原标题+链接 | AI总结 | 选取原因 | 等级 |",
        "|---:|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for idx, it in enumerate(items, start=1):
        title = str(it.get("title") or "").replace("|", "｜")
        link = str(it.get("url") or "")
        ai_summary = str(it.get("ai_summary") or it.get("content_summary") or it.get("summary") or "").replace("|", "｜")
        selection = str(it.get("selection_reason") or "").replace("|", "｜")
        lines.append(
            "| {idx} | {industry} | {brand} | {category} | {platform} | {theme} | {published} | {collected} | {title_link} | {ai_summary} | {selection} | {level} |".format(
                idx=idx,
                industry=it.get("industry") or "-",
                brand=it.get("brand") or "-",
                category=it.get("category") or "-",
                platform=it.get("platform") or "-",
                theme=it.get("content_theme") or it.get("info_type") or "-",
                published=it.get("news_published_at") or "-",
                collected=it.get("collected_at") or "-",
                title_link=f"[{title}]({link})" if link else title,
                ai_summary=ai_summary,
                selection=selection,
                level=it.get("level") or "-",
            )
        )
    lines.extend(
        [
            "",
            "## 本地数据库",
            "",
            f"- SQLite：`{db_path}`",
        ]
    )
    path = daily_dir / f"{date_label} 竞品信息简报.md"
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")
    return path


def _intelligence_item_dicts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM intelligence_items
        ORDER BY COALESCE(collected_at, last_seen_at, first_collected_at, news_published_at, '') DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _write_competitor_index_files(
    root: Path,
    db_path: Path,
    latest_date: str,
    intelligence_count: int,
    report_count: int,
    run_count: int,
) -> None:
    now = _fmt(_now_local())
    (root / "情报条目.md").write_text(
        "\n".join(
            [
                "---",
                "type: competitor_entry_index",
                f"updated: {_yaml_quote(now)}",
                "tags:",
                "  - 竞品情报",
                "  - 数据库",
                "  - 索引",
                "---",
                "",
                "# 情报条目",
                "",
                "## 上级入口",
                "",
                "- [[竞品情报/竞品情报 Dashboard|竞品情报 Dashboard]]",
                "- [[竞品情报/数据库同步状态|数据库同步状态]]",
                "",
                "## 当前说明",
                "",
                "这里是 `competitor_intel.db` 导出的情报条目目录索引；单条情报文件位于 `竞品情报/情报条目`，每条包含 `## AI总结`。",
                "",
                "## 最新条目",
                "",
                "```dataview",
                "TABLE industry AS \"行业\", brand AS \"品牌\", platform AS \"来源\", info_type AS \"类型\", news_published_at AS \"发布时间\", collected_at AS \"采集时间\", has_ai_summary AS \"AI总结\"",
                "FROM \"竞品情报/情报条目\"",
                "SORT collected_at DESC",
                "LIMIT 80",
                "```",
            ]
        )
        + "\n",
        encoding="utf-8-sig",
    )
    (root / "数据库同步状态.md").write_text(
        "\n".join(
            [
                "---",
                "type: competitor_sync_status",
                f"updated: {_yaml_quote(now)}",
                "tags:",
                "  - 竞品情报",
                "  - 同步状态",
                "---",
                "",
                "# 数据库同步状态",
                "",
                f"- SQLite：`{db_path}`",
                f"- 最新日报：[[竞品情报/每日简报/{latest_date} 竞品信息简报|{latest_date} 竞品信息简报]]",
                f"- 最新归档：[[竞品情报/{latest_date}_竞品情报|{latest_date}_竞品情报]]",
                f"- 情报条目：{intelligence_count}",
                f"- 日报条目：{report_count}",
                f"- 运行记录：{run_count}",
                f"- 更新时间：{now}",
            ]
        )
        + "\n",
        encoding="utf-8-sig",
    )
    (root / "竞品情报 Dashboard.md").write_text(
        "\n".join(
            [
                "# 竞品情报 Dashboard",
                "",
                "## 核心入口",
                "",
                "- [[索引/数据库关联总览|数据库关联总览]]",
                "- [[竞品情报/数据库同步状态|数据库同步状态]]",
                f"- [[竞品情报/{latest_date}_竞品情报|最新归档：{latest_date}]]",
                f"- [[竞品情报/每日简报/{latest_date} 竞品信息简报|最新简报：{latest_date}]]",
                "- [[竞品情报/情报条目|情报条目目录]]",
                "",
                "## 数据链路",
                "",
                f"`competitor_intel.db` → [[竞品情报/情报条目|情报条目]] / [[竞品情报/每日简报/{latest_date} 竞品信息简报|每日简报]] / [[竞品情报/{latest_date}_竞品情报|按日归档]] → 产品与播客选题复盘。",
                "",
                "```dataview",
                "TABLE industry AS \"行业\", brand AS \"品牌\", platform AS \"来源\", info_type AS \"类型\", news_published_at AS \"发布时间\", has_ai_summary AS \"AI总结\"",
                "FROM \"竞品情报/情报条目\"",
                "SORT collected_at DESC",
                "LIMIT 50",
                "```",
            ]
        )
        + "\n",
        encoding="utf-8-sig",
    )


def _write_competitor_intel_mirror_from_db(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    db_path: Path,
    dates: list[str] | None = None,
    include_all_items: bool = True,
) -> dict[str, int]:
    root = obsidian_root_from_config(config)
    root.mkdir(parents=True, exist_ok=True)
    item_dir = root / "情报条目"
    item_dir.mkdir(parents=True, exist_ok=True)

    if dates is None:
        dates = [
            row[0]
            for row in conn.execute("SELECT DISTINCT report_date FROM report_items ORDER BY report_date").fetchall()
        ]
    daily_written = 0
    for date_label in dates:
        items = _report_item_dicts_for_date(conn, date_label)
        _write_competitor_daily_brief(root, date_label, items, db_path)
        _write_obsidian_note(root / f"{date_label}_竞品情报.md", date_label, items, db_path)
        daily_written += 1

    existing_by_key = _existing_competitor_item_paths(item_dir)
    item_rows = _intelligence_item_dicts(conn) if include_all_items else []
    item_written = 0
    for item in item_rows:
        key = str(item.get("item_key") or "")
        path = existing_by_key.get(key) or (item_dir / _competitor_item_filename(item))
        _write_competitor_item_note(path, item)
        item_written += 1

    latest_date = dates[-1] if dates else _now_local().strftime("%Y-%m-%d")
    intelligence_count = conn.execute("SELECT count(*) FROM intelligence_items").fetchone()[0]
    report_count = conn.execute("SELECT count(*) FROM report_items").fetchone()[0]
    run_count = conn.execute("SELECT count(*) FROM collector_runs").fetchone()[0]
    _write_competitor_index_files(root, db_path, latest_date, intelligence_count, report_count, run_count)
    return {"daily_written": daily_written, "items_written": item_written}


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


def _backfill_missing_ai_summaries(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT item_key, title, snippet, industry, brand, category, platform, news_published_at
        FROM intelligence_items
        WHERE ai_summary IS NULL OR trim(ai_summary) = ''
        """
    ).fetchall()
    for row in rows:
        ai_summary, method, updated_at = _build_ai_summary_fields(
            row["title"] or "",
            row["snippet"] or "",
            row["industry"] or "",
            row["brand"] or "",
            row["category"] or "",
            row["platform"] or "",
            row["news_published_at"] or "",
        )
        conn.execute(
            """
            UPDATE intelligence_items
            SET ai_summary = ?, ai_summary_method = ?, ai_summary_updated_at = ?
            WHERE item_key = ?
            """,
            (ai_summary, method, updated_at, row["item_key"]),
        )
    if rows:
        conn.commit()
    return len(rows)


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
    backfilled_ai_count = _backfill_missing_ai_summaries(conn)

    raw_dir = Path(settings.get("raw_dir", DEFAULT_RAW_DIR))
    raw_dir.mkdir(parents=True, exist_ok=True)
    date_label = args.date or _now_local().strftime("%Y-%m-%d")
    run_id = secrets.token_hex(8)
    started_at = _now_local()
    source_mode = args.source_mode
    max_items = int(args.max_items or settings.get("max_daily_items", 30))
    competitor_mirror_result: dict[str, int] = {}

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
    filtered = [it for it in filtered if _passes_visible_relevance_gate(it, config)]
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
    conn.execute(
        "UPDATE intelligence_items SET latest_report_date = NULL, is_report_item = 0 WHERE latest_report_date = ?",
        (date_label,),
    )
    conn.execute("DELETE FROM report_items WHERE report_date = ?", (date_label,))
    if selected:
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
                        tags = ?, query = ?, is_report_item = 1, raw_json = ?, content_summary = ?,
                        ai_summary = ?, ai_summary_method = ?, ai_summary_updated_at = ?, source_mode = ?,
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
                        it.ai_summary,
                        it.ai_summary_method,
                        it.ai_summary_updated_at,
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
                        query, is_report_item, raw_json, content_summary, ai_summary, ai_summary_method,
                        ai_summary_updated_at, source_mode, source_name, snippet, category, content_theme,
                        platform_layers
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        it.ai_summary,
                        it.ai_summary_method,
                        it.ai_summary_updated_at,
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
                i.selection_reason, i.content_summary, i.ai_summary, i.ai_summary_method,
                i.ai_summary_updated_at, i.query, i.source_mode
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
        competitor_mirror_result = _write_competitor_intel_mirror_from_db(
            conn,
            config,
            db_path,
            dates=[date_label],
            include_all_items=True,
        )

    if settings.get("ob_database_sync_enabled", True):
        _write_ob_database_competitor_notes(
            ob_database_project_root_from_config(config),
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
        print(f"competitor mirror items: {competitor_mirror_result.get('items_written', 0)}")
    if settings.get("ob_database_sync_enabled", True):
        print(f"ob_database: {ob_database_project_root_from_config(config)}")
    print(f"items: {len(selected)} / {max_items}")
    print(f"new collected: {len(unique_raw)}")
    print(f"ai summaries backfilled: {backfilled_ai_count}")
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
