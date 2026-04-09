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
BASE_DIR    = Path(__file__).parent.parent
RAW_DIR     = BASE_DIR / "data" / "palxp-raw"
ASSETS_DIR  = BASE_DIR / "data" / "assets"
OUT_DIR     = BASE_DIR / "data" / "renders"
COVER_DIR   = BASE_DIR / "data" / "assets" / "covers"
INDEX_PATH  = BASE_DIR / "data" / "template_index_v2.json"
VECTORS_PATH = BASE_DIR / "data" / "template_vectors.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

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


def _keyword_fallback(query: str, size_type: Optional[str], n: int) -> list[dict]:
    """向量库不存在时的降级：关键词匹配 + 随机扰动。"""
    import random
    pool = list(_index)
    if size_type:
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
    把 N 张封面缩略图拼成一张横排合图，返回 base64 PNG。
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

    import io
    buf = io.BytesIO()
    grid.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode()

_COLORS = [
    "#FF5733", "#33C1FF", "#28B463", "#F39C12",
    "#9B59B6", "#E74C3C", "#1ABC9C", "#2E86C1",
    "#D35400", "#7D3C98",
]

# ── 全局 browser 状态 ────────────────────────────────────────
_pw      = None
_browser = None
_lock    = asyncio.Lock()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    global _pw, _browser
    _load_search_data()          # 加载向量库和模板索引
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


# ── inspect 标注图（同 render_single.py） ─────────────────────
def _build_inspect_image(render_path: Path, elements: list[dict]) -> Path:
    img     = Image.open(render_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    try:
        font       = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        font = font_small = ImageFont.load_default()

    for i, el in enumerate(elements):
        hex_c  = _COLORS[i % len(_COLORS)]
        r, g, b = int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)
        x, y, w, h = el["x"], el["y"], el["w"], el["h"]

        draw.rectangle([x, y, x + w, y + h], fill=(r, g, b, 40))
        for off in range(2):
            draw.rectangle([x+off, y+off, x+w-off, y+h-off], outline=(r, g, b, 220))

        label = el["id"][:8]
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

    finally:
        await page.close()

    inspect_path = _build_inspect_image(out_path, elements)
    return {"render": str(out_path), "inspect": str(inspect_path)}


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
    n: int = 5


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

        # 前置过滤（size_type）
        pool = _index
        if req.size_type:
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
        fallback = _keyword_fallback(req.query, req.size_type, n)
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
        })

    template_ids = [r["id"] for r in results]
    grid_b64     = _make_thumbnail_grid(template_ids)

    return JSONResponse({
        "query":      req.query,
        "count":      len(results),
        "candidates": results,
        "thumbnail_grid": {
            "format": "image/png;base64",
            "data":   grid_b64,
            "note":   f"横排 {len(results)} 张缩略图，下方标注模板 ID",
        },
    })


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
