"""ChromaDB snapshot backup utility.

Missing feature fix: LocalMemoryStore had no backup mechanism. A ChromaDB
corruption or accidental deletion would permanently wipe all local memories.

This module exports `schedule_daily_backup(scheduler)` which registers a daily
cron job to export the ChromaDB collection to a JSON snapshot in `exports/memory/`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def _backup_chromadb(chroma_dir: str = ".jarvis_chroma", export_dir: str = "exports/memory") -> str:
    """Export all ChromaDB documents to a JSON snapshot.

    Returns the path of the written snapshot file.
    """
    try:
        import chromadb

        client = chromadb.PersistentClient(path=chroma_dir)
        collections = client.list_collections()
        snapshot: dict = {"timestamp": time.time(), "collections": {}}

        for col in collections:
            try:
                result = col.get(include=["documents", "metadatas", "ids"])
                snapshot["collections"][col.name] = {
                    "ids": result.get("ids", []),
                    "documents": result.get("documents", []),
                    "metadatas": result.get("metadatas", []),
                }
            except Exception as exc:
                snapshot["collections"][col.name] = {"error": str(exc)}

        out_dir = Path(export_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        out_path = out_dir / f"memory_backup_{ts}.json"
        out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        # Keep only the last 7 snapshots
        existing = sorted(out_dir.glob("memory_backup_*.json"))
        for old in existing[:-7]:
            old.unlink(missing_ok=True)

        return str(out_path)
    except Exception as exc:
        return f"backup_failed: {exc}"


def schedule_daily_backup(scheduler, chroma_dir: str = ".jarvis_chroma") -> None:
    """Register a daily 02:00 cron job in the given TaskScheduler to back up ChromaDB."""
    def _run():
        path = _backup_chromadb(chroma_dir=chroma_dir)
        print(f"[memory_backup] Snapshot written: {path}")

    try:
        scheduler.add_from_text(_run, "every day at 2:00 am", job_id="nova_memory_backup")
    except Exception:
        # Non-fatal — best-effort
        pass
