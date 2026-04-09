"""
虾稿设计 · 单模板渲染接口

输入：模板 ID + 槽位内容（uuid → text 映射）+ 可选元素样式调整
输出：render PNG 路径 + inspect 标注图路径

Usage:
  cd /Users/mlamp/visual-rag
  .venv/bin/python src/render_single.py \\
    --id 708 \\
    --slots '{"020de73ca8d9":"副业没有收入？","da615a5c7df6":"这3个方法\\n帮你重新\\n找到节奏！"}'

  # 带元素位置调整（从 inspect 图找到 UUID 后使用）：
  .venv/bin/python src/render_single.py \\
    --id 704 \\
    --slots '{"2462d596a434":"租房踩坑？\\n先看这条！"}' \\
    --adjustments '[{"id":"3eeb6f74e1ee","style":{"transform":"translateX(60px)"}}]'

stdout 输出两行：
  RENDER:/absolute/path/t708_render.png
  INSPECT:/absolute/path/t708_inspect.png
"""

import argparse
import json
import mimetypes
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

BASE_DIR   = Path(__file__).parent.parent
RAW_DIR    = BASE_DIR / "data" / "palxp-raw"
ASSETS_DIR = BASE_DIR / "data" / "assets"
OUT_DIR    = BASE_DIR / "data" / "renders"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# inspect 标注图颜色循环（半透明填充 + 实线边框）
_COLORS = [
    "#FF5733", "#33C1FF", "#28B463", "#F39C12",
    "#9B59B6", "#E74C3C", "#1ABC9C", "#2E86C1",
    "#D35400", "#7D3C98",
]


def _build_inspect_image(render_path: Path, elements: list[dict]) -> Path:
    """在渲染图上叠加元素边框和 UUID 标签，生成 inspect 标注图。"""
    img = Image.open(render_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 尝试加载系统字体，失败则用内置默认字体
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        font = ImageFont.load_default()
        font_small = font

    for i, el in enumerate(elements):
        color_hex = _COLORS[i % len(_COLORS)]
        r, g, b = int(color_hex[1:3], 16), int(color_hex[3:5], 16), int(color_hex[5:7], 16)
        x, y, w, h = el["x"], el["y"], el["w"], el["h"]

        # 半透明填充
        draw.rectangle([x, y, x + w, y + h], fill=(r, g, b, 40))
        # 实线边框（2px）
        for offset in range(2):
            draw.rectangle(
                [x + offset, y + offset, x + w - offset, y + h - offset],
                outline=(r, g, b, 220),
            )

        # UUID 标签（白底，深色文字）
        label = el["id"][:8]
        bbox = draw.textbbox((0, 0), label, font=font_small)
        lw, lh = bbox[2] - bbox[0] + 6, bbox[3] - bbox[1] + 4
        lx, ly = x + 2, y + 2
        draw.rectangle([lx, ly, lx + lw, ly + lh], fill=(255, 255, 255, 220))
        draw.text((lx + 3, ly + 2), label, fill=(r, g, b, 255), font=font_small)

    composite = Image.alpha_composite(img, overlay).convert("RGB")
    inspect_path = render_path.parent / render_path.name.replace("_render.png", "_inspect.png")
    composite.save(str(inspect_path))
    return inspect_path


def render_single(
    template_id: int,
    slots: dict[str, str],
    adjustments: list[dict] | None = None,
) -> dict[str, str]:
    """
    渲染指定模板，注入文本槽位，可选元素样式调整，截图后生成 inspect 标注图。

    返回 dict：
      {"render": "/path/t708_render.png", "inspect": "/path/t708_inspect.png"}
    """
    layer_file = RAW_DIR / f"t{template_id}_layers.json"
    if not layer_file.exists():
        raise FileNotFoundError(f"模板数据不存在: {layer_file}")

    d = json.loads(layer_file.read_text(encoding="utf-8"))
    page_data = d.get("dActiveElement", {})
    canvas_h  = int(page_data.get("height", 1656))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1300, "height": max(canvas_h + 200, 2400)}
        )

        # 本地素材拦截
        def handle_route(route):
            url = route.request.url
            if "design.palxp.cn/static" in url:
                fname = url.split("/")[-1].split("?")[0]
                for sub in ["images", "svgs", "covers", "fonts"]:
                    p = ASSETS_DIR / sub / fname
                    if p.exists():
                        mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                        route.fulfill(status=200,
                                      headers={"Content-Type": mime,
                                               "Access-Control-Allow-Origin": "*"},
                                      body=p.read_bytes())
                        return
            route.continue_()

        page.route("**/*", handle_route)

        # 导航（依赖本地 mock_api_server:7001 + vite:5173）
        page.goto(
            f"http://127.0.0.1:5173/html?tempid={template_id}",
            wait_until="networkidle",
            timeout=30000,
        )

        # 等待字体与布局稳定
        try:
            page.evaluate("async () => { await document.fonts.ready }", timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(800)

        # 关闭水印
        page.evaluate("""() => {
            const pinia = document.getElementById('app')
                ?.__vue_app__?.config?.globalProperties?.$pinia;
            if (pinia?.state?.value?.base)
                pinia.state.value.base.watermark = [];
        }""")

        # 注入槽位文本
        # 保留 \n 原样传入 JS，让 pre-wrap 用 \n 分行（而非 <br>）。
        # edit-text 有 text-align:justify + white-space:pre-wrap，用 \n 分行时
        # 每段都是段落末行，justify 不生效，字距正常。
        # 额外设置 text-align-last:left 抑制 Chromium 对显式换行前一行的 justify。
        if slots:
            slots_js = json.dumps(slots, ensure_ascii=False)
            result = page.evaluate(f"""() => {{
                const slots = {slots_js};
                const report = {{}};
                for (const [uuid, text] of Object.entries(slots)) {{
                    const el = document.getElementById(uuid);
                    if (!el) {{
                        report[uuid] = 'NOT_FOUND';
                        continue;
                    }}
                    const targets = el.querySelectorAll('.edit-text');
                    targets.forEach(div => {{
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
                        div.style.textAlignLast = 'left';
                    }});
                    report[uuid] = targets.length > 0 ? 'OK' : 'NO_EDIT_TEXT';
                }}
                return report;
            }}""")
            page.wait_for_timeout(200)

            failed = {uuid: status for uuid, status in result.items() if status != "OK"}
            if failed:
                browser.close()
                raise RuntimeError(
                    f"槽位注入失败，以下 UUID 无法找到或无 .edit-text 子元素：\n"
                    + "\n".join(f"  {uuid}: {status}" for uuid, status in failed.items())
                    + "\n请检查 edit_spec 中的 uuid 是否与模板实际 DOM ID 一致。"
                )

        # 元素样式调整（可选，用于修正布局问题）
        if adjustments:
            adj_js = json.dumps(adjustments, ensure_ascii=False)
            page.evaluate(f"""() => {{
                const adjs = {adj_js};
                for (const adj of adjs) {{
                    const el = document.getElementById(adj.id);
                    if (!el) continue;
                    for (const [prop, val] of Object.entries(adj.style)) {{
                        el.style[prop] = val;
                    }}
                }}
            }}""")
            page.wait_for_timeout(200)

        # 截图
        canvas = page.query_selector("#page-design-canvas")
        if not canvas:
            browser.close()
            raise RuntimeError("找不到画布元素 #page-design-canvas，请确认 Vite 服务正常运行")

        box = canvas.bounding_box()
        out_path = OUT_DIR / f"t{template_id}_render.png"
        page.screenshot(
            path=str(out_path),
            clip={"x": box["x"], "y": box["y"],
                  "width": box["width"], "height": box["height"]},
        )

        # 获取所有元素位置（相对于画布），用于生成 inspect 标注图
        elements = page.evaluate(f"""() => {{
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

        browser.close()

    # 生成 inspect 标注图
    inspect_path = _build_inspect_image(out_path, elements)

    return {"render": str(out_path), "inspect": str(inspect_path)}


def main():
    parser = argparse.ArgumentParser(description="虾稿设计单模板渲染")
    parser.add_argument("--id",          type=int, required=True,  help="模板 ID")
    parser.add_argument("--slots",       type=str, default="{}",   help='槽位内容 JSON，格式: {"uuid":"text"}')
    parser.add_argument("--adjustments", type=str, default="[]",   help='元素样式调整 JSON，格式: [{"id":"uuid","style":{"transform":"translateX(30px)"}}]')
    args = parser.parse_args()

    try:
        slots = json.loads(args.slots)
    except json.JSONDecodeError as e:
        print(f"slots JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        adjustments = json.loads(args.adjustments)
    except json.JSONDecodeError as e:
        print(f"adjustments JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = render_single(args.id, slots, adjustments or None)
        print(f"RENDER:{result['render']}")
        print(f"INSPECT:{result['inspect']}")
    except Exception as e:
        print(f"渲染失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
