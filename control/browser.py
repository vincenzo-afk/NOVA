"""Browser automation via Playwright sync API."""

from __future__ import annotations

from contextlib import suppress

from playwright.sync_api import sync_playwright


class Browser:
    def __init__(self, headless: bool = True, timeout_ms: int = 20_000):
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=headless)
        self.page = self.browser.new_page()
        self.page.set_default_timeout(timeout_ms)

    def open(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")

    def click(self, selector: str) -> None:
        self.page.click(selector)

    def fill(self, selector: str, value: str) -> None:
        self.page.fill(selector, value)

    def extract_text(self) -> str:
        return self.page.inner_text("body")

    def get_links(self) -> list[str]:
        return self.page.eval_on_selector_all("a", "els => els.map(e => e.href)")

    def screenshot(self, path: str | None = None) -> bytes:
        if path:
            return self.page.screenshot(path=path)
        return self.page.screenshot()

    def current_url(self) -> str:
        return self.page.url

    def wait_for_text(self, text: str, timeout_ms: int = 10_000) -> bool:
        try:
            self.page.get_by_text(text).first.wait_for(timeout=timeout_ms)
            return True
        except Exception:
            return False

    def __enter__(self) -> "Browser":
        return self

    def close(self) -> None:
        with suppress(Exception):
            self.browser.close()
        with suppress(Exception):
            self._pw.stop()

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)
        self.close()
