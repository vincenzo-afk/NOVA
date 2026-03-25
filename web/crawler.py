"""Simple breadth-first crawler."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def crawl(seed_url: str, max_pages: int = 5) -> list[str]:
    seen = set()
    queue = [seed_url]
    pages: list[str] = []

    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)

        try:
            response = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (JARVIS/1.0)"},
            )
            if not response.ok:
                continue
            if "text/html" not in response.headers.get("Content-Type", ""):
                continue
            html = response.text
        except Exception:
            continue

        pages.append(url)
        soup = BeautifulSoup(html, "html.parser")
        domain = urlparse(seed_url).netloc
        for link in soup.find_all("a", href=True):
            nxt = urljoin(url, link["href"])
            if urlparse(nxt).netloc == domain and nxt not in seen:
                queue.append(nxt)

    return pages
