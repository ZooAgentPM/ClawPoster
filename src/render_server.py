"""
虾稿设计 · 渲染 HTTP 服务（browser 复用版）

启动：
  cd /Users/mlamp/visual-rag
  .venv/bin/python src/render_server.py          # 默认端口 7002
  .venv/bin/python src/render_server.py --port 7002

接口：
  POST /render
    Body: {"id": 708, "slots": {"uuid": "text"}, "adjustments": [{"id":"uuid","style":{...}}]}
    返回: {"render": "/path/t708_render.png", "inspect": "/path/t708_inspect.png"}

  GET  /health
    返回: {"status": "ready", "browser": "connected"}

与 render_single.py 的区别：
  - browser 在服务启动时 launch 一次，所有请求复用
  - 每次请求新建/关闭 page（隔离状态，安全）
  - 请求串行处理（asyncio.Lock），避免 Playwright 并发问题
  - 渲染核心逻辑与 render_single.py 保持一致
"""

import asyncio
import base64
import json
import math
import mimetypes
from pathlib import Path
from typing import Optional

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright
from pydantic import BaseModel

# ── 路径配置 ──────────────────────────────────────────────────
# DATA_DIR 可通过环境变量覆盖，支持 demo 数据包（data-demo/）或自定义路径
import os as _os
BASE_DIR    = Path(__file__).parent.parent
DATA_DIR    = Path(_os.environ.get("VISUAL_RAG_DATA_DIR", str(BASE_DIR / "data")))
RAW_DIR     = DATA_DIR / "palxp-raw"
ASSETS_DIR  = DATA_DIR / "assets"
OUT_DIR     = DATA_DIR / "renders"
COVER_DIR   = DATA_DIR / "assets" / "covers"
INDEX_PATH  = DATA_DIR / "template_index_v2.json"
VECTORS_PATH = DATA_DIR / "template_vectors.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)
ECHARTS_JS    = Path(__file__).parent / "echarts.min.js"   # 本地 ECharts（可选）
EDIT_SPECS_DIR = DATA_DIR / "edit_specs"                   # 槽位规格目录

# ── 语义搜索：向量库（启动时加载）──────────────────────────────
_vectors: dict   = {}   # {template_id_str: np.ndarray}
_index:   list   = []   # template_index_v2 列表
_embed_model     = None  # sentence-transformers 模型（懒加载）


def _load_search_data():
    """启动时加载向量库和模板索引。向量库不存在时静默跳过（降级到关键词搜索）。"""
    global _vectors, _index
    if INDEX_PATH.exists():
        _index = json.loads(INDEX_PATH.read_text())
    if VECTORS_PATH.exists():
        raw = json.loads(VECTORS_PATH.read_text())
        _vectors = {k: np.array(v, dtype=np.float32) for k, v in raw["vectors"].items()}
        print(f"向量库加载完成：{len(_vectors)} 个模板，dim={raw['dim']}")
    else:
        print("⚠ 向量库不存在，/search_templates 将使用关键词 fallback")


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer("BAAI/bge-m3")
    return _embed_model


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _mmr(query_vec: np.ndarray, candidates: list[tuple], n: int, lam: float = 0.7) -> list:
    """
    Maximal Marginal Relevance：在相关性和多样性之间取平衡。
    candidates: [(id_str, relevance_score, vec), ...]
    lam=1 纯相关性，lam=0 纯多样性。
    """
    selected = []
    remaining = list(candidates)
    while len(selected) < n and remaining:
        if not selected:
            best = max(remaining, key=lambda x: x[1])
        else:
            sel_vecs = [s[2] for s in selected]
            best = max(
                remaining,
                key=lambda c: lam * c[1] - (1 - lam) * max(_cosine_sim(c[2], sv) for sv in sel_vecs)
            )
        selected.append(best)
        remaining.remove(best)
    return selected


def _keyword_fallback(query: str, size_type: Optional[str], n: int, usage_type: Optional[str] = None) -> list[dict]:
    """向量库不存在时的降级：关键词匹配 + 随机扰动。"""
    import random
    pool = list(_index)
    if usage_type:
        pool = [t for t in pool if t.get("usage_type") == usage_type] or pool
    elif size_type:
        pool = [t for t in pool if t.get("size_type") == size_type] or pool
    query_words = set(query)
    def score(t):
        text = " ".join([t.get("brief",""), t.get("style",""), " ".join(t.get("visual_tags",[])),
                         " ".join(t.get("scenarios",[]))])
        return sum(1 for w in query_words if w in text) + random.uniform(0, 0.5)
    pool.sort(key=score, reverse=True)
    return pool[:n]


def _make_thumbnail_grid(template_ids: list[int], thumb_w: int = 240, thumb_h: int = 320) -> str:
    """
    把 N 张封面缩略图拼成一张横排合图，保存到 renders/ 目录，返回文件名。
    每张下方标注模板编号。
    """
    n = len(template_ids)
    pad = 12
    label_h = 28
    grid_w = (thumb_w + pad) * n + pad
    grid_h = thumb_h + label_h + pad * 2
    grid = Image.new("RGB", (grid_w, grid_h), (245, 245, 245))
    draw = ImageDraw.Draw(grid)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 18)
    except Exception:
        font = ImageFont.load_default()

    for i, tid in enumerate(template_ids):
        x = pad + i * (thumb_w + pad)
        y = pad

        cover = COVER_DIR / f"t{tid}-cover_0.webp"
        if cover.exists():
            img = Image.open(cover).convert("RGB")
            img = img.resize((thumb_w, thumb_h), Image.LANCZOS)
            grid.paste(img, (x, y))
        else:
            draw.rectangle([x, y, x + thumb_w, y + thumb_h], fill=(200, 200, 200))

        # 边框
        draw.rectangle([x, y, x + thumb_w, y + thumb_h], outline=(180, 180, 180), width=1)

        # 模板编号标签
        label = f"t{tid}"
        lx = x + thumb_w // 2
        ly = y + thumb_h + 6
        draw.text((lx, ly), label, fill=(80, 80, 80), font=font, anchor="mt")

    import io, time as _t
    filename = f"grid_{'_'.join(str(i) for i in template_ids[:4])}_{int(_t.time()*1000)}.png"
    out_path = OUT_DIR / filename
    grid.save(str(out_path), format="PNG")
    return filename

_COLORS = [
    "#FF5733", "#33C1FF", "#28B463", "#F39C12",
    "#9B59B6", "#E74C3C", "#1ABC9C", "#2E86C1",
    "#D35400", "#7D3C98",
]

# 质检颜色（RGB）
_QA_COLORS = {
    "red":    (220,  50,  50),   # 🔴 已确认问题
    "yellow": (255, 180,   0),   # 🟡 疑似问题
    "green":  ( 50, 180,  80),   # 🟢 正常
    "gray":   (140, 140, 140),   # ⬜ 装饰/非必填
}

# ── 全局 browser 状态 ────────────────────────────────────────
_pw      = None
_browser = None
_lock    = asyncio.Lock()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    global _pw, _browser
    _load_search_data()          # 加载向量库和模板索引
    # 预热 bge-m3（在线程中加载，避免阻塞事件循环；首次调用约 15-30s）
    if _vectors:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _get_embed_model)
        print("[render_server] bge-m3 预热完成 ✓")
    _pw      = await async_playwright().start()
    _browser = await _pw.chromium.launch(headless=True)
    print("[render_server] browser launched ✓")
    yield
    if _browser:
        await _browser.close()
    if _pw:
        await _pw.stop()
    print("[render_server] browser closed")

app = FastAPI(title="虾稿设计渲染服务", lifespan=lifespan)


# ── 请求模型 ──────────────────────────────────────────────────
class RenderRequest(BaseModel):
    id:          int
    slots:       dict  = {}
    adjustments: list  = []


# ── inspect 标注图 ────────────────────────────────────────────
def _build_inspect_image(
    render_path: Path,
    elements: list[dict],
    slot_qa: dict | None = None,
) -> Path:
    """
    slot_qa: {uuid: "red"/"yellow"/"green"/"gray"} — 有则按质检颜色上色，无则彩虹色。
    """
    img     = Image.open(render_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    try:
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        font_small = ImageFont.load_default()

    for i, el in enumerate(elements):
        uuid = el["id"]
        if slot_qa is not None:
            r, g, b = _QA_COLORS.get(slot_qa.get(uuid, "gray"), (140, 140, 140))
        else:
            hex_c  = _COLORS[i % len(_COLORS)]
            r, g, b = int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)

        x, y, w, h = el["x"], el["y"], el["w"], el["h"]
        draw.rectangle([x, y, x + w, y + h], fill=(r, g, b, 40))
        for off in range(2):
            draw.rectangle([x+off, y+off, x+w-off, y+h-off], outline=(r, g, b, 220))

        label = uuid[:8]
        bbox  = draw.textbbox((0, 0), label, font=font_small)
        lw, lh = bbox[2] - bbox[0] + 6, bbox[3] - bbox[1] + 4
        lx, ly = x + 2, y + 2
        draw.rectangle([lx, ly, lx+lw, ly+lh], fill=(255, 255, 255, 220))
        draw.text((lx+3, ly+2), label, fill=(r, g, b, 255), font=font_small)

    out = Image.alpha_composite(img, overlay).convert("RGB")
    inspect_path = render_path.parent / render_path.name.replace("_render.png", "_inspect.png")
    out.save(str(inspect_path))
    return inspect_path


# ── 核心渲染逻辑（async Playwright，复用 browser） ────────────
async def _do_render(template_id: int, slots: dict, adjustments: list) -> dict:
    layer_file = RAW_DIR / f"t{template_id}_layers.json"
    if not layer_file.exists():
        raise FileNotFoundError(f"模板数据不存在: {layer_file}")

    d        = json.loads(layer_file.read_text(encoding="utf-8"))
    page_data = d.get("dActiveElement", {})
    canvas_h  = int(page_data.get("height", 1656))

    page = await _browser.new_page(
        viewport={"width": 1300, "height": max(canvas_h + 200, 2400)}
    )
    try:
        # 本地素材拦截
        async def handle_route(route):
            url = route.request.url
            if "design.palxp.cn/static" in url:
                fname = url.split("/")[-1].split("?")[0]
                for sub in ["images", "svgs", "covers", "fonts"]:
                    p = ASSETS_DIR / sub / fname
                    if p.exists():
                        mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                        await route.fulfill(
                            status=200,
                            headers={"Content-Type": mime, "Access-Control-Allow-Origin": "*"},
                            body=p.read_bytes(),
                        )
                        return
            await route.continue_()

        await page.route("**/*", handle_route)

        # 导航
        await page.goto(
            f"http://127.0.0.1:5173/html?tempid={template_id}",
            wait_until="networkidle",
            timeout=30000,
        )

        # 等待字体与布局稳定
        try:
            await page.evaluate("async () => { await document.fonts.ready }", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(800)

        # 关闭水印
        await page.evaluate("""() => {
            const pinia = document.getElementById('app')
                ?.__vue_app__?.config?.globalProperties?.$pinia;
            if (pinia?.state?.value?.base)
                pinia.state.value.base.watermark = [];
        }""")

        # 注入槽位文本（Vue reactive 优先，DOM 回退）
        if slots:
            slots_js = json.dumps(slots, ensure_ascii=False)
            result = await page.evaluate(f"""() => {{
                const slots = {slots_js};
                const report = {{}};

                function searchInst(vnode, depth) {{
                    if (!vnode || depth > 8) return null;
                    if (vnode.component) {{
                        const inst = vnode.component;
                        if (inst.setupState && 'pageGroup' in inst.setupState) return inst;
                        const r = searchInst(inst.subTree, depth + 1);
                        if (r) return r;
                    }}
                    const ch = vnode.children;
                    if (Array.isArray(ch)) {{
                        for (const c of ch) {{ const r = searchInst(c, depth + 1); if (r) return r; }}
                    }} else if (ch && typeof ch === 'object') {{
                        for (const c of Object.values(ch)) {{
                            if (c && typeof c === 'object') {{
                                const r = searchInst(c, depth + 1);
                                if (r) return r;
                            }}
                        }}
                    }}
                    return null;
                }}

                const appInst = document.getElementById('app')?.__vue_app__?._instance;
                const htmlComp = appInst ? searchInst(appInst.subTree, 0) : null;
                const dWidgets = htmlComp?.setupState?.pageGroup?.[0]?.dWidgets || [];

                for (const [uuid, text] of Object.entries(slots)) {{
                    // 优先：Vue reactive 注入（不触发 textEffects GPU 合成层颜色错误）
                    // 例外：widget.text 含 rough-annotation SVG 时，直接覆盖会丢失手绘装饰，
                    //       必须 fall-through 到 DOM 注入路径（DOM 注入会保留 SVG 子节点）。
                    const widget = dWidgets.find(w => String(w.uuid) === uuid);
                    const hasRoughAnnotation = widget && String(widget.text || '').includes('rough-annotation');
                    if (widget && !hasRoughAnnotation) {{
                        widget.text = text;
                        // 仅 justify 模板才设 textAlignLast:left 抑制末行拉伸
                        // center/left 模板不能改，否则所有行变左对齐
                        if (widget.textAlign === 'justify') {{
                            widget.textAlignLast = 'left';
                        }}
                        report[uuid] = 'OK';
                        continue;
                    }}

                    const el = document.getElementById(uuid);
                    if (!el) {{ report[uuid] = 'NOT_FOUND'; continue; }}
                    const targets = el.querySelectorAll('.edit-text');
                    targets.forEach(div => {{
                        const isJustify = window.getComputedStyle(div).textAlign === 'justify';
                        const isEffect = div.classList.contains('effect-text');
                        if (isEffect) {{
                            div.textContent = text;
                            if (isJustify) div.style.textAlignLast = 'left';
                        }} else {{
                            const firstSpan = div.querySelector('span');
                            const attrs = firstSpan
                                ? [...firstSpan.attributes].filter(a => a.name.startsWith('data-v-'))
                                : [];
                            [...div.childNodes].forEach(n => {{
                                if (n.nodeName.toLowerCase() !== 'svg') n.remove();
                            }});
                            const span = document.createElement('span');
                            attrs.forEach(a => span.setAttribute(a.name, ''));
                            span.textContent = text;
                            span.style.position = 'relative';
                            span.style.zIndex = '1';
                            div.insertBefore(span, div.firstChild);
                            if (isJustify) div.style.textAlignLast = 'left';
                        }}
                    }});
                    report[uuid] = targets.length > 0 ? 'OK' : 'NO_EDIT_TEXT';
                }}
                return report;
            }}""")
            await page.wait_for_timeout(200)

            failed = {uuid: s for uuid, s in result.items() if s != "OK"}
            if failed:
                raise RuntimeError(
                    "槽位注入失败：\n"
                    + "\n".join(f"  {uuid}: {s}" for uuid, s in failed.items())
                )

        # 元素样式调整
        if adjustments:
            adj_js = json.dumps(adjustments, ensure_ascii=False)
            await page.evaluate(f"""() => {{
                const adjs = {adj_js};
                for (const adj of adjs) {{
                    const el = document.getElementById(adj.id);
                    if (!el) continue;
                    for (const [prop, val] of Object.entries(adj.style)) {{
                        el.style[prop] = val;
                    }}
                }}
            }}""")
            await page.wait_for_timeout(200)

        # w-chart 渲染（palxp 未内置 ECharts，需手动初始化）
        # slots 中 value 为 JSON 对象字符串的条目视为图表数据（其余为文本）
        chart_slots: dict = {}
        for uuid, val in (slots or {}).items():
            if isinstance(val, str) and val.strip().startswith("{"):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, dict):
                        chart_slots[uuid] = parsed
                except json.JSONDecodeError:
                    pass

        has_charts = await page.evaluate("""() => {
            return document.querySelectorAll('w-chart').length > 0;
        }""")
        if has_charts and ECHARTS_JS.exists():
            await page.add_script_tag(path=str(ECHARTS_JS))
            await page.wait_for_timeout(200)
            chart_slots_js = json.dumps(chart_slots, ensure_ascii=False)
            await page.evaluate(f"""() => {{
                const chartSlots = {chart_slots_js};
                function searchInst(vnode, depth) {{
                    if (!vnode || depth > 8) return null;
                    if (vnode.component) {{
                        const inst = vnode.component;
                        if (inst.setupState && 'pageGroup' in inst.setupState) return inst;
                        const r = searchInst(inst.subTree, depth + 1);
                        if (r) return r;
                    }}
                    const ch = vnode.children;
                    if (Array.isArray(ch)) {{
                        for (const c of ch) {{ const r = searchInst(c, depth + 1); if (r) return r; }}
                    }} else if (ch && typeof ch === 'object') {{
                        for (const c of Object.values(ch)) {{
                            if (c && typeof c === 'object') {{ const r = searchInst(c, depth + 1); if (r) return r; }}
                        }}
                    }}
                    return null;
                }}
                const appInst = document.getElementById('app')?.__vue_app__?._instance;
                const htmlComp = appInst ? searchInst(appInst.subTree, 0) : null;
                const dWidgets = htmlComp?.setupState?.pageGroup?.[0]?.dWidgets || [];
                const charts = dWidgets.filter(w => w.type === 'w-chart');
                for (const widget of charts) {{
                    const el = document.getElementById(widget.uuid);
                    if (!el || typeof echarts === 'undefined') continue;
                    el.innerHTML = '';
                    el.style.position = 'absolute';
                    el.style.left     = widget.left   + 'px';
                    el.style.top      = widget.top    + 'px';
                    el.style.width    = widget.width  + 'px';
                    el.style.height   = widget.height + 'px';
                    el.style.overflow = 'hidden';
                    const container = document.createElement('div');
                    container.style.width  = '100%';
                    container.style.height = '100%';
                    el.appendChild(container);
                    const chart = echarts.init(container, null, {{renderer: 'canvas'}});
                    const option = {{backgroundColor: 'transparent'}};
                    // 基础数据来自 widget JSON
                    if (widget.title)  option.title  = widget.title;
                    if (widget.xAxis)  {{ option.xAxis = widget.xAxis; option.yAxis = widget.yAxis; }}
                    if (widget.series) option.series  = widget.series;
                    if (widget.legend) option.legend  = widget.legend;
                    // 用 slots 传入的自定义数据覆盖
                    const custom = chartSlots[widget.uuid];
                    if (custom) {{
                        if (custom.title_text && option.title)
                            option.title.text = custom.title_text;
                        if (custom.xAxis_data && option.xAxis)
                            option.xAxis.data = custom.xAxis_data;
                        if (custom.series_data && option.series && option.series[0])
                            option.series[0].data = custom.series_data;
                        if (custom.series_name && option.series && option.series[0])
                            option.series[0].name = custom.series_name;
                        if (custom.legend_data && option.legend)
                            option.legend.data = custom.legend_data;
                    }}
                    chart.setOption(option);
                }}
            }}""")
            await page.wait_for_timeout(500)

        # 截图
        canvas = await page.query_selector("#page-design-canvas")
        if not canvas:
            raise RuntimeError("找不到画布元素 #page-design-canvas，请确认 Vite 服务正常运行")

        box      = await canvas.bounding_box()
        import time as _time
        _ts = int(_time.time() * 1000)
        out_path = OUT_DIR / f"t{template_id}_{_ts}_render.png"
        await page.screenshot(
            path=str(out_path),
            clip={"x": box["x"], "y": box["y"],
                  "width": box["width"], "height": box["height"]},
        )

        # 获取元素位置用于 inspect 图
        elements = await page.evaluate(f"""() => {{
            const canvas = document.getElementById('page-design-canvas');
            if (!canvas) return [];
            const canvasBox = canvas.getBoundingClientRect();
            const scale = {box["width"]} / canvasBox.width;
            return [...canvas.querySelectorAll('[id]')]
                .map(el => {{
                    const b = el.getBoundingClientRect();
                    return {{
                        id: el.id,
                        x: Math.round((b.left - canvasBox.left) * scale),
                        y: Math.round((b.top  - canvasBox.top)  * scale),
                        w: Math.round(b.width  * scale),
                        h: Math.round(b.height * scale),
                    }};
                }})
                .filter(e => e.id && e.w > 10 && e.h > 10);
        }}""")

        # ── 质检：DOM 溢出检测（在 page 关闭前执行） ─────────────────
        slot_info: dict = {}  # {uuid: {role, label, must_edit, widget_type}}
        spec_path = EDIT_SPECS_DIR / f"t{template_id}.json"
        if spec_path.exists():
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            for s in spec.get("slots", []):
                uid = s.get("uuid", "")
                if uid:
                    slot_info[uid] = {
                        "role":        s.get("role", ""),
                        "label":       s.get("label", s.get("role", "")),
                        "must_edit":   bool(s.get("must_edit", False)),
                        "widget_type": s.get("widget_type", ""),
                    }

        must_edit_uuids = [u for u, info in slot_info.items() if info["must_edit"]]
        dom_metrics: dict = {}
        if must_edit_uuids:
            uuids_js = json.dumps(must_edit_uuids)
            dom_metrics = await page.evaluate(f"""() => {{
                const uuids = {uuids_js};
                const result = {{}};
                for (const uuid of uuids) {{
                    const el = document.getElementById(uuid);
                    if (!el) {{ result[uuid] = {{missing: true}}; continue; }}
                    const bbox = el.getBoundingClientRect();
                    result[uuid] = {{
                        scrollW: el.scrollWidth,
                        clientW: el.clientWidth,
                        scrollH: el.scrollHeight,
                        clientH: el.clientHeight,
                        bboxW:   Math.round(bbox.width),
                        bboxH:   Math.round(bbox.height),
                    }};
                }}
                return result;
            }}""")

    finally:
        await page.close()

    # ── 质检结果处理 ─────────────────────────────────────────────
    slot_qa:   dict = {}   # uuid → "red"/"yellow"/"green"/"gray"
    qa_issues: list = []   # [(level, uuid, label, reason)]
    elem_ids   = {el["id"] for el in elements}

    for el in elements:
        uuid = el["id"]
        info = slot_info.get(uuid)
        if info is None or not info["must_edit"]:
            slot_qa[uuid] = "gray"
            continue

        if info.get("widget_type") == "w-chart":
            if el["w"] <= 0 or el["h"] <= 0:
                slot_qa[uuid] = "red"
                qa_issues.append(("red", uuid, info["label"], "图表未渲染"))
            else:
                slot_qa[uuid] = "green"
            continue

        m = dom_metrics.get(uuid, {})
        if m.get("missing"):
            slot_qa[uuid] = "red"
            qa_issues.append(("red", uuid, info["label"], "元素缺失"))
        elif m.get("bboxW", 1) == 0:
            slot_qa[uuid] = "red"
            qa_issues.append(("red", uuid, info["label"], "元素未渲染"))
        else:
            sw, cw = m.get("scrollW", 0), max(m.get("clientW", 1), 1)
            sh, ch = m.get("scrollH", 0), max(m.get("clientH", 1), 1)
            if sw > cw or sh > ch:
                slot_qa[uuid] = "red"
                if sw > cw:
                    reason = f"文字溢出（scrollW={sw} > clientW={cw}）"
                else:
                    reason = f"文字溢出（scrollH={sh} > clientH={ch}）"
                qa_issues.append(("red", uuid, info["label"], reason))
            elif sw > cw * 0.85 or sh > ch * 0.85:
                slot_qa[uuid] = "yellow"
                pct = int(max(sw / cw, sh / ch) * 100)
                qa_issues.append(("yellow", uuid, info["label"], f"接近溢出（{pct}%）"))
            else:
                slot_qa[uuid] = "green"

    # must_edit 槽位未出现在画布
    for uuid in must_edit_uuids:
        if uuid not in elem_ids and uuid not in slot_qa:
            info = slot_info.get(uuid, {})
            slot_qa[uuid] = "red"
            qa_issues.append(("red", uuid, info.get("label", uuid[:8]), "未出现在画布"))

    green_count = sum(1 for v in slot_qa.values() if v == "green")
    if qa_issues:
        lines = ["📊 质检报告"]
        for level, uuid, label, reason in qa_issues:
            icon = "🔴" if level == "red" else "🟡"
            lines.append(f"  {icon} {uuid[:8]} ({label}): {reason}")
        if green_count:
            lines.append(f"  ✅ 另有 {green_count} 个槽位正常")
        qa_text = "\n".join(lines)
    elif green_count:
        qa_text = f"📊 质检报告：✅ 全部 {green_count} 个槽位正常"
    else:
        qa_text = ""

    # ── 生成 inspect 标注图（色码） ──────────────────────────────
    inspect_path = _build_inspect_image(out_path, elements, slot_qa or None)

    # ── 高危裁图（🔴 items）─────────────────────────────────────
    red_uuids = [uuid for uuid, level in slot_qa.items() if level == "red"]
    el_map    = {el["id"]: el for el in elements}
    crops: dict = {}
    if red_uuids:
        img_crop = Image.open(out_path).convert("RGB")
        W, H = img_crop.size
        PAD  = 20
        for uuid in red_uuids:
            el = el_map.get(uuid)
            if not el:
                continue
            x, y, w, h = el["x"], el["y"], el["w"], el["h"]
            x1, y1 = max(0, x - PAD), max(0, y - PAD)
            x2, y2 = min(W, x + w + PAD), min(H, y + h + PAD)
            crop = img_crop.crop((x1, y1, x2, y2))
            crop_path = out_path.parent / out_path.name.replace("_render.png", f"_crop_{uuid[:8]}.png")
            crop.save(str(crop_path))
            crops[uuid] = str(crop_path)

    # ── 保存元素位置 JSON（供 /crop_slots 按需裁图） ─────────────
    el_json_path = out_path.parent / out_path.name.replace("_render.png", "_elements.json")
    el_json_path.write_text(json.dumps(elements, ensure_ascii=False))

    return {
        "render":    str(out_path),
        "inspect":   str(inspect_path),
        "qa_report": qa_text,
        "crops":     crops,   # {uuid: path_str} for 🔴 items
    }


# ── HTTP 接口 ─────────────────────────────────────────────────
@app.post("/render")
async def render(req: RenderRequest):
    async with _lock:
        try:
            result = await _do_render(req.id, req.slots, req.adjustments)
            return JSONResponse(result)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


class SearchRequest(BaseModel):
    query: str
    size_type: Optional[str] = None
    usage_type: Optional[str] = None   # cover / content / poster
    n: int = 5
    exclude: Optional[str] = ""        # 负向语义，如 "古风 国风 水墨 手绘"


@app.post("/search_templates")
async def search_templates(req: SearchRequest):
    """
    语义搜索模板。
    - 有向量库：embed query → cosine similarity → MMR → Top N
    - 无向量库：关键词 fallback
    返回：候选列表 + 缩略图合图（base64 PNG）
    """
    n = min(max(req.n, 1), 10)

    if not _vectors or not _index:
        return JSONResponse({"error": "模板数据未加载"}, status_code=503)

    if _vectors:
        # 语义搜索路径
        model = _get_embed_model()
        qvec  = np.array(model.encode(req.query, normalize_embeddings=True), dtype=np.float32)

        # 负向风格向量减法：将 qvec 推离排除风格方向
        if req.exclude and req.exclude.strip():
            exc_vec = np.array(model.encode(req.exclude.strip(), normalize_embeddings=True), dtype=np.float32)
            qvec = qvec - 0.4 * exc_vec
            norm = np.linalg.norm(qvec)
            if norm > 0:
                qvec = qvec / norm

        # 前置过滤（usage_type 优先，向下兼容 size_type）
        pool = _index
        if req.usage_type:
            filtered = [t for t in _index if t.get("usage_type") == req.usage_type]
            if filtered:
                pool = filtered
        elif req.size_type:
            filtered = [t for t in _index if t.get("size_type") == req.size_type]
            if filtered:
                pool = filtered

        # cosine 相似度
        candidates = []
        for t in pool:
            tid = str(t["id"])
            if tid not in _vectors:
                continue
            score = _cosine_sim(qvec, _vectors[tid])
            candidates.append((tid, score, _vectors[tid]))

        candidates.sort(key=lambda x: x[1], reverse=True)
        top20 = candidates[:20]

        # MMR 多样性筛选
        selected = _mmr(qvec, top20, n=n, lam=0.7)
    else:
        # fallback
        fallback = _keyword_fallback(req.query, req.size_type, n, req.usage_type)
        selected = [(str(t["id"]), 0.0, None) for t in fallback]

    # 组装返回结果
    index_map = {str(t["id"]): t for t in _index}
    results = []
    for tid_str, score, _ in selected:
        t = index_map.get(tid_str, {})
        results.append({
            "id":           int(tid_str),
            "score":        round(score, 4),
            "brief":        t.get("brief", ""),
            "style":        t.get("style", ""),
            "visual_tags":  t.get("visual_tags", []),
            "color_palette": t.get("color_palette", []),
            "layout_structure": t.get("layout_structure", ""),
            "content_density":  t.get("content_density", ""),
            "decorative_interference": t.get("decorative_interference", ""),
            "size":         t.get("size", ""),
            "usage_type":   t.get("usage_type", ""),
        })

    template_ids  = [r["id"] for r in results]
    grid_filename = _make_thumbnail_grid(template_ids)

    return JSONResponse({
        "query":      req.query,
        "count":      len(results),
        "candidates": results,
        "thumbnail_grid": {
            "filename": grid_filename,
            "note":     f"横排 {len(results)} 张缩略图，下方标注模板 ID",
        },
    })


class ThumbnailGridRequest(BaseModel):
    ids: list[int]
    thumb_w: int = 240
    thumb_h: int = 320


@app.post("/thumbnail_grid")
async def thumbnail_grid(req: ThumbnailGridRequest):
    """
    根据模板 ID 列表生成缩略图合图，返回 base64 PNG。
    供 list_templates 等工具附加视觉参考。
    """
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    grid_filename = _make_thumbnail_grid(req.ids, thumb_w=req.thumb_w, thumb_h=req.thumb_h)
    return JSONResponse({
        "filename": grid_filename,
        "count":    len(req.ids),
        "note":     f"横排 {len(req.ids)} 张缩略图，下方标注模板 ID",
    })


class CropRequest(BaseModel):
    render_path: str
    uuids:       list[str]
    pad:         int = 20


@app.post("/crop_slots")
async def crop_slots(req: CropRequest):
    """
    按需裁剪指定槽位区域。
    render_path: generate_poster 返回的 render 文件路径。
    uuids: 要裁剪的槽位 uuid 列表。
    返回：{uuid: {data: base64, mimeType: "image/png"}} 或 {uuid: {error: ...}}
    """
    import io as _io
    render_path = Path(req.render_path)
    if not render_path.exists():
        raise HTTPException(status_code=404, detail=f"渲染文件不存在：{render_path}")
    el_json_path = render_path.parent / render_path.name.replace("_render.png", "_elements.json")
    if not el_json_path.exists():
        raise HTTPException(status_code=404, detail="元素位置数据不存在，请重新渲染")

    elements = json.loads(el_json_path.read_text())
    img      = Image.open(render_path).convert("RGB")
    W, H     = img.size
    pad      = max(0, req.pad)
    result   = {}

    def _find_el(uid: str):
        """支持完整 UUID 或前缀匹配（8位前缀即可定位）"""
        for el in elements:
            if el["id"] == uid or el["id"].startswith(uid):
                return el
        return None

    for uuid in req.uuids:
        el = _find_el(uuid)
        if not el:
            result[uuid] = {"error": "uuid 未在画布中找到"}
            continue
        x, y, w, h = el["x"], el["y"], el["w"], el["h"]
        x1, y1 = max(0, x - pad), max(0, y - pad)
        x2, y2 = min(W, x + w + pad), min(H, y + h + pad)
        crop = img.crop((x1, y1, x2, y2))
        # 保存裁图到 renders 目录，同时保留 base64 供本地模式用
        crop_filename = render_path.name.replace("_render.png", f"_crop_{uuid[:8]}.png")
        crop_path = OUT_DIR / crop_filename
        crop.save(str(crop_path), format="PNG")
        buf = _io.BytesIO()
        crop.save(buf, format="PNG")
        result[uuid] = {
            "data":      base64.standard_b64encode(buf.getvalue()).decode(),
            "mimeType":  "image/png",
            "crop_file": str(crop_path),
        }

    return JSONResponse(result)


# ── 任务状态页 ───────────────────────────────────────────────────
_status_store: dict = {}
STATUS_DIR = BASE_DIR / "data" / "status"
STATUS_DIR.mkdir(parents=True, exist_ok=True)


def _persist_status(task_id: str):
    (STATUS_DIR / f"{task_id}.json").write_text(
        json.dumps(_status_store[task_id], ensure_ascii=False), encoding="utf-8")


def _load_status(task_id: str):
    if task_id in _status_store:
        return _status_store[task_id]
    f = STATUS_DIR / f"{task_id}.json"
    if f.exists():
        _status_store[task_id] = json.loads(f.read_text(encoding="utf-8"))
        return _status_store[task_id]
    return None


class StatusCreateRequest(BaseModel):
    agent_id: Optional[str] = "unknown"


class StatusUpdateRequest(BaseModel):
    step: str
    message: str
    data: Optional[dict] = {}


_STATUS_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>出图进度</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #111; color: #eee; font-family: -apple-system, sans-serif;
         padding: 24px 16px; max-width: 640px; margin: 0 auto; }
  h1 { font-size: 18px; font-weight: 600; margin-bottom: 20px; color: #fff; }
  .step { display: flex; gap: 12px; padding: 12px 0;
          border-bottom: 1px solid #222; align-items: flex-start; }
  .step:last-child { border-bottom: none; }
  .icon { font-size: 18px; min-width: 24px; text-align: center; margin-top: 2px; }
  .body { flex: 1; }
  .msg { font-size: 15px; line-height: 1.5; }
  .ts { font-size: 12px; color: #666; margin-top: 4px; }
  .thumb { margin-top: 10px; max-width: 100%; border-radius: 8px; }
  .render-img { margin-top: 12px; width: 100%; border-radius: 10px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.6); }
  .done-badge { display: inline-block; background: #1a3a1a; color: #4caf50;
                padding: 4px 10px; border-radius: 20px; font-size: 13px; margin-top: 8px; }
</style>
</head>
<body>
<h1 id="title">⏳ 出图进度</h1>
<div id="timeline"></div>
<script>
const taskId = "TASK_ID_PLACEHOLDER";
let lastCount = 0;
let done = false;

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
}

function renderStep(s) {
  const div = document.createElement('div');
  div.className = 'step';
  const isDone = s.step === 'done';
  const icon = isDone ? '✅' : '⏳';
  let extra = '';
  if (s.data && s.data.grid_url) {
    extra = `<img class="thumb" src="${s.data.grid_url}" alt="模板预览">`;
  }
  if (isDone && s.data && s.data.render_url) {
    extra = `<img class="render-img" src="${s.data.render_url}" alt="渲染结果">`;
  }
  div.innerHTML = `
    <div class="icon">${icon}</div>
    <div class="body">
      <div class="msg">${s.message}</div>
      <div class="ts">${fmtTime(s.ts)}</div>
      ${extra}
    </div>`;
  return div;
}

async function poll() {
  if (done) return;
  try {
    const r = await fetch('/status/' + taskId + '/data');
    const d = await r.json();
    if (d.steps && d.steps.length > lastCount) {
      const tl = document.getElementById('timeline');
      for (let i = lastCount; i < d.steps.length; i++) {
        tl.appendChild(renderStep(d.steps[i]));
      }
      lastCount = d.steps.length;
      window.scrollTo(0, document.body.scrollHeight);
    }
    if (d.done) {
      done = true;
      document.getElementById('title').textContent = '✅ 任务完成';
    }
  } catch(e) {}
}

poll();
setInterval(poll, 2000);
</script>
</body>
</html>"""


@app.post("/status/create")
async def status_create(req: StatusCreateRequest):
    import time as _time
    task_id = f"{int(_time.time() * 1000) % 1000000:06d}"
    _status_store[task_id] = {
        "created_at": _time.time(),
        "agent_id": req.agent_id,
        "steps": [],
        "done": False,
    }
    _persist_status(task_id)
    return {"task_id": task_id, "status_url": f"/status/{task_id}"}


@app.post("/status/{task_id}/update")
async def status_update(task_id: str, req: StatusUpdateRequest):
    import time as _time
    state = _load_status(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="task not found")
    state["steps"].append({
        "step": req.step,
        "message": req.message,
        "data": req.data or {},
        "ts": _time.time(),
    })
    if req.step == "done":
        state["done"] = True
    _persist_status(task_id)
    return {"ok": True, "total_steps": len(state["steps"])}


@app.get("/status/{task_id}/data")
async def status_data(task_id: str):
    state = _load_status(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="task not found")
    return JSONResponse(state)


@app.get("/status/{task_id}")
async def status_page(task_id: str):
    from fastapi.responses import HTMLResponse
    state = _load_status(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="task not found")
    html = _STATUS_HTML.replace("TASK_ID_PLACEHOLDER", task_id)
    return HTMLResponse(html)


@app.get("/health")
async def health():
    connected = _browser is not None and _browser.is_connected()
    return {"status": "ready" if connected else "degraded", "browser": "connected" if connected else "disconnected"}


@app.get("/files/{filename}")
async def download_file(filename: str):
    """提供渲染结果文件的直接下载（供 ngrok 公网访问）"""
    from fastapi.responses import FileResponse
    path = OUT_DIR / filename
    if not path.exists() or path.suffix not in (".png", ".jpg", ".webp"):
        raise HTTPException(status_code=404, detail=f"文件不存在：{filename}")
    return FileResponse(str(path), media_type="image/png", filename=filename)


# ── 入口 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7002)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
