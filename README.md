# 竞品情报采集 Skill

这是一个可复用的 Codex skill 和本地采集工具，用于自动收集美妆、医药、计生/两性健康行业的公开竞品信息，并同步到本地 SQLite 数据库和 Obsidian 目录。

默认策略：

- 单日最多输出 30 条。
- 计生/两性健康占比严格大于 60%。
- 每条保留原标题、链接、新闻发布时间、收录时间、平台、品牌、品类、内容总结和选取原因。
- 新闻发布时间距离收集日不超过 6 个月。
- 跨天按 180 天窗口去重，同一天重跑允许覆盖刷新当天报告。
- 邮件发送默认关闭，只更新数据库和 Obsidian。

## 目录结构

```text
skill/competitor-intel-collector/SKILL.md  Codex skill
src/competitor_collector.py                采集器核心逻辑
scripts/run_collector.py                   手动运行入口
scripts/run_daily_db_update.ps1            每日数据库更新脚本
scripts/install_windows_task.ps1           Windows 计划任务安装脚本
scripts/generate_weekly_report.py          周报 Markdown/长图生成脚本
configs/collector_config.json              默认配置
configs/collector_config.example.json      配置模板
```

## 快速运行

```powershell
$py = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py .\scripts\run_collector.py --max-items 30 --no-email
```

默认写入：

- SQLite：`D:\kin\competitor_intel.db`
- Obsidian：`D:\kin\竞品情报\YYYY-MM-DD_竞品情报.md`
- 本地报告：`outputs\YYYY-MM-DD_competitor_brief.md` 和 `.csv`
- 原始抓取：`data\raw\YYYY-MM-DD_raw_items.jsonl`

## 安装每日任务

```powershell
.\scripts\install_windows_task.ps1
```

默认任务：

- 名称：`KinCompetitorDbUpdate`
- 时间：每天 09:05
- 动作：运行 `scripts\run_daily_db_update.ps1`
- 邮件：关闭

## 使用 Skill

将 `skill/competitor-intel-collector` 复制或同步到 Codex skills 目录后，可用类似请求触发：

```text
使用 competitor-intel-collector，今天重新采集竞品情报并验证 D:\kin 数据库和 Obsidian 是否更新。
```

Skill 会要求优先验证真实落地结果，包括 `collector_runs`、`report_items`、`intelligence_items`、OB 文件和自动化任务结果。

## 配置

主要配置在 `configs/collector_config.json`：

- `brands`：品牌和别名。
- `platforms`：平台和来源域名。
- `source_pack_queries`：官方/行业固定来源。
- `platform_search_queries`：微信、抖音、小红书、微博、知乎、B 站、电商等定向搜索。
- `supplemental_queries`：补充搜索词。
- `settings.required_report_industry`：默认 `计生/两性健康`。
- `settings.required_report_min_share`：默认 `0.6`，实际执行为严格大于 60%。
- `settings.report_duplicate_window_days`：默认 `180`。

## GitHub 注意事项

仓库不应提交以下内容：

- `data/` 原始抓取和去重状态。
- `outputs/` 日报、邮件草稿和自动化日志。
- `D:\kin` 本地数据库或 Obsidian 文件。
- SMTP 密码、邮箱授权码、Cookie、浏览器会话或任何账号凭据。

