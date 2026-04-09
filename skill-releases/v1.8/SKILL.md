---
name: visual-rag-design
description: 自动生成设计海报/图片。当用户提出设计需求（如「帮我做个促销海报」「做一张活动通知图」「生成一张小红书封面」）时使用此技能。从本地模板库中智能选择最合适的模板，填写内容，渲染输出 PNG 图片。
---

# 虾稿设计 — 参考手册

<!-- v1.8 — slot_capacity 粗过滤 -->

## 模板目录

共 **95套** 模板（10套原版 + 85套新增），完整数据：`/Users/mlamp/visual-rag/data/template_index_v2.json`

选模板时，用 Read 工具读取 template_index_v2.json，根据以下字段综合判断：

| 字段 | 说明 | 选模板用途 |
|------|------|-----------|
| `brief` / `scenarios` | 语义描述和适用场景 | 主要匹配依据 |
| `content_density` | light/medium/heavy | 与内容信息量匹配 |
| `slot_capacity` | 各必填槽位容量（见下方说明） | **容量粗过滤，排除放不下的模板** |
| `background_type` | 背景类型（见下表） | 排除风格明显不符的模板 |
| `text_align_main` | 主标题对齐方式（justify/center/left） | 判断排版风格 |
| `has_non_replaceable_images` | true = 含不可替换的产品/示例图 | 避免选到无法自定义的模板 |

**容量粗过滤（`slot_capacity`）：**

`slot_capacity` 是每个模板所有 `must_edit` 槽位的容量摘要，在读取 template_index_v2.json 时即可直接对比，无需再读 edit_spec。

```json
"slot_capacity": [
  {"role": "main_title", "max_chars": 16, "max_per_line": 6, "line_break": true},
  {"role": "content_list", "max_chars": 80, "max_per_line": 9, "line_break": true}
]
```

过滤规则：

1. **按 role 匹配**：用户内容中最长的主标题 → 对应 `main_title` 槽位；列表条目 → 对应 `content_list` 槽位
2. **总字数**：内容字数 > `max_chars` × 1.2，排除该模板
3. **每行字数**：`line_break: true` 的槽位，内容最长一行 > `max_per_line` + 2，排除该模板

> 注意：`max_per_line` 和 `max_chars` 均为估算值，±2字以内属正常误差，允许略超。真正的硬性判断只需排除明显放不下的情况（超出20%以上）。

**`background_type` 参考值：**

| 值 | 含义 |
|----|------|
| `white_minimal` / `gray_minimal` | 干净极简，适合大多数内容 |
| `white_illustrated` / `illustrated_*` | 含插画/手绘装饰，风格性强 |
| `white_blank` | 无背景设计，慎用（可能视觉效果差） |
| `photo` | 背景图片，文字需与图对比 |
| `illustrated_manga` | 漫画爆炸感，冲击力强 |

> `background_type` 仅对部分已确认的模板设置，未设置的模板需渲染验证。

### 模板分类速查

**小红书封面（60套）** — size 1242×1656 或 1242×1660，单图封面

| 风格类型 | 代表模板 ID | 适用场景 |
|---------|------------|---------|
| 极简大字/爆款 | 708, 703, 699, 186, 412, 419, 553, 643, 680, 681, 682, 683, 684, 686, 693, 712, 871, 873, 878, 884 | 话题封面、爆款内容、情感表达 |
| 双段/双层结构 | 699, 189, 426, 702, 872 | 方法论、攻略、日签 |
| 多段/列表型 | 689, 183, 503, 185, 460 | 干货攻略、知识科普、新手入门 |
| 对比/讨论型 | 424, 425, 685 | 好坏对比、A vs B、话题讨论 |
| 特殊结构 | 359（数据表格）, 505（emoji解释）, 879（竖排五字）, 880（备忘录）, 910（复杂备忘录20+槽） | 数据/特殊布局需求 |
| 节日/活动 | 337, 528, 542, 631, 869 | 节日促销、政策活动 |
| 情感/语录 | 461, 503, 643, 871 | 情感共鸣、日签语录 |
| 知识/科普 | 188, 416, 418, 463, 870 | 知识科普、金融、教育 |
| 品牌/日签 | 426 | 企业日签 |

**手机海报（15套）** — size 1242×2208，竖版长图

| 风格类型 | 代表模板 ID | 适用场景 |
|---------|------------|---------|
| 节日贺卡 | 7, 200, 687 | 节日祝福、晚安、毕业 |
| 通知/招聘 | 12, 278, 676, 678 | 会议、招聘、政务通知 |
| 活动营销 | 239, 267, 451, 913 | 直播预告、课程招生、招商 |
| 清单/攻略 | 1, 620 | 计划清单、备考攻略 |
| 日签/激励 | 214, 660 | 微商日签、开学激励 |

**小红书配图（20套）** — size 1242×1656 或 1242×1660，正文配套图

| 风格类型 | 代表模板 ID | 适用场景 |
|---------|------------|---------|
| 干货列表（多条） | 179（10条）, 181（10条）, 182（14条）, 216（7条）, 217（6条） | 攻略、备考、知识清单 |
| 朋友圈文案 | 494（6条）, 629（7条） | 跨年/节日朋友圈文案 |
| 对比型 | 896（PK双项）, 909（VS多维） | 产品对比、方案比较 |
| 活动/互动 | 548（活动详情）, 657（集赞奖品） | 宠粉活动、互动营销 |
| 清单/好物 | 647（资料10项）, 664（清单）, 670（清单A）, 671（清单B）, 690（好物3项） | 资料合集、开学清单、好物推荐 |
| 推文/语录 | 645（推文配图）, 646（金句）, 610（攻略详情22槽） | 账号推文、书摘金句 |
| 评测 | 669（3维度评测） | 产品多维评测 |

### 原版10套（精选核心模板）

| ID | 风格 | 内容体量 | 适用场景 | 品牌区域 |
|----|------|---------|---------|---------|
| 708 | 极简冲击 | light | 学习方法、情绪调节、职场干货 | — |
| 703 | 直给冲击 | light | 内容运营、爆款技巧、涨粉攻略 | — |
| 699 | 简洁利落 | light | 求职技巧、效率提升、职场晋升 | — |
| 883 | 简约权威 | light | 每日资讯、财经热点、日报周报 | — |
| 704 | 警示活泼 | light | 避坑指南、消费决策、重要提醒 | — |
| 672 | 文艺温暖 | medium | 励志语录、每日一句、个人品牌 | Logo + 二维码 |
| 701 | 中英双语简约 | medium | 内容种草、书影音推荐、英语学习 | — |
| 689 | 干货清单 | medium | 攻略、步骤清单、新手入门 | — |
| 905 | 喜庆热闹 | medium | 促销活动、节日大促、电商营销 | — |
| 677 | 正式权威 | heavy | 机构通知、招聘公告、知识科普（含6条列表） | Logo + 二维码 |

`content_density`：light ≤3个编辑槽；medium = 4-8个；heavy = 9+个

各模板详细槽位规格见 `edit_spec` 字段路径，封面预览见 `cover` 字段。

---

## 槽位字段说明

每个 edit_spec JSON 含 `slots` 数组：

| 字段 | 说明 |
|------|------|
| `uuid` | DOM 元素 ID，用于 --slots 和 --adjustments |
| `role` | 语义角色（main_title / subtitle / content_list 等） |
| `must_edit` | true = 必须填入真实内容；false = 可保留 current |
| `max_chars` | 总字数上限 |
| `line_break` | true = 用 `\n` 手动控制换行 |
| `list_line_count` | 列表槽专用：模板固定装饰行数，内容须填满该行数，否则出现裸露空行 |
| `char_px` | 单字像素宽（约）= fontSize × (1 + letterSpacing/100) |
| `element_width_px` | 文本框宽度（像素） |
| `max_per_line` | 每行最多字数参考 = floor(element_width_px / char_px)；justify 模板此值为压缩临界点，略超1-2字通常可接受 |
| `hint` | 填写建议 |
| `current` | 原始占位内容（字数和节奏参考，**最可靠的每行字数参考**） |

---

## 渲染工具

### 推荐：render_server HTTP 接口（browser 复用，速度快）

```bash
# 渲染命令（POST JSON）
curl -s -X POST http://127.0.0.1:7002/render \
  -H "Content-Type: application/json" \
  -d '{"id": <模板ID>, "slots": {"<uuid>": "<内容>"}, "adjustments": [{"id":"<uuid>","style":{"transform":"translateY(-30px)"}}]}'
```

**返回 JSON：**
```json
{"render": "/Users/mlamp/visual-rag/data/renders/t<ID>_render.png",
 "inspect": "/Users/mlamp/visual-rag/data/renders/t<ID>_inspect.png"}
```

健康检查：`curl -s http://127.0.0.1:7002/health`

### 备用：CLI 单次渲染（无需 render_server）

```bash
cd /Users/mlamp/visual-rag && .venv/bin/python src/render_single.py \
  --id <模板ID> \
  --slots '{"<uuid>":"<内容>"}' \
  --adjustments '[{"id":"<uuid>","style":{"transform":"translateY(-30px)"}}]'
```

stdout 输出两行：`RENDER:/path/render.png` + `INSPECT:/path/inspect.png`

---

渲染完成后用 Read 工具查看这两张图，确认内容注入正确、视觉无明显异常；发现问题用 `adjustments` 调整后重渲。

**`adjustments` 支持的 style 属性：**
`transform`（translateX/Y、scale）、`display: none`（隐藏元素）、`opacity`、`width`、`fontSize`、`top`、`left`

**依赖服务（三个，全部需要运行）：**
```bash
# 1. mock API（端口 7001）
cd /Users/mlamp/visual-rag && .venv/bin/python src/mock_api_server.py &

# 2. Vite 前端（端口 5173）—— 必须从此目录启动
cd /Users/mlamp/Desktop/虾稿设计-01/渲染器/poster-design && npm run dev -- --port 5173 --host 127.0.0.1 &

# 3. render_server（端口 7002）—— 推荐使用，browser 复用提速
cd /Users/mlamp/visual-rag && .venv/bin/python src/render_server.py &
```

健康检查：`curl -s http://127.0.0.1:7002/health`（`{"status":"ready"}` 即可）

---

## 品牌区域（t672 / t677）

品牌区域由两个元素组成视觉整体：**圆形图标（w-image）** + **品牌文字（logo_text 槽位）**。

**内置默认值：**
- 圆形图标：蓝紫渐变 M 图标（已内置于模板）
- logo_text 槽位默认值：`YOUR LOGO`
- brand 槽位（底部署名）默认值：`遨游设计`
- 二维码：微信收款码（已内置，wxp://...）

**两种使用情况：**

| 情况 | 处理方式 |
|------|---------|
| 文字品牌（任何文字名称） | 填写 logo_text 槽位，圆形图标保持内置默认 |
| 外部图片 Logo | --adjustments 隐藏圆形图标和 logo_text；渲染后用 Pillow 将图片叠加到品牌区域 |

**Pillow 叠加参考：**
```python
from PIL import Image
base = Image.open("t677_render.png")
logo = Image.open("logo.png").convert("RGBA")
# 裁切透明边距 → 缩放到合适宽度（约400-500px，保持比例）→ 粘贴到品牌区域坐标
# 品牌区域坐标参考 inspect.png 中对应元素位置
base.paste(logo_resized, (x, y), logo_resized)
base.save("t677_final.png")
```

注：每次重渲后需重新执行叠加，不能复用上次的 final 图。

---

## 与用户的交互准则

- **用户看不到渲染图**：对话中无法展示图片，完成后需用 `open` 命令在用户电脑上打开
  ```bash
  open /Users/mlamp/visual-rag/data/renders/t<ID>_render.png
  ```
- **多方案自己比较**：有多个调整思路时，逐一渲染并用 Read 自行比较，选出最佳后再展示给用户，不在中间过程询问用户选哪个
- **给成品，不给过程**：用户看到的应该是已经自检通过的成品，而不是待确认的中间状态

---

## 常见错误

| 错误信息 | 原因 |
|---------|------|
| 找不到画布元素 | Vite 服务未启动，或从错误目录启动 |
| 模板数据不存在 | 模板 ID 不在 data/palxp-raw/，换模板重试 |
| 端口占用 | 服务已在运行，直接渲染即可 |

**Read 工具读图看不到内容：** 确认使用支持视觉的模型（claude-sonnet-4-6）；检查模型配置 `input` 字段是否含 `"image"`
