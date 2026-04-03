# 虾稿设计 · 系统架构与维护手册

> 给参与维护的 Agent 看的。读完这份文档，你应该能理解每个模块的职责、关键机制的实现原理，以及哪些地方改动会引发连锁反应。

---

## 一、系统全景

```
外部 Claude Agent（飞书/网页）
       │  MCP over HTTP
       ▼
  mcp_server.py :3000          ← 对外唯一入口（ngrok 穿透）
       │  内部 HTTP
       ├──▶ render_server.py :7002   ← 渲染引擎 + 语义搜索 + 状态页
       │         │  Playwright
       │         └──▶ Vite 前端 :5173  ← palxp 渲染器（不可修改）
       │                   │  API
       │                   └──▶ mock_api_server.py :7001  ← 本地模板数据
       │
       └──▶ /files/ /status/*  代理路由 → render_server
```

**三个本地服务由 `ensure_services` MCP 工具在需要时自动启动，无需手动管理。**

---

## 二、模块职责

### `src/mcp_server.py` — 对外网关

**角色**：唯一对外暴露的 MCP 服务。运行在端口 3000（HTTP 模式），通过 ngrok 暴露公网。

**两种运行模式**：
- `python src/mcp_server.py --port 3000`：HTTP 模式，供远端 Agent 通过 ngrok 访问
- `python src/mcp_server.py`（无参数）：stdio 模式，供本地 Claude Code 直接使用

**提供的 MCP 工具**：

| 工具 | 作用 |
|------|------|
| `ensure_services` | 检测并启动三个依赖服务 |
| `search_templates` | 语义搜索模板（bge-m3 向量）|
| `list_templates` | 关键词过滤模板（降级备用）|
| `get_template_spec` | 读取模板槽位规格（edit_specs/）|
| `generate_poster` | 调 render_server 渲染，返回图片 |
| `get_slot_crops` | 调 render_server 裁图，质检用 |

**提供的 HTTP 代理路由**（Starlette custom_route，仅 HTTP 模式生效）：

| 路由 | 代理目标 |
|------|--------|
| `GET /files/{filename}` | render_server /files/ |
| `POST /status/create` | render_server /status/create（同时记录 task_id）|
| `POST /status/{id}/update` | render_server /status/{id}/update |
| `GET /status/{id}/data` | render_server /status/{id}/data |
| `GET /status/{id}` | render_server /status/{id}（HTML 页面）|

**关键路径常量**（全部支持 `VISUAL_RAG_DATA_DIR` 环境变量覆盖）：
```python
BASE_DIR       = Path(__file__).parent.parent          # /visual-rag/
_DATA_DIR      = Path(os.environ.get("VISUAL_RAG_DATA_DIR", str(BASE_DIR / "data")))
INDEX_PATH     = _DATA_DIR / "template_index_v2.json"
EDIT_SPECS_DIR = _DATA_DIR / "edit_specs"
RENDER_URL     = "http://127.0.0.1:7002"
VITE_DIR       = BASE_DIR.parent / "虾稿设计-01" / "渲染器" / "poster-design"
```

---

### `src/render_server.py` — 渲染引擎

**角色**：核心后端，承载渲染、语义搜索、质检、状态页四大功能。端口 7002，仅本地访问。

**启动时初始化**：
1. 加载 `template_index_v2.json` 和 `template_vectors.json`（bge-m3 向量）
2. 预热 bge-m3 嵌入模型（首次约 15-30s）
3. 启动 Playwright Chromium browser（全程复用，每次渲染 new_page + close_page）

**关键 API**：

| 接口 | 功能 |
|------|------|
| `GET /health` | 返回 `{"status":"ready"}` |
| `POST /render` | 渲染海报，返回 render/inspect 路径 + 质检报告 |
| `POST /search_templates` | 向量语义搜索 |
| `POST /thumbnail_grid` | 拼接缩略图合图 |
| `POST /crop_slots` | 裁剪指定槽位区域 |
| `GET /files/{filename}` | 返回 renders/ 目录下的渲染产物 |
| `POST /status/create` | 创建状态页任务 |
| `POST /status/{id}/update` | 追加进度步骤 |
| `GET /status/{id}/data` | 轮询用 JSON 接口 |
| `GET /status/{id}` | 返回 HTML 状态页（含 JS 轮询逻辑）|

**渲染流程**（`_do_render`）：
1. 读取 `palxp-raw/t{id}_layers.json`（渲染引擎的原始数据）
2. 启动 Playwright page，拦截 palxp CDN 请求转发到本地 assets/
3. 加载 `http://127.0.0.1:5173/html?tempid={id}`（Vite 前端）
4. 等待前端加载完成，JS 注入：应用 slots 文字替换 + adjustments 样式调整
5. 截图 → 质检 → 生成 inspect 标注图 → 返回文件路径

**向量搜索**（`/search_templates`）：
- 模型：BAAI/bge-m3（多语言，中文效果好）
- 策略：余弦相似度 → MMR 多样性重排（λ=0.7）
- 负向排除：`exclude` 参数，向量减法 `qvec = normalize(qvec - 0.4 * exc_vec)`
- 降级：向量库不存在时自动切换关键词 fallback

**路径常量**（全部支持 `VISUAL_RAG_DATA_DIR`）：
```python
BASE_DIR    = Path(__file__).parent.parent
DATA_DIR    = Path(os.environ.get("VISUAL_RAG_DATA_DIR", str(BASE_DIR / "data")))
RAW_DIR     = DATA_DIR / "palxp-raw"       # 渲染层数据，render 必需
ASSETS_DIR  = DATA_DIR / "assets"          # SVG/图片/字体
OUT_DIR     = DATA_DIR / "renders"         # 渲染产物输出
COVER_DIR   = DATA_DIR / "assets/covers"  # 缩略图
INDEX_PATH  = DATA_DIR / "template_index_v2.json"
VECTORS_PATH = DATA_DIR / "template_vectors.json"
EDIT_SPECS_DIR = DATA_DIR / "edit_specs"
```

---

### `src/mock_api_server.py` — 本地 API 服务

**角色**：模拟 palxp 线上 API，让 Vite 前端能在本地读取模板数据。端口 7001。

**两个端点**：
- `GET /design/temp?id={tid}` → 返回 `palxp-raw/t{tid}_layers.json` 的处理结果
- `GET /assets/...` → 返回 `data/assets/` 下的静态资源

**处理逻辑**（`load_template`）：
- `w-svg` 组件：读取本地 SVG 文件内容，替换到 `svgUrl` 字段（Snap.parse 需要 XML 字符串）
- `w-image` 组件：把本地路径转换为 `http://127.0.0.1:7001/assets/...` URL
- `w-text` 组件：应用 slots 文字替换（如果有）
- 修复字体 URL、背景图 URL 等

**注意**：mock_api_server 里有**唯一的硬编码路径**残留：
```python
local = Path('/Users/mlamp/visual-rag/data') / rel   # GET /assets/ 的路径拼接
```
其他路径已支持 `VISUAL_RAG_DATA_DIR`。这处硬编码只影响 `/assets/` 静态文件路由，demo 部署时如果数据路径不同需注意。

---

### Vite 前端 `poster-design/` — palxp 渲染器

**角色**：把 palxp 模板 JSON 渲染为可截图的 HTML 页面。

**位置**：`/Users/mlamp/虾稿设计-01/渲染器/poster-design/`（不在本仓库）

**维护原则**：
- **不要修改这部分代码**，它是上游 palxp 的前端，改了就不好追更新
- 渲染器通过 `http://127.0.0.1:7001/design/temp?id=X` 取数据，跟 mock_api_server 对接
- 渲染器的 CDN 请求（`design.palxp.cn/static/...`）被 render_server 的 Playwright 路由拦截，替换为本地资源

---

## 三、关键机制

### 1. 状态页实时更新

**用户体验**：Agent 收到任务后立即发一条消息 + 状态页链接，用户随时打开查看进度，页面每 2s 自动轮询更新。

**实现链路**：
```
Agent bash → POST :3000/status/create
                    │
            mcp_server 记录 task_id
            (_session_task_map + _latest_task_id)
                    │
            → 代理到 render_server /status/create
                    │
            MCP 工具执行时自动调用 _status_update(ctx, step, message)
                    │
            → httpx.post render_server /status/{task_id}/update
                    │
            状态页 JS 每 2s fetch /status/{id}/data
            → 有新 step 时追加到 DOM
```

**并发支持**：
- `_session_task_map: dict` 以 `ctx.session_id` 为 key，多 session 互不干扰
- `_latest_task_id` 作为 fallback，兜底 bash curl 创建（无 session_id header）的场景

**⚠ 不要跳过 `/status/create` 的代理路由**：task_id 记录发生在 mcp_server 的 `proxy_status_create` 里。如果直接 curl port 7002，mcp_server 无法感知，`_status_update` 就找不到 task_id，状态页会是空的。

---

### 2. 一次性 cron 通知

**用途**：任务开始时，通过飞书发一条带状态页链接的消息，消息只发一次。

**实现**（`start_notify.sh`）：
- 创建 `openclaw cron`，每 15s 检查 FLAG_FILE 是否存在
- **不存在** → 读 PROGRESS_FILE 内容原样转发给用户，创建 FLAG_FILE
- **已存在** → 输出 NO_REPLY，什么都不发
- cron 不自删，由主 Agent 完成后 `openclaw cron rm $CRON_ID` 清理

**为什么不让 cron 自删**：让 cron Agent 执行自删属于提示词注入，会被安全检测拦截。

---

### 3. 渲染截图管线

**JS 注入顺序**（render_server `_do_render`）：
1. 等待前端 `#canvas` 元素出现（最多 60s）
2. 注入文字替换 slot：`document.querySelector('[data-uuid="..."]').innerText = "..."`
3. 注入 adjustments 样式：直接修改 DOM element.style
4. 等待字体/图片加载完成（额外 2s）
5. 截图 canvas 区域 → `_render.png`
6. 从截图 + 层数据生成质检标注图 → `_inspect.png`

**质检逻辑**：读取 edit_specs 里每个槽位的 `max_chars`/`max_per_line`，对比渲染后 DOM 的实际 boundingBox 判断是否溢出。

---

### 4. 向量语义搜索

**模型**：`BAAI/bge-m3`（多语言，推荐中文场景）
**向量库文件**：`data/template_vectors.json`
```json
{
  "model": "BAAI/bge-m3",
  "dim": 1024,
  "count": 417,
  "vectors": {
    "148": [0.123, -0.456, ...],
    ...
  }
}
```

**负向排除**（`exclude` 参数）：
```python
exc_vec = model.encode(exclude_text, normalize_embeddings=True)
qvec = qvec - 0.4 * exc_vec
qvec = normalize(qvec)
```
系数 0.4 是经验值，过大会破坏正向相关性，过小排除效果不明显。

**多样性重排（MMR）**：λ=0.7，在相关性和视觉多样性间取平衡，避免返回风格雷同的结果。

---

### 5. 数据目录结构

```
data/                          ← 完整私有数据（不进公开仓库）
├── template_index_v2.json     ← 417 个模板的元数据索引
├── template_vectors.json      ← bge-m3 向量库
├── edit_specs/                ← 每个模板的槽位规格 t{id}.json
├── palxp-raw/                 ← 渲染引擎原始层数据 t{id}_layers.json（render 必需）
├── assets/
│   ├── covers/                ← 模板封面缩略图（缩略图合图用）
│   ├── covers_webp/           ← WebP 格式封面
│   ├── svgs/                  ← SVG 素材
│   ├── images/                ← 图片素材
│   └── fonts/                 ← 字体文件
└── renders/                   ← 渲染产物输出（.gitignore 排除）

data-demo/                     ← 精简版 demo 数据（12 个模板，进公开仓库）
├── template_index_v2.json
├── template_vectors.json
├── edit_specs/
├── palxp-raw/                 ← demo 用的 12 个模板的层数据
└── assets/
```

**demo 数据生成**：`~/Desktop/虾稿备份/demo-builder/build_demo_data.py`
- 按 usage_type 均衡抽样（cover 50%，content 30%，poster 20%）
- 生成完整可运行的 demo 包

---

### 6. 环境变量

| 变量 | 作用 | 默认值 |
|------|------|--------|
| `VISUAL_RAG_DATA_DIR` | 数据目录路径，三个服务都读 | `{项目根}/data` |
| `VISUAL_RAG_PUBLIC_URL` | 生成公网下载链接用，如 ngrok URL | `""` |

**demo 模式启动**：
```bash
VISUAL_RAG_DATA_DIR=./data-demo python src/render_server.py
```

---

## 四、数据流与用户体验

### 典型单张出图

```
用户发消息
  ↓
Agent 调 ensure_services         (服务启动，约5-25s，后续复用)
  ↓ 自动上报 "服务就绪"
Agent 调 search_templates        (语义搜索，约3s)
  ↓ 自动上报 "N款候选 🎨"
  ↓ 用户收到飞书消息（状态页链接），可随时查看
Agent 选模板，调 get_template_spec  (读 edit_specs，<1s)
  ↓ 自动上报 "规格就绪 ✍️"
Agent 填槽内容，调 generate_poster  (Playwright 截图，约10-20s)
  ↓ 自动上报 "出炉了 🎉"
Agent 验收（质检报告 + WebFetch render URL）
  ↓
Agent 上报 done，清理 cron
  ↓
状态页停止轮询，展示大图
用户打开状态页，看到完整时间线 + 最终图片
```

### 批量出图（3张以上）

- 主 Agent 持有唯一 cron
- 子 Agent 负责单张出图并回传 render_url
- 主 Agent 收到回传后更新进度文件
- cron 读进度文件转发给用户（实时）
- 所有子 Agent 完成后，主 Agent 写 done 并清理 cron

---

## 五、GitHub 仓库策略

| 仓库 | 内容 | 可见性 |
|------|------|--------|
| `ZooAgentPM/ClawPoster` | 代码（src/、.venv、.gitignore、data-demo/）| 公开 |
| `ZooAgentPM/visual-rag-data` | 完整私有数据（data/）| 私有 |

**ClawPoster 的 .gitignore 关键规则**：
```
data/          # 私有数据排除
*.json         # 所有 JSON 排除
!data-demo/**/*.json  # demo 数据 JSON 例外
```

---

## 六、维护注意事项

### 不要动的

1. **Vite 前端**（`poster-design/`）：palxp 上游，改了追更新会很痛
2. **JS 注入顺序**（`render_server._do_render`）：这些 JS 是调试多次得出的正确顺序，顺序错了会导致文字替换或截图失败
3. **状态页 `/status/create` 代理**：task_id 的 session 绑定在这里，绕过会导致状态页空白
4. **mock_api_server 的 `svgUrl` 逻辑**：有个历史 bug 修复，`w-svg` 组件要求 `svgUrl` 是 SVG XML 字符串而不是 URL，代码里读文件并替换，不要改回去

### 修改时检查连锁影响

| 修改点 | 需要同步检查 |
|--------|------------|
| render_server API 接口 | mcp_server 里调用该接口的工具 |
| edit_specs 槽位格式 | `get_template_spec` 的格式化逻辑 |
| 数据目录结构 | 三个服务的路径常量 + demo 打包脚本 |
| SKILL.md 协议 | 部署到 `~/.agents/skills/visual-rag-design/` |

### 部署更新

SKILL.md 改动后，同步部署：
```bash
cp -r /tmp/visual-rag-design/. ~/.agents/skills/visual-rag-design/
```

render_server 改动后需重启（ensure_services 会自动检测并重启）。

### 常见排查

| 症状 | 原因 | 解决 |
|------|------|------|
| 状态页无更新 | bash curl 走了 7002 而非 3000 | SKILL.md 里 curl 改为 `http://127.0.0.1:3000/status/...` |
| 渲染报「模板数据不存在」| palxp-raw/ 里缺 `t{id}_layers.json` | 检查 DATA_DIR，或重新打包 demo 数据 |
| 语义搜索返回不相关结果 | 向量库未加载（文件不存在）| 检查 `template_vectors.json` 是否在 DATA_DIR |
| 缩略图合图全灰 | covers/ 目录为空或命名不对 | 文件名格式应为 `t{id}-cover_0.webp` |
| 图片质检误报 | edit_specs 字数限制设置过严 | 找对应 `edit_specs/t{id}.json` 调整 `max_chars` |

---

## 七、技术选型说明

- **FastMCP**：MCP 服务框架，支持 stdio 和 streamable-http 双模式
- **FastAPI + uvicorn**：render_server HTTP 框架
- **Playwright**：无头浏览器截图，browser 全程复用（性能关键）
- **sentence-transformers bge-m3**：多语言语义向量，1024 维，中文效果好
- **Pillow**：缩略图合图 + inspect 标注图生成
- **ngrok**：本地服务公网穿透，固定域名（`VISUAL_RAG_PUBLIC_URL`）
