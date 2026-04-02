"""
visual-rag filler: uses Claude to fill template content slots from a user brief.

Input:  template dict (with content_slots) + user brief string
Output: dict of {slot_name: filled_value}
"""

import os
import json
from openai import OpenAI

# vibe.deepminer.ai uses OpenAI-compatible API format
from config import BASE_URL, API_KEY, MODEL

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


async def fill_slots(template: dict, brief: str, pre_filled: dict = {}) -> dict:
    """
    Use Claude to fill all content_slots in a template based on a user brief.

    Args:
        template:    The design template dict (with content_slots)
        brief:       User's description, e.g. "耳机双十一大促，优惠价299元"
        pre_filled:  Slots already provided by user (e.g. image URLs)

    Returns:
        Dict of {slot_name: value} for all slots
    """
    slots = template.get("content_slots", {})
    if not slots:
        return {}

    # Build slot descriptions for the prompt
    slot_desc = "\n".join(
        f'- {name}: {info.get("hint", "")} (最多{info.get("max_chars", "?")}字, '
        f'{"必填" if info.get("required") else "选填"})'
        for name, info in slots.items()
        if name not in pre_filled and info.get("max_chars", 0) > 0  # skip image slots
    )

    prompt = f"""你是一个设计文案助手。根据用户的需求简介，为设计模板填写文字内容。

模板信息：
- 模板描述：{template.get("description", "")}
- 适用场景：{", ".join(template.get("use_cases", []))}
- 风格调性：{", ".join(template.get("style", {}).get("mood", []))}

用户需求：{brief}

需要填写的内容槽（严格遵守字数限制）：
{slot_desc}

请以 JSON 格式返回所有内容槽的填写值，只返回 JSON，不要解释：
{{
  "slot_name": "填写内容",
  ...
}}"""

    result = {}

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content.strip()
        # Extract JSON from response (handle ```json ... ``` wrapping)
        if "```" in text:
            parts = text.split("```")
            # parts[1] is the code block content
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[filler] ERROR: {e}")
        # Fallback: return empty strings so render still works
        result = {
            name: ""
            for name, info in slots.items()
            if info.get("max_chars", 0) > 0
        }

    # Merge pre-filled image slots
    result.update(pre_filled)

    # Enforce max_chars
    for name, info in slots.items():
        max_c = info.get("max_chars", 0)
        if name in result and isinstance(result[name], str) and max_c > 0:
            result[name] = result[name][:max_c]

    return result
