"""
visual-rag: Schema definition for textualized design assets.

This is the core data contract. Every design asset, once textualized,
becomes a DesignAsset dict that AI agents can reason about.
"""

# Example of a fully textualized design asset
SCHEMA_EXAMPLE = {
    "id": "template_001",
    "source": "稿定",                          # 素材来源
    "file": "assets/template_001.png",         # 原始文件路径

    # 用途 — AI 用这个来匹配需求
    "use_cases": ["小红书封面", "产品推广", "美妆"],
    "platforms": ["小红书", "Instagram", "微信朋友圈"],

    # 布局 — 告诉 AI 内容区域在哪
    "layout": {
        "type": "上图下文",                    # 上图下文 / 左右分割 / 全图 / 文字为主
        "content_areas": [
            {"name": "hero_image", "position": "top", "ratio": 0.6},
            {"name": "title", "position": "middle", "ratio": 0.2},
            {"name": "subtitle", "position": "bottom", "ratio": 0.1},
            {"name": "cta", "position": "bottom", "ratio": 0.1},
        ]
    },

    # 风格 — 让 AI 理解视觉调性
    "style": {
        "mood": ["高级感", "极简", "干净"],    # 氛围标签
        "color_palette": ["#FFFFFF", "#1A1A1A", "#FF4D4D"],
        "color_theme": "黑白撞色",
        "typography": "无衬线现代体",
        "visual_weight": "轻量",               # 轻量 / 中等 / 厚重
    },

    # 内容要求 — 告诉 AI 这个模板需要填什么
    "content_slots": {
        "title": {"required": True, "max_chars": 10, "hint": "产品名或主题词"},
        "subtitle": {"required": False, "max_chars": 20, "hint": "卖点或描述"},
        "cta": {"required": False, "max_chars": 8, "hint": "行动号召，如'立即抢购'"},
        "hero_image": {"required": True, "hint": "产品主图，建议白底"},
    },

    # 语义摘要 — 最重要，AI 靠这个做语义匹配
    "description": "极简黑白风格小红书封面模板，适合美妆、时尚、科技类产品推广。上方留大图区域，下方两行文字，整体干净高级。",

    # 向量（搜索时自动生成，存储时填入）
    "embedding": None,
}
