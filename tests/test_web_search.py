from __future__ import annotations

from web import search as search_mod


def test_search_with_ddgs_adapter(monkeypatch):
    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

        def text(self, query, max_results=5):
            return [{"title": f"Result for {query}", "href": "https://example.com"}] * max_results

    monkeypatch.setattr(search_mod, "DDGS", FakeDDGS)
    results = search_mod.search("jarvis", max_results=2)
    assert len(results) == 2
    assert "jarvis" in results[0]["title"].lower()


def test_search_html_fallback(monkeypatch):
    monkeypatch.setattr(search_mod, "DDGS", None)

    class Resp:
        status_code = 200
        text = """
        <div class='result'>
          <a class='result__a' href='https://example.org'>Example Org</a>
          <a class='result__title'>Example Org Title</a>
          <a class='result__snippet'>Snippet here</a>
        </div>
        """

        def raise_for_status(self):
            return None

    monkeypatch.setattr(search_mod.requests, "get", lambda *a, **k: Resp())
    results = search_mod.search("example", max_results=1)
    assert len(results) == 1
    assert results[0]["href"] == "https://example.org"
