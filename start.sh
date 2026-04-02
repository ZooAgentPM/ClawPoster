#!/bin/bash
# visual-rag: start the design asset server
cd "$(dirname "$0")"

# vibe.deepminer.ai — OpenAI-compatible proxy
export VISUAL_RAG_BASE_URL="https://vibe.deepminer.ai/v1"
export VISUAL_RAG_MODEL="claude-sonnet-4-5-20250929"
# API key: get from openclaw config (or set manually)
if [ -z "$VISUAL_RAG_API_KEY" ]; then
  VISUAL_RAG_API_KEY=$(python3 -c "
import json,pathlib
cfg = pathlib.Path.home()/'.openclaw'/'openclaw.json'
d = json.loads(cfg.read_text())
print(d.get('models',{}).get('providers',{}).get('vibe',{}).get('apiKey','dummy-key'))
" 2>/dev/null)
fi
export VISUAL_RAG_API_KEY
export VISUAL_RAG_PORT="${VISUAL_RAG_PORT:-8765}"

echo ""
echo "  visual-rag Design Asset Server"
echo "  ──────────────────────────────"
echo "  API:  http://localhost:$VISUAL_RAG_PORT"
echo "  Docs: http://localhost:$VISUAL_RAG_PORT/docs"
echo ""

.venv/bin/python src/server.py
