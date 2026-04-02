"""
共享配置：从环境变量或 ~/.claude/settings.json 读取 API key。
"""
import json
import os
from pathlib import Path


def load_api_key() -> str:
    key = os.environ.get("VISUAL_RAG_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    if key:
        return key
    settings = Path.home() / ".claude" / "settings.json"
    if settings.exists():
        d = json.loads(settings.read_text())
        key = d.get("env", {}).get("ANTHROPIC_AUTH_TOKEN", "")
        if key:
            return key
    return "dummy-key"


BASE_URL = os.environ.get("VISUAL_RAG_BASE_URL", "https://vibe.deepminer.ai/v1")
API_KEY  = load_api_key()
MODEL    = os.environ.get("VISUAL_RAG_MODEL", "claude-sonnet-4-6")
