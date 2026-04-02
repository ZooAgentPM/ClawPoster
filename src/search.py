"""
visual-rag: Semantic search engine for design assets.

Flow:
1. Load index (JSON with descriptions)
2. Build embeddings via Claude API (text-embedding)
3. Query: embed the user's natural language request
4. Return top-K matches ranked by cosine similarity
"""

import json
import math
import os
import sys
from pathlib import Path
from typing import Optional
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://vibe.deepminer.ai")
API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "dummy-key")
DATA_DIR   = Path(__file__).parent.parent / "data"
INDEX_PATH = DATA_DIR / "mock_index.json"
PD_INDEX_PATH = DATA_DIR / "pd_index.json"
CACHE_PATH = DATA_DIR / "embedding_cache.json"

client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

# ── Embedding ─────────────────────────────────────────────────────────────────

def _embed(text: str) -> list[float]:
    """Call Claude embedding API (voyager model via proxy)."""
    try:
        resp = client.beta.messages.batches  # Not the right API, use raw HTTP
        # Use the messages API with a trick: ask Claude to embed via tool
        # Actually, use the embeddings endpoint directly
        import httpx
        r = httpx.post(
            f"{BASE_URL}/v1/embeddings",
            headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
            json={"model": "text-embedding-3-small", "input": text},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()["data"][0]["embedding"]
    except Exception:
        pass

    # Fallback: use Claude to generate a pseudo-embedding via keyword extraction
    return _pseudo_embed(text)


def _pseudo_embed(text: str) -> list[float]:
    """
    Fallback when embedding API unavailable.
    Use TF-IDF-like keyword matching instead of real vectors.
    Stores keywords as a special marker in the 'embedding' field.
    """
    # Return None to signal: use keyword search instead
    return None


def _keyword_score(query: str, asset: dict) -> float:
    """
    Keyword overlap score for Chinese text.
    Chinese has no word boundaries, so we use sliding n-gram matching:
    check if any substring of length 2+ from the query appears in the blob.
    """
    # Build a text blob from the asset
    blob_parts = [
        asset.get("description", ""),
        "".join(asset.get("use_cases", [])),
        "".join(asset.get("platforms", [])),
        asset.get("style", {}).get("color_theme", ""),
        "".join(asset.get("style", {}).get("mood", [])),
        "".join(asset.get("source", "")),
    ]
    blob = "".join(blob_parts)

    # Clean query
    q = query.replace("，", "").replace(",", "").replace(" ", "").replace("、", "")

    if not q:
        return 0.0

    # Score: how many 2-char n-grams from query appear in blob
    total_ngrams = max(len(q) - 1, 1)
    hits = sum(1 for i in range(len(q) - 1) if q[i:i+2] in blob)
    return hits / total_ngrams


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Index Management ──────────────────────────────────────────────────────────

def load_index() -> list[dict]:
    with open(INDEX_PATH, encoding="utf-8") as f:
        assets = json.load(f)
    # Merge poster-design converted templates if available
    if PD_INDEX_PATH.exists():
        with open(PD_INDEX_PATH, encoding="utf-8") as f:
            pd_assets = json.load(f)
        # Avoid duplicates by id
        existing_ids = {a["id"] for a in assets}
        assets += [a for a in pd_assets if a["id"] not in existing_ids]
    return assets


def load_cache() -> dict:
    if CACHE_PATH.exists():
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def build_embeddings(assets: list[dict], force: bool = False) -> dict:
    """Generate and cache embeddings for all assets."""
    cache = {} if force else load_cache()
    changed = False

    for asset in assets:
        aid = asset["id"]
        if aid not in cache:
            text = asset["description"] + " " + " ".join(asset.get("use_cases", []))
            print(f"  Embedding {aid}...", end=" ", flush=True)
            vec = _embed(text)
            if vec:
                cache[aid] = vec
                print(f"✓ ({len(vec)}d)")
            else:
                cache[aid] = None
                print("→ keyword fallback")
            changed = True

    if changed:
        save_cache(cache)

    return cache


# ── Search ────────────────────────────────────────────────────────────────────

def search(
    query: str,
    top_k: int = 3,
    platform: Optional[str] = None,
) -> list[dict]:
    """
    Search design assets by natural language query.

    Args:
        query:    Natural language description, e.g. "小红书美妆封面，奶油风"
        top_k:    Number of results to return
        platform: Optional filter by platform, e.g. "小红书"

    Returns:
        List of matched assets with scores, sorted by relevance.
    """
    assets = load_index()
    cache  = load_cache()

    # Apply platform filter
    if platform:
        assets = [a for a in assets if platform in a.get("platforms", [])]

    # Try to embed the query
    query_vec = _embed(query)

    results = []
    for asset in assets:
        aid = asset["id"]
        asset_vec = cache.get(aid)

        if query_vec and asset_vec:
            score = _cosine(query_vec, asset_vec)
            method = "semantic"
        else:
            score = _keyword_score(query, asset)
            method = "keyword"

        results.append({
            **asset,
            "_score": score,
            "_match_method": method,
        })

    results.sort(key=lambda x: x["_score"], reverse=True)
    return results[:top_k]


def format_result(asset: dict, rank: int) -> str:
    """Format a single search result for display."""
    score_bar = "█" * int(asset["_score"] * 10) + "░" * (10 - int(asset["_score"] * 10))
    lines = [
        f"#{rank}  [{asset['id']}] {asset['source']}",
        f"    相关度: {score_bar} {asset['_score']:.2f}  ({asset['_match_method']})",
        f"    描述:   {asset['description'][:60]}...",
        f"    用途:   {', '.join(asset['use_cases'][:3])}",
        f"    风格:   {asset['style']['color_theme']} | {', '.join(asset['style']['mood'][:3])}",
        f"    平台:   {', '.join(asset['platforms'][:3])}",
    ]
    return "\n".join(lines)
