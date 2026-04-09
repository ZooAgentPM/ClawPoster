---
name: visual-rag-design
description: 自动生成设计海报/图片。当用户提出设计需求（如「帮我做个促销海报」「做一张活动通知图」「生成一张小红书封面」）时使用此技能。从本地模板库中智能选择最合适的模板，填写内容，渲染输出 PNG 图片。
---

# 虾稿设计技能

<!-- v1.3 — 品牌配置系统 + 模板索引 branding 字段 -->

## 用户品牌配置

以下是当前已配置的品牌信息，渲染含有 Logo 或二维码的模板时默认使用：

```
圆形图标：已内置在模板中（蓝紫渐变 M 图标）
品牌文字（logo_text 槽位）：YOUR LOGO（可在每次渲染时自定义）
底部署名（brand 槽位）：遨游设计（可在每次渲染时自定义）
二维码内容：微信收款码（已内置，wxp://...）
```

**Logo 槽位说明：**
- `logo_text`（role=logo_text）：圆形图标右侧的品牌文字，默认「YOUR LOGO」，可填入公司名/品牌名/产品线名（如「HRBP」「遨游设计」「遨游科技」）
- `brand`（role=brand）：底部小字署名，默认「遨游设计」，可修改
- 圆形图标和 logo_text **是一个整体品牌区域**，通常需要一起考虑：图标固定（已内置），文字可自定义

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
- `brief`：一句话描述，说明模板的结构和适用内容类型
- `scenarios`：典型使用场景标签列表
- `style`：视觉风格（如「极简冲击」「干货清单」「喜庆热闹」）
- `size`：画布尺寸
- `platforms`：适用平台
- `visual`：视觉元素描述（背景、排版、装饰等）
- `branding`：品牌元素标记（`has_logo` / `has_qrcode`）
- `edit_spec`：第二级详细规格的相对路径

### Step 2：选择最匹配的模板

根据用户需求，综合以下维度选择一个模板：

1. **scenarios** 与用户需求的场景匹配度（最重要）
2. **style** 与所需氛围是否吻合
3. **platforms** 是否覆盖用户目标平台
4. **brief** / **visual** 整体描述是否贴合

选定后，**一句话告诉用户选择理由**，然后直接继续，**不需要用户确认**。

**⚠️ 如果选中的模板 `branding.has_logo = true` 或 `branding.has_qrcode = true`：**

在继续之前，**必须主动告知用户**并询问品牌偏好：

> 「这个模板包含品牌区域（圆形图标 + 品牌文字 + 二维码）。
> 默认使用内置图标，品牌文字填「YOUR LOGO」，底部署名填「遨游设计」。
> 请问这次品牌文字填什么？（直接回复即可，或说"用默认"跳过）」

收到用户回复后再继续 Step 3。若用户说"用默认"或无特别要求，使用上方品牌配置的默认值。

### Step 3：读取第二级编辑规格，查看原版封面

```bash
cat /Users/mlamp/visual-rag/data/<edit_spec路径>
# 例如：cat /Users/mlamp/visual-rag/data/edit_specs/t708.json
```

读取后，**用 Read 工具查看 `cover` 字段对应的封面图**，了解模板原始的视觉风格、排版结构，作为填写文案和评估结果的参照：

```
Read: /Users/mlamp/visual-rag/data/<cover路径>
# 例如：/Users/mlamp/visual-rag/data/assets/covers/t708-cover_0.webp
```

每个槽位（slot）包含：
- `uuid`：DOM 元素 ID，渲染时直接注入
- `role`：语义角色（main_title / hook / answer / subtitle / body_desc / date / brand / logo_text / marquee 等）
- `label`：中文名称
- `must_edit`：是否必须修改（true = 必须填入用户内容）
- `deletable`：是否可以留空（false = 不可删除，必须有内容）
- `max_chars`：建议最大字数
- `line_break`：是否支持手动换行（`\n` → `<br>`）
- `hint`：填写建议，说明风格和写法
- `current`：模板原始占位内容（参考用）
- `uuids`：仅 MARQUEE_GROUP 有此字段，包含多个相同装饰文字的 uuid 列表

### Step 4：生成槽位内容，写出完整渲染命令

根据用户需求和每个槽位的规格，为槽位生成合适的文字：

**填写规则：**
- `must_edit: true` 的槽位必须填入用户相关内容
- `must_edit: false` 的槽位（如日期、品牌名、装饰文字）可保留 `current` 原始内容或按用户要求修改
- 字数不超过 `max_chars`（中文按字数，英文按字符数粗估）
- `line_break: true` 的槽位，**必须用 `\n` 手动控制换行**，不能依赖自动折行。换行位置要保证每行字数均匀（相差不超过2字），不能让短行或长行单独存在。例如8字应写成4+4，5字应写成3+2或2+3
- 参考 `hint` 的建议写法，让文案符合模板风格
- 如果用户没有提供具体文案，**根据需求自行创作**，保持简洁有力

**Logo 品牌区域处理（role=logo_text 或 role=brand）：**
- `logo_text` 槽位：填入 Step 2 中用户确认的品牌文字（默认「YOUR LOGO」）
- `brand` 槽位：填入底部署名（默认「遨游设计」）
- 圆形图标已内置，无需操作

**构建 slots JSON：**
- 普通槽位：`{"uuid": "文本内容"}`
- MARQUEE_GROUP 槽位：将 `uuids[]` 中每个 uuid 都映射到同一文本

**⚠️ 本步骤必须产出一条完整可执行的命令，包含所有真实文案：**

```bash
cd /Users/mlamp/visual-rag && .venv/bin/python src/render_single.py \
  --id <模板ID> \
  --slots '{"<uuid1>":"<你生成的真实文案>","<uuid2>":"<你生成的真实文案>"}'
```

不允许在命令里留占位符，不允许使用空 `{}`，不允许复用上次渲染的文件。
**这条命令写出来之后，直接在 Step 6 执行它。**

### Step 5：确认两个服务正在运行

渲染前检查服务状态：
```bash
curl -s http://127.0.0.1:7001/design/temp?id=708 | head -c 50
curl -s http://127.0.0.1:5173/html?tempid=708 | head -c 50
```

如果任一服务未启动，提示用户：
```bash
# 启动 mock API server（端口 7001）
cd /Users/mlamp/visual-rag && .venv/bin/python src/mock_api_server.py &

# 启动 Vite 前端（端口 5173）
cd /Users/mlamp/Desktop/虾稿设计-01/渲染器/poster-design && npm run dev -- --port 5173 --host 127.0.0.1 &
```

### Step 6：执行渲染

执行 Step 4 写出的完整命令。**必须是真实执行 bash 命令，不是描述它。**

渲染成功后标准输出会打印两行路径：
```
RENDER:/Users/mlamp/visual-rag/data/renders/t708_render.png
INSPECT:/Users/mlamp/visual-rag/data/renders/t708_inspect.png
```

如果没有看到 `RENDER:` 开头的输出，说明渲染未执行或失败，不能跳过直接展示结果。

### Step 7：验证结果，必要时用 inspect 标注图调整布局

渲染完成后，**必须用 Read 工具分别查看两张图**：

```
Read: <RENDER 路径>   ← 正常渲染图，评估整体效果
Read: <INSPECT 路径>  ← 标注图，每个元素用彩色边框标出 UUID 前8位
```

**文案质量检查（对照原版封面）：**

| 检查项 | 标准 |
|--------|------|
| 文案是否正确注入 | 图中显示的是你填的内容，不是模板默认文字 |
| 文字是否完整显示 | 没有被截断、没有溢出边框 |
| 换行是否合理 | 视觉上平衡，不出现单字悬挂在最后一行 |
| 整体是否美观 | 与原版封面风格一致，有设计感 |

**布局问题检查：**

| 检查项 | 标准 |
|--------|------|
| 元素是否重叠 | 装饰贴纸/图形不遮挡文字内容 |
| 装饰元素位置 | 位置符合设计预期，不因文字长度变化而错位 |

**如果发现布局问题（元素重叠、遮挡等）：**

1. 从 inspect 标注图中找到需要调整的元素 UUID（看彩色框角落的标签）
2. 用 `--adjustments` 重新渲染：

```bash
cd /Users/mlamp/visual-rag && .venv/bin/python src/render_single.py \
  --id <模板ID> \
  --slots '{"<uuid>":"<文案>"}' \
  --adjustments '[{"id":"<目标元素UUID>","style":{"transform":"translateX(50px)"}}]'
```

支持的调整类型：
- 移动：`{"transform": "translateX(30px)"}` 或 `translateY`
- 缩放：`{"transform": "scale(0.8)"}`
- 隐藏：`{"display": "none"}`
- 透明度：`{"opacity": "0.5"}`

3. 再次读取 RENDER 和 INSPECT 图，验证调整效果，直到满意

**如果文案质量不满意，调整后重渲（最多3轮）：**
- 文字太长 → 缩短，严格控制在 max_chars 以内
- 换行不美观 → 调整 `\n` 的位置，让每行字数更均匀
- 内容不够吸引人 → 重写文案，参考 hint 的风格要求

满意后：
```bash
open /Users/mlamp/visual-rag/data/renders/t<ID>_render.png
```

告诉用户文件路径，并说明文案逻辑，询问是否需要进一步调整。

---

## 当前可用模板（10套）

| ID | 风格 | 适用场景 | 品牌区域 |
|----|------|---------|---------|
| 708 | 极简冲击 | 学习方法、情绪调节、职场干货、副业变现 | — |
| 703 | 直给冲击 | 内容运营、爆款技巧、涨粉攻略 | — |
| 699 | 简洁利落 | 求职技巧、效率提升、职场晋升 | — |
| 883 | 简约权威 | 每日资讯、财经热点、日报周报 | — |
| 704 | 警示活泼 | 避坑指南、消费决策、重要提醒 | — |
| 672 | 文艺温暖 | 励志语录、每日一句、个人品牌 | Logo + 二维码 |
| 701 | 中英双语简约 | 内容种草、书影音推荐、英语学习 | — |
| 689 | 干货清单 | 攻略、步骤清单、新手入门 | — |
| 905 | 喜庆热闹 | 促销活动、节日大促、电商营销 | — |
| 677 | 正式权威 | 机构通知、政策说明、知识科普 | Logo + 二维码 |

---

## 错误处理

- **渲染失败「找不到画布元素」**：Vite 服务未启动，先启动再重试
- **渲染失败「模板数据不存在」**：模板 ID 不在 data/palxp-raw/ 中，换模板重试
- **服务已在运行**：若启动服务提示端口占用，说明已运行，直接渲染即可
- **其他失败**：换一个模板重试，并告知用户
- 不要向用户解释技术细节，直接展示结果或简短说明原因

## 图片读取异常排查

如果 Read 工具读取渲染图后看不到图像内容（只有文字描述、内容为空、或报告"无法读取图片"），按以下顺序排查：

1. **模型没有视觉能力**：当前使用的模型不支持图像输入。需要切换到支持视觉的模型（如 claude-sonnet-4-6）。
2. **平台配置缺少 image 能力声明**：若通过 openclaw 等平台运行，检查模型配置中 `input` 字段是否包含 `"image"`（默认可能只有 `"text"`）。将其改为 `["text", "image"]` 并重启服务。
3. **代理或网关过滤了图片**：部分 API 代理会剥离图片内容。可测试直连 Anthropic API 验证。
4. **图片格式或大小问题**：渲染图为 PNG，如遇问题可尝试在 render_single.py 输出目录手动转为 JPEG 后重新 Read。

排查期间，可让用户通过系统文件管理器直接打开渲染文件：
```bash
open /Users/mlamp/visual-rag/data/renders/t<ID>_render.png
```
