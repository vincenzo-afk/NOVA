"""Web search utilities."""

from __future__ import annotations

from urllib.parse import quote_plus

import requests
import re

try:
    from duckduckgo_search import DDGS
except Exception:  # pragma: no cover
    DDGS = None


def search(query: str, max_results: int = 5) -> list[dict]:
    if DDGS is not None:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.text, "html.parser")
        items = []
        for result in soup.select(".result")[:max_results]:
            title_el = result.select_one(".result__title")
            link_el = result.select_one(".result__a")
            body_el = result.select_one(".result__snippet")
            if not link_el:
                continue
            items.append(
                {
                    "title": title_el.get_text(" ", strip=True) if title_el else "",
                    "href": link_el.get("href", ""),
                    "body": body_el.get_text(" ", strip=True) if body_el else "",
                }
            )
        return items
    except Exception:
        pattern = re.compile(
            r"<a[^>]*class=['\"]result__a['\"][^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
            re.IGNORECASE | re.DOTALL,
        )
        hits = []
        for href, title in pattern.findall(response.text):
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            hits.append({"title": clean_title, "href": href, "body": ""})
            if len(hits) >= max_results:
                break
        return hits
