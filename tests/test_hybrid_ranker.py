from __future__ import annotations

from web.hybrid_ranker import HybridRanker


def test_hybrid_ranker_returns_relevant_doc_first():
    ranker = HybridRanker()
    docs = [
        "Cooking recipes for dinner",
        "Python asyncio guide with examples",
        "Travel plan for japan",
    ]
    ranked = ranker.rank("python asyncio", docs, top_k=2)
    assert ranked
    assert "python" in ranked[0].lower()
