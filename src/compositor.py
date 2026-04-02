"""
visual-rag compositor: compose a background image + asset layers → HTML → PNG.

Layer types:
  - text_effect:     花字/艺术字，叠加在底图上（用 render.font_url + render.effects）
  - text_block:      文字组合块，多行排版（用 render.layers 定义每行）
  - text:            自定义文字，直接指定 font_size/color/text
  - image:           图片素材，绝对定位

Position zones (best_position field):
  top-left | top-center | top-right
  upper-middle-left | upper-middle-center | upper-middle-right
  lower-middle-left | lower-middle-center | lower-middle-right
  bottom-left | bottom-center | bottom-right
"""

import base64
import json
import mimetypes
import os
from pathlib import Path
from openai import OpenAI

from config import BASE_URL, API_KEY, MODEL

ASSET_INDEX_PATH = Path(__file__).parent.parent / "data" / "asset_index.json"


def _to_data_url(path_or_url: str, max_bytes: int = 4_000_000) -> str:
    """
    Convert a local file path to a base64 data URL.
    Resizes/compresses the image if it exceeds max_bytes (default 4MB).
    HTTP URLs are returned as-is.
    """
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    p = Path(path_or_url).expanduser()
    if not p.exists():
        return path_or_url

    raw = p.read_bytes()
    if len(raw) <= max_bytes:
        mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    # Image too large — resize with Pillow
    try:
        from PIL import Image
        import io
        with Image.open(p) as img:
            img = img.convert("RGB")
            # Scale down until under max_bytes
            scale = (max_bytes / len(raw)) ** 0.5
            new_w = max(64, int(img.width * scale))
            new_h = max(64, int(img.height * scale))
            img = img.resize((new_w, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            data = buf.getvalue()
            # Further reduce quality if still too big
            q = 75
            while len(data) > max_bytes and q >= 30:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=q)
                data = buf.getvalue()
                q -= 10
        return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
    except Exception as e:
        print(f"[compositor] image resize failed: {e}")
        return path_or_url

_client = None
def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


# ── Zone → CSS position ───────────────────────────────────────────────────────

ZONE_CSS = {
    "top-left":               {"top": "5%",  "left": "5%",  "transform": "none"},
    "top-center":             {"top": "5%",  "left": "50%", "transform": "translateX(-50%)"},
    "top-right":              {"top": "5%",  "right": "5%", "transform": "none"},
    "upper-middle-left":      {"top": "25%", "left": "5%",  "transform": "none"},
    "upper-middle-center":    {"top": "25%", "left": "50%", "transform": "translateX(-50%)"},
    "upper-middle-right":     {"top": "25%", "right": "5%", "transform": "none"},
    "center":                 {"top": "50%", "left": "50%", "transform": "translate(-50%,-50%)"},
    "lower-middle-left":      {"top": "62%", "left": "5%",  "transform": "none"},
    "lower-middle-center":    {"top": "62%", "left": "50%", "transform": "translateX(-50%)"},
    "lower-middle-right":     {"top": "62%", "right": "5%", "transform": "none"},
    "bottom-left":            {"bottom": "5%", "left": "5%",   "transform": "none"},
    "bottom-center":          {"bottom": "5%", "left": "50%",  "transform": "translateX(-50%)"},
    "bottom-right":           {"bottom": "5%", "right": "5%",  "transform": "none"},
}

def _zone_to_css(zone: str) -> str:
    props = ZONE_CSS.get(zone, ZONE_CSS["upper-middle-center"])
    parts = []
    for k, v in props.items():
        parts.append(f"{k.replace('_','-')}:{v}")
    return ";".join(parts)


# ── Asset loader ──────────────────────────────────────────────────────────────

def load_asset(asset_id: str) -> dict | None:
    if ASSET_INDEX_PATH.exists():
        with open(ASSET_INDEX_PATH, encoding="utf-8") as f:
            assets = json.load(f)
        return next((a for a in assets if a["id"] == asset_id), None)
    return None


# ── Layer HTML builders ───────────────────────────────────────────────────────

def _build_text_effect_layer(layer: dict, asset: dict) -> tuple[str, set]:
    """花字/艺术字叠加层，返回 (html, font_urls)."""
    render = asset.get("render", {})
    text = layer.get("text", "标题")
    zone = layer.get("position", asset.get("usage", {}).get("best_position", "upper-middle-center"))
    font_size_vw = render.get("default_font_size_vw", 12)
    font_url = render.get("font_url", "")
    font_family = render.get("font_family", "PingFang SC")
    color = render.get("color", "#ffffff")
    letter_sp = render.get("letter_spacing", 2)
    line_h = render.get("line_height", 1.2)

    # Build text-shadow / glow from effects list
    shadow_parts = []
    for effect in render.get("effects", []):
        parts = effect.split(":")
        etype = parts[0]
        if etype == "glow" and len(parts) >= 3:
            shadow_parts.append(f"0 0 {parts[2]} {parts[1]}")
        elif etype == "shadow" and len(parts) >= 3:
            shadow_parts.append(f"2px 2px {parts[2]} {parts[1]}")
    text_shadow = f"text-shadow:{','.join(shadow_parts)};" if shadow_parts else ""

    css_pos = _zone_to_css(zone)
    font_urls = {font_url} if font_url else set()

    html = (
        f'<div style="position:absolute;{css_pos};'
        f'font-family:\'{font_family}\',sans-serif;'
        f'font-size:{font_size_vw}vw;color:{color};'
        f'letter-spacing:{letter_sp}px;line-height:{line_h};'
        f'text-align:center;white-space:nowrap;'
        f'{text_shadow}z-index:10;">'
        f'{text}</div>'
    )
    return html, font_urls


def _build_text_block_layer(layer: dict, asset: dict) -> tuple[str, set]:
    """文字组合块，多行排版."""
    render = asset.get("render", {})
    zone = layer.get("position", asset.get("usage", {}).get("best_position", "bottom-center"))
    fields = layer.get("fields", {})   # {title, subtitle, tag, cta}
    bg = render.get("bg", "transparent")
    padding = render.get("padding", "4vw")
    gap = render.get("gap", "1vw")
    layout = render.get("layout", "vertical")

    rows_html = []
    for row in render.get("layers", []):
        field = row.get("field", "title")
        text = fields.get(field, layer.get("text", ""))
        if not text:
            continue
        fs = row.get("font_size_vw", 5)
        color = row.get("color", "#111111")
        fw = row.get("font_weight", 400)
        row_bg = row.get("bg", "")
        role = row.get("role", "text")

        if row_bg:
            rows_html.append(
                f'<div style="font-size:{fs}vw;color:{color};font-weight:{fw};'
                f'background:{row_bg};padding:0.5vw 2vw;border-radius:2px;'
                f'display:inline-block;margin-top:{gap};">{text}</div>'
            )
        else:
            rows_html.append(
                f'<div style="font-size:{fs}vw;color:{color};font-weight:{fw};'
                f'margin-top:{gap};">{text}</div>'
            )

    direction = "row" if layout == "horizontal" else "column"
    css_pos = _zone_to_css(zone)
    html = (
        f'<div style="position:absolute;{css_pos};'
        f'background:{bg};padding:{padding};'
        f'display:flex;flex-direction:{direction};'
        f'align-items:flex-start;gap:{gap};'
        f'border-radius:4px;z-index:10;max-width:90%;">'
        f'{"".join(rows_html)}</div>'
    )
    return html, set()


def _build_custom_text_layer(layer: dict) -> tuple[str, set]:
    """自定义文字层，不依赖 asset."""
    text = layer.get("text", "")
    zone = layer.get("position", "bottom-center")
    font_size = layer.get("font_size_vw", 5)
    color = layer.get("color", "#ffffff")
    fw = layer.get("font_weight", 700)
    bg = layer.get("bg", "")
    opacity = layer.get("opacity", 1.0)
    text_shadow = "text-shadow:0 2px 8px rgba(0,0,0,0.6);" if layer.get("shadow") else ""

    css_pos = _zone_to_css(zone)
    bg_css = f"background:{bg};padding:1vw 2vw;border-radius:3px;" if bg else ""
    html = (
        f'<div style="position:absolute;{css_pos};'
        f'font-size:{font_size}vw;color:{color};font-weight:{fw};'
        f'text-align:center;{bg_css}{text_shadow}opacity:{opacity};z-index:10;">'
        f'{text}</div>'
    )
    return html, set()


# ── Main compose ──────────────────────────────────────────────────────────────

def compose_html(background_url: str, layers: list[dict],
                 canvas_width: int = 600, canvas_height: int = 800) -> str:
    background_url = _to_data_url(background_url)
    """
    Compose a background image + layers into standalone HTML.

    Each layer dict:
      type: "text_effect" | "text_block" | "text" | "image"
      asset_id: str (for text_effect / text_block)
      text: str (for text_effect / text)
      fields: dict (for text_block: {title, subtitle, tag, cta})
      position: zone string, e.g. "upper-middle-center"
      ... extra style overrides
    """
    font_urls = set()
    layers_html = []

    # Background
    if background_url:
        bg_html = (
            f'<img src="{background_url}" '
            f'style="position:absolute;inset:0;width:100%;height:100%;'
            f'object-fit:cover;z-index:0;" />'
        )
    else:
        bg_html = '<div style="position:absolute;inset:0;background:#1a1a2e;z-index:0;"></div>'

    for layer in layers:
        ltype = layer.get("type", "text")
        asset_id = layer.get("asset_id")

        if ltype == "text_effect" and asset_id:
            asset = load_asset(asset_id)
            if asset:
                h, fu = _build_text_effect_layer(layer, asset)
                layers_html.append(h)
                font_urls.update(fu)

        elif ltype == "text_block" and asset_id:
            asset = load_asset(asset_id)
            if asset:
                h, fu = _build_text_block_layer(layer, asset)
                layers_html.append(h)
                font_urls.update(fu)

        elif ltype == "text":
            h, fu = _build_custom_text_layer(layer)
            layers_html.append(h)

        elif ltype == "image":
            img_url = layer.get("url", "")
            zone = layer.get("position", "center")
            w = layer.get("width", "40%")
            h_size = layer.get("height", "40%")
            css_pos = _zone_to_css(zone)
            if img_url:
                layers_html.append(
                    f'<img src="{img_url}" '
                    f'style="position:absolute;{css_pos};'
                    f'width:{w};height:{h_size};object-fit:contain;z-index:5;" />'
                )

    font_imports = "\n    ".join(f"@import url('{u}');" for u in font_urls if u)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <style>
    {font_imports}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: {canvas_width}px;
      height: {canvas_height}px;
      overflow: hidden;
      position: relative;
      background: #000;
    }}
  </style>
</head>
<body>
{bg_html}
{"".join(layers_html)}
</body>
</html>"""


# ── Background analyzer ───────────────────────────────────────────────────────

async def analyze_background(image_url: str) -> dict:
    """
    Use Claude Vision to analyze a background image.
    Returns structured metadata for asset matching.
    Accepts both HTTP URLs and local file paths.
    """
    client = _get_client()
    image_url = _to_data_url(image_url)
    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    },
                    {
                        "type": "text",
                        "text": (
                            "分析这张图片的视觉特征，以JSON格式返回，只返回JSON不要解释：\n"
                            "{\n"
                            '  "dominant_colors": ["#颜色1", "#颜色2"],\n'
                            '  "is_dark": true/false,\n'
                            '  "mood": ["风格词1", "风格词2"],\n'
                            '  "busy_zones": ["bottom", "left"],\n'
                            '  "clear_zones": ["upper-middle-center", "top-center"],\n'
                            '  "suitable_text_colors": ["#ffffff"],\n'
                            '  "compatible_asset_moods": ["科技感", "酷炫"],\n'
                            '  "avoid_asset_moods": ["喜庆", "可爱"],\n'
                            '  "description": "一句话描述这张图的视觉感受"\n'
                            "}"
                        )
                    }
                ]
            }]
        )
        text = response.choices[0].message.content.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        print(f"[compositor] analyze_background error: {e}")
        return {
            "dominant_colors": ["#000000"],
            "is_dark": True,
            "mood": ["未知"],
            "busy_zones": [],
            "clear_zones": ["upper-middle-center", "bottom-center"],
            "suitable_text_colors": ["#ffffff"],
            "compatible_asset_moods": [],
            "avoid_asset_moods": [],
            "description": "无法分析，使用默认参数"
        }
