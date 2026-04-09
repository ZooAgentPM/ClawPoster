# 虾稿设计 Skill 更新日志

每个版本归档包含：`SKILL.md` · `render_single.py` · `template_index_v2.json` · `edit_specs/`

---

## v1.10 (2026-03-25)

### Bug 修复：rough-annotation SVG 装饰丢失（v1.6 回归）

- **根因**：v1.6 新增 Vue reactive 优先注入路径，找到 widget 即 `continue` 跳过 DOM 注入。v1.1 在 DOM 注入路径里加的"保留 SVG 子节点"逻辑因此对所有能被 dWidgets 找到的 widget 失效，导致 t708 等含 rough-annotation 装饰的模板渲染后手绘圆圈/高亮全部消失。

- **修复**：在 Vue reactive 路径入口增加检测——`widget.text` 含 `rough-annotation` 时跳过该路径，fall-through 到 DOM 注入，由 DOM 注入保留 SVG 子节点再插入新文本。

- **影响文件**：`src/render_single.py` · `src/render_server.py`（两者注入逻辑独立复制，同步修改）

- **回归测试基准**：
  - t708（极简冲击）：验证 rough-annotation 圆圈/高亮保留 → DOM 注入路径
  - t873（漫画爆款）：验证 textEffects 描边颜色正确 → Vue reactive 路径

---

## v1.9 (2026-03-24)

### 视觉元数据字段：全部95套模板人工标注

新增4个视觉语义字段，写入 `template_index_v2.json` 和 `visual_metadata.json`：

- **`visual_tags`**：5-6个中文视觉特征词（如「大字霸屏」「手绘插画风」），描述观察者第一眼印象；LLM可语义匹配用户的视觉偏好描述
- **`color_palette`**：主色调列表（中文颜色词），用于配色需求过滤
- **`decorative_interference`**：装饰干扰度 none/low/medium/high，反映装饰元素对文字区域的占用程度；内容重时选low/none
- **`layout_structure`**：固定词表版面结构（hero_text / split_section / title_with_list / split_with_image / multi_block / card_layout），按内容组织方式快速缩小候选

### 配套工具

- **`tools/label_server.py`**（port 7003）：FastAPI标注服务，提供模板列表、封面图预览、字段更新接口
- **`tools/label.html`**：浏览器标注界面，可视化封面图、AI生成字段可编辑、支持键盘快捷键、缩略图条导航、过滤待标注/已完成

### SKILL.md 更新（v1.8 → v1.9）

- 模板目录字段表新增 `visual_tags` / `color_palette` / `decorative_interference` / `layout_structure` 四行及使用说明
- 新增 `layout_structure` 固定词表说明

---

## v1.8 (2026-03-24)

### template_index_v2.json：新增 slot_capacity 容量摘要

- **`slot_capacity` 字段**（全部95套模板）：把每个模板所有 `must_edit` 槽位的 `role` / `max_chars` / `max_per_line` / `line_break` 汇总进 template_index，选模板时无需再逐个读 edit_spec 即可做容量粗过滤
- **过滤规则**：内容字数 > `max_chars` × 1.2 或最长行 > `max_per_line` + 2 时排除该模板，避免选到明显放不下的模板后才发现溢出

### SKILL.md 更新（v1.7 → v1.8）

- 模板目录字段表新增 `slot_capacity` 行，标注为容量粗过滤的主要依据
- 新增"容量粗过滤"说明：字段结构、role 匹配方式、过滤规则及误差容忍范围

---

## v1.7 (2026-03-24)

### render_server：browser 复用，渲染提速

- **新增 `src/render_server.py`**：FastAPI HTTP daemon（端口 7002），browser 在服务启动时 launch 一次，所有请求复用；每次请求新建/关闭 page 保证隔离
- **接口**：`POST /render {"id":int, "slots":{}, "adjustments":[]}` → `{"render":"/path/...","inspect":"/path/..."}`；`GET /health`
- **实测提速**：连续渲染不同模板时，第2次起从 ~18s 降至 ~5s（browser 缓存 Vite 资源后热导航）

### template_index_v2.json：新增结构化筛选字段

- **`background_type`**（15个已确认模板）：`white_minimal` / `gray_minimal` / `illustrated_*` / `white_blank` / `photo`，直接排除风格不符模板（如 t553 `white_blank` 避免选到空白背景）
- **`text_align_main`**（71个模板自动提取）：`justify` / `center` / `left`，从 layers.json 自动读取主标题对齐方式
- **`has_non_replaceable_images`**：标注含不可替换示例图的模板（如 t896）

### edit_spec：新增字宽数据（全部95套）

- **`char_px`**：单字像素宽 = `fontSize × (1 + letterSpacing/100)`
- **`element_width_px`**：文本框设计宽度
- **`max_per_line`**：每行最多字数参考 = `floor(element_width_px / char_px)`；为 Agent 提供可靠的溢出预判依据，减少同一模板反复迭代

### SKILL.md 更新（v1.6 → v1.7）

- 渲染工具：推荐改用 render_server HTTP 接口，保留 CLI 备用
- 模板目录：新增 background_type / text_align_main / has_non_replaceable_images 字段说明
- 槽位字段说明：新增 char_px / element_width_px / max_per_line 及使用方法

---

## v1.6 (2026-03-24)

### Bug 修复：textEffects 模板文字颜色渲染错误

- **根因**：Playwright 直接操作 DOM 后，Chromium GPU 合成层顺序错乱——描边层（透明填充+黑色描边）渲染在填充层（橙色）上方，导致文字显示为黑色
- **修复方案**：注入时优先通过 Vue reactive 数据（`pageGroup[0].dWidgets`）更新 `widget.text`，让 Vue 正常 diff/re-render，绕过 GPU 层问题；找不到 widget 时回退为 DOM 注入
- **关键细节**：`setupState.pageGroup` 在 Vue 3 proxy 中已自动解包为数组，需用 `pageGroup[0]` 而非 `pageGroup.value[0]`
- **验证**：t873（漫画爆款）注入后文字正确显示橙色+黑色描边

### 模板库大扩充：10套 → 95套

- **新增85套模板 edit_spec**：涵盖小红书封面（50套）、手机海报（15套）、小红书配图（20套）
- **template_index_v2.json 扩充至95条**：每条含 brief、scenarios、style、content_density、branding 等完整字段
- **SKILL.md 新增分类速查表**：按封面/海报/配图三大类，细分风格子类，列出代表模板 ID 和适用场景，方便龙虾快速选模板

### 新增模板覆盖场景

- 爆款大字系列（20+套）：极简霸屏、emoji大字、涂鸦、撕纸、肌理、漫画等变体
- 内容型（10+套）：数据表格、5字竖排、备忘录、关键词解释、A vs B 对比
- 配图系列：干货列表（6-14条）、朋友圈文案、PK对比、VS多维对比、资料合集、好物推荐、产品评测
- 手机海报：节日贺卡、招聘/会议通知、直播预告、课程招生、招商邀请、副业招募

---

## v1.5 (2026-03-23)

### 重构：从行为脚本改为参考手册

- **SKILL.md 全面重写**：从 256 行压缩到 95 行，去除所有 Step N 编号流程、"必须先…再…"行为指令、检查清单、溢出处理优先级链
- **保留领域知识**：模板目录、槽位字段说明、渲染命令语法、inspect 图说明、品牌区域两种情况+Pillow 参考、服务地址、错误速查
- **设计原则变更**：手册只说"有什么、能做什么"，不规定"怎么做"——执行策略交由 AI 自行判断

---

## v1.4 (2026-03-23)

### 内容优先原则

- **SKILL.md Step 4 新增内容优先原则**：「模板服务于内容，不要为了装进模板而损失关键信息」，作为 Step 4 的首要原则声明
- **Step 7 溢出处理完全重写**：原「文字太长→缩短」改为三步优先级链：①语义压缩（精炼表达，不删关键信息）→ ②换 content_density 更高的模板 → ③告知用户由用户决定。明确禁止因模板限制删除关键信息

### 模板容量匹配

- **template_index_v2.json 新增 `content_density` 字段**：light（1-2个大字槽）/ medium（3-5个槽）/ heavy（多槽+长文本+列表）；全部10个模板已标注
- **SKILL.md Step 2 更新选模板优先级**：`content_density` 与内容体量匹配成为第2优先级（仅次于 scenarios 场景匹配）
- **t677 `list_structure` 字段**：template_index 新增说明「固定6条装饰下划线，内容必须填满6条」

### 列表溢出防护

- **t677 edit_spec `list_line_count: 6`**：edit_spec 新增字段，Agent 生成内容时必须规划满6条
- **列表 hint 强化**：单条控制14字以内；避免中英文混排（英文在单词边界断行导致溢出）；宁可补充信息也不留空行（空行显示裸露下划线）
- **`current` 字段补全第6条**：t677 content_list 示例从5条补为6条

### 品牌区域处理逻辑（完善 v1.3 基础）

- **SKILL.md 新增品牌区域结构说明**：以表格明确3种情况：文字品牌 / 外部文字名称 / 外部图片Logo → 三种处理方式
- **图片Logo叠加完整流程**：Step 4 加入 Pillow 叠加代码模板（裁切透明边距→缩放→粘贴到品牌区域）；Step 6 警告「每次重渲后都必须重新叠加，不能复用上次的 final 图」
- **列表容量参考**：Step 4 明确「参考 current 中单条字数作为每行容量参考（通常14字以内单行显示）」

---

## v1.3 (2026-03-23)

### 品牌系统

- **template_index_v2.json 新增 `branding` 字段**：每个模板标注 `has_logo` / `has_qrcode`，并附说明文字；t672、t677 标记为含品牌区域
- **SKILL.md 新增「用户品牌配置」区块**：顶部统一声明圆形图标、默认品牌文字、底部署名、二维码 URL
- **Step 2 主动询问逻辑**：选中含 Logo/QR 模板后，必须先询问用户本次品牌文字，收到回复再继续渲染
- **模板列表增加「品牌区域」列**，方便一眼识别

### Logo 策略调整

- **换用新 Logo**：`新Logo.svg`（蓝紫渐变圆形 M 图标）→ 渲染为 200×200 WebP，替换 `1756953810240_997826.webp`
- **logo_text 槽位保留「YOUR LOGO」**：hint 改为「不要修改默认值」，由用户在渲染时指定
- **QR typeNumber 修复**：`method.ts` 中 `typeNumber: 3` → `typeNumber: 0`，修复微信收款码链接（54字符）溢出导致二维码不渲染的问题

### t672 排版优化

- **Logo 图标**：79×78 → 96×96，并修正位置使 icon+文字组合真正水平居中（原偏右 34px）
- **QR 码**：225×225 → 256×256，保持居中，底部署名位置随之调整

### SKILL.md 其他更新

- Step 5 服务检查改用 `/html?tempid=708` 路径（更准确反映 Vite 实际可用状态）
- Step 4 明确 logo_text / brand 槽位的处理规则

---

## v1.2 (2026-03-20)

### 新功能
- **Inspect 标注图**：每次渲染自动生成 `t{id}_inspect.png`，用彩色边框标注所有元素位置，左上角显示 UUID 前8位，方便定位需要调整的元素
- **`--adjustments` 参数**：支持对任意 DOM 元素应用 CSS 样式（transform/opacity/display/fontSize 等），在截图前注入，用于修正布局问题

### SKILL.md 更新
- Step 7 新增布局检查流程：读取 inspect 图 → 定位问题元素 UUID → 用 `--adjustments` 重渲 → 验证满意后输出
- 龙虾可自主处理元素重叠、位置偏移等布局问题，无需人工介入

### 渲染器输出格式变更
- stdout 从单行路径改为两行：`RENDER:/path/render.png` + `INSPECT:/path/inspect.png`

---

## v1.1 (2026-03-20)

### Bug 修复
- **UUID 截断修复**：edit_specs 中所有 UUID 从8位前缀补全为12位完整 ID（涉及10个模板，38个 UUID），修复了槽位注入静默失败的问题
- **justify 字间距修复**：注入后对 `.edit-text` div 设置 `text-align-last: left`，抑制 Chromium 对 `white-space: pre-wrap` + `text-align: justify` 组合下显式换行前一行的 justify 拉伸
- **rough-annotation SVG 保留**：注入时只移除非 SVG 子节点，保留手绘高亮/下划线 SVG 装饰
- **SVG 遮挡修复**：注入的 span 设置 `position: relative; z-index: 1`，浮在 `position: absolute` 的装饰 SVG 上方

### SKILL.md 更新
- Step 3：渲染前必须用 Read 工具查看原版封面图，了解视觉风格
- Step 4：必须输出完整可执行命令（含真实文案），禁止使用占位符或空 `{}`
- Step 4：`line_break: true` 的槽位必须手动加 `\n` 控制换行，不能依赖自动折行
- Step 6：必须实际执行 bash 命令，stdout 看到 RENDER: 路径才算成功
- Step 7：渲染后必须读图验证，不满意必须重渲

---

## v1.0 (2026-03-19)

### 初始版本
- 10个模板（708/703/699/883/704/672/701/689/905/677），覆盖极简冲击/干货清单/喜庆热闹等主流风格
- 基础文本注入渲染：Playwright 无头 Chromium + Vue3/Vite 前端
- 本地素材拦截：字体/图片/SVG 全部本地化，无需联网
- mock API server（port 7001）提供模板数据

---

## v2.1 (2026-04-09)

### Skill 结构化重构 + MCP 公网服务完善

**SKILL.md 重构**
- 参考 opencli-explorer 风格，引入「Agent 必读」工作流总表 + 常犯错误表
- 新增 Step 8 交付模块：图片预览展示 + 响应链接规则 + base64 本地存图
- 新增实战案例章节（含整批放弃重搜、文案诊断推导核心词两个完整案例）
- 新增 references/ 子目录：`copy-xhs-cover.md` 小红书封面文案方法论
- 陷阱表新增：下载链接不得自行构造文件名（石小泽案例）
- 修复：`start_notify.sh` → `start_broadcast.sh`

**MCP 服务端**
- `render_server.py`：新增 `/files/{filename}` 公网下载接口，文件名含时间戳（防多用户覆盖）
- `mcp_server.py`：新增 `VISUAL_RAG_PUBLIC_URL` 注入，渲染响应含公网下载链接；新增 `/status` 和 `/files` 代理路由
- `start_public.sh`：静态 ngrok 域名一键启动

**已验证**：list_templates / generate_poster / 下载链接 均在 `syncopated-retractively-anitra.ngrok-free.dev` 正常工作
