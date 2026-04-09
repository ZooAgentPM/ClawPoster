---
name: visual-rag-design
description: 自动生成设计海报/图片。当用户提出设计需求（如「帮我做个促销海报」「做一张活动通知图」「生成一张小红书封面」）时使用此技能。从本地模板库中智能选择最合适的模板，填写内容，渲染输出 PNG 图片。
---

# 虾稿设计 — 参考手册

<!-- v1.5 — 从行为脚本改为情景/工具说明书 -->

## 模板目录

共10套模板，完整数据：`/Users/mlamp/visual-rag/data/template_index_v2.json`

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

`content_density`：light = 1-2个大字槽；medium = 3-5个槽；heavy = 多槽+长文本+列表

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
| `hint` | 填写建议 |
| `current` | 原始占位内容（字数和节奏参考） |

---

## 渲染工具

**渲染命令：**
```bash
cd /Users/mlamp/visual-rag && .venv/bin/python src/render_single.py \
  --id <模板ID> \
  --slots '{"<uuid>":"<内容>","<uuid>":"<内容>"}' \
  --adjustments '[{"id":"<uuid>","style":{"transform":"translateY(-30px)"}}]'
```

**输出：** 渲染成功后 stdout 输出两行：
```
RENDER:/Users/mlamp/visual-rag/data/renders/t<ID>_render.png
INSPECT:/Users/mlamp/visual-rag/data/renders/t<ID>_inspect.png
```

- `render.png`：最终效果图
- `inspect.png`：元素标注图，每个带 ID 的元素用彩色边框标注，左上角显示 UUID 前8位

渲染完成后用 Read 工具查看这两张图，确认内容注入正确、视觉无明显异常；发现问题用 `--adjustments` 调整后重渲。

**`--adjustments` 支持的 style 属性：**
`transform`（translateX/Y、scale）、`display: none`（隐藏元素）、`opacity`、`width`、`fontSize`、`top`、`left`

**依赖服务：**
```bash
# mock API（端口 7001）
cd /Users/mlamp/visual-rag && .venv/bin/python src/mock_api_server.py &

# Vite 前端（端口 5173）—— 必须从此目录启动
cd /Users/mlamp/Desktop/虾稿设计-01/渲染器/poster-design && npm run dev -- --port 5173 --host 127.0.0.1 &
```

检查是否已启动：`curl -s http://127.0.0.1:7001/design/temp?id=708 | head -c 50`

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
