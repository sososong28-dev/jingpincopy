---
name: ppt-skill
description: Fixed swimlane-first UI and structural framework for Chinese product department weekly or quick report PowerPoint decks. Use when Codex creates, redesigns, or updates 产品部周汇报, 产品部快速汇报, 进度同步PPT, 事项汇报PPT, 稽查流程PPT, 控价流程PPT, 串货处理PPT, or similar product-team operating review decks that need consistent layout, typography, palette, workflow diagrams, responsibility matrices, and QA standards.
---

# PPT Skill

## Purpose

Apply the permanent design framework for product department weekly or quick report decks. Treat this skill as a visual system and slide-structure standard, not as a content source.

When building the actual `.pptx`, also use the Presentations skill and its artifact-tool workflow. This skill defines what the deck should look like and how pages should be organized.

## Core Direction

Use a pragmatic operating-review style:

- Primary design pattern: horizontal swimlane workflow.
- Secondary pattern: responsibility matrix for cross-department roles.
- Supporting pattern: concise matter pages for progress, evidence, and next actions.
- Avoid AI dashboard-style mockups, fake UI screenshots, decorative data cards, marketing hero pages, and generic SaaS layouts.
- Keep every meaningful element editable in PowerPoint.

## Non-Negotiables

- Use 16:9 widescreen PowerPoint.
- Build a work-report deck, not a marketing deck.
- Do not invent business conclusions, metrics, deadlines, owners, or action items.
- Use the user's provided content as source of truth. If content is missing, use concise placeholders or ask for it.
- Follow the `事项X · 主题` title pattern for main slides.
- Keep each main slide claim-led: one title, one short summary sentence, then structured proof, workflow, matrix, or progress modules.
- Do not include content categories the user removed from the deck.
- Do not flatten the deck into screenshots except when screenshots are source evidence.

## Visual System

### Palette

Use a white or very light blue report background.

- Primary navy: `#061B4E` for main titles and top bars.
- Main blue: `#0B4FD3` for 产品部, current-state labels, and primary workflow nodes.
- Deep blue: `#003B9E` for left rails and emphasis blocks.
- Teal: `#007F73` for 业务部, execution states, and resolution modules.
- Light blue fill: `#F3F8FF` for swimlane bands and page sections.
- Pale neutral fill: `#F7FAFC` for matrix cells and low-emphasis modules.
- Border blue: `#BFD7F7` for product-side cards.
- Border teal: `#B7DDD8` for business-side cards.
- Neutral text: `#172033` for body copy.
- Muted text: `#5E6B7D` for notes and secondary labels.
- Escalation red: `#E33131` only for unresolved risks, escalation arrows, or warning states.
- Success green: `#0E9F6E` only for closed-loop or completed states.

Balance navy, blue, teal, neutral fills, and limited red/green. Do not let the deck become a one-hue blue template.

### Typography

Use Chinese system fonts that render reliably in PowerPoint:

- Preferred: Microsoft YaHei / Microsoft YaHei UI.
- Alternative: DengXian or SimHei for heavy labels.
- Cover title: 36-44 pt, bold.
- Main slide title: 24-30 pt, bold.
- Summary sentence: 13-16 pt.
- Lane headers and module headings: 13-17 pt, bold.
- Body bullets: 10.5-14 pt.
- Footer and metadata: 8-10 pt.

Use `0` letter spacing. Avoid text below 8 pt.

### Layout Grid

- Canvas: 13.333 x 7.5 in.
- Outer margin: 0.35-0.5 in.
- Header zone: 0.55-0.75 in.
- Footer metadata: bottom right or bottom center, low contrast.
- Minimum inner gutter: 0.12 in.
- Use consistent column widths in workflows and matrices.
- Use restrained rounded rectangles only for cards, pills, repeated nodes, and status chips.
- Do not place cards inside larger decorative cards. Use lane bands, grid cells, or direct layout groups.

## Deck Rhythm

Use this default sequence unless the user specifies otherwise:

1. Cover: deck name, date, department, optional topic list.
2. Optional overview: use only when the deck has more than three matters.
3. Matter slides: one or more pages per `事项`.
4. Closing slide: next-week focus, pending collaboration, or unresolved risks.

For short decks, skip the overview and go directly from cover to `事项一`.

## Slide Types

### Cover

Use a clean corporate title page:

- Main title: `产品部快速汇报` or user-provided title.
- Subtitle: topic list separated by `/`.
- Date: `YYYY.MM.DD`.
- Optional micro-label: `Internal Update | Product Team`.

Keep the cover plain, high-contrast, and report-oriented. Do not use a large image hero unless explicitly requested.

### Matter Slide

Use for normal weekly report pages.

Required structure:

- Top title: `事项一 · 稽查处理流程`
- One-line summary below title.
- Main body split into 2-4 logical modules.
- Footer: `产品部快速汇报` and page number if building a full deck.

Preferred modules:

- 当前状态
- 流程机制
- 关键证据
- 待解决问题
- 下一步动作

### Swimlane Workflow Slide

Use as the default core slide for 稽查流程, 控价流程, 串货处理, cross-department execution, and escalation mechanisms.

Build it as a horizontal swimlane:

- Rows are responsible parties or escalation levels.
  - Example rows: `产品部`, `业务部`, `总经办`, `公司层面`.
  - Alternative rows: `第一层沟通`, `第二层沟通`, `第三层沟通` when escalation level matters more than department.
- Columns are process stages.
  - Recommended columns: `发现问题`, `证据收集`, `沟通整改`, `升级处理`, `结果归档`.
- Left rail contains the row label. Use deep blue for primary process rows, teal for business/execution rows, and neutral/gray for company-level rows.
- Each cell contains one action node or a short status note.
- Arrows show handoff direction across columns.
- Red downward arrows show escalation only when unresolved.
- The final column should show closure: `问题解决`, `归档结果`, `持续监控`.

Design rules:

- Use light lane bands rather than heavy bordered containers.
- Keep all row heights consistent unless one row carries substantially more content.
- Align all nodes to a shared grid.
- Keep action text verb-led and short.
- Use icons sparingly: one small role/action icon per row or key node is enough.
- Do not use top responsibility cards if they duplicate swimlane rows.

### Responsibility Matrix Slide

Use when the deck needs to explain who owns what.

Structure:

- Rows: tasks or workflow stages.
- Columns: departments or roles.
- Cells: responsibility markers such as `主责`, `协同`, `知会`, `审批`, `执行`.
- Use color chips, not large filled cells, to keep the matrix readable.
- Add a one-line conclusion above the matrix, e.g. `产品部负责证据链，业务部负责对外整改，总经办负责升级处置。`

Use this instead of long paragraphs about responsibility boundaries.

### Progress Slide

Use for tracking product, channel, or action progress.

Structure:

- Left category rail or small section tags.
- Right grouped modules by status: `已完成`, `推进中`, `待确认`, `风险`.
- Include dates only when provided by the user.
- Keep bullet text short enough to scan at thumbnail size.

### Comparison Or Before/After Slide

Use for 整改前后, 方案对比, or channel handling differences.

Structure:

- Title and one-line conclusion.
- Two or three columns with identical dimensions.
- Each column has a concise label, evidence area, and conclusion chip.
- Use blue for baseline/current, teal or green for resolved/target, red only for risk.

### Selling-Point Breakdown Slide

Use for 产品卖点拆解.

Preferred structure:

- Left: product/category and 拆解目标.
- Center: 3-5 selling-point dimensions such as `功能利益`, `场景利益`, `人群痛点`, `信任背书`, `表达话术`.
- Right: output status or next action.

Use a matrix or modular grid. Do not force selling-point content into a process diagram unless the user explicitly frames it as a workflow.

### Closing Slide

Use a simple operating checklist:

- `下周重点`
- `需协同支持`
- `待决策/风险`

Do not add motivational closing slogans.

## Component Rules

- Section tags: compact rounded pills with blue or teal fill and white bold text.
- Status tags: compact chips, not button-like blocks.
- Icons: simple line icons, consistent stroke weight, only when they clarify the role or action.
- Arrows: blue or teal for normal flow, red only for escalation.
- Tables and matrices: light borders, bold header row, restrained fills.
- Screenshots/images: crop tightly, label clearly, and avoid blurry low-value images.
- Page numbers and report labels should be present but visually quiet.

## Writing Rules

Keep wording brief and report-oriented:

- Prefer verbs: `收集`, `判断`, `通知`, `整改`, `反馈`, `归档`, `监控`, `升级`, `处罚`.
- Prefer short bullets over paragraphs.
- Use conclusion labels such as `已完成`, `推进中`, `待确认`, `问题解决`, `持续监控`.
- Avoid explanatory filler and generic statements.
- Do not use AI-generated placeholder gibberish in visuals or mockups.

## QA Checklist

Before delivering a PPTX:

- Render previews or inspect the deck visually.
- Check title alignment, lane alignment, matrix alignment, arrow direction, and spacing.
- Confirm no text overflows or overlaps at slide size.
- Confirm every slide has a clear operating purpose.
- Confirm the core workflow uses swimlane structure when responsibility handoff is central.
- Confirm palette consistency across slides.
- Confirm removed topics are not present.
- Confirm the deck remains editable PowerPoint.
