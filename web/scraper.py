"""Web scraping utilities."""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup


def scrape_text(url: str) -> str:
    response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (JARVIS/1.0)"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)
