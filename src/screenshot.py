"""
visual-rag screenshot: convert HTML render → real PNG image.
Uses Playwright (headless Chromium) to screenshot our renderer.
"""

import asyncio
import base64
from pathlib import Path

SCREENSHOTS_DIR = Path(__file__).parent.parent / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)


async def html_to_png(html: str, width: int = 600, height: int = 600) -> bytes:
    """Render HTML string to PNG bytes using Playwright."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.set_content(html, wait_until="networkidle")
        png_bytes = await page.screenshot(
            type="png",
            clip={"x": 0, "y": 0, "width": width, "height": height},
        )
        await browser.close()
        return png_bytes


async def url_to_png(url: str, width: int = 600, height: int = 600) -> bytes:
    """Screenshot a URL to PNG bytes."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.goto(url, wait_until="networkidle")
        png_bytes = await page.screenshot(
            type="png",
            clip={"x": 0, "y": 0, "width": width, "height": height},
        )
        await browser.close()
        return png_bytes


def save_screenshot(png_bytes: bytes, filename: str) -> Path:
    """Save PNG bytes to disk, return path."""
    path = SCREENSHOTS_DIR / filename
    path.write_bytes(png_bytes)
    return path


def png_to_data_url(png_bytes: bytes) -> str:
    """Convert PNG bytes to base64 data URL for embedding in responses."""
    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"
