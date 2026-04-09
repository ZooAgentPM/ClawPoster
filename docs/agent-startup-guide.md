# 虾稿设计服务启动指南（Agent 版）

> 本文档面向有 bash 权限的 Agent，描述如何在本机启动虾稿设计 MCP 服务。

---

## 服务架构

```
远端 Agent
    ↓ HTTPS MCP
ngrok 公网隧道（静态域名）
    ↓
mcp_server.py（port 3000）
    ↓
render_server.py（port 7002，Playwright 渲染）
    ↓
Vite 前端（port 5173）+ mock API（port 7001）
```

---

## 快速检查：服务是否已在运行

在执行任何启动操作前，先检查：

```bash
lsof -i -nP | grep LISTEN | grep -E ":3000|:7001|:5173|:7002"
curl -s http://localhost:4040/api/tunnels | python3 -c "
import sys,json
d=json.load(sys.stdin)
for t in d.get('tunnels',[]):
    print(t['proto'], t['public_url'], '->', t['config']['addr'])
" 2>/dev/null || echo "ngrok 未运行"
```

**理想状态**：4 个端口都有进程在监听，ngrok 指向 localhost:3000。

---

## 一键启动（推荐）

```bash
bash /Users/mlamp/visual-rag/start_public.sh --domain syncopated-retractively-anitra.ngrok-free.dev
```

脚本会自动：
1. 启动 ngrok 隧道
2. 启动 MCP HTTP server（注入公网 URL 用于生成下载链接）
3. 打印 MCP 端点地址

> **注意**：脚本不负责启动 render_server / Vite / mock API，这三个服务通常已常驻。如果未运行，参考下方手动启动。

---

## 手动启动各服务

### 1. mock API（port 7001）

```bash
cd /Users/mlamp/visual-rag
.venv/bin/python src/mock_api_server.py &
```

### 2. Vite 前端（port 5173）

```bash
cd /Users/mlamp/Desktop/虾稿设计-01/渲染器/poster-design
npm run dev -- --port 5173 --host 127.0.0.1 &
```

### 3. render_server（port 7002）

```bash
cd /Users/mlamp/visual-rag
.venv/bin/python src/render_server.py &
```

健康检查：
```bash
curl http://127.0.0.1:7002/health
# 期望返回：{"status":"ready","browser":"connected"}
```

### 4. MCP HTTP server（port 3000）

```bash
cd /Users/mlamp/visual-rag
VISUAL_RAG_PUBLIC_URL="https://syncopated-retractively-anitra.ngrok-free.dev" \
  .venv/bin/python src/mcp_server.py --port 3000 &
```

> `VISUAL_RAG_PUBLIC_URL` 必须注入，否则渲染响应不含下载链接。

### 5. ngrok 隧道

```bash
# 免费账号同时只能跑 1 个 session，有旧进程先 kill
kill $(pgrep ngrok) 2>/dev/null
ngrok http 3000 --domain=syncopated-retractively-anitra.ngrok-free.dev --log=stdout &

# 验证隧道
sleep 3
curl -s http://localhost:4040/api/tunnels | python3 -c "
import sys,json
d=json.load(sys.stdin)
for t in d.get('tunnels',[]):
    print(t['proto'], t['public_url'], '->', t['config']['addr'])
"
```

---

## 常见故障处理

| 现象 | 原因 | 处理 |
|------|------|------|
| 502 Bad Gateway | ngrok 指向的端口已死 | 重启 ngrok 并指向正确端口 |
| 渲染失败 / render_server 无响应 | render_server 崩溃 | 重启 render_server（步骤 3）|
| 图片下载 404 | render_server 是旧版本（无 /files 接口）| 重启 render_server |
| list_templates 404 | MCP server 是旧进程 | 重启 MCP server（步骤 4）|
| 两人渲染图片相同 | 不会发生（已修复，文件名含时间戳）| — |
| 域名失效 | ngrok 静态域名需重新激活 | 联系小邹获取新域名 |

---

## MCP 端点

```
https://syncopated-retractively-anitra.ngrok-free.dev/mcp
```

图片下载（文件名从渲染响应中取，不得自行构造）：
```
https://syncopated-retractively-anitra.ngrok-free.dev/files/<filename>
```
