# Database Reference

Canonical database: `D:\kin\competitor_intel.db`.

Core tables:

- `collector_runs`: one row per run, including report date, counts, output paths, raw path, and sync time.
- `intelligence_items`: canonical item records keyed by `item_key`; includes title, url, industry, brand, category, platform, publish time, collected time, summaries, query, source, score, and raw JSON.
- `report_items`: daily selected items keyed by `(report_date, item_key)` with rank and sync time.

Minimum daily validation:

- `report_items` count should be at least 10 when enough candidates are available and never above 30.
- `计生/两性健康` count divided by total must be greater than 0.6.
- Duplicate item keys for the same date must be zero.
- Items older than 6 months must be zero.
- Empty `content_summary` rows must be zero.

