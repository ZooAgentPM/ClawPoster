"""
visual-rag renderer: converts a template + filled slots into an HTML page.

For poster-design templates: renders actual layer JSON (pixel-accurate).
For mock templates: uses CSS layout based on metadata.
"""

import json
from urllib.parse import unquote


def render_html(template: dict, slots: dict) -> str:
    """Render a template as a standalone HTML page."""
    # poster-design templates: use real layer data for accurate rendering
    if template.get("source") == "poster-design":
        raw = template.get("editor", {}).get("raw_data", "")
        if raw:
            return _render_poster_design_layers(template, slots, raw)

    # Mock / generic templates: CSS layout based on metadata
    return _render_generic(template, slots)


# ── Poster-Design Layer Renderer ──────────────────────────────────────────────

def _render_poster_design_layers(template: dict, slots: dict, raw_data_str: str) -> str:
    """Pixel-accurate render using poster-design layer JSON."""
    try:
        pages = json.loads(raw_data_str)
        page = pages[0]
    except Exception:
        return _render_generic(template, slots)

    global_data = page.get("global", {})
    layers = page.get("layers", [])

    canvas_w = float(global_data.get("width", 1242))
    canvas_h = float(global_data.get("height", 2208))
    bg_color = _strip_alpha(global_data.get("backgroundColor", "#ffffff"))
    bg_image = global_data.get("backgroundImage", "")

    # Scale to 600px wide
    scale = 600 / canvas_w
    display_h = int(canvas_h * scale)

    # Map layer_uuid → slot_name for text replacement
    content_slots = template.get("content_slots", {})
    uuid_to_slot = {
        info.get("layer_id"): name
        for name, info in content_slots.items()
        if info.get("layer_id")
    }
    image_slots = template.get("image_slots", {})
    uuid_to_img_slot = {
        info.get("layer_id"): name
        for name, info in image_slots.items()
        if info.get("layer_id")
    }

    font_urls = set()
    layers_html = []

    for layer in layers:
        ltype = layer.get("type", "")
        uuid = str(layer.get("uuid", ""))

        left   = float(layer.get("left", 0))
        top    = float(layer.get("top", 0))
        width  = float(str(layer.get("width", 0)).replace("px", "") or 0)
        height = float(str(layer.get("height", 0)).replace("px", "") or 0)
        opacity = float(layer.get("opacity", 1))

        sl, st, sw, sh = left * scale, top * scale, width * scale, height * scale

        if ltype == "w-text":
            fc = layer.get("fontClass", {})
            font_url = fc.get("url", "")
            if font_url:
                font_urls.add(font_url)
            font_family = fc.get("alias") or "PingFang SC"
            font_size   = float(layer.get("fontSize", 14)) * scale
            color       = _strip_alpha(layer.get("color", "#000000"))
            text_align  = layer.get("textAlign", "left")
            font_weight = layer.get("fontWeight", 400)
            font_style  = layer.get("fontStyle", "normal")
            # letterSpacing in palxp is stored as em/100 ratio, matching original: fontSize*letterSpacing/100
            raw_ls = float(layer.get("letterSpacing", 0))
            letter_sp = font_size * raw_ls / 100 if raw_ls != 0 else 0
            line_h    = float(layer.get("lineHeight", 1.2))
            # lineHeight in px matching original: fontSize * lineHeight
            line_h_px = font_size * line_h

            # Use filled slot value if available, else show original template text
            slot_name = uuid_to_slot.get(uuid)
            if slot_name and slots.get(slot_name):
                text = slots[slot_name].replace("\n", "<br>")
            else:
                raw_text = layer.get("text", "")
                text = unquote(raw_text) if "%" in raw_text else raw_text
                import re as _re
                text = _re.sub(r'<[^>]+>', '', text).strip()

            # Shared text CSS (font properties, no color — color set per effect layer)
            base_font_css = (
                f"font-family:'{font_family}','PingFang SC',sans-serif;"
                f"font-size:{font_size:.2f}px;"
                f"font-weight:{font_weight};"
                f"font-style:{font_style};"
                f"text-align:{text_align};"
                f"letter-spacing:{letter_sp:.2f}px;"
                f"line-height:{line_h_px:.2f}px;"
                f"word-break:break-word;white-space:pre-wrap;"
            )

            def _effect_css(eff):
                """Build CSS string for one textEffect entry."""
                css = ""
                fill = eff.get("filling", {})
                if fill.get("enable"):
                    ftype = int(fill.get("type", 0))
                    if ftype == 0:
                        css += f"color:{_strip_alpha(fill.get('color','#000000'))};"
                    elif ftype == 2:  # gradient
                        grad = fill.get("gradient", {})
                        stops = grad.get("stops", [])
                        stops_css = ",".join(f"{s['color']} {float(s['offset'])*100:.0f}%" for s in stops)
                        css += f"color:transparent;background-image:linear-gradient({grad.get('angle',90)}deg,{stops_css});-webkit-background-clip:text;background-clip:text;"
                    else:
                        css += f"color:{_strip_alpha(fill.get('color','#000000'))};"
                else:
                    css += "color:transparent;"

                stroke = eff.get("stroke", {})
                if stroke.get("enable"):
                    sw_px = float(stroke.get("width", 0)) * scale
                    sc = _strip_alpha(stroke.get("color", "#000000"))
                    css += f"-webkit-text-stroke:{sw_px:.2f}px {sc};"

                shadow = eff.get("shadow", {})
                if shadow.get("enable"):
                    sx = float(shadow.get("offsetX", 0)) * scale
                    sy = float(shadow.get("offsetY", 0)) * scale
                    sb = float(shadow.get("blur", 0)) * scale
                    sc2 = _strip_alpha(shadow.get("color", "#000000"))
                    css += f"text-shadow:{sx:.1f}px {sy:.1f}px {sb:.1f}px {sc2};"

                offset = eff.get("offset", {})
                if offset.get("enable"):
                    ox = float(offset.get("x", 0)) * scale
                    oy = float(offset.get("y", 0)) * scale
                    css += f"transform:translate({ox:.2f}px,{oy:.2f}px);"

                return css

            text_effects = layer.get("textEffects", [])

            # Outer container: positioned on canvas, acts as clipping/reference box
            container_open = (
                f'<div style="position:absolute;left:{sl:.2f}px;top:{st:.2f}px;'
                f'width:{sw:.2f}px;height:{sh:.2f}px;'
                f'opacity:{opacity};overflow:visible;pointer-events:none;">'
            )

            if text_effects:
                # Each effect is an absolutely-stacked layer inside the container
                # matching the original Vue component's .effect-text approach
                inner = ""
                for eff in text_effects:
                    ecss = _effect_css(eff)
                    inner += (
                        f'<div style="position:absolute;top:0;left:0;width:100%;height:100%;'
                        f'{base_font_css}{ecss}">{text}</div>'
                    )
                layers_html.append(f'{container_open}{inner}</div>')
            else:
                layers_html.append(
                    f'{container_open}'
                    f'<div style="position:absolute;top:0;left:0;width:100%;height:100%;'
                    f'{base_font_css}color:{color};">{text}</div>'
                    f'</div>'
                )

        elif ltype == "w-image":
            img_url = layer.get("imgUrl", "")
            # Slot override
            slot_name = uuid_to_img_slot.get(uuid)
            if slot_name and slots.get(slot_name):
                img_url = slots[slot_name]
            # Convert local paths to file:// URLs
            if img_url and img_url.startswith("/") and not img_url.startswith("file://"):
                img_url = f"file://{img_url}"
            # Skip local 127.0.0.1 placeholders
            if img_url and "127.0.0.1" not in img_url:
                layers_html.append(
                    f'<img src="{img_url}" style="position:absolute;left:{sl:.1f}px;top:{st:.1f}px;'
                    f'width:{sw:.1f}px;height:{sh:.1f}px;object-fit:cover;opacity:{opacity};" />'
                )
            else:
                layers_html.append(
                    f'<div style="position:absolute;left:{sl:.1f}px;top:{st:.1f}px;'
                    f'width:{sw:.1f}px;height:{sh:.1f}px;background:#e8e8e8;opacity:{opacity};'
                    f'display:flex;align-items:center;justify-content:center;'
                    f'font-size:{min(sw,sh)*0.25:.0f}px;">🖼</div>'
                )

        elif ltype == "w-svg":
            svg_colors = layer.get("colors", [])
            svg_path   = layer.get("_svg_path", "")
            svg_url    = layer.get("imgUrl", "")
            if svg_url and svg_url.startswith("/") and not svg_url.startswith("file://"):
                svg_url = f"file://{svg_url}"

            inlined = False
            if svg_path:
                try:
                    from pathlib import Path as _Path
                    import re as _re2
                    import uuid as _uuid
                    raw_svg = _Path(svg_path).read_text(encoding="utf-8", errors="replace")
                    # Substitute {{colors[N]}} with actual hex colors
                    def _repl_color(m):
                        idx = int(m.group(1))
                        c = svg_colors[idx] if idx < len(svg_colors) else "#cccccc"
                        return _strip_alpha(c)
                    raw_svg = _re2.sub(r'\{\{colors\[(\d+)\]\}\}', _repl_color, raw_svg)
                    # Namespace all id= and href/xlink:href="#..." to avoid collisions
                    ns = _uuid.uuid4().hex[:8]
                    raw_svg = _re2.sub(r'\bid="([^"]+)"', lambda m: f'id="{ns}_{m.group(1)}"', raw_svg)
                    raw_svg = _re2.sub(r'href="#([^"]+)"', lambda m: f'href="#{ns}_{m.group(1)}"', raw_svg)
                    raw_svg = _re2.sub(r'xlink:href="#([^"]+)"', lambda m: f'xlink:href="#{ns}_{m.group(1)}"', raw_svg)
                    # Find <svg tag and inject sized wrapper
                    svg_start = raw_svg.find("<svg")
                    if svg_start >= 0:
                        svg_tag = raw_svg[svg_start:]
                        # Override width/height to fill container
                        svg_tag = _re2.sub(r'\bwidth="[^"]*"', 'width="100%"', svg_tag)
                        svg_tag = _re2.sub(r'\bheight="[^"]*"', 'height="100%"', svg_tag)
                        layers_html.append(
                            f'<div style="position:absolute;left:{sl:.2f}px;top:{st:.2f}px;'
                            f'width:{sw:.2f}px;height:{sh:.2f}px;opacity:{opacity};overflow:hidden;">'
                            f'{svg_tag}</div>'
                        )
                        inlined = True
                except Exception:
                    pass

            if not inlined and svg_url and "127.0.0.1" not in svg_url:
                layers_html.append(
                    f'<img src="{svg_url}" style="position:absolute;left:{sl:.2f}px;top:{st:.2f}px;'
                    f'width:{sw:.2f}px;height:{sh:.2f}px;object-fit:contain;opacity:{opacity};" />'
                )

        elif ltype == "w-qrcode":
            layers_html.append(
                f'<div style="position:absolute;left:{sl:.1f}px;top:{st:.1f}px;'
                f'width:{sw:.1f}px;height:{sh:.1f}px;background:#fff;'
                f'border:1px solid #ddd;display:flex;align-items:center;justify-content:center;'
                f'opacity:{opacity};font-size:{min(sw,sh)*0.25:.0f}px;">◼◻◼</div>'
            )

    def _font_css_url(u: str) -> str:
        # Local absolute paths → file:// so Playwright can load them
        if u.startswith("/"):
            return f"file://{u}"
        return u
    font_imports = "\n    ".join(f"@import url('{_font_css_url(u)}');" for u in font_urls)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <style>
    {font_imports}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: 600px;
      height: {display_h}px;
      overflow: hidden;
      background: {bg_color}{f' url("{bg_image}") center/cover no-repeat' if bg_image else ''};
      position: relative;
    }}
  </style>
</head>
<body>
{"".join(layers_html)}
</body>
</html>"""


# ── Generic CSS Renderer (mock templates) ────────────────────────────────────

def _render_generic(template: dict, slots: dict) -> str:
    style = template.get("style", {})
    layout = template.get("layout", {})

    palette   = style.get("color_palette", ["#FFFFFF", "#1A1A1A", "#666666"])
    bg_color  = palette[0] if palette else "#FFFFFF"
    txt_color = palette[1] if len(palette) > 1 else "#1A1A1A"
    acc_color = palette[2] if len(palette) > 2 else "#FF4D4D"

    mood        = style.get("mood", [])
    layout_type = layout.get("type", "上图下文")
    use_cases   = ", ".join(template.get("use_cases", [])[:2])

    title    = slots.get("title") or slots.get("project_name") or slots.get("job_title") or slots.get("course_title") or slots.get("show_name") or ""
    subtitle = slots.get("subtitle") or slots.get("tagline") or slots.get("sub_text") or slots.get("greeting") or ""
    cta      = slots.get("cta", "")
    tag      = slots.get("tag", "")
    image    = slots.get("hero_image") or slots.get("food_image") or slots.get("product_image") or slots.get("product_render") or ""

    font_family      = _pick_font(style.get("typography", ""))
    font_weight_title = "900" if "粗" in style.get("typography", "") else "700"

    body_html = _build_layout(layout_type, title, subtitle, cta, tag, image,
                               bg_color, txt_color, acc_color, font_family,
                               font_weight_title, mood)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <title>{title or template.get('id', 'design')}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      width: 600px; height: 600px; overflow: hidden;
      font-family: {font_family};
      background: {bg_color}; color: {txt_color};
      position: relative;
    }}
    .tag {{ display:inline-block;background:{acc_color};color:#fff;font-size:13px;
            font-weight:700;padding:4px 12px;border-radius:3px;letter-spacing:1px; }}
    .cta {{ display:inline-block;background:{acc_color};color:#fff;font-size:15px;
            font-weight:700;padding:10px 28px;border-radius:4px;letter-spacing:1px; }}
    .meta {{ position:absolute;bottom:10px;right:14px;font-size:10px;opacity:0.3; }}
  </style>
</head>
<body>
{body_html}
<div class="meta">{use_cases} · visual-rag</div>
</body>
</html>"""


def _build_layout(layout_type, title, subtitle, cta, tag, image,
                  bg, txt, acc, font, weight, mood):
    is_dark = _is_dark(bg)
    overlay_txt = "#FFFFFF" if is_dark else txt

    if layout_type in ("上图下文",):
        return f"""
<div style="display:flex;flex-direction:column;height:600px;">
  <div style="flex:0 0 65%;background:#f0ede8;overflow:hidden;position:relative;">
    {_img_or_placeholder(image,"100%","100%",acc,mood)}
    {f'<div style="position:absolute;top:16px;left:16px;"><span class="tag">{tag}</span></div>' if tag else ""}
  </div>
  <div style="flex:1;display:flex;flex-direction:column;justify-content:center;padding:24px 32px;gap:10px;">
    <div style="font-size:28px;font-weight:{weight};line-height:1.2;">{title}</div>
    {f'<div style="font-size:16px;opacity:0.65;">{subtitle}</div>' if subtitle else ""}
    {f'<div style="margin-top:8px;"><span class="cta">{cta}</span></div>' if cta else ""}
  </div>
</div>"""

    elif layout_type in ("左右分割",):
        return f"""
<div style="display:flex;height:600px;">
  <div style="flex:0 0 50%;background:#f0ede8;overflow:hidden;">
    {_img_or_placeholder(image,"100%","100%",acc,mood)}
  </div>
  <div style="flex:1;display:flex;flex-direction:column;justify-content:center;padding:32px 28px;gap:16px;">
    {f'<span class="tag">{tag}</span>' if tag else ""}
    <div style="font-size:26px;font-weight:{weight};line-height:1.25;">{title}</div>
    {f'<div style="font-size:15px;opacity:0.7;">{subtitle}</div>' if subtitle else ""}
    {f'<div style="margin-top:4px;"><span class="cta">{cta}</span></div>' if cta else ""}
  </div>
</div>"""

    elif layout_type in ("全图叠文字", "深色全图", "全图大字"):
        return f"""
<div style="position:relative;width:600px;height:600px;overflow:hidden;">
  {_img_or_placeholder(image,"600px","600px",acc,mood)}
  <div style="position:absolute;inset:0;background:rgba(0,0,0,{'0.45' if _is_dark(bg) else '0.25'});"></div>
  {f'<div style="position:absolute;top:20px;left:20px;"><span class="tag">{tag}</span></div>' if tag else ""}
  <div style="position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:40px;gap:14px;color:{overlay_txt};">
    <div style="font-size:36px;font-weight:{weight};line-height:1.2;text-shadow:0 2px 8px rgba(0,0,0,0.4);">{title}</div>
    {f'<div style="font-size:17px;opacity:0.85;">{subtitle}</div>' if subtitle else ""}
    {f'<div style="margin-top:8px;"><span class="cta">{cta}</span></div>' if cta else ""}
  </div>
</div>"""

    elif layout_type in ("居中对称",):
        return f"""
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:600px;padding:40px;text-align:center;gap:20px;">
  <div style="font-size:72px;line-height:1;">🎊</div>
  <div style="font-size:40px;font-weight:{weight};color:{acc};letter-spacing:4px;">{title}</div>
  {f'<div style="font-size:16px;opacity:0.7;max-width:360px;">{subtitle}</div>' if subtitle else ""}
  {f'<div style="margin-top:10px;font-size:14px;opacity:0.5;">{cta}</div>' if cta else ""}
</div>"""

    elif layout_type in ("信息图表型", "三段式"):
        items = [x.strip() for x in (subtitle or "").split("、") if x.strip()] or [subtitle or ""]
        items_html = "".join(
            f'<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid rgba(0,0,0,0.08);">'
            f'<span style="color:{acc};font-weight:700;font-size:18px;">✓</span>'
            f'<span style="font-size:15px;line-height:1.4;">{item}</span></div>'
            for item in items
        )
        return f"""
<div style="display:flex;flex-direction:column;height:600px;padding:40px 44px;gap:20px;">
  <div style="font-size:26px;font-weight:{weight};line-height:1.25;">{title}</div>
  <div style="flex:1;overflow:hidden;">{items_html}</div>
  {f'<div><span class="cta">{cta}</span></div>' if cta else ""}
</div>"""

    elif layout_type in ("正方形居中",):
        return f"""
<div style="position:relative;width:600px;height:600px;overflow:hidden;">
  {_img_or_placeholder(image,"600px","600px",acc,mood)}
  <div style="position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,0.7) 0%,transparent 60%);"></div>
  <div style="position:absolute;bottom:0;left:0;right:0;padding:28px 32px;">
    <div style="font-size:24px;font-weight:{weight};color:#fff;line-height:1.3;">{title}</div>
    {f'<div style="font-size:14px;color:rgba(255,255,255,0.75);margin-top:6px;">{subtitle}</div>' if subtitle else ""}
  </div>
</div>"""

    else:
        return f"""
<div style="display:flex;flex-direction:column;justify-content:center;align-items:center;height:600px;padding:48px;text-align:center;gap:20px;">
  {f'<div style="height:200px;width:100%;margin-bottom:8px;overflow:hidden;border-radius:8px;">{_img_or_placeholder(image,"100%","200px",acc,mood)}</div>' if image else ""}
  {f'<span class="tag">{tag}</span>' if tag else ""}
  <div style="font-size:32px;font-weight:{weight};line-height:1.2;">{title}</div>
  {f'<div style="font-size:16px;opacity:0.65;max-width:400px;">{subtitle}</div>' if subtitle else ""}
  {f'<span class="cta">{cta}</span>' if cta else ""}
</div>"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_alpha(color: str) -> str:
    """Remove alpha from 8-char hex color (#rrggbbaa → #rrggbb)."""
    if color and len(color) == 9 and color.startswith("#"):
        return color[:7]
    return color or "#000000"


def _img_or_placeholder(url, w, h, acc, mood):
    if url:
        return f'<img src="{url}" style="width:{w};height:{h};object-fit:cover;" />'
    gradient = _mood_gradient(mood, acc)
    return f'<div style="width:{w};height:{h};background:{gradient};display:flex;align-items:center;justify-content:center;"><span style="font-size:40px;opacity:0.3;">🖼</span></div>'


def _mood_gradient(mood, acc):
    mood_str = "".join(mood)
    if any(x in mood_str for x in ["科技", "未来", "酷炫"]):
        return "linear-gradient(135deg,#0a0a1a 0%,#1a0535 50%,#0a1a2a 100%)"
    if any(x in mood_str for x in ["喜庆", "热烈", "促销"]):
        return "linear-gradient(135deg,#8B0000 0%,#CC0000 50%,#FF4400 100%)"
    if any(x in mood_str for x in ["奢华", "高端", "大气"]):
        return "linear-gradient(135deg,#1A1208 0%,#3D2B0A 50%,#1A1208 100%)"
    if any(x in mood_str for x in ["奶油", "温柔", "高级"]):
        return "linear-gradient(135deg,#F5F0EB 0%,#E8DDD4 100%)"
    if any(x in mood_str for x in ["欢快", "庆祝", "温馨"]):
        return "linear-gradient(135deg,#fff0f3 0%,#ffe4e8 100%)"
    return "linear-gradient(135deg,#f5f5f5 0%,#e0e0e0 100%)"


def _pick_font(typography: str) -> str:
    t = typography.lower()
    if any(x in t for x in ["衬线", "serif"]):
        return "'Georgia','Noto Serif SC',serif"
    if any(x in t for x in ["毛笔", "书法"]):
        return "'KaiTi','STKaiti',serif"
    return "'PingFang SC','Helvetica Neue','Microsoft YaHei',sans-serif"


def _is_dark(hex_color: str) -> bool:
    h = hex_color.lstrip("#")
    if len(h) < 6:
        return False
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.4
