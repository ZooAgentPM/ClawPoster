---
name: visual-rag-design
description: 自动生成设计海报/图片。当用户提出设计需求（如「帮我做个促销海报」「做一张活动通知图」「生成一张小红书封面」）时使用此技能。从本地模板库中智能选择最合适的模板，填写内容，渲染输出 PNG 图片。
---

# 虾稿设计技能

<!-- v1.4 — 内容优先原则 + 溢出处理逻辑 + 外部Logo流程 + 模板容量匹配 -->

## 用户品牌配置

以下是当前已配置的品牌信息，渲染含有 Logo 或二维码的模板时默认使用：

```
圆形图标：已内置在模板中（蓝紫渐变 M 图标）
品牌文字（logo_text 槽位）：YOUR LOGO（可在每次渲染时自定义）
底部署名（brand 槽位）：遨游设计（可在每次渲染时自定义）
二维码内容：微信收款码（已内置，wxp://...）
```

**品牌区域结构说明：**

模板的品牌区域由两个元素组成：`圆形图标（w-image）` + `品牌文字（logo_text槽位）`，它们是视觉上的一个整体。处理方式取决于用户的品牌类型：

| 情况 | 处理方式 |
|------|---------|
| 自有品牌（文字名称） | 填写 logo_text 槽位，圆形图标保持内置默认 |
| 外部公司（仅文字名称） | 填写 logo_text 槽位为公司名，圆形图标保持内置默认 |
| 外部公司（提供了图片 Logo） | 渲染时用 `--adjustments` 隐藏圆形图标和 logo_text；渲染完成后用 Pillow 将图片 Logo 叠加到品牌区域 |

外部图片 Logo 叠加流程（Step 4 写命令时同时准备好）：
```python
from PIL import Image
base = Image.open("t677_render.png")
logo = Image.open("logo.png").convert("RGBA")
# 裁切 logo 实际内容区（去除透明边距）
# 缩放到合适宽度（约400-500px），保持比例
# 粘贴到品牌区域坐标（需参考 inspect 图确认位置）
base.paste(logo_resized, (x, y), logo_resized)
base.save("t677_final.png")
```

---

## 触发条件

当用户说出以下类型需求时，**立即启动此流程**，不要询问是否需要帮助：
- 「帮我做/生成/制作一张/个...海报/图片/封面/配图/通知」
- 「设计一个...」「做个...图」
- 提到具体内容类型：促销、活动通知、节日祝福、种草、招聘、课程招生等

---

## 执行流程（两级框架）

### Step 1：读取第一级模板索引

```bash
cat /Users/mlamp/visual-rag/data/template_index_v2.json
```

每条记录包含：
- `id`：模板 ID
- `brief`：一句话描述
- `scenarios`：典型使用场景
- `style`：视觉风格
- `size`：画布尺寸
- `platforms`：适用平台
- `visual`：视觉元素描述
- `content_density`：内容体量 — `light`（1-2个大字槽）/ `medium`（3-5个槽）/ `heavy`（多槽+长文本+列表）
- `list_structure`：若模板有固定行数的列表装饰，此字段说明行数要求
- `branding`：品牌元素标记
- `edit_spec`：第二级详细规格路径

### Step 2：选择最匹配的模板

根据用户需求，综合以下维度选择一个模板：

1. **scenarios** 与用户需求的场景匹配度（最重要）
2. **content_density** 与内容体量匹配：用户要表达的信息多 → 选 heavy；一句话金句 → 选 light
3. **style** 与所需氛围是否吻合
4. **platforms** 是否覆盖用户目标平台

选定后，**一句话告诉用户选择理由**，然后直接继续，**不需要用户确认**。

**⚠️ 如果选中的模板 `branding.has_logo = true` 或 `branding.has_qrcode = true`，在继续之前询问：**

> 「这个模板有品牌区域（圆形图标 + 品牌文字）。请问：
> 1. 品牌文字填什么？（如「明略科技」，或说"用默认"保留 YOUR LOGO）
> 2. 有没有提供图片 Logo 文件？（有的话告诉我路径，没有则跳过）」

- 若用户只给文字名称 → 填 logo_text，圆形图标保持内置
- 若用户提供了图片文件 → 准备 Step 4 的 adjustments 隐藏 + 渲染后 Pillow 叠加流程

### Step 3：读取第二级编辑规格，查看原版封面

```bash
cat /Users/mlamp/visual-rag/data/<edit_spec路径>
```

**用 Read 工具查看 `cover` 字段对应的封面图**，了解模板排版结构和各槽位的视觉比例：

```
Read: /Users/mlamp/visual-rag/data/<cover路径>
```

注意查看：
- 每个槽位在版面中占多大比例
- 列表类槽位：参考 `current` 中每条的字数作为单行容量参考
- 若有 `list_line_count` 字段，必须填满对应行数

每个槽位字段含义：
- `uuid`：DOM 元素 ID
- `role`：语义角色
- `must_edit`：是否必须填入用户内容
- `max_chars`：总字数上限
- `list_line_count`：（列表槽专用）固定装饰行数，必须填满
- `line_break`：是否用 `\n` 手动换行
- `hint`：填写建议
- `current`：原始占位内容（字数参考）

### Step 4：生成内容，写出完整渲染命令

**内容优先原则：先写出最能表达用户意图的内容，再考虑视觉适配。模板服务于内容，不要为了装进模板而损失关键信息。**

**填写规则：**
- `must_edit: true` 的槽位：写出真实、完整、有表达力的内容，参考 `current` 的字数节奏但不受其限制
- `must_edit: false` 的槽位：可保留 `current` 内容或按需修改
- `line_break: true` 的槽位：用 `\n` 手动控制换行，每行字数均匀（相差不超过2字）
- 列表类槽位：
  - 参考 `current` 中单条字数作为每行容量参考（通常14字以内单行显示）
  - 若有 `list_line_count`，内容必须填满该行数；内容不足时补充合理信息
  - 避免中英文混排（英文按单词边界断行，容易导致溢出）

**品牌区域处理：**
- 文字品牌：填 logo_text 槽位（公司名/品牌名），brand 槽位填底部署名
- 图片 Logo：在 `--adjustments` 中隐藏圆形图标和 logo_text，渲染后 Pillow 叠加

**构建渲染命令（必须包含所有真实内容，不允许占位符）：**

```bash
cd /Users/mlamp/visual-rag && .venv/bin/python src/render_single.py \
  --id <模板ID> \
  --slots '{"<uuid1>":"<真实内容>","<uuid2>":"<真实内容>"}' \
  --adjustments '[{"id":"<uuid>","style":{"display":"none"}}]'  # 仅图片Logo场景需要
```

**这条命令写出来之后，直接在 Step 6 执行它。**

### Step 5：确认两个服务正在运行

```bash
curl -s http://127.0.0.1:7001/design/temp?id=708 | head -c 50
curl -s http://127.0.0.1:5173/html?tempid=708 | head -c 50
```

如果任一服务未启动：
```bash
# 启动 mock API server（端口 7001）
cd /Users/mlamp/visual-rag && .venv/bin/python src/mock_api_server.py &

# 启动 Vite 前端（端口 5173）
cd /Users/mlamp/Desktop/虾稿设计-01/渲染器/poster-design && npm run dev -- --port 5173 --host 127.0.0.1 &
```

### Step 6：执行渲染

执行 Step 4 的命令。渲染成功后输出两行：
```
RENDER:/Users/mlamp/visual-rag/data/renders/t<ID>_render.png
INSPECT:/Users/mlamp/visual-rag/data/renders/t<ID>_inspect.png
```

若使用了图片 Logo，渲染完成后立即执行 Pillow 叠加，输出 `t<ID>_final.png`。**每次重渲后都必须重新叠加，不能复用上次的 final 图。**

### Step 7：验证结果，必要时调整

**必须用 Read 工具查看两张图：**

```
Read: <RENDER 路径>   ← 整体效果
Read: <INSPECT 路径>  ← 各元素边框 + UUID 标注
```

**检查清单：**

| 检查项 | 标准 |
|--------|------|
| 内容是否准确注入 | 图中是真实内容，不是模板占位文字 |
| 文字是否完整显示 | 没有溢出、截断 |
| 换行是否自然 | 断句合理，无单字悬挂 |
| 列表是否填满 | list_line_count 要求的行数全部有内容 |
| 元素是否重叠 | 装饰元素不遮挡文字 |

**发现视觉溢出时，按以下优先级处理：**

1. **语义压缩**：用更精炼的表达说同样的意思，不删除关键信息
2. **换模板**：如果压缩会损失核心意思，改选 `content_density` 更高的模板
3. **告知用户**：如果确实没有更合适的模板，说明情况，由用户决定取舍

**不要为了让内容适配模板而删除关键信息。**

发现布局重叠时，用 `--adjustments` 调整：
```bash
--adjustments '[{"id":"<uuid>","style":{"transform":"translateY(-30px)"}}]'
```
支持：`transform`（位移/缩放）/ `display: none`（隐藏）/ `opacity`

满意后：
```bash
open /Users/mlamp/visual-rag/data/renders/t<ID>_render.png
# 若有叠加 Logo：
open /Users/mlamp/visual-rag/data/renders/t<ID>_final.png
```

告诉用户文件路径，询问是否需要进一步调整。

---

## 当前可用模板（10套）

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

---

## 错误处理

- **渲染失败「找不到画布元素」**：Vite 服务未启动，先启动再重试
- **渲染失败「模板数据不存在」**：模板 ID 不在 data/palxp-raw/ 中，换模板重试
- **服务已在运行**：端口占用说明已运行，直接渲染即可
- **其他失败**：换一个模板重试，并告知用户

## 图片读取异常排查

如果 Read 工具读取渲染图后看不到图像内容，按以下顺序排查：

1. **模型没有视觉能力**：切换到支持视觉的模型（如 claude-sonnet-4-6）
2. **平台配置缺少 image 能力声明**：检查模型配置 `input` 字段是否包含 `"image"`，改为 `["text", "image"]` 并重启
3. **代理或网关过滤了图片**：测试直连 Anthropic API 验证
4. **图片格式问题**：尝试转为 JPEG 后重新 Read

```bash
open /Users/mlamp/visual-rag/data/renders/t<ID>_render.png
```
