from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from competitor_collector import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT_DIR,
    database_path_from_config,
    ensure_database,
    load_config,
    obsidian_root_from_config,
    search_result_from_database_row,
    send_report_email,
)


LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def load_report_items(db_path: Path, date_label: str):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        ensure_database(conn)
        rows = conn.execute(
            """
            SELECT i.*
            FROM report_items r
            JOIN intelligence_items i ON i.item_key = r.item_key
            WHERE r.report_date = ?
            ORDER BY r.rank
            """,
            (date_label,),
        ).fetchall()
    return [search_result_from_database_row(row) for row in rows]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send the generated competitor intelligence daily email.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to collector config JSON.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for report outputs.")
    parser.add_argument("--date", default=datetime.now(LOCAL_TZ).strftime("%Y-%m-%d"), help="Report date label.")
    parser.add_argument("--force", action="store_true", help="Send even if the same report hash is already marked sent.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(Path(args.config))
    db_path = database_path_from_config(config)
    output_dir = Path(args.output_dir)
    date_label = args.date
    md_path = output_dir / f"{date_label}_competitor_brief.md"
    csv_path = output_dir / f"{date_label}_competitor_brief.csv"
    xlsx_path = output_dir / f"{date_label}_competitor_brief.xlsx"
    items = load_report_items(db_path, date_label)
    result = send_report_email(
        config=config,
        date_label=date_label,
        items=items,
        max_items=int(config["settings"]["max_daily_items"]),
        db_path=db_path,
        obsidian_root=obsidian_root_from_config(config),
        md_path=md_path,
        csv_path=csv_path,
        xlsx_path=xlsx_path if xlsx_path.exists() else None,
        force_send=args.force,
    )
    print(f"email: {result.get('status')} - {result.get('message')}")
    if result.get("draft_path"):
        print(f"email draft: {result['draft_path']}")
    if result.get("preview_path"):
        print(f"email preview: {result['preview_path']}")
    return 0 if result.get("status") in {"sent", "skipped", "draft", "disabled"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
