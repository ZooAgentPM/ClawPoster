# MCP 工具返回值说明

---

## ensure_services

**返回类型**：`str`（纯文本）

```
✓ 所有服务就绪

  ✓ mock_api:7001: already running
  ✓ vite:5173: already running
  ✓ render_server:7002: already running

─────────────────────────────
💡 环境就绪。

通常按这个顺序走会比较顺：
  1. ensure_services   ← 当前
  2. search_templates  — 找到视觉风格合适的模板
  3. get_template_spec — 看清槽位结构和字数限制
  4. 填写内容          — 真实用户信息建议先向用户确认
  5. generate_poster   — 图片会直接在响应里返回
  6. 验收              — 确认没问题后把链接发给用户

建议从 search_templates 开始，带上缩略图方便视觉选模板。
如果需要做的内容非常多，建议创建子 Agent 来完成图片工作，尽可能批量并行。
```

**失败时**：每个服务后面显示 `FAILED to start`，summary 行换成 `✗ 以下服务启动失败：[...]`

---

## search_templates

**返回类型**：`list[{"type": "text", "text": str}]`

```
语义搜索「清新减脂打卡封面」，匹配 8 个候选：

t553 (score=0.82)  清新手绘风健康生活封面
  视觉: 手绘 插画 清新 绿色
  配色: 绿色、白色、米色  版面: title_with_list  密度: medium

t149 (score=0.79)  轻量化运动打卡记录封面
  视觉: 简约 线条 运动 清爽
  配色: 蓝色、白色  版面: hero_text  密度: light

... （N 条）

─────────────────────────────
💡 选好模板后，建议调 get_template_spec 看槽位结构。
   UUID 每个模板不同，不从 spec 里取容易注入到错误位置。

   如果这批候选风格不合适：
   · 在 query 里加结构描述词再搜
   · 或用 list_templates 按版面类型过滤

📷 以上候选模板的缩略图预览（横排合图，每张下方标有模板 ID）：
   https://xxx.ngrok-free.dev/files/grid_553_149_xxx.png
   建议用 WebFetch 访问此 URL 查看各模板视觉风格。
   选定模板后，用选中的模板 ID 调用 get_template_spec 获取槽位详情。
```

**字段说明**：
- 每条候选：`t{id} (score={余弦相似度})` + `brief`（截40字）+ `visual_tags`（前4个）+ `color_palette`（前3个）+ `layout_structure` + `content_density`
- 缩略图合图 URL 仅 `include_thumbnails=True` 时出现
- `exclude` 参数生效时无额外提示，向量已在服务端处理

---

## list_templates

**返回类型**：`list[{"type": "text", "text": str}]`

```
共找到 12 个模板：

ID:553  [medium]  清新手绘风健康生活封面
  场景: 健康生活、减脂打卡
  视觉: 手绘 插画 清新 绿色
  配色: 绿色、白色、米色
  版面: title_with_list  背景: 纯色
  容量: main_title(≤10字) | list_item(≤15字)

... （N 条）

─────────────────────────────
💡 list_templates 是关键词匹配，语义理解有限。
   结果不理想时，search_templates 通常能找到更贴近需求的候选。
   选定后建议调 get_template_spec 获取槽位规格。

📷 以上候选模板的缩略图预览：
   https://xxx.ngrok-free.dev/files/grid_553_149_xxx.png
```

**字段说明**：
- 每条：`ID` / `[density]` / `brief` / `场景`（前2个）/ `visual_tags`（前4）/ `color_palette`（前3）/ `layout_structure` / `background_type` / `slot_capacity`（各槽 role + max_chars）
- 缩略图同 search_templates

---

## get_template_spec

**返回类型**：`str`（纯文本）

```
模板 553 — 共 6 个槽位

【必填槽位 3 个】
  uuid: 4b4c414680a0
    role: main_title | 最多10字 | 每行≤5字 | ⚠ 需手动\n换行
    来源: 可根据需求创作
    填写指引: 封面主标题，制造点击欲望
    示例: 21天减脂\n打卡计划

  uuid: 829a39150c12
    role: account_name | 最多12字
    来源: ⚠ 必须来自真实用户信息，不能编造
    填写指引: 账号名或品牌名
    示例: @健康生活研究所

  uuid: f3c2190a44bb
    role: list_item | 最多60字 | ⚠ 列表必须填满4条
    来源: 可根据需求创作
    填写指引: 每条一行，\n分隔，恰好4条
    示例: 第一周：建立饮食习惯\n第二周：加入有氧运动\n...

【可选槽位 3 个（可保留原值）】
  uuid: c9d1038ef201
    role: subtitle | 最多20字
    来源: 装饰文字，可保留默认
    示例: Health & Fitness

  ...

─────────────────────────────
💡 填写前建议先整体看一遍槽位结构，判断这个模板能不能装下用户的内容。
   槽位数量、版面结构、风格不匹配的话，现在换模板比渲完再返工省事。

   fill_source 值得注意：
   · 标注「真实用户信息」的槽位（账号名、品牌名等），建议先向用户确认再填
   · current 字段是字数节奏最直观的参考，内容大致对齐就不容易溢出

   如果模板不合适，可以带结构描述词重新 search_templates。
```

**字段说明**：
- 必填（`must_edit: true`）和可选槽位分组展示
- `来源` 三种值：`⚠ 必须来自真实用户信息` / `可根据需求创作` / `装饰文字，可保留默认`
- `line_break: true` → 显示 `⚠ 需手动\n换行`
- `list_line_count: N` → 显示 `⚠ 列表必须填满N条`
- `w-chart` 类型槽位有特殊格式（`value 为 JSON 字符串`）

---

## generate_poster

**返回类型**：`list[{"type": "text", "text": str}]`

```
✓ 渲染完成  模板: t553
  📥 render（成品）:  https://xxx.ngrok-free.dev/files/t553_xxx_render.png
  📥 inspect（标注）: https://xxx.ngrok-free.dev/files/t553_xxx_inspect.png
  render_path: /Users/.../data/renders/t553_xxx_render.png  ← 调用 get_slot_crops 时传此路径（每次渲染不同，必须用本次的）
  🔴 高危裁图 4b4c4146: https://xxx.ngrok-free.dev/files/t553_xxx_crop_4b4c4146.png

📊 质检报告
  🔴 4b4c4146 (main_title): 文字溢出，实际宽度超出槽位 23px
  🟡 829a3915 (account_name): 接近边缘，建议确认
  🟢 f3c2190a (list_item): 正常
  ⬜ c9d1038e (subtitle): 装饰/非必填

─────────────────────────────
💡 图片通过公网 URL 提供，建议用 WebFetch 访问 📥 URL 查看。

验收建议（先看质检报告，再看图）：

【有视觉能力的模型】
  🔴 有确认问题时：
    → 高危裁图 URL 已附在上方，建议先 WebFetch 确认具体溢出情况
    → 通常缩短对应槽位文字后重渲即可
    → 若是布局遮挡，参考 resource/ADJUSTMENTS.md 用 adjustments 微调
  🟡 疑似问题时：
    → 建议先用 get_slot_crops 放大看，确认后再决定要不要处理
  🟢 全部正常时：
    → 用 WebFetch 访问 📥 render URL，目视确认整体效果
    → 没问题就把 📥 render URL 发给用户

【非视觉模型】
  → 依据质检报告文字处理 🔴，🟡 从源头控制字数规避，🟢 直接把 📥 render URL 发给用户

批量生成时，建议每张独立验收后再做下一张。
```

**字段说明**：
- `render_path`：服务端本地路径，只用于传给 `get_slot_crops`，不能直接访问
- `🔴 高危裁图`：有 🔴 问题时才出现，每个问题槽位一条
- 质检报告颜色：🔴 已确认溢出 / 🟡 疑似（接近边缘）/ 🟢 正常 / ⬜ 装饰非必填
- `inspect` 图：每个槽位叠加彩色边框 + 左上角 UUID 前8位标注

---

## get_slot_crops

**返回类型**：`list[{"type": "text", "text": str}]`

```
↓ 4b4c4146 裁图: https://xxx.ngrok-free.dev/files/t553_xxx_crop_4b4c4146.png
↓ 829a3915 裁图: https://xxx.ngrok-free.dev/files/t553_xxx_crop_829a3915.png

─────────────────────────────
💡 用 WebFetch 访问上方裁图 URL 查看放大内容。
   · 文字明显被截断 → 缩短内容后重新 generate_poster
   · 布局位置问题 → 参考 resource/ADJUSTMENTS.md
   · 只是贴近边缘、内容完整 → 误报，继续验收
```

**字段说明**：
- 每个 uuid 一条裁图 URL
- uuid 报错时（找不到对应槽位）显示 `❌ {uuid[:8]}: {error}`
- 裁图默认留白 20px（`pad` 参数可调）

---

## 通用错误格式

所有工具在异常时均返回：

```
[{"type": "text", "text": "具体错误描述"}]
```

常见错误：
- `render_server 未就绪，请先调用 ensure_services`
- `渲染失败：模板数据不存在: .../palxp-raw/t{id}_layers.json`
- `search_templates 失败：{网络错误}`
- `裁图失败：{错误}`
