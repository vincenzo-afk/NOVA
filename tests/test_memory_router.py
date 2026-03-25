from __future__ import annotations

from core.memory.local_store import LocalMemoryStore
from core.memory.mem0_client import Mem0Client
from core.memory.memory_router import MemoryRouter


def test_memory_router_dedup_and_sync():
    router = MemoryRouter(mem0=Mem0Client(), local=LocalMemoryStore())
    session_id = "s1"

    result1 = router.add("hello world", session_id)
    result2 = router.add("hello world", session_id)

    assert result1["status"] == "ok"
    assert result2["status"] == "duplicate"

    router.set_online(False)
    router.add("offline memory", session_id)
    router.set_online(True)
    synced = router.sync_pending(session_id)
    assert synced == 1


def test_memory_router_search_returns_ranked_results():
    router = MemoryRouter(mem0=Mem0Client(), local=LocalMemoryStore())
    session_id = "s2"
    router.add("python async programming", session_id)
    router.add("cooking pasta quickly", session_id)

    results = router.search("python", session_id)
    assert results
    assert "python" in results[0]["text"].lower()
