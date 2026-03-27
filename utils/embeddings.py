"""Shared embedding utilities with graceful fallbacks."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import threading
from typing import Iterable, List


@dataclass
class EmbeddingConfig:
    model_name: str = "all-MiniLM-L6-v2"


class EmbeddingBackend:
    """Lazy SentenceTransformer wrapper.

    Falls back by raising RuntimeError if the dependency/model is unavailable.
    """

    def __init__(self, config: EmbeddingConfig | None = None):
        self.config = config or EmbeddingConfig()
        self._lock = threading.Lock()
        self._model = None

    @staticmethod
    def is_available() -> bool:
        try:
            import sentence_transformers  # noqa: F401

            return True
        except Exception:
            return False

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.config.model_name)
        except Exception as exc:  # pragma: no cover - depends on optional deps
            raise RuntimeError(f"SentenceTransformer unavailable: {exc}") from exc

    def encode(self, texts: Iterable[str]) -> List[list[float]]:
        with self._lock:
            if self._model is None:
                self._load()
            embeddings = self._model.encode(
                list(texts),
                normalize_embeddings=True,
            )
        try:
            return embeddings.tolist()
        except Exception:
            return [list(vec) for vec in embeddings]


@lru_cache(maxsize=4)
def get_embedder(model_name: str = "all-MiniLM-L6-v2") -> EmbeddingBackend:
    return EmbeddingBackend(EmbeddingConfig(model_name=model_name))
