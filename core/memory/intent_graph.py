"""Intent Graph Builder — Proactive Intelligence Tier 2.

Builds and persists a local graph of user intent clusters based on
conversation topics. Used to pre-load RAG context and synthesize proactive goals.

Graph is stored locally in .jarvis/intent_graph.json — never sent externally.
"""
from __future__ import annotations

import json
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_GRAPH_PATH = Path(".jarvis/intent_graph.json")
_MAX_EDGES = 200  # max co-occurrence pairs to persist
_MIN_EDGE_WEIGHT = 2  # minimum co-occurrences to surface an edge


# ── simple stopword filter ────────────────────────────────────────────────────

_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would can could should shall may might must that this these those "
    "i you he she it we they me my your his her its our their to of in on at "
    "for with by from up about into through during including until against "
    "from than because if then just also when where who how what which some "
    "all no not or and but so".split()
)


def _extract_keywords(text: str, max_kw: int = 10) -> list[str]:
    """Extract cleaned keywords from a text snippet."""
    words = re.findall(r"\b[a-z]{4,}\b", text.lower())
    filtered = [w for w in words if w not in _STOPWORDS]
    # Take most common to focus on dominant topics
    counts = Counter(filtered)
    return [w for w, _ in counts.most_common(max_kw)]


# ── graph ─────────────────────────────────────────────────────────────────────

class IntentGraph:
    """Co-occurrence-based intent graph over conversation keywords.

    node  → keyword/topic
    edge  → co-occurrence count between two topics in the same turn/session
    """

    def __init__(self, path: Path = _GRAPH_PATH, privacy_mode: bool = False):
        self._path = path
        self.privacy_mode = privacy_mode
        self._lock = threading.Lock()
        # adjacency: {kw: {kw: count}}
        self._adj: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # node recency: {kw: last_seen_iso}
        self._last_seen: dict[str, str] = {}
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                for src, neighbors in raw.get("adj", {}).items():
                    for dst, cnt in neighbors.items():
                        self._adj[src][dst] = cnt
                self._last_seen = raw.get("last_seen", {})
            except Exception:
                pass

    def _save(self) -> None:
        if self.privacy_mode:
            return
        try:
            import tempfile
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Prune to top edges so file stays small
            all_edges: list[tuple[str, str, int]] = []
            for src, neighbors in self._adj.items():
                for dst, cnt in neighbors.items():
                    all_edges.append((src, dst, cnt))
            all_edges.sort(key=lambda x: x[2], reverse=True)
            pruned: dict[str, dict[str, int]] = defaultdict(dict)
            for src, dst, cnt in all_edges[:_MAX_EDGES]:
                pruned[src][dst] = cnt
            payload = {"adj": pruned, "last_seen": self._last_seen}
            content = json.dumps(payload, indent=2)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self._path.parent),
                delete=False,
                suffix=".tmp",
            ) as tmp:
                tmp.write(content)
                tmp.flush()
                tmp_path = Path(tmp.name)
            tmp_path.replace(self._path)
        except Exception:
            pass

    # ── update ────────────────────────────────────────────────────────────────

    def ingest_turn(self, text: str) -> list[str]:
        """Extract keywords and update co-occurrence edges. Returns extracted keywords."""
        if self.privacy_mode or not text:
            return []
        kws = _extract_keywords(text)
        if not kws:
            return []
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for kw in kws:
                self._last_seen[kw] = now_iso
            for i, src in enumerate(kws):
                for dst in kws[i + 1:]:
                    if src != dst:
                        self._adj[src][dst] += 1
                        self._adj[dst][src] += 1
        self._save()
        return kws

    # ── queries ───────────────────────────────────────────────────────────────

    def related_topics(self, keyword: str, top_k: int = 5) -> list[tuple[str, int]]:
        """Return topics most strongly associated with `keyword`."""
        with self._lock:
            neighbors = self._adj.get(keyword.lower(), {})
        ranked = sorted(neighbors.items(), key=lambda x: x[1], reverse=True)
        return [(k, v) for k, v in ranked[:top_k] if v >= _MIN_EDGE_WEIGHT]

    def hot_topics(self, top_k: int = 8) -> list[tuple[str, int]]:
        """Return the most connected nodes (highest total edge weight)."""
        with self._lock:
            scored = {
                kw: sum(self._adj[kw].values())
                for kw in self._adj
            }
        return sorted(scored.items(), key=lambda x: x[1], reverse=True)[:top_k]

    def build_rag_query_hints(self, recent_text: str, top_k: int = 6) -> list[str]:
        """Return contextually relevant keywords for speculative RAG pre-loading."""
        fresh_kws = _extract_keywords(recent_text, max_kw=5)
        hints: set[str] = set(fresh_kws)
        with self._lock:
            for kw in fresh_kws:
                for related, _ in list(self._adj.get(kw, {}).items())[:3]:
                    hints.add(related)
        return list(hints)[:top_k]

    def summary(self) -> dict[str, Any]:
        """Return a JSON-safe summary for the `intent.graph` tool."""
        return {
            "node_count": len(self._adj),
            "privacy_mode": self.privacy_mode,
            "hot_topics": [{"topic": t, "weight": w} for t, w in self.hot_topics(5)],
        }
