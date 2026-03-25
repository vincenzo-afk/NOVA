"""Hybrid BM25 + semantic + RRF ranking."""

from __future__ import annotations

try:
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover - fallback for minimal environments
    BM25Okapi = None


class HybridRanker:
    def rank(self, query: str, docs: list[str], top_k: int = 5) -> list[str]:
        if not docs:
            return []

        if BM25Okapi is None:
            return docs[:top_k]

        tokenized = [d.lower().split() for d in docs]
        bm25 = BM25Okapi(tokenized)
        bm25_scores = bm25.get_scores(query.lower().split())

        semantic_scores = [self._jaccard(query, d) for d in docs]

        bm25_ranks = sorted(range(len(docs)), key=lambda i: bm25_scores[i], reverse=True)
        sem_ranks = sorted(range(len(docs)), key=lambda i: semantic_scores[i], reverse=True)

        fused = []
        for i, _ in enumerate(docs):
            r1 = bm25_ranks.index(i) + 1
            r2 = sem_ranks.index(i) + 1
            fused.append(((1 / (60 + r1)) + (1 / (60 + r2)), docs[i]))

        fused.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in fused[:top_k]]

    @staticmethod
    def _jaccard(a: str, b: str) -> float:
        sa = set(a.lower().split())
        sb = set(b.lower().split())
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)
