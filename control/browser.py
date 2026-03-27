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
        try:
            self.page.goto(url, wait_until="domcontentloaded")
        except Exception:
            # Fix 5.2: Force re-initialization on unexpected exceptions
            self._cleanup_on_error()
            raise

    def click(self, selector: str) -> None:
        try:
            self.page.click(selector)
        except Exception:
            self._cleanup_on_error()
            raise

    def fill(self, selector: str, value: str) -> None:
        try:
            self.page.fill(selector, value)
        except Exception:
            self._cleanup_on_error()
            raise

    def extract_text(self) -> str:
        try:
            return self.page.inner_text("body")
        except Exception:
            self._cleanup_on_error()
            raise

    def get_links(self) -> list[str]:
        try:
            return self.page.eval_on_selector_all("a", "els => els.map(e => e.href)")
        except Exception:
            self._cleanup_on_error()
            raise

    def screenshot(self, path: str | None = None) -> bytes:
        try:
            if path:
                return self.page.screenshot(path=path)
            return self.page.screenshot()
        except Exception:
            self._cleanup_on_error()
            raise

    def current_url(self) -> str:
        return self.page.url

    def wait_for_text(self, text: str, timeout_ms: int = 10_000) -> bool:
        try:
            self.page.get_by_text(text).first.wait_for(timeout=timeout_ms)
            return True
        except Exception:
            return False

    def _cleanup_on_error(self) -> None:
        """Clean up browser state on unexpected errors (fix 5.2)."""
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass
        # Re-initialize
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=True)
        self.page = self.browser.new_page()

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
