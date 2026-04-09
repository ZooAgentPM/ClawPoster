---
name: visual-rag-design
description: 自动生成设计海报/图片。当用户提出设计需求（如「帮我做个促销海报」「做一张活动通知图」「生成一张小红书封面」）时使用此技能。通过 visual-rag MCP 服务直接生成 PNG 图片，图片实时返回对话，无需管理文件或服务。
---

# 虾稿设计

使用 `visual-rag` MCP 工具生成设计图片。

MCP 服务地址：`https://syncopated-retractively-anitra.ngrok-free.dev/mcp`
若工具不可用或域名失效，告知用户联系**小邹**获取新地址。

---

## 工具与流程

**1. `search_templates(query, size_type?)`**
根据自然语言需求语义搜索模板。返回 Top 5 候选列表 + 一张缩略图合图（横排，下方标注模板 ID）。
将合图展示给用户，从候选中选出最合适的一个。

**2. `get_template_spec(id)`**
获取选定模板的槽位详情（uuid、role、max_chars、hint、current）。

**3. `generate_poster(id, slots, adjustments?)`**
渲染并返回两张图：**render**（成品）+ **inspect**（UUID 标注图，用于定位元素坐标）。

---

## 槽位填写

- `must_edit: true` 的槽位必须填写，其余保留原值
- `line_break: true` → 手动加 `\n` 换行，不靠自动折行
- `list_line_count: N` → 必须填满 N 条
- 参考 `current` 控制每行字数，不大幅超出 `max_per_line`

---

## 布局微调

inspect 图左上角显示 UUID 前 8 位，用于定位元素。先看 render 图确认内容，inspect 图仅用于坐标参考。

adjustments 支持：`transform` / `display: none` / `opacity` / `fontSize` / `top` / `left`

---

## 原则

- **内容优先**：内容多换高密度模板，不删减用户内容
- **给成品**：自行调整到满意后再展示，不问用户要不要继续
- 渲染完成后展示 render 图，并提供响应中返回的下载链接（不自行构造文件名）
