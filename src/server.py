"""
visual-rag HTTP server — OpenClaw calls this to search & render design assets.

Endpoints:
  GET  /browse/templates?q=...&page=1  → paginated template browsing (AI picks)
  GET  /browse/assets?q=...&page=1     → paginated asset browsing
  POST /fill                           → AI fills content slots from a brief
  GET  /render/{id}?...                → render as HTML (preview in browser)
  GET  /screenshot/{id}?...            → render as real PNG image (for sending in IM)
  GET  /health                         → service status + output modes

  (Legacy)
  GET  /search?q=...&top=3        → ranked search (still works)
  POST /compose                   → one-shot search+fill+render
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from search import search, load_index
from filler import fill_slots
from renderer import render_html
from screenshot import html_to_png, save_screenshot

app = FastAPI(title="visual-rag", description="Design Asset Index for AI Agents")

INDEX = load_index()

ASSET_INDEX_PATH = Path(__file__).parent.parent / "data" / "asset_index.json"

def load_assets() -> list[dict]:
    if ASSET_INDEX_PATH.exists():
        with open(ASSET_INDEX_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []

ASSETS = load_assets()


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "assets": len(INDEX),
        "output_modes": {
            "html_preview": "GET /render/{id}?title=...  → open in browser",
            "png_image":    "GET /screenshot/{id}?title=... → real PNG for IM",
            "editor":       "GET /editor/{id} → open in poster-design editor",
        }
    }


# ── Browse (paginated, AI picks) ──────────────────────────────────────────────

def _asset_keyword_score(query: str, asset: dict) -> float:
    """Simple keyword match for assets."""
    blob = " ".join([
        asset.get("title", ""),
        asset.get("description", ""),
        " ".join(asset.get("usage", {}).get("use_cases", [])),
        " ".join(asset.get("style", {}).get("mood", [])),
        asset.get("style", {}).get("color_name", ""),
    ])
    q = query.replace("，", "").replace(",", "").replace(" ", "").replace("、", "")
    if not q:
        return 0.0
    total = max(len(q) - 1, 1)
    hits = sum(1 for i in range(len(q) - 1) if q[i:i+2] in blob)
    return hits / total


@app.get("/browse/templates")
def browse_templates(
    q: str = Query("", description="搜索关键词，空则按默认顺序列出所有模板"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(5, ge=1, le=10, description="每页数量"),
    platform: str = Query(None, description="按平台筛选，如'小红书'"),
    mood: str = Query(None, description="按风格筛选，如'喜庆'"),
):
    """
    分页浏览设计模板。AI 应读取每条描述后自主选择，而非依赖排名。
    如当前页无合适模板，可请求下一页（page+1）。
    """
    assets = list(INDEX)  # copy

    # Filter
    if platform:
        assets = [a for a in assets if platform in a.get("platforms", [])]
    if mood:
        assets = [a for a in assets if any(mood in m for m in a.get("style", {}).get("mood", []))]

    # Score and sort (if query given), else stable order
    if q.strip():
        from search import _keyword_score
        assets = sorted(assets, key=lambda a: _keyword_score(q, a), reverse=True)

    total = len(assets)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_items = assets[start:start + page_size]

    items = []
    for a in page_items:
        slots = a.get("content_slots", {})
        items.append({
            "id": a["id"],
            "type": "template",
            "cover": a.get("cover", ""),          # image AI can optionally view
            "description": a.get("description", ""),
            "use_cases": a.get("use_cases", []),
            "platforms": a.get("platforms", []),
            "style": {
                "mood": a.get("style", {}).get("mood", []),
                "color_theme": a.get("style", {}).get("color_theme", ""),
            },
            "layout_type": a.get("layout", {}).get("type", ""),
            "slot_names": list(slots.keys()),
            "has_editor": bool(a.get("editor", {}).get("editor_url")),
        })

    hint = f"当前第{page}/{total_pages}页，共{total}个模板。" + (
        f"如需更多选项，请调用 GET /browse/templates?q={q}&page={page+1}" if page < total_pages else "已是最后一页。"
    )

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "query": q,
        "items": items,
        "hint": hint,
    }


@app.get("/browse/assets")
def browse_assets(
    q: str = Query("", description="搜索关键词，如'科技感蓝色特效'"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(5, ge=1, le=10, description="每页数量"),
    element_type: str = Query(None, description="类型筛选：text_effect / text_composition"),
):
    """
    分页浏览设计素材（图标、花字、文字组合等）。
    每个素材附带语义描述和使用规则，AI 根据描述选择合适的素材。
    """
    assets = list(ASSETS)

    if element_type:
        assets = [a for a in assets if a.get("element_type") == element_type]

    if q.strip():
        assets = sorted(assets, key=lambda a: _asset_keyword_score(q, a), reverse=True)

    total = len(assets)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_items = assets[start:start + page_size]

    items = []
    for a in page_items:
        usage = a.get("usage", {})
        items.append({
            "id": a["id"],
            "type": "asset",
            "element_type": a.get("element_type", ""),
            "cover": a.get("cover", ""),           # image AI can optionally view
            "title": a.get("title", ""),
            "description": a.get("description", ""),
            "style": a.get("style", {}),
            "placement": usage.get("placement", ""),
            "best_position": usage.get("best_position", ""),
            "compatible_bg": usage.get("compatible_bg", []),
            "avoid_bg": usage.get("avoid_bg", []),
            "char_limit": usage.get("char_limit", 0),
            "use_cases": usage.get("use_cases", []),
            "platforms": a.get("platforms", []),
        })

    hint = f"当前第{page}/{total_pages}页，共{total}个素材。" + (
        f"如需更多，请调用 GET /browse/assets?q={q}&page={page+1}" if page < total_pages else "已是最后一页。"
    )

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "query": q,
        "items": items,
        "hint": hint,
    }


# ── Analyze Background ────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    image_url: str

@app.post("/analyze-background")
async def analyze_background_endpoint(req: AnalyzeRequest):
    """
    Given a background image URL, use Claude Vision to analyze it:
    - dominant colors, dark/light, mood
    - which zones are clear (good for placing text/assets)
    - which asset moods are compatible
    Returns structured metadata to guide asset selection.
    """
    from compositor import analyze_background
    result = await analyze_background(req.image_url)
    # Also suggest matching assets from our library
    compatible_moods = result.get("compatible_asset_moods", [])
    suggested_assets = []
    for asset in ASSETS:
        asset_moods = asset.get("style", {}).get("mood", [])
        if any(m in compatible_moods for m in asset_moods):
            suggested_assets.append({
                "id": asset["id"],
                "title": asset["title"],
                "element_type": asset.get("element_type"),
                "best_position": asset.get("usage", {}).get("best_position"),
                "description": asset.get("description", "")[:60],
            })
    result["suggested_assets"] = suggested_assets
    return result


# ── Composite ─────────────────────────────────────────────────────────────────

def _parse_font_weight(v) -> int:
    """Accept int or string font weight ('bold'→700, 'normal'→400)."""
    if isinstance(v, int):
        return v
    mapping = {"thin": 100, "light": 300, "normal": 400, "medium": 500,
               "semibold": 600, "bold": 700, "extrabold": 800, "black": 900}
    return mapping.get(str(v).lower(), 400) if not str(v).isdigit() else int(v)

class CompositeLayer(BaseModel):
    type: str                      # text_effect | text_block | text | image
    asset_id: str = ""             # for text_effect / text_block
    text: str = ""                 # for text_effect / text
    fields: dict = {}              # for text_block: {title, subtitle, tag, cta}
    position: str = ""             # zone, e.g. "upper-middle-center"
    font_size_vw: float = 5.0      # for type=text
    color: str = "#ffffff"         # for type=text
    font_weight: int = 700         # also accepts "bold", "normal", etc.
    bg: str = ""
    shadow: bool = False
    url: str = ""                  # for type=image
    width: str = "40%"
    height: str = "40%"

    @classmethod
    def model_validate(cls, obj, **kw):
        if isinstance(obj, dict) and "font_weight" in obj:
            obj = dict(obj)
            obj["font_weight"] = _parse_font_weight(obj["font_weight"])
        return super().model_validate(obj, **kw)

class CompositeRequest(BaseModel):
    background_url: str
    layers: list[CompositeLayer]
    canvas_width: int = 600
    canvas_height: int = 800

@app.post("/composite")
async def composite_endpoint(req: CompositeRequest):
    """
    Compose a background image + asset layers → PNG image.

    AI workflow:
      1. POST /analyze-background to understand the image
      2. GET /browse/assets to find matching assets
      3. POST /composite with chosen layers and positions
      4. Returns image/png ready to send

    Layer positions (zone strings):
      top-left | top-center | top-right
      upper-middle-left | upper-middle-center | upper-middle-right
      center
      lower-middle-left | lower-middle-center | lower-middle-right
      bottom-left | bottom-center | bottom-right
    """
    from compositor import compose_html
    from screenshot import html_to_png

    layers_data = [layer.model_dump() for layer in req.layers]
    html = compose_html(
        background_url=req.background_url,
        layers=layers_data,
        canvas_width=req.canvas_width,
        canvas_height=req.canvas_height,
    )
    png_bytes = await html_to_png(html, width=req.canvas_width, height=req.canvas_height)
    return Response(content=png_bytes, media_type="image/png")


# ── Search (legacy) ───────────────────────────────────────────────────────────

@app.get("/search")
def search_endpoint(
    q: str = Query(..., description="Natural language query, e.g. '双十一大促海报红色喜庆'"),
    top: int = Query(3, description="Number of results"),
    platform: str = Query(None, description="Filter by platform, e.g. '小红书'"),
):
    """
    Search design assets by natural language.
    Returns top matching templates with scores and metadata.
    """
    results = search(q, top_k=top, platform=platform)
    # Remove embedding field (too large) and internal score fields for clean output
    clean = []
    for r in results:
        item = {k: v for k, v in r.items() if k not in ("embedding", "_match_method")}
        item["score"] = round(r.get("_score", 0), 3)
        clean.append(item)
    return {"query": q, "results": clean}


# ── Fill ─────────────────────────────────────────────────────────────────────

class FillRequest(BaseModel):
    template_id: str
    brief: str          # e.g. "耳机双十一大促，优惠价299元，强调音质好"
    images: dict = {}   # optional: {"hero_image": "https://..."} pre-supplied images


@app.post("/fill")
async def fill_endpoint(req: FillRequest):
    """
    Given a template ID and a user brief, use AI to fill all content slots.
    Returns filled slot values ready for rendering.
    """
    # Find the template
    template = next((a for a in INDEX if a["id"] == req.template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{req.template_id}' not found")

    filled = await fill_slots(template, req.brief, req.images)
    return {
        "template_id": req.template_id,
        "brief": req.brief,
        "filled_slots": filled,
        "template": {k: v for k, v in template.items() if k != "embedding"},
    }


# ── Render ────────────────────────────────────────────────────────────────────

@app.get("/render/{template_id}", response_class=HTMLResponse)
def render_endpoint(
    template_id: str,
    title: str = Query("", description="Title text"),
    subtitle: str = Query("", description="Subtitle text"),
    cta: str = Query("", description="Call-to-action text"),
    tag: str = Query("", description="Tag/badge text"),
    image_url: str = Query("", description="Hero image URL"),
):
    """
    Render a template as an HTML page.
    Open in browser or screenshot with puppeteer/playwright.
    """
    template = next((a for a in INDEX if a["id"] == template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    slots = {
        "title": title,
        "subtitle": subtitle,
        "cta": cta,
        "tag": tag,
        "hero_image": image_url,
        "food_image": image_url,
        "product_image": image_url,
        "product_render": image_url,
    }

    html = render_html(template, slots)
    return HTMLResponse(content=html)


# ── Screenshot (real PNG image) ───────────────────────────────────────────────

@app.get("/screenshot/{template_id}")
async def screenshot_endpoint(
    template_id: str,
    title: str = Query("", description="Title text"),
    subtitle: str = Query("", description="Subtitle text"),
    cta: str = Query("", description="CTA button text"),
    tag: str = Query("", description="Tag text"),
    image_url: str = Query("", description="Hero image URL"),
):
    """
    Render template as a real PNG image.
    Returns image/png — can be sent directly in IM (飞书/Discord).
    """
    template = next((a for a in INDEX if a["id"] == template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    slots = {
        "title": title, "subtitle": subtitle, "cta": cta, "tag": tag,
        "hero_image": image_url, "food_image": image_url,
        "product_image": image_url, "product_render": image_url,
    }
    html = render_html(template, slots)

    # Get canvas dimensions if available (for poster-design templates)
    canvas = template.get("canvas", {})
    w = min(canvas.get("width", 600), 800)
    h = min(canvas.get("height", 600), 1200)
    # Normalize to max 600px wide for preview
    if w > 600:
        h = int(h * 600 / w)
        w = 600

    png_bytes = await html_to_png(html, width=w, height=h)
    return Response(content=png_bytes, media_type="image/png")


# ── Editor redirect ───────────────────────────────────────────────────────────

@app.get("/editor/{template_id}")
def editor_endpoint(template_id: str):
    """
    Redirect to poster-design editor with this template pre-loaded.
    Requires poster-design running locally on port 5173.
    """
    template = next((a for a in INDEX if a["id"] == template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    editor_info = template.get("editor", {})
    editor_url = editor_info.get("editor_url")

    if not editor_url:
        raise HTTPException(status_code=400, detail="This template has no editor integration")

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=editor_url)


# ── Compose (search + fill + render URL in one shot) ─────────────────────────

class ComposeRequest(BaseModel):
    brief: str
    platform: str = None
    images: dict = {}


def _extract_search_query(brief: str, platform: str = None) -> str:
    """
    Distill a user's brief into compact search keywords.
    Long sentences confuse n-gram search; short keywords work better.
    """
    from openai import OpenAI
    import os
    try:
        c = OpenAI(
            api_key=os.environ.get("VISUAL_RAG_API_KEY", "dummy-key"),
            base_url=os.environ.get("VISUAL_RAG_BASE_URL", "https://vibe.deepminer.ai/v1"),
        )
        platform_hint = f"目标平台：{platform}。" if platform else ""
        resp = c.chat.completions.create(
            model=os.environ.get("VISUAL_RAG_MODEL", "claude-sonnet-4-5-20250929"),
            max_tokens=60,
            messages=[{"role": "user", "content":
                f"从以下设计需求中提炼5-8个搜索关键词，用空格分隔，只输出关键词不要解释。\n"
                f"{platform_hint}需求：{brief}"
            }],
        )
        keywords = resp.choices[0].message.content.strip()
        return keywords
    except Exception:
        return brief  # fallback to original brief


@app.post("/compose")
async def compose_endpoint(req: ComposeRequest):
    """
    One-shot: give a brief, get back the best template + filled content + render URL.
    This is the main endpoint OpenClaw should call.
    """
    # Step 1: Extract search keywords from brief (better than raw brief for n-gram search)
    search_query = _extract_search_query(req.brief, req.platform)

    # Step 2: Search with top_k=3, pick best
    results = search(search_query, top_k=3, platform=req.platform)
    if not results:
        # fallback: search with original brief
        results = search(req.brief, top_k=3, platform=req.platform)
    if not results:
        raise HTTPException(status_code=404, detail="No matching template found")

    best = results[0]
    template_id = best["id"]

    # Step 2: Fill
    filled = await fill_slots(best, req.brief, req.images)

    # Step 3: Build render URL
    base = "http://localhost:8765"
    params = "&".join(
        f"{k}={v}" for k, v in filled.items()
        if isinstance(v, str) and v and k not in ("hero_image", "food_image", "product_image", "product_render")
    )
    image_url = filled.get("hero_image") or filled.get("food_image") or filled.get("product_image") or ""
    render_url = f"{base}/render/{template_id}?{params}&image_url={image_url}"

    # Build all three output URLs
    base = f"http://localhost:{os.environ.get('VISUAL_RAG_PORT', 8765)}"
    screenshot_url = render_url.replace(f"{base}/render/", f"{base}/screenshot/")
    editor_url = best.get("editor", {}).get("editor_url", "")

    # Slot positions for agent self-review (where will the text appear?)
    slot_positions = best.get("layout", {}).get("slot_positions", {})

    return {
        "template": {k: v for k, v in best.items()
                     if k not in ("embedding", "_score", "_match_method", "editor")},
        "score": round(best.get("_score", 0), 3),
        "search_query_used": search_query,
        "filled_slots": filled,
        "slot_positions": slot_positions,   # where each slot appears in the image
        "output": {
            "preview_url":    render_url,       # open in browser
            "image_url":      screenshot_url,   # real PNG, send in IM directly
            "editor_url":     editor_url,       # open in poster-design to edit manually
        },
        # Keep render_url for backwards compat with SKILL.md
        "render_url": render_url,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("VISUAL_RAG_PORT", 8765))
    print(f"\n visual-rag server starting on http://localhost:{port}")
    print(f" Docs: http://localhost:{port}/docs\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
