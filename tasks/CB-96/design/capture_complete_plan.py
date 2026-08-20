"""Capture the complete CB-96 planning board with Playwright."""

# ruff: noqa: INP001, S101

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )
    for source, target in (
        ("cb93-complete-screen-board.html", "cb93-v5-complete-screen-board.png"),
        ("cb93-transition-map.html", "cb93-v5-transition-map.png"),
        ("cb93-contract-coverage-v5.html", "cb93-v5-contract-coverage.png"),
    ):
        page = browser.new_page(
            viewport={"width": 1600, "height": 1400},
            device_scale_factor=1,
        )
        page.goto((ROOT / source).as_uri())
        page.evaluate("document.fonts.ready")
        assert page.evaluate("document.documentElement.scrollWidth <= 1600"), source
        page.screenshot(path=str(ROOT / target), full_page=True)
        page.close()
    browser.close()
