---
name: competitor-intel-collector
description: Use this skill to run, maintain, debug, or extend a local competitor intelligence collector for beauty, pharma, and family-planning/sexual-health industries. It covers daily collection, SQLite and Obsidian sync, dedupe, strict family-planning share constraints, source expansion including WeChat and Douyin searches, and Windows scheduled-task verification.
---

# Competitor Intel Collector

## When To Use

Use this skill when the user asks to collect, refresh, debug, automate, summarize, or extend the competitor intelligence workflow for 美妆, 医药, or 计生/两性健康.

## Operating Contract

- Keep one shared pipeline: `configs/collector_config.json`, `D:\kin\competitor_intel.db`, `D:\kin\竞品情报`, and `data/seen_items.json`.
- Daily report output is capped at 30 items.
- `计生/两性健康` must be strictly more than 60% of the daily report when enough candidates exist.
- Each item must preserve original title, link, publish time, collected time, platform, brand, category, content summary, and selection reason.
- News publish time must be within 6 months of the collection date.
- Cross-day dedupe uses `settings.report_duplicate_window_days`, default 180. Same-day reruns may overwrite the day so the user can refresh results.
- Email is not the primary delivery path. Prefer DB and Obsidian verification.

## Standard Workflow

1. Inspect the working directory and confirm the collector files exist:
   - `src/competitor_collector.py`
   - `scripts/run_collector.py`
   - `configs/collector_config.json`
2. Compile-check before running after edits:
   ```powershell
   $py = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
   & $py -m py_compile src\competitor_collector.py
   ```
3. Run a daily DB-only collection:
   ```powershell
   & $py scripts\run_collector.py --max-items 30 --no-email
   ```
4. Verify real downstream state, not only terminal output:
   - `collector_runs` has a recent successful row.
   - `report_items` has today's rows.
   - `intelligence_items` has non-empty `content_summary`.
   - Industry split satisfies the required share.
   - `D:\kin\竞品情报\YYYY-MM-DD_竞品情报.md` exists and was updated.
5. If automation is involved, check Windows task `KinCompetitorDbUpdate` and its log under `outputs\automation`.

## Verification Queries

Use SQLite verification similar to:

```python
import sqlite3
conn = sqlite3.connect("D:/kin/competitor_intel.db")
c = conn.cursor()
date = "YYYY-MM-DD"
print(c.execute("select count(*) from report_items where report_date=?", (date,)).fetchone())
print(c.execute("""
select i.industry, count(*)
from report_items r join intelligence_items i on i.item_key = r.item_key
where r.report_date=?
group by i.industry
""", (date,)).fetchall())
```

## Source Expansion Rules

Update `configs/collector_config.json`, not a parallel config, when adding sources.

Preferred source buckets:

- Official/regulatory: NMPA, CDE, chinadrugtrials, NHC, NHSA.
- Social/content: WeChat public articles, Douyin, Xiaohongshu, Weibo, Zhihu, Bilibili.
- Commerce/vertical: JD, Tmall, Chunshuitang, Zuiqingfeng, Taqu.
- Industry media: Qingyan, Jumeili, HZPGC, China Pharmaceutical News, Yaozh, PharmCube.

## Failure Triage

- If OB has no new note, verify the actual DB first, then the Obsidian path.
- If few items survive, inspect raw JSONL candidate counts, dedupe window, score threshold, and publish-time filter.
- If a scheduled task fails, run `scripts\run_daily_db_update.ps1` manually and inspect `outputs\automation\YYYY-MM-DD-db-update.log`.
- If PowerShell displays Chinese as mojibake, validate with Python UTF-8 reads before rewriting files.

