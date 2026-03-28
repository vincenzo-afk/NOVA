"""Simple breadth-first web crawler with SSRF protection.

Fix 4.2: applies the same private IP guard from scraper.py before visiting any URL.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from web.scraper import _validate_url


def crawl(seed_url: str, max_pages: int = 5, max_depth: int = 2) -> list[str]:
    # Validate seed URL before starting
    try:
        _validate_url(seed_url)
    except ValueError as exc:
        raise ValueError(f"Crawl blocked: {exc}") from exc

    seen: set[str] = set()
    queue: list[tuple[str, int]] = [(seed_url, 0)]
    pages: list[str] = []

    while queue and len(pages) < max_pages:
        url, depth = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)

        # SSRF guard on each queued link
        try:
            _validate_url(url)
        except ValueError:
            continue

        try:
            response = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (NOVA/1.0)"},
            )
            if not response.ok:
                continue
            if "text/html" not in response.headers.get("Content-Type", ""):
                continue
            html = response.text
        except Exception:
            continue

        pages.append(url)
        if depth >= max_depth:
            continue
        soup = BeautifulSoup(html, "html.parser")
        domain = urlparse(seed_url).netloc
        for link in soup.find_all("a", href=True):
            nxt = urljoin(url, link["href"])
            if urlparse(nxt).netloc == domain and nxt not in seen:
                if len(queue) < max_pages * 10:
                    queue.append((nxt, depth + 1))

    return pages
