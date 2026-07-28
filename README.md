# 行业竞品情报收集工具

本仓库是一个本地运行的竞品情报采集与沉淀工具，面向美妆、医药、计生/两性健康等行业。它从公开搜索、新闻源和授权浏览器采集入口发现候选信息，整理为日报、候选池、SQLite 数据库记录和 Obsidian 笔记。

## 项目结构

| 路径 | 用途 |
|---|---|
| `src/competitor_collector.py` | 主采集器：公开搜索、去重、筛选、数据库写入、日报生成、Obsidian 同步。 |
| `scripts/run_collector.py` | Python 主采集器命令行入口。 |
| `scripts/import_social_candidates.py` | 将小红书/抖音浏览器采集 JSONL 导入候选池和本地数据库。 |
| `scripts/generate_weekly_report.py` | 基于 `D:\kin\competitor_intel.db` 生成周报 Markdown 和长图。 |
| `scripts/social_browser_collect.mjs` | Playwright 授权浏览器采集脚本。 |
| `scripts/run_social_browser_collect.ps1` | Windows PowerShell 封装入口，会按需安装 Node 依赖。 |
| `scripts/run_daily_db_update.ps1` | 每日自动更新入口。 |
| `scripts/send_daily_email.py` | 日报邮件发送辅助脚本。 |
| `configs/collector_config.json` | 主采集配置：行业、品牌、来源、查询词、数据库/Obsidian 路径。 |
| `configs/social_browser_config.json` | 社媒浏览器采集配置。 |
| `docs/CODE_INDEX.md` | 更详细的代码索引、运行链路和验证清单。 |

运行产物默认写入 `data/`、`outputs/` 和 `D:\kin`，这些目录不应作为源码上传。

## 默认机制

- 单日输出默认不超过 30 条。
- 计生/两性健康在日报中保持配置要求的最低占比。
- 跨天按配置窗口去重，同一天重跑允许覆盖刷新当天报告。
- 数据同步到本地 SQLite：`D:\kin\competitor_intel.db`。
- Obsidian 同步目录：`D:\kin\竞品情报`。
- OB 数据库同步目录：`D:\kin\OB数据库\08 项目\竞品情报收集`。

## 环境要求

- Windows + PowerShell。
- Python 3.11+。本机推荐使用 Codex bundled Python：

```powershell
$py = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
```

- Node.js + npm，用于 Playwright 社媒采集。
- 已登录的小红书/抖音浏览器 profile，仅用于合规的授权浏览器采集，不绕过登录、验证码或平台风控。

## 安装

```powershell
npm install
```

Python 当前只使用标准库；`scripts/generate_weekly_report.py` 需要 Pillow：

```powershell
& $py -m pip install pillow
```

## 运行主采集

```powershell
$py = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py .\scripts\run_collector.py --max-items 30 --no-email
```

常用参数：

```powershell
& $py .\scripts\run_collector.py --source-mode both --max-items 30 --no-email
& $py .\scripts\run_collector.py --source-mode news --max-items 30 --no-email
& $py .\scripts\run_collector.py --source-mode bing --max-items 30 --no-email
```

## 运行社媒授权采集

首次使用先打开持久化浏览器 profile 完成登录：

```powershell
.\scripts\run_social_browser_collect.ps1 --login-only --platforms xiaohongshu,douyin --login-wait-seconds 240
```

登录后小规模采集：

```powershell
.\scripts\run_social_browser_collect.ps1 --platforms xiaohongshu,douyin --queries "杜蕾斯 避孕套,杰士邦 润滑剂,冈本 测评" --limit-per-query 5
```

导入社媒候选池：

```powershell
& $py .\scripts\import_social_candidates.py --input data\social\YYYY-MM-DD_social_raw.jsonl --date YYYY-MM-DD
```

## 输出

- `outputs\YYYY-MM-DD_competitor_brief.md`
- `outputs\YYYY-MM-DD_competitor_brief.csv`
- `data\raw\YYYY-MM-DD_raw_items.jsonl`
- `D:\kin\competitor_intel.db`
- `D:\kin\竞品情报\...`
- `D:\kin\OB数据库\08 项目\竞品情报收集\...`

## 验证

上传或交付前至少运行：

```powershell
$py = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m py_compile src\competitor_collector.py scripts\run_collector.py scripts\import_social_candidates.py scripts\generate_weekly_report.py
node --check scripts\social_browser_collect.mjs
git status --short
```

如果执行真实采集，还要验证 SQLite 表、当日报告、Obsidian 同步文件和候选池文件是否真实更新。
