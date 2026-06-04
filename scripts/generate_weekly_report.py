from __future__ import annotations

import argparse
import sqlite3
import textwrap
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(r"D:\kin\competitor_intel.db")
OUTPUT_DIR = ROOT / "outputs" / "weekly"
FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a weekly competitor intelligence presentation.")
    parser.add_argument("--start", default="2026-05-25", help="Week start date, YYYY-MM-DD.")
    parser.add_argument("--end", default="2026-05-31", help="Week end date, YYYY-MM-DD.")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Output directory.")
    return parser.parse_args()


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size=size)


def load_rows(db_path: Path, start: str, end: str) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT
                r.report_date,
                r.rank,
                i.industry,
                i.brand,
                i.category,
                i.platform,
                i.content_theme,
                i.title,
                i.url,
                i.news_published_at,
                i.collected_at
            FROM report_items r
            JOIN intelligence_items i ON i.item_key = r.item_key
            WHERE r.report_date BETWEEN ? AND ?
            ORDER BY r.report_date, r.rank
            """,
            (start, end),
        ).fetchall()


def display_value(value: object, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text if text and text.lower() != "none" else fallback


def display_date(value: object) -> str:
    text = display_value(value)
    if text == "-":
        return text
    try:
        return datetime.strptime(text[:25], "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
    except ValueError:
        return text[:10]


def domain(value: str) -> str:
    host = urlparse(value or "").netloc
    return host.replace("www.", "") or "-"


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def write_markdown(rows: list[sqlite3.Row], start: str, end: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{start}_{end}_weekly_competitor_summary.md"
    by_date: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_date[row["report_date"]].append(row)

    lines = [
        f"# 竞品信息周报 {start} 至 {end}",
        "",
        f"- 数据来源：`{DB_PATH}` / `D:\\kin\\竞品情报`",
        f"- 收录条目：{len(rows)} 条",
        "",
        "## 汇总",
        "",
        "| 日期 | 条目数 |",
        "|---|---:|",
    ]
    for date in sorted(by_date):
        lines.append(f"| {date} | {len(by_date[date])} |")

    lines.extend(["", "## 行业分布", "", "| 行业 | 条目数 |", "|---|---:|"])
    for industry, count in Counter(display_value(row["industry"]) for row in rows).most_common():
        lines.append(f"| {markdown_escape(industry)} | {count} |")

    lines.extend(["", "## 明细", ""])
    for date in sorted(by_date):
        lines.extend(
            [
                f"### {date}",
                "",
                "| # | 行业 | 品牌/公司 | 品类 | 平台/来源 | 内容主题 | 新闻发布时间 | 收录时间 | 原标题+链接 |",
                "|---:|---|---|---|---|---|---|---|---|",
            ]
        )
        for row in by_date[date]:
            title = display_value(row["title"])
            url = display_value(row["url"], "")
            link = f"[{markdown_escape(title)}]({url})" if url else markdown_escape(title)
            lines.append(
                "| {rank} | {industry} | {brand} | {category} | {platform} | {theme} | {published} | {collected} | {link} |".format(
                    rank=row["rank"],
                    industry=markdown_escape(display_value(row["industry"])),
                    brand=markdown_escape(display_value(row["brand"])),
                    category=markdown_escape(display_value(row["category"])),
                    platform=markdown_escape(display_value(row["platform"])),
                    theme=markdown_escape(display_value(row["content_theme"])),
                    published=markdown_escape(display_date(row["news_published_at"])),
                    collected=markdown_escape(display_value(row["collected_at"])[:19]),
                    link=link,
                )
            )
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8-sig")
    return path


def wrap_pixels(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    chunks = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for char in paragraph:
            candidate = line + char
            if draw.textlength(candidate, font=text_font) <= max_width:
                line = candidate
            else:
                if line:
                    chunks.append(line)
                line = char
        if line:
            chunks.append(line)
    return chunks or [""]


def rounded_rect(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], fill: str, radius: int = 18, outline: str | None = None) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline)


def draw_pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: str, fg: str, text_font: ImageFont.FreeTypeFont) -> int:
    x, y = xy
    pad_x = 18
    width = int(draw.textlength(text, font=text_font)) + pad_x * 2
    height = 38
    rounded_rect(draw, (x, y, x + width, y + height), fill, radius=19)
    draw.text((x + pad_x, y + 8), text, fill=fg, font=text_font)
    return width


def render_image(rows: list[sqlite3.Row], start: str, end: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{start}_{end}_weekly_competitor_summary_long.png"
    width = 1440
    margin = 64
    card_gap = 20
    row_gap = 12
    header_h = 290
    day_header_h = 58
    footer_h = 80

    scratch = Image.new("RGB", (width, 200), "#f6f8fb")
    draw = ImageDraw.Draw(scratch)
    f_title = font(46, True)
    f_subtitle = font(22)
    f_section = font(28, True)
    f_label = font(19, True)
    f_body = font(22)
    f_small = font(18)
    f_tiny = font(16)

    by_date: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_date[row["report_date"]].append(row)

    row_heights: dict[tuple[str, int], int] = {}
    content_width = width - margin * 2
    title_width = content_width - 250
    for date, date_rows in by_date.items():
        for row in date_rows:
            title_lines = wrap_pixels(draw, display_value(row["title"]), f_body, title_width)
            meta_lines = wrap_pixels(
                draw,
                f"{display_value(row['industry'])} · {display_value(row['brand'])} · {display_value(row['category'])} · {display_value(row['platform'])} · {display_value(row['content_theme'])}",
                f_small,
                title_width,
            )
            row_heights[(date, int(row["rank"]))] = 92 + len(title_lines) * 32 + len(meta_lines) * 26

    height = header_h + 120 + footer_h
    for date in sorted(by_date):
        height += day_header_h + card_gap
        height += sum(row_heights[(date, int(row["rank"]))] + row_gap for row in by_date[date])

    img = Image.new("RGB", (width, height), "#f6f8fb")
    draw = ImageDraw.Draw(img)
    rounded_rect(draw, (0, 0, width, header_h), "#0f766e", radius=0)
    draw.text((margin, 58), "行业竞品信息周报", fill="#ffffff", font=f_title)
    draw.text((margin, 126), f"{start} 至 {end}", fill="#d1fae5", font=f_subtitle)
    draw.text((margin, 166), r"数据来源：D:\kin\competitor_intel.db / D:\kin\竞品情报", fill="#e0f2fe", font=f_small)

    counts = Counter(display_value(row["industry"]) for row in rows)
    pill_x = margin
    pill_y = 218
    for label, fill, fg in [
        (f"总计 {len(rows)} 条", "#ffffff", "#0f766e"),
        (f"计生/两性健康 {counts.get('计生/两性健康', 0)} 条", "#fef3c7", "#92400e"),
        (f"美妆 {counts.get('美妆', 0)} 条", "#fce7f3", "#9d174d"),
        (f"医药 {counts.get('医药', 0)} 条", "#dbeafe", "#1d4ed8"),
    ]:
        pill_x += draw_pill(draw, (pill_x, pill_y), label, fill, fg, f_small) + 14

    y = header_h + 42
    draw.text((margin, y), "按日期汇总", fill="#0f172a", font=f_section)
    y += 58

    industry_colors = {
        "计生/两性健康": ("#fef3c7", "#92400e"),
        "美妆": ("#fce7f3", "#9d174d"),
        "医药": ("#dbeafe", "#1d4ed8"),
    }

    for date in sorted(by_date):
        date_rows = by_date[date]
        rounded_rect(draw, (margin, y, width - margin, y + day_header_h), "#e2e8f0", radius=16)
        draw.text((margin + 24, y + 14), f"{date}  ·  {len(date_rows)} 条", fill="#0f172a", font=f_label)
        y += day_header_h + card_gap
        for row in date_rows:
            row_h = row_heights[(date, int(row["rank"]))]
            rounded_rect(draw, (margin, y, width - margin, y + row_h), "#ffffff", radius=16, outline="#e5e7eb")
            rank_text = str(row["rank"])
            rounded_rect(draw, (margin + 22, y + 24, margin + 82, y + 84), "#0f766e", radius=30)
            rank_w = draw.textlength(rank_text, font=f_label)
            draw.text((margin + 52 - rank_w / 2, y + 41), rank_text, fill="#ffffff", font=f_label)

            x = margin + 108
            yy = y + 22
            industry = display_value(row["industry"])
            fill, fg = industry_colors.get(industry, ("#f1f5f9", "#334155"))
            pill_w = draw_pill(draw, (x, yy), industry, fill, fg, f_tiny)
            x += pill_w + 10
            for value in [display_value(row["platform"]), display_value(row["brand"])]:
                pill_w = draw_pill(draw, (x, yy), value[:18], "#f8fafc", "#334155", f_tiny)
                x += pill_w + 10

            title_lines = wrap_pixels(draw, display_value(row["title"]), f_body, title_width)
            yy += 50
            for line in title_lines:
                draw.text((margin + 108, yy), line, fill="#111827", font=f_body)
                yy += 32

            meta = f"品类：{display_value(row['category'])}    主题：{display_value(row['content_theme'])}    发布时间：{display_date(row['news_published_at'])}    收录：{display_value(row['collected_at'])[:19]}"
            for line in wrap_pixels(draw, meta, f_small, title_width):
                draw.text((margin + 108, yy + 8), line, fill="#64748b", font=f_small)
                yy += 26
            draw.text((margin + 108, y + row_h - 34), f"链接域名：{domain(display_value(row['url'], ''))}", fill="#64748b", font=f_tiny)
            y += row_h + row_gap
        y += 10

    draw.text((margin, height - 52), "本图仅呈现数据库条目，不包含分析及结论。完整可跳转链接见同目录 Markdown 周报。", fill="#64748b", font=f_small)
    img.save(path, quality=95)
    return path


def main() -> int:
    args = parse_args()
    start = args.start
    end = args.end
    db_path = Path(args.db)
    output_dir = Path(args.output_dir)
    rows = load_rows(db_path, start, end)
    if not rows:
        raise SystemExit(f"No report items found for {start} to {end}")
    md_path = write_markdown(rows, start, end, output_dir)
    image_path = render_image(rows, start, end, output_dir)
    print(f"rows: {len(rows)}")
    print(f"markdown: {md_path}")
    print(f"image: {image_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
