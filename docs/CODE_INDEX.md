# 代码索引

## 主流程

1. `scripts/run_collector.py` 将仓库根目录下的 `src/` 放入 `sys.path`。
2. `src/competitor_collector.py` 读取 `configs/collector_config.json`。
3. 采集器按配置生成查询词，调用公开新闻/RSS/搜索源。
4. 采集结果写入 `data/raw/`，再按行业、品牌、来源、分数、日期窗口去重和筛选。
5. 入选条目写入 `D:\kin\competitor_intel.db` 的 `collector_runs`、`intelligence_items`、`report_items`。
6. 同步生成 `outputs/` 日报和 `D:\kin` 下的 Obsidian 笔记。

## 文件职责

### Python

- `src/competitor_collector.py`
  - 配置加载：`load_config`
  - 数据库路径：`database_path_from_config`
  - 数据库建表/补列：`ensure_database`
  - 搜索源采集：`search_google_news`、`search_bing_web`
  - 结果标准化：`SearchResult`
  - 去重和可见相关性过滤：`_passes_visible_relevance_gate`
  - 报告生成和 Obsidian 同步：`_write_competitor_intel_mirror_from_db`
  - CLI 入口：`build_parser`、`run`

- `scripts/import_social_candidates.py`
  - 读取 `scripts/social_browser_collect.mjs` 输出的 JSONL。
  - 将小红书/抖音候选内容转换成 `SearchResult`。
  - 可选择把高分候选提升到当日 `report_items`。

- `scripts/generate_weekly_report.py`
  - 从 SQLite 读取指定日期范围的 `report_items`。
  - 输出周报 Markdown 和一张长图。
  - 需要 Pillow。

- `scripts/send_daily_email.py`
  - 邮件发送辅助逻辑。
  - SMTP 配置从环境变量读取，不应写入仓库。

### Node/PowerShell

- `scripts/social_browser_collect.mjs`
  - 使用 Playwright 持久化浏览器 profile。
  - 支持 `--login-only`、`--platforms`、`--queries`、`--limit-per-query`、`--output`。
  - 输出 JSONL 到 `data/social/`，截图到 `outputs/social_screenshots/`。

- `scripts/run_social_browser_collect.ps1`
  - 社媒采集 Windows 封装入口。
  - 如果 `node_modules/playwright` 不存在，会设置 `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` 后运行 `npm install`。

- `scripts/run_daily_db_update.ps1`
  - 每日自动更新封装入口，适合 Windows 计划任务。

## 配置索引

- `configs/collector_config.json`
  - `settings.max_daily_items`：单日最多报告条目数。
  - `settings.required_report_industry`：日报必保行业。
  - `settings.required_report_min_share`：必保行业最低占比。
  - `settings.database_dir` / `database_file`：SQLite 输出位置。
  - `settings.obsidian_*`：Obsidian 主同步目录。
  - `brands`：行业、品牌、别名和优先级。
  - `platforms`：来源平台和域名识别。
  - `source_pack_queries`、`platform_search_queries`、`supplemental_queries`：查询词池。

- `configs/social_browser_config.json`
  - 社媒平台搜索 URL、浏览器 profile、滚动和截图参数。

## 运行产物

这些内容是运行产物，默认通过 `.gitignore` 排除：

- `data/`
- `outputs/`
- `node_modules/`
- `*.db`、`*.sqlite`、`*.sqlite3`
- `.env`、`.env.*`
- Python 缓存目录

## 上传前检查

```powershell
$py = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m py_compile src\competitor_collector.py scripts\run_collector.py scripts\import_social_candidates.py scripts\generate_weekly_report.py
node --check scripts\social_browser_collect.mjs
git status --short
```

## 已知问题

- 仓库当前不提交 `D:\kin` 数据库和 Obsidian 输出，只提交工具代码、配置和文档。
- PowerShell 默认编码可能导致中文输出显示异常；检查文件内容时优先使用 UTF-8 工具或 `git diff`。
