# 行业竞品信息收集工具 V1

这是一个本地可运行的竞品信息收集工具，覆盖美妆、医药、计生/两性健康行业。工具会从公开搜索、新闻源、社交内容入口和行业来源中发现信息，保留原标题和可跳转链接，并为每条信息生成 AI 总结、内容总结、选取原因、发布时间和收录时间。

## 默认机制

- 单日输出不超过 30 条。
- 计生/两性健康在日报中严格大于 60%。
- 每条信息保留：行业、品牌、品类、平台、来源、原标题、原始链接、新闻发布时间、收录时间、AI 总结、内容总结、相关性理由、选取原因、等级。
- 新闻发布时间距离收集日不超过 6 个月。
- 跨天按 180 天窗口去重，同一天重跑允许覆盖刷新当天报告。
- 数据同步到本地 SQLite：`D:\kin\competitor_intel.db`。
- Obsidian 同步目录：`D:\kin\竞品情报`。
- OB 数据库同步目录：`D:\kin\OB数据库\08 项目\竞品情报收集`。
- 邮件发送已关闭，当前自动化任务只更新数据库和 Obsidian。

## 运行

```powershell
$py = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py .\scripts\run_collector.py --max-items 30 --no-email
```

可选参数：

```powershell
& $py .\scripts\run_collector.py --max-items 30
& $py .\scripts\run_collector.py --source-mode news --no-email
& $py .\scripts\run_collector.py --source-mode bing --no-email
```

## 输出文件

- `outputs\YYYY-MM-DD_competitor_brief.md`：当日日报 Markdown。
- `outputs\YYYY-MM-DD_competitor_brief.csv`：当日日报 CSV。
- `data\raw\YYYY-MM-DD_raw_items.jsonl`：原始抓取结果。
- `D:\kin\competitor_intel.db`：本地 SQLite 数据库，包含 `collector_runs`、`intelligence_items`、`report_items`。
- `D:\kin\竞品情报\YYYY-MM-DD_竞品情报.md`：Obsidian 可读日报。
- `D:\kin\竞品情报\每日简报\YYYY-MM-DD 竞品信息简报.md`：沉淀到竞品情报目录的正式日报，包含 AI 总结。
- `D:\kin\竞品情报\情报条目\*.md`：每条收录内容的竞品情报笔记，包含 `## AI总结`、选取原因和检索上下文。
- `D:\kin\OB数据库\08 项目\竞品情报收集\每日运行\YYYY-MM-DD 竞品情报收集.md`：OB 数据库项目日报。
- `D:\kin\OB数据库\08 项目\竞品情报收集\情报条目\*.md`：每条入库日报条目的独立 OB 数据库笔记。

## 自动化

Windows 计划任务名称：`KinCompetitorDbUpdate`。

脚本入口：

```powershell
.\scripts\run_daily_db_update.ps1
```

日志目录：

```text
outputs\automation\
```

## 配置

核心配置在 `configs\collector_config.json`：

- `settings.max_daily_items` 控制单日上限，默认 30。
- `settings.required_report_industry` 默认 `计生/两性健康`。
- `settings.required_report_min_share` 默认 `0.6`，实际执行为严格大于 60%。
- `settings.report_duplicate_window_days` 控制跨天去重窗口，默认 180。
- `brands` 控制品牌池和别名。
- `platforms` 控制平台和域名识别。
- `source_registry` 控制结构化来源池，可按行业、域名、模板、单来源查询上限扩展高信号来源。
- `source_pack_queries` 控制官方/行业固定来源。
- `platform_search_queries` 控制微信公众号、抖音、小红书、微博、知乎、B 站、电商等定向搜索。
- `supplemental_queries` 控制补充搜索词。
- `settings.ob_database_sync_enabled` 控制是否同步到 `D:\kin\OB数据库`。
- `settings.ob_competitor_project_folder` 默认 `08 项目\竞品情报收集`。

## 社媒扩源：小红书/抖音

社媒扩源使用浏览器授权采集，不绕过登录、验证码或平台风控。首次使用先打开持久化浏览器 profile 完成登录：

```powershell
.\scripts\run_social_browser_collect.ps1 --login-only --platforms xiaohongshu,douyin --login-wait-seconds 240
```

登录后运行小规模试采集：

```powershell
.\scripts\run_social_browser_collect.ps1 --platforms xiaohongshu,douyin --queries "杰士邦 被卖,乐福思 股权转让,杜蕾斯 杰士邦 冈本 测评" --limit-per-query 5 --output 2026-06-12_social_pilot.jsonl
```

导入社媒候选池：

```powershell
$py = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py .\scripts\import_social_candidates.py --input data\social\2026-06-12_social_pilot.jsonl --date 2026-06-12
```

导入后会写入：

- `D:\kin\competitor_intel.db` 的 `intelligence_items` 候选记录。
- `outputs\YYYY-MM-DD_social_candidates.md/csv`。
- `D:\kin\竞品情报\社媒候选\YYYY-MM-DD 社媒候选.md`。
- `D:\kin\OB数据库\08 项目\竞品情报收集\社媒候选\YYYY-MM-DD 社媒候选.md`。

如果采集结果只有 `status: login_required`，说明浏览器授权尚未完成或登录态失效，需要重新运行登录命令并扫码。

## 验收要点

不要只看脚本是否运行完成，要验证真实落地结果：

- `collector_runs` 有最新运行记录。
- `report_items` 有当天日报条目。
- `intelligence_items.content_summary` 非空。
- `intelligence_items.ai_summary` 非空。
- 当天计生/两性健康占比严格大于 60%。
- `D:\kin\竞品情报\YYYY-MM-DD_竞品情报.md` 实际存在并更新。
- `D:\kin\竞品情报\每日简报` 和 `D:\kin\竞品情报\情报条目` 实际存在并更新，且情报条目包含 `## AI总结`。
- `D:\kin\OB数据库\08 项目\竞品情报收集` 下的每日运行和情报条目实际存在并更新。
