"""
Mock API server for palxp frontend dev mode.
Serves template data from local JSON files.

Key mapping for w-svg widgets:
  imgUrl (local path) → svgUrl (SVG XML content, as expected by wSvg.vue / Snap.parse)
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

RAW_DIR  = Path('/Users/mlamp/visual-rag/data/palxp-raw')
SVG_DIR  = Path('/Users/mlamp/visual-rag/data/assets/svgs')
IMG_DIR  = Path('/Users/mlamp/visual-rag/data/assets/images')
FONT_DIR = Path('/Users/mlamp/visual-rag/data/assets/fonts')


def _local_path_for(url: str) -> Path | None:
    """CDN URL 或本地绝对路径 → 本地文件 Path"""
    if not url:
        return None
    if url.startswith('/Users/mlamp/visual-rag/data/'):
        p = Path(url)
        return p if (p.exists() and p.is_file()) else None
    fname = url.split('/')[-1].split('?')[0]
    if not fname:
        return None
    for d in [IMG_DIR, SVG_DIR, FONT_DIR, IMG_DIR.parent / 'covers']:
        p = d / fname
        if p.exists() and p.is_file():
            return p
    return None


def _fix_image_url(url: str) -> str:
    """把本地路径转成 http://127.0.0.1:7001/assets/... URL，浏览器可直接加载"""
    if not url:
        return url
    if url.startswith('http'):
        local = _local_path_for(url)
        if local:
            rel = local.relative_to(Path('/Users/mlamp/visual-rag/data'))
            return f'http://127.0.0.1:7001/assets/{rel}'
        return url
    if url.startswith('/Users/mlamp/visual-rag/data/'):
        rel = Path(url).relative_to(Path('/Users/mlamp/visual-rag/data'))
        return f'http://127.0.0.1:7001/assets/{rel}'
    return url


def load_template(template_id: int, slots: dict | None = None) -> dict | None:
    layer_file = RAW_DIR / f't{template_id}_layers.json'
    if not layer_file.exists():
        return None

    d = json.loads(layer_file.read_text(encoding='utf-8'))
    widgets = d.get('dWidgets', [])
    elem    = d.get('dActiveElement', {})

    # 修复背景图 URL
    if elem.get('backgroundImage'):
        elem['backgroundImage'] = _fix_image_url(elem['backgroundImage'])

    # 处理每个 widget
    for w in widgets:
        wtype = w.get('type', '')

        if wtype == 'w-svg':
            img_url = w.get('imgUrl', '')
            # 若没有 imgUrl，尝试从已有的 svgUrl（可能是远程 URL）提取文件名查找本地文件
            existing_svg_url = w.get('svgUrl', '')
            source_url = img_url or existing_svg_url
            local = _local_path_for(source_url)
            if local and local.exists():
                w['svgUrl'] = local.read_text(encoding='utf-8')
            elif img_url:
                w['svgUrl'] = img_url  # fallback to imgUrl
            # else: 保留 existing_svg_url 不覆盖（避免把有效 URL 覆写成空字符串）
            # 确保 colors 字段存在，且去掉 8位 hex 末尾的 alpha（SVG fill 只支持 6位）
            if 'colors' not in w:
                w['colors'] = []
            w['colors'] = [c[:7] if len(c) == 9 and c.startswith('#') else c for c in w['colors']]

        elif wtype == 'w-image':
            img_url = w.get('imgUrl', '')
            w['imgUrl'] = _fix_image_url(img_url)
            # 修复 mask URL（CSS -webkit-mask-image 用的遮罩图）
            if w.get('mask'):
                w['mask'] = _fix_image_url(w['mask'])

        elif wtype == 'w-text':
            # 应用 slots 内容替换（如果有）
            if slots:
                uuid = str(w.get('uuid', ''))
                if uuid in slots:
                    w['text'] = slots[uuid]

        # 修复 fontClass.url
        fc = w.get('fontClass', {})
        if fc and fc.get('url'):
            fc['url'] = _fix_image_url(fc['url'])

    content = [{'global': elem, 'layers': widgets}]
    return {
        'id': template_id,
        'title': f'Template {template_id}',
        'data': json.dumps(content),
        'width': elem.get('width', 1242),
        'height': elem.get('height', 2208),
    }


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[API] {format % args}")

    def _serve_file(self, path: Path):
        import mimetypes
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        mime = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        data = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # GET /design/temp?id=XXX
        if parsed.path == '/design/temp':
            tid = int(params.get('id', [0])[0])
            data = load_template(tid)
            if data:
                body = json.dumps({'code': 200, 'result': data}).encode()
                self.send_response(200)
            else:
                body = json.dumps({'code': 404, 'msg': 'not found'}).encode()
                self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

        # GET /assets/... (本地资源文件)
        elif parsed.path.startswith('/assets/'):
            rel = parsed.path[len('/assets/'):]
            local = Path('/Users/mlamp/visual-rag/data') / rel
            self._serve_file(local)

        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'code': 200, 'result': {}}).encode())

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        self.rfile.read(content_len) if content_len else b''
        resp = json.dumps({'code': 200, 'result': {}}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(resp)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.end_headers()


if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 7001), MockHandler)
    print('Mock API server running on http://127.0.0.1:7001')
    server.serve_forever()
