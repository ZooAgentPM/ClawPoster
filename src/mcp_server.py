"""
虾稿设计 MCP Server — stdio 模式，供 Claude Code 自动管理

配置方式（~/.claude/settings.json）：
  "mcpServers": {
    "visual-rag": {
      "command": "/Users/mlamp/visual-rag/.venv/bin/python",
      "args": ["/Users/mlamp/visual-rag/src/mcp_server.py"]
    }
  }

工具清单：
  ensure_services   — 检查并自动启动三个依赖服务
  search_templates  — 语义搜索模板，返回 Top 5 候选 + 缩略图合图
  list_templates    — 关键词过滤模板（降级备用）
  get_template_spec — 获取指定模板的槽位详情
  generate_poster   — 渲染海报，返回 PNG + 质检报告 + 高危裁图
  get_slot_crops    — 按需裁剪指定槽位区域（用于检查 🟡 疑似问题）
"""

import base64
import json
import socket
import subprocess
import time
from pathlib import Path

import httpx
from fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import Response

# ── 路径 ──────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent.parent
_DATA_DIR      = Path(os.environ.get("VISUAL_RAG_DATA_DIR", str(BASE_DIR / "data")))
INDEX_PATH     = _DATA_DIR / "template_index_v2.json"
EDIT_SPECS_DIR = _DATA_DIR / "edit_specs"
RENDER_URL     = "http://127.0.0.1:7002"
VITE_DIR       = BASE_DIR.parent / "虾稿设计-01" / "渲染器" / "poster-design"
PYTHON         = str(BASE_DIR / ".venv/bin/python")

# 公网基础 URL（通过环境变量注入，供生成下载链接用）
# 设置方式：export VISUAL_RAG_PUBLIC_URL=https://your-domain.ngrok-free.app
import os
PUBLIC_URL: str = os.environ.get("VISUAL_RAG_PUBLIC_URL", "").rstrip("/")

# ── 状态页自动上报 ────────────────────────────────────────────
# session_id → task_id，支持并发；_latest_task_id 作为 fallback 兜底单 session 场景
_session_task_map: dict = {}
_latest_task_id: str = ""

def _status_update(ctx: "Context", step: str, message: str, data: dict = {}) -> None:
    """工具执行完后自动上报进度，静默失败不影响主流程。
    优先用 session_id 精确匹配，fallback 到最近创建的 task。"""
    task_id = _session_task_map.get(ctx.session_id, "") or _latest_task_id
    if not task_id:
        return
    try:
        httpx.post(
            f"{RENDER_URL}/status/{task_id}/update",
            json={"step": step, "message": message, "data": data},
            timeout=5,
        )
    except Exception:
        pass

mcp = FastMCP(
    name="虾稿设计",
    instructions=(
        "生成设计海报的工具集。"
        "标准流程：ensure_services → list_templates → get_template_spec → generate_poster。"
        "generate_poster 直接返回渲染好的图片，无需额外读取文件。"
        "返回结果含质检报告（🔴已确认问题/🟡疑似/🟢正常）和高危裁图；"
        "需要放大查看 🟡 槽位时调用 get_slot_crops。"
    ),
)


# ── 自定义路由：文件代理（HTTP 模式下代理 render_server 的渲染图） ──────
@mcp.custom_route("/files/{filename}", methods=["GET"])
async def proxy_file(request: Request) -> Response:
    """将 /files/<filename> 请求代理到 render_server（仅 HTTP 模式生效）"""
    filename = request.path_params["filename"]
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{RENDER_URL}/files/{filename}", timeout=10)
        if r.status_code != 200:
            return Response(content=r.text, status_code=r.status_code)
        return Response(
            content=r.content,
            media_type=r.headers.get("content-type", "image/png"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        return Response(content=str(e), status_code=502)


@mcp.custom_route("/status/create", methods=["POST"])
async def proxy_status_create(request: Request) -> Response:
    global _latest_task_id
    session_id = request.headers.get("mcp-session-id", "")
    body = await request.body()
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{RENDER_URL}/status/create", content=body,
                                  headers={"Content-Type": "application/json"}, timeout=10)
        if r.status_code == 200:
            task_id = r.json().get("task_id", "")
            _latest_task_id = task_id          # 始终更新全局 fallback
            if session_id:
                _session_task_map[session_id] = task_id
        return Response(content=r.content, media_type="application/json", status_code=r.status_code)
    except Exception as e:
        return Response(content=str(e), status_code=502)


@mcp.custom_route("/status/{task_id}/update", methods=["POST"])
async def proxy_status_update(request: Request) -> Response:
    task_id = request.path_params["task_id"]
    body = await request.body()
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{RENDER_URL}/status/{task_id}/update", content=body,
                                  headers={"Content-Type": "application/json"}, timeout=10)
        return Response(content=r.content, media_type="application/json", status_code=r.status_code)
    except Exception as e:
        return Response(content=str(e), status_code=502)


@mcp.custom_route("/status/{task_id}/data", methods=["GET"])
async def proxy_status_data(request: Request) -> Response:
    task_id = request.path_params["task_id"]
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{RENDER_URL}/status/{task_id}/data", timeout=10)
        return Response(content=r.content, media_type="application/json", status_code=r.status_code)
    except Exception as e:
        return Response(content=str(e), status_code=502)


@mcp.custom_route("/status/{task_id}", methods=["GET"])
async def proxy_status_page(request: Request) -> Response:
    task_id = request.path_params["task_id"]
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{RENDER_URL}/status/{task_id}", timeout=10)
        return Response(content=r.content, media_type="text/html", status_code=r.status_code)
    except Exception as e:
        return Response(content=str(e), status_code=502)


# ── 工具函数 ──────────────────────────────────────────────────

def _port_open(port: int) -> bool:
    """检测端口是否已监听"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_port(port: int, timeout: int = 20) -> bool:
    """等待端口就绪，最多 timeout 秒"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.5)
    return False


# ── 工具 1：确保依赖服务运行 ──────────────────────────────────

@mcp.tool()
def ensure_services(ctx: Context) -> str:
    """
    检查三个依赖服务是否运行，缺少的自动启动并等待就绪。

    三个服务：
      - mock API 服务器（端口 7001）
      - Vite 前端渲染器（端口 5173）
      - render_server（端口 7002，Playwright 渲染引擎）

    首次调用约需 15-25 秒（browser 冷启动）。已运行的服务不受影响。
    返回每个服务的最终状态。
    """
    status = {}

    # mock API（7001）
    if _port_open(7001):
        status["mock_api:7001"] = "already running"
    else:
        subprocess.Popen(
            [PYTHON, "src/mock_api_server.py"],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ok = _wait_port(7001, timeout=10)
        status["mock_api:7001"] = "started" if ok else "FAILED to start"

    # Vite 前端（5173）
    if _port_open(5173):
        status["vite:5173"] = "already running"
    else:
        subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", "5173", "--host", "127.0.0.1"],
            cwd=str(VITE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ok = _wait_port(5173, timeout=30)
        status["vite:5173"] = "started" if ok else "FAILED to start"

    # render_server（7002）
    if _port_open(7002):
        status["render_server:7002"] = "already running"
    else:
        subprocess.Popen(
            [PYTHON, "src/render_server.py"],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ok = _wait_port(7002, timeout=30)
        status["render_server:7002"] = "started" if ok else "FAILED to start"

    failed = [k for k, v in status.items() if "FAILED" in v]
    summary = "✓ 所有服务就绪" if not failed else f"✗ 以下服务启动失败：{failed}"

    lines = [summary, ""]
    for k, v in status.items():
        icon = "✓" if "FAILED" not in v else "✗"
        lines.append(f"  {icon} {k}: {v}")

    lines += [
        "",
        "─────────────────────────────",
        "💡 环境就绪。",
        "",
        "通常按这个顺序走会比较顺：",
        "  1. ensure_services   ← 当前",
        "  2. search_templates  — 找到视觉风格合适的模板",
        "  3. get_template_spec — 看清槽位结构和字数限制",
        "  4. 填写内容          — 真实用户信息建议先向用户确认",
        "  5. generate_poster   — 图片会直接在响应里返回",
        "  6. 验收              — 确认没问题后把链接发给用户",
        "",
        "建议从 search_templates 开始，带上缩略图方便视觉选模板。",
        "如果需要做的内容非常多，建议创建子 Agent 来完成图片工作，尽可能批量并行。",
    ]
    _status_update(ctx, "ensure_services", "服务就绪，开始找模板 🚀")
    return "\n".join(lines)


# ── 工具 2：语义搜索模板 ─────────────────────────────────────

@mcp.tool()
def search_templates(
    ctx: Context,
    query: str,
    usage_type: str = "",
    n: int = 5,
    include_thumbnails: bool = True,
    exclude: str = "",
) -> list:
    """
    根据自然语言需求语义搜索模板，返回 Top N 候选 + 缩略图合图。

    参数：
      query              自然语言需求描述（如"清新手绘风减肥打卡封面"）
      usage_type         可选用途前置过滤：cover（小红书封面）/ content（正文配图）/ poster（手机海报）
      n                  返回候选数（默认5，最多10）
      include_thumbnails 是否附带缩略图合图（默认True；无视觉能力的模型设为False）
      exclude            负向风格描述，用向量减法排除（如"古风 国风 水墨 手绘"）

    返回：候选模板列表（含语义匹配度、视觉标签、配色等）
         + 一张缩略图合图（横排 N 张，下方标注模板 ID）[include_thumbnails=True时]
    """
    try:
        resp = httpx.post(
            f"{RENDER_URL}/search_templates",
            json={"query": query, "usage_type": usage_type or None, "n": n, "exclude": exclude},
            timeout=90,
        )
        resp.raise_for_status()
    except Exception as e:
        return [{"type": "text", "text": f"search_templates 失败：{e}"}]

    data       = resp.json()
    candidates = data.get("candidates", [])
    grid       = data.get("thumbnail_grid", {})

    # 文字摘要
    lines = [f"语义搜索「{query}」，匹配 {data.get('count', 0)} 个候选：\n"]
    for c in candidates:
        lines.append(
            f"t{c['id']} (score={c['score']})  {c['brief'][:36]}\n"
            f"  视觉: {' '.join(c.get('visual_tags', [])[:4])}\n"
            f"  配色: {'、'.join(c.get('color_palette', [])[:3])}  "
            f"版面: {c.get('layout_structure', '')}  "
            f"密度: {c.get('content_density', '')}"
        )

    lines += [
        "",
        "─────────────────────────────",
        "💡 选好模板后，建议调 get_template_spec 看槽位结构。",
        "   UUID 每个模板不同，不从 spec 里取容易注入到错误位置。",
        "",
        "   如果这批候选风格不合适：",
        "   · 在 query 里加结构描述词再搜（比如，描述目标群体、视觉风格等）",
        "   · 或用 list_templates 按版面类型过滤",
    ]

    # 缩略图合图 URL（仅 include_thumbnails=True 时附加）
    grid_url = ""
    if include_thumbnails and grid.get("filename"):
        grid_url = f"{PUBLIC_URL}/files/{grid['filename']}" if PUBLIC_URL else grid["filename"]
        lines += [
            "",
            f"📷 以上候选模板的缩略图预览（横排合图，每张下方标有模板 ID）：",
            f"   {grid_url}",
            f"   建议用 WebFetch 访问此 URL 查看各模板视觉风格。",
            f"   选定模板后，用选中的模板 ID 调用 get_template_spec 获取槽位详情。",
        ]

    _status_update(
        ctx,
        "search_templates",
        f"模板库淘货结束！{data.get('count', 0)} 款候选都在这儿 🎨",
        {"grid_url": grid_url} if grid_url else {},
    )
    return [{"type": "text", "text": "\n".join(lines)}]


# ── 工具 3（降级）：关键词过滤模板 ────────────────────────────

@mcp.tool()
def list_templates(
    keyword: str = "",
    size_type: str = "",
    content_density: str = "",
    layout_structure: str = "",
    color_palette: str = "",
    limit: int = 12,
    include_thumbnails: bool = True,
) -> list:
    """
    搜索可用的设计模板，返回经过过滤的关键元数据列表。

    参数：
      keyword            关键词，匹配模板描述和适用场景（如"小红书""喜庆""干货"）
      size_type          尺寸分类：xhs_cover（小红书封面1242×1656）、
                                   phone_poster（手机海报1242×2208）、
                                   xhs_content（小红书配图）
      content_density    内容密度：light（≤3槽）、medium（4-8槽）、heavy（9+槽）
      layout_structure   版面结构：hero_text / split_section / title_with_list /
                                    split_with_image / multi_block / card_layout
      color_palette      配色关键词（如"红色""黑白""蓝色"）
      limit              最多返回条数（默认12）
      include_thumbnails 是否附带缩略图合图（默认True；无视觉能力的模型设为False）

    返回每个模板的：ID、风格描述、适用场景、密度、配色、视觉标签、容量摘要。
    [include_thumbnails=True时] + 一张缩略图合图（横排，下方标注模板 ID）
    """
    with open(INDEX_PATH, encoding="utf-8") as f:
        index = json.load(f)

    templates = index if isinstance(index, list) else index.get("templates", [])

    matched_ids = []
    text_blocks = []
    for t in templates:
        # 过滤
        if keyword:
            blob = " ".join([
                t.get("brief", ""),
                " ".join(t.get("scenarios", [])),
                " ".join(t.get("visual_tags", [])),
                t.get("style", ""),
            ]).lower()
            if keyword.lower() not in blob:
                continue

        if size_type:
            w = t.get("width", 0)
            h = t.get("height", 0)
            if size_type == "xhs_cover" and not (w == 1242 and h in (1656, 1660)):
                continue
            if size_type == "phone_poster" and not (w == 1242 and h == 2208):
                continue
            if size_type == "xhs_content" and not (w == 1242 and h in (1656, 1660)):
                continue

        if content_density and t.get("content_density", "") != content_density:
            continue

        if layout_structure and t.get("layout_structure", "") != layout_structure:
            continue

        if color_palette:
            palette_blob = " ".join(t.get("color_palette", [])).lower()
            if color_palette.lower() not in palette_blob:
                continue

        # 提取关键字段
        tid      = t.get("id", "")
        brief    = t.get("brief", "")[:40]
        scenes   = "、".join(t.get("scenarios", [])[:2])
        density  = t.get("content_density", "")
        palette  = "、".join(t.get("color_palette", [])[:3])
        tags     = " ".join(t.get("visual_tags", [])[:4])
        layout   = t.get("layout_structure", "")
        bg_type  = t.get("background_type", "")

        caps = t.get("slot_capacity", [])
        cap_str = " | ".join(
            f"{c['role']}(≤{c.get('max_chars','?')}字)"
            for c in caps
        ) if caps else ""

        lines = [f"ID:{tid}  [{density}]  {brief}", f"  场景: {scenes}"]
        if tags:    lines.append(f"  视觉: {tags}")
        if palette: lines.append(f"  配色: {palette}")
        if layout:  lines.append(f"  版面: {layout}" + (f"  背景: {bg_type}" if bg_type else ""))
        if cap_str: lines.append(f"  容量: {cap_str}")

        text_blocks.append("\n".join(lines))
        matched_ids.append(tid)

        if len(text_blocks) >= limit:
            break

    if not text_blocks:
        msg = f"没有找到符合条件的模板（keyword={keyword!r} size_type={size_type!r} density={content_density!r}）"
        return [{"type": "text", "text": msg}]

    hint = (
        "\n─────────────────────────────\n"
        "💡 list_templates 是关键词匹配，语义理解有限。\n"
        "   结果不理想时，search_templates 通常能找到更贴近需求的候选。\n"
        "   选定后建议调 get_template_spec 获取槽位规格。"
    )

    output = [{"type": "text", "text": f"共找到 {len(text_blocks)} 个模板：\n\n" + "\n\n".join(text_blocks) + hint}]

    # 缩略图合图 URL（仅 include_thumbnails=True 时附加）
    if include_thumbnails and matched_ids:
        try:
            resp = httpx.post(
                f"{RENDER_URL}/thumbnail_grid",
                json={"ids": matched_ids},
                timeout=10,
            )
            if resp.status_code == 200:
                grid = resp.json()
                if grid.get("filename"):
                    grid_url = f"{PUBLIC_URL}/files/{grid['filename']}" if PUBLIC_URL else grid["filename"]
                    output[0]["text"] += (
                        f"\n\n📷 以上候选模板的缩略图预览（横排合图，每张下方标有模板 ID）：\n"
                        f"   {grid_url}\n"
                        f"   建议用 WebFetch 访问此 URL 查看各模板视觉风格。\n"
                        f"   选定模板后，用选中的模板 ID 调用 get_template_spec 获取槽位详情。"
                    )
        except Exception:
            pass

    return output


# ── 工具 3：获取模板槽位详情 ──────────────────────────────────

@mcp.tool()
def get_template_spec(ctx: Context, template_id: int) -> str:
    """
    获取指定模板的完整槽位规格，用于确定要填哪些内容及字数限制。

    返回每个槽位的：
      - uuid（填充时用作 key）
      - role（语义角色）
      - must_edit（是否必填）
      - max_chars / max_per_line（字数上限和每行字数）
      - line_break（是否需手动 \\n 控制换行）
      - list_line_count（列表必须填满的行数）
      - hint（填写建议）
      - current（原始示例，最可靠的字数参考）

    在调用 generate_poster 之前必须先查看此规格。
    """
    spec_path = EDIT_SPECS_DIR / f"t{template_id}.json"
    if not spec_path.exists():
        return f"未找到模板 {template_id} 的槽位规格（{spec_path.name}）"

    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    slots = spec.get("slots", [])
    if not slots:
        return f"模板 {template_id} 没有可编辑槽位"

    must_slots = [s for s in slots if s.get("must_edit")]
    opt_slots  = [s for s in slots if not s.get("must_edit")]

    def fmt_slot(s: dict) -> str:
        uuid        = s.get("uuid", "")
        role        = s.get("role", "")
        fill_source = s.get("fill_source", "")
        fill_guide  = s.get("fill_guidance", "")
        current     = s.get("current", "")[:80]
        hint        = s.get("hint", "")

        # fill_source 标注
        source_labels = {
            "real_user_data":   "⚠ 必须来自真实用户信息，不能编造",
            "original_content": "可根据需求创作",
            "template_default": "装饰文字，可保留默认",
        }
        source_line = f"\n    来源: {source_labels.get(fill_source, fill_source)}" if fill_source else ""
        guide_line  = f"\n    填写指引: {fill_guide}" if fill_guide else ""

        # w-chart 槽位：特殊格式
        if s.get("widget_type") == "w-chart":
            chart_type = s.get("chart_type", "Chart")
            return (
                f"  uuid: {uuid}\n"
                f"    role: {role} | 类型: {chart_type} | value 为 JSON 字符串"
                f"{source_line}{guide_line}\n"
                f"    示例: {hint}"
            )

        max_chars   = s.get("max_chars", "?")
        max_per_ln  = s.get("max_per_line", "")
        char_px     = s.get("char_px", "")
        el_width    = s.get("element_width_px", "")
        lb          = "  ⚠ 需手动\\n换行" if s.get("line_break") else ""
        lc          = f"  ⚠ 列表必须填满{s['list_line_count']}条" if s.get("list_line_count") else ""

        per_line_info = f" | 每行≤{max_per_ln}字" if max_per_ln else ""
        px_info = f" | {char_px}px/字 × {el_width}px宽" if char_px and el_width else ""

        return (
            f"  uuid: {uuid}\n"
            f"    role: {role} | 最多{max_chars}字{per_line_info}{px_info}{lb}{lc}"
            f"{source_line}{guide_line}\n"
            f"    示例: {current}"
        )

    lines = [f"模板 {template_id} — 共 {len(slots)} 个槽位\n"]

    if must_slots:
        lines.append(f"【必填槽位 {len(must_slots)} 个】")
        lines.extend(fmt_slot(s) for s in must_slots)

    if opt_slots:
        lines.append(f"\n【可选槽位 {len(opt_slots)} 个（可保留原值）】")
        lines.extend(fmt_slot(s) for s in opt_slots)

    lines += [
        "",
        "─────────────────────────────",
        "💡 填写前建议先整体看一遍槽位结构，判断这个模板能不能装下用户的内容。",
        "   槽位数量、版面结构、风格不匹配的话，现在换模板比渲完再返工省事。",
        "   你一定要为用户的目标受众着想，多思考。",
        "",
        "   fill_source 值得注意：",
        "   · 标注「真实用户信息」的槽位（账号名、品牌名等），建议先向用户确认再填",
        "   · current 字段是字数节奏最直观的参考，内容大致对齐就不容易溢出",
        "",
        "   如果模板不合适，可以带结构描述词重新 search_templates，",
        "   比如需要清单结构可以加「title_with_list」之类的词。",
    ]

    _status_update(ctx, "get_template_spec", f"模板 t{template_id} 规格就绪，开始填槽 ✍️")
    return "\n".join(lines)


# ── 工具 4：渲染海报 ──────────────────────────────────────────

@mcp.tool()
def generate_poster(
    ctx: Context,
    template_id: int,
    slots: dict,
    adjustments: list = [],
    open_after: bool = False,
) -> list:
    """
    根据模板 ID 和槽位内容生成海报，直接返回渲染好的 PNG 图片。

    参数：
      template_id  模板 ID（从 list_templates 获取）
      slots        槽位内容，格式：{"uuid": "填入的文字"}
                   必须先用 get_template_spec 确认各 uuid
      adjustments  可选样式微调，格式：
                   [{"id": "uuid", "style": {"transform": "translateY(-20px)"}}]
                   支持：transform / display / opacity / fontSize / top / left
      open_after   是否自动在 Preview.app 打开结果（默认 True）

    返回：文字状态说明 + render 图（最终成品）+ inspect 图（带 UUID 标注，用于定位调整元素）

    使用建议：
      1. 看 render 图确认内容和视觉效果
      2. 看 inspect 图定位需调整的元素（左上角显示 UUID 前8位）
      3. 有问题就带 adjustments 重渲
    """
    # 检查 render_server
    try:
        resp = httpx.get(f"{RENDER_URL}/health", timeout=3)
        if resp.json().get("status") != "ready":
            return [{"type": "text", "text": "render_server 未就绪，请先调用 ensure_services"}]
    except Exception:
        return [{"type": "text", "text": "无法连接 render_server（端口 7002），请先调用 ensure_services"}]

    # 渲染
    try:
        resp = httpx.post(
            f"{RENDER_URL}/render",
            json={"id": template_id, "slots": slots, "adjustments": adjustments},
            timeout=60,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        detail = e.response.json().get("detail", str(e))
        return [{"type": "text", "text": f"渲染失败：{detail}"}]
    except Exception as e:
        return [{"type": "text", "text": f"请求失败：{e}"}]

    result       = resp.json()
    render_path  = Path(result.get("render", ""))
    inspect_path = Path(result.get("inspect", ""))
    qa_report    = result.get("qa_report", "")
    crops        = result.get("crops", {})   # {uuid: path_str} for 🔴 items

    if not render_path.exists():
        return [{"type": "text", "text": f"渲染文件不存在：{render_path}"}]

    # 自动打开
    if open_after:
        subprocess.Popen(["open", str(render_path)])

    # 构建公网 URL（服务始终以 HTTP 模式 + PUBLIC_URL 运行）
    render_url  = f"{PUBLIC_URL}/files/{render_path.name}"  if PUBLIC_URL else str(render_path)
    inspect_url = f"{PUBLIC_URL}/files/{inspect_path.name}" if PUBLIC_URL and inspect_path.exists() else ""

    qa_section = f"\n\n{qa_report}" if qa_report else ""

    crop_url_lines = ""
    for uuid, crop_path_str in crops.items():
        crop_name = Path(crop_path_str).name
        crop_url  = f"{PUBLIC_URL}/files/{crop_name}" if PUBLIC_URL else crop_path_str
        crop_url_lines += f"\n  🔴 高危裁图 {uuid[:8]}: {crop_url}"

    output = [{"type": "text", "text": (
        f"✓ 渲染完成  模板: t{template_id}\n"
        f"  📥 render（成品）:  {render_url}\n"
        f"  📥 inspect（标注）: {inspect_url}\n"
        f"  render_path: {render_path}  ← 调用 get_slot_crops 时传此路径（每次渲染不同，必须用本次的）"
        f"{crop_url_lines}"
        f"{qa_section}\n\n"
        "─────────────────────────────\n"
        "💡 图片通过公网 URL 提供，建议用 WebFetch 访问 📥 URL 查看——render_path 是服务端本地路径，你的机器上没有这个文件。\n"
        "\n"
        "验收建议（先看质检报告，再看图）：\n"
        "\n"
        "【有视觉能力的模型】\n"
        "  🔴 有确认问题时：\n"
        "    → 高危裁图 URL 已附在上方，建议先 WebFetch 确认具体溢出情况\n"
        "    → 通常缩短对应槽位文字后重渲即可\n"
        "    → 若是布局遮挡，参考 resource/ADJUSTMENTS.md 用 adjustments 微调\n"
        "    → 示例：「主标题溢出」→ WebFetch 高危裁图确认 → 把 hook 从14字缩到6字 → 重新 generate_poster\n"
        "  🟡 疑似问题时：\n"
        "    → 建议先用 get_slot_crops 放大看，确认后再决定要不要处理\n"
        "    → 示例：「副标题接近溢出」→ get_slot_crops(render_path=..., uuids=[\"829a3915\"]) → WebFetch 裁图 URL 确认\n"
        "  🟢 全部正常时：\n"
        "    → 用 WebFetch 访问 📥 render URL，目视确认整体效果（贴纸有没有盖字、列表有没有大片空白）\n"
        "    → 没问题就把 📥 render URL 发给用户\n"
        "\n"
        "【非视觉模型】\n"
        "  → 依据质检报告文字处理 🔴，🟡 从源头控制字数规避，🟢 直接把 📥 render URL 发给用户\n"
        "  → 不需要也没有办法做视觉检查\n"
        "\n"
        "批量生成时，建议每张独立验收后再做下一张。"
    )}]

    _status_update(
        ctx,
        "generate_poster",
        "出炉了！热乎的 🎉",
        {"render_url": render_url},
    )
    return output


# ── 工具 5：按需裁图 ──────────────────────────────────────────

@mcp.tool()
def get_slot_crops(ctx: Context, render_path: str, uuids: list, pad: int = 20) -> list:
    """
    对指定槽位进行高清裁图，便于仔细检查具体内容区域。

    参数：
      render_path  渲染结果路径（generate_poster 返回的 render 字段值）
      uuids        要裁剪的槽位 uuid 列表（支持完整 uuid 或前8位）
      pad          四周留白像素（默认 20）

    返回：各 uuid 对应的裁剪图片。

    使用时机：
      - 质检报告出现 🟡 疑似问题，想仔细确认时
      - 任何槽位需要高清放大查看时
    """
    try:
        resp = httpx.post(
            f"{RENDER_URL}/crop_slots",
            json={"render_path": render_path, "uuids": uuids, "pad": pad},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        return [{"type": "text", "text": f"裁图失败：{e}"}]

    data   = resp.json()
    output = []

    for uuid, info in data.items():
        if "error" in info:
            output.append({"type": "text", "text": f"❌ {uuid[:8]}: {info['error']}"})
        else:
            crop_file = Path(info.get("crop_file", ""))
            crop_url  = f"{PUBLIC_URL}/files/{crop_file.name}" if PUBLIC_URL and crop_file.name else str(crop_file)
            output.append({"type": "text", "text": f"↓ {uuid[:8]} 裁图: {crop_url}"})

    output.append({"type": "text", "text": (
        "\n─────────────────────────────\n"
        "💡 用 WebFetch 访问上方裁图 URL 查看放大内容。\n"
        "   · 文字明显被截断 → 缩短内容后重新 generate_poster\n"
        "   · 布局位置问题 → 参考 resource/ADJUSTMENTS.md\n"
        "   · 只是贴近边缘、内容完整 → 误报，继续验收"
    )})
    _status_update(ctx, "get_slot_crops", "放大裁图完成，质检确认中 🔍")
    return output


# ── 启动 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="虾稿设计 MCP Server")
    parser.add_argument(
        "--port", type=int, default=None,
        help="HTTP 模式端口（省略则用 stdio）。ngrok 穿透时使用此模式。",
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="HTTP 模式监听地址（默认 127.0.0.1，ngrok 不需要改为 0.0.0.0）",
    )
    args = parser.parse_args()

    if args.port:
        # HTTP 模式：供 ngrok 公网穿透，或局域网直接访问
        # 远端 Claude Code 注册命令：
        #   claude mcp add --transport http visual-rag https://<ngrok-url>/mcp
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        # stdio 模式：本地 Claude Code 自动管理
        mcp.run(transport="stdio")
