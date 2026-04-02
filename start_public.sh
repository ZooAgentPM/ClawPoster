#!/usr/bin/env bash
# 虾稿设计 公网 MCP 服务 一键启动
# 启动：bash /Users/mlamp/visual-rag/start_public.sh
# 静态域名：bash /Users/mlamp/visual-rag/start_public.sh --domain your-name.ngrok-free.app
# 停止：Ctrl+C（自动清理子进程）

set -euo pipefail

BASE_DIR="/Users/mlamp/visual-rag"
PYTHON="$BASE_DIR/.venv/bin/python"
MCP_PORT=3001
NGROK_DOMAIN=""

# ── 解析参数 ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)
            NGROK_DOMAIN="$2"
            shift 2
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# ── 清理函数 ─────────────────────────────────────────────────
PIDS=()
cleanup() {
    echo ""
    echo "正在停止服务..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "已停止。"
}
trap cleanup EXIT INT TERM

# ── 检查 ngrok ────────────────────────────────────────────────
if ! command -v ngrok &>/dev/null; then
    echo "❌ ngrok 未找到，请先安装"
    exit 1
fi

# ── 端口占用检查 ──────────────────────────────────────────────
if lsof -i :"$MCP_PORT" -sTCP:LISTEN &>/dev/null; then
    echo "⚠  端口 $MCP_PORT 已被占用，请先停止占用的进程，或修改 MCP_PORT"
    lsof -i :"$MCP_PORT" -sTCP:LISTEN
    exit 1
fi

# ── 启动 ngrok 隧道（先启动，以便获取 URL 后注入到 MCP server）──
echo "▶ 启动 ngrok 隧道..."
if [[ -n "$NGROK_DOMAIN" ]]; then
    ngrok http "$MCP_PORT" --domain="$NGROK_DOMAIN" --log=stdout --log-format=json \
        > /tmp/ngrok-visual-rag.log 2>&1 &
else
    ngrok http "$MCP_PORT" --log=stdout --log-format=json \
        > /tmp/ngrok-visual-rag.log 2>&1 &
fi
PIDS+=($!)

# 等待 ngrok 隧道建立（轮询本地 API）
echo -n "  获取公网地址..."
NGROK_URL=""
for i in $(seq 1 30); do
    sleep 1
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null \
        | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tunnels = d.get('tunnels', [])
    for t in tunnels:
        if t.get('proto') == 'https':
            print(t['public_url'])
            break
except:
    pass
" 2>/dev/null || true)
    if [[ -n "$NGROK_URL" ]]; then
        break
    fi
    echo -n "."
done
echo ""

if [[ -z "$NGROK_URL" ]]; then
    echo "❌ 无法获取 ngrok 公网地址，请检查 ngrok 配置"
    exit 1
fi

# ── 启动 MCP HTTP 服务器（注入公网 URL，用于生成图片下载链接）──
echo "▶ 启动 MCP HTTP 服务器 → http://127.0.0.1:$MCP_PORT/mcp"
VISUAL_RAG_PUBLIC_URL="$NGROK_URL" \
    "$PYTHON" "$BASE_DIR/src/mcp_server.py" --port "$MCP_PORT" &
PIDS+=($!)

# 等待 MCP 服务就绪
echo -n "  等待就绪..."
for i in $(seq 1 20); do
    if nc -z 127.0.0.1 "$MCP_PORT" 2>/dev/null; then
        break
    fi
    sleep 0.5
    echo -n "."
done
echo " OK"

# ── 打印连接信息 ──────────────────────────────────────────────
MCP_ENDPOINT="$NGROK_URL/mcp"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           虾稿设计 MCP 公网服务已就绪                   ║"
echo "╠══════════════════════════════════════════════════════════╣"
printf "║  本地端口 : http://127.0.0.1:%d/mcp\n" "$MCP_PORT"
printf "║  公网地址 : %s\n" "$MCP_ENDPOINT"
printf "║  图片下载 : %s/files/<filename>\n" "$NGROK_URL"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  远端注册命令（在其他机器 Claude Code 上运行）：         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  claude mcp add --scope user --transport http visual-rag \\"
echo "    $MCP_ENDPOINT"
echo ""
if [[ -z "$NGROK_DOMAIN" ]]; then
echo "  ⚠ 免费版 URL 每次重启变化，用户需重新注册 MCP。"
echo "    申请固定域名（每账号1个免费）：https://dashboard.ngrok.com/domains"
echo "    使用固定域名启动："
echo "    bash start_public.sh --domain your-name.ngrok-free.app"
else
echo "  ✓ 使用静态域名：$NGROK_DOMAIN（URL 不会变化）"
fi
echo ""
echo "  Ctrl+C 停止所有服务"
echo ""

# ── 保持运行 ─────────────────────────────────────────────────
wait
