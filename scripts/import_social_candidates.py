from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from competitor_collector import (  # noqa: E402
    SearchResult,
    _build_ai_summary,
    _canonical_item_url,
    _fmt,
    _now_local,
    _passes_visible_relevance_gate,
    _plain_text,
    _resolve_info_theme,
    _score_result,
    _select_brand_and_category,
    _write_competitor_intel_mirror_from_db,
    database_path_from_config,
    ensure_database,
    load_config,
    ob_database_project_root_from_config,
    obsidian_root_from_config,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Xiaohongshu/Douyin browser candidates into competitor intel DB.")
    parser.add_argument("--input", required=True, help="JSONL from scripts/social_browser_collect.mjs")
    parser.add_argument("--config", default="configs/collector_config.json")
    parser.add_argument("--date", default=_now_local().strftime("%Y-%m-%d"))
    parser.add_argument("--min-score", type=int, default=35)
    parser.add_argument("--max-candidates", type=int, default=120)
    parser.add_argument("--promote-report", action="store_true", help="Append high-score social items to today's report_items.")
    parser.add_argument("--promote-min-score", type=int, default=80)
    parser.add_argument("--max-promote", type=int, default=8)
    parser.add_argument("--no-obsidian-sync", action="store_true")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def short_key(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def build_record(raw: dict[str, Any], config: dict[str, Any]) -> SearchResult | None:
    title = _plain_text(raw.get("title") or "")
    url = _canonical_item_url(str(raw.get("url") or ""))
    snippet = _plain_text(raw.get("snippet") or raw.get("raw_text") or "")
    query = str(raw.get("query") or "")
    platform = str(raw.get("platform") or raw.get("platform_key") or "社媒")
    if not title or not url:
        return None

    brands = list(config.get("brands", []))
    rules = list(config.get("info_type_rules", []))
    text = f"{title} {snippet} {query}".strip()
    industry, category, brand = _select_brand_and_category(text, brands, "", query)
    query_industry, query_category, query_brand = _brand_from_query(text, query, brands)
    if query_brand:
        industry, category, brand = query_industry, query_category, query_brand
    if not industry:
        return None

    content_theme, bonus = _resolve_info_theme(text, rules)
    required_industry = config.get("settings", {}).get("required_report_industry", "计生/两性健康")
    score = _score_result(text, industry, required_industry, bonus)
    if raw.get("metrics_text"):
        score += 4
    if str(raw.get("priority") or "").upper() == "P0":
        score += 6
    score = min(score, 100)

    collected_at = str(raw.get("collected_at") or _fmt(_now_local()))
    source_name = f"social_browser_{raw.get('platform_key') or platform}"
    selection = f"浏览器授权采集命中社媒平台 {platform}，搜索词“{query}”，匹配行业/品牌：{industry}/{brand or '未识别品牌'}。"
    summary = f"{platform} 社媒候选：{title}"
    content_summary = (
        f"社媒标题：{title}；平台：{platform}；搜索词：{query}；采集时间：{collected_at}；"
        f"互动线索：{raw.get('metrics_text') or '未提取'}；匹配理由：{selection}"
    )
    item_key = short_key(f"social|{platform}|{url}|{title}")
    record = SearchResult(
        item_key=item_key,
        title=title,
        url=url,
        snippet=snippet,
        news_published_at=collected_at,
        collected_at=collected_at,
        industry=industry,
        brand=brand,
        category=category,
        platform=platform,
        platform_layers=str(raw.get("platform_key") or platform),
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
        level="high" if score >= 70 else "medium",
        query=query,
        source_mode="browser",
        source_name=source_name,
        tags="社媒候选",
        is_report_item=0,
        content_theme="社媒候选",
    )
    record.ai_summary, record.ai_summary_method, record.ai_summary_updated_at = _build_ai_summary(record)
    return record


def _brand_from_query(text: str, query: str, brands: list[dict[str, Any]]) -> tuple[str, str, str]:
    visible = str(text or "").casefold()
    query_text = str(query or "").casefold()
    for brand in brands:
        names = [brand.get("name", ""), *list(brand.get("aliases", []) or [])]
        for name in names:
            token = str(name or "").strip()
            if not token:
                continue
            folded = token.casefold()
            if folded in query_text and folded in visible:
                return str(brand.get("industry") or ""), str(brand.get("subcategory") or ""), str(brand.get("name") or token)
    return "", "", ""


def upsert_item(conn: sqlite3.Connection, item: SearchResult, raw: dict[str, Any], latest_report_date: str | None) -> bool:
    exists = conn.execute("SELECT 1 FROM intelligence_items WHERE item_key = ?", (item.item_key,)).fetchone()
    raw_json = json.dumps(raw | item.__dict__, ensure_ascii=False)
    if exists:
        conn.execute(
            """
            UPDATE intelligence_items SET
                last_seen_at = ?, latest_report_date = COALESCE(?, latest_report_date), score = ?,
                brand = ?, industry = ?, platform = ?, title = ?, url = ?, info_type = ?,
                industry_relevance = ?, relevance_reason = ?, news_published_at = ?, collected_at = ?,
                summary = ?, selection_reason = ?, level = ?, tags = ?, query = ?,
                is_report_item = CASE WHEN ? IS NULL THEN is_report_item ELSE 1 END,
                raw_json = ?, content_summary = ?, ai_summary = ?, ai_summary_method = ?,
                ai_summary_updated_at = ?, source_mode = ?, source_name = ?, snippet = ?,
                category = ?, content_theme = ?, platform_layers = ?
            WHERE item_key = ?
            """,
            (
                item.collected_at,
                latest_report_date,
                item.score,
                item.brand,
                item.industry,
                item.platform,
                item.title,
                item.url,
                item.info_type,
                item.industry_relevance,
                item.relevance_reason,
                item.news_published_at,
                item.collected_at,
                item.summary,
                item.selection_reason,
                item.level,
                item.tags,
                item.query,
                latest_report_date,
                raw_json,
                item.content_summary,
                item.ai_summary,
                item.ai_summary_method,
                item.ai_summary_updated_at,
                item.source_mode,
                item.source_name,
                item.snippet,
                item.category,
                item.content_theme,
                item.platform_layers,
                item.item_key,
            ),
        )
        return False

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
            item.item_key,
            item.collected_at,
            item.collected_at,
            latest_report_date,
            item.industry,
            item.brand,
            item.platform,
            item.title,
            item.url,
            item.info_type,
            item.industry_relevance,
            item.relevance_reason,
            item.news_published_at,
            item.collected_at,
            item.summary,
            item.selection_reason,
            item.level,
            item.score,
            item.tags,
            item.query,
            1 if latest_report_date else 0,
            raw_json,
            item.content_summary,
            item.ai_summary,
            item.ai_summary_method,
            item.ai_summary_updated_at,
            item.source_mode,
            item.source_name,
            item.snippet,
            item.category,
            item.content_theme,
            item.platform_layers,
        ),
    )
    return True


def write_candidate_briefs(
    candidates: list[tuple[SearchResult, dict[str, Any]]],
    config: dict[str, Any],
    date_label: str,
    input_path: Path,
) -> tuple[Path, Path, Path]:
    output_path = ROOT / "outputs" / f"{date_label}_social_candidates.md"
    csv_path = ROOT / "outputs" / f"{date_label}_social_candidates.csv"
    obsidian_dir = obsidian_root_from_config(config) / "社媒候选"
    obsidian_dir.mkdir(parents=True, exist_ok=True)
    obsidian_path = obsidian_dir / f"{date_label} 社媒候选.md"
    lines = [
        "---",
        "type: social_competitor_candidates",
        f"date: '{date_label}'",
        f"source_file: '{input_path}'",
        "---",
        "",
        f"# 社媒候选情报 {date_label}",
        "",
        f"- 候选数：{len(candidates)}",
        "- 来源：浏览器授权采集的小红书/抖音公开搜索结果。",
        "- 说明：候选默认不进入日报，需要达到高分或人工确认后再提升为正式日报条目。",
        "",
        "| # | 分数 | 平台 | 行业 | 品牌 | 品类 | 搜索词 | 标题 | AI总结 | 链接 |",
        "|---:|---:|---|---|---|---|---|---|---|---|",
    ]
    for idx, (item, _raw) in enumerate(candidates, start=1):
        lines.append(
            "| {idx} | {score} | {platform} | {industry} | {brand} | {category} | {query} | {title} | {ai} | {url} |".format(
                idx=idx,
                score=item.score,
                platform=item.platform,
                industry=item.industry,
                brand=item.brand or "-",
                category=item.category or "-",
                query=item.query.replace("|", "｜"),
                title=item.title.replace("|", "｜"),
                ai=item.ai_summary.replace("|", "｜"),
                url=item.url,
            )
        )
    text = "\n".join(lines).strip() + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8-sig")
    obsidian_path.write_text(text, encoding="utf-8-sig")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "score", "platform", "industry", "brand", "category", "query", "title", "ai_summary", "url"],
        )
        writer.writeheader()
        for item, _raw in candidates:
            writer.writerow(
                {
                    "date": date_label,
                    "score": item.score,
                    "platform": item.platform,
                    "industry": item.industry,
                    "brand": item.brand,
                    "category": item.category,
                    "query": item.query,
                    "title": item.title,
                    "ai_summary": item.ai_summary,
                    "url": item.url,
                }
            )
    return output_path, csv_path, obsidian_path


def write_ob_candidate_brief(config: dict[str, Any], date_label: str, candidates: list[tuple[SearchResult, dict[str, Any]]]) -> Path:
    root = ob_database_project_root_from_config(config) / "社媒候选"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{date_label} 社媒候选.md"
    lines = [
        "---",
        "ob_db_type: 'social_competitor_candidates'",
        f"run_date: '{date_label}'",
        "tags:",
        "  - 'OB数据库'",
        "  - '竞品情报'",
        "  - '社媒候选'",
        "---",
        "",
        f"# {date_label} 社媒候选",
        "",
        f"候选数：{len(candidates)}",
        "",
    ]
    for idx, (item, _raw) in enumerate(candidates, start=1):
        lines.extend(
            [
                f"## {idx}. {item.title}",
                f"- 分数：{item.score}",
                f"- 平台：{item.platform}",
                f"- 行业/品牌/品类：{item.industry} / {item.brand or '-'} / {item.category or '-'}",
                f"- 搜索词：{item.query}",
                f"- 链接：{item.url}",
                f"- AI总结：{item.ai_summary}",
                "",
            ]
        )
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")
    return path


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    input_path = Path(args.input)
    raw_rows = read_jsonl(input_path)
    records: list[tuple[SearchResult, dict[str, Any]]] = []
    seen_keys: set[str] = set()
    for raw in raw_rows:
        item = build_record(raw, config)
        if not item or item.item_key in seen_keys:
            continue
        if item.score < args.min_score:
            continue
        if not _passes_visible_relevance_gate(item, config):
            continue
        seen_keys.add(item.item_key)
        records.append((item, raw))

    records.sort(key=lambda pair: (pair[0].score, pair[0].platform, pair[0].title), reverse=True)
    records = records[: args.max_candidates]

    promote_keys: set[str] = set()
    if args.promote_report:
        for item, _raw in records:
            if item.score >= args.promote_min_score:
                promote_keys.add(item.item_key)
            if len(promote_keys) >= args.max_promote:
                break

    db_path = database_path_from_config(config)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_database(conn)
    inserted = 0
    updated = 0
    promoted = 0
    for item, raw in records:
        latest_report_date = args.date if item.item_key in promote_keys else None
        if upsert_item(conn, item, raw, latest_report_date):
            inserted += 1
        else:
            updated += 1
        if latest_report_date:
            max_rank = conn.execute("SELECT COALESCE(MAX(rank), 0) FROM report_items WHERE report_date = ?", (args.date,)).fetchone()[0]
            conn.execute(
                "INSERT OR REPLACE INTO report_items (report_date, item_key, rank, synced_at) VALUES (?, ?, ?, ?)",
                (args.date, item.item_key, int(max_rank) + 1, _fmt(_now_local())),
            )
            promoted += 1
    conn.commit()

    output_path, csv_path, obsidian_path = write_candidate_briefs(records, config, args.date, input_path)
    ob_candidate_path = write_ob_candidate_brief(config, args.date, records)
    if not args.no_obsidian_sync:
        _write_competitor_intel_mirror_from_db(conn, config, db_path, dates=[args.date], include_all_items=True)
    conn.close()

    print(f"input: {input_path}")
    print(f"database: {db_path}")
    print(f"candidates: {len(records)}")
    print(f"inserted: {inserted}")
    print(f"updated: {updated}")
    print(f"promoted: {promoted}")
    print(f"markdown: {output_path}")
    print(f"csv: {csv_path}")
    print(f"obsidian: {obsidian_path}")
    print(f"ob_database: {ob_candidate_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
