"""ChromaDB snapshot backup utility.

Missing feature fix: LocalMemoryStore had no backup mechanism. A ChromaDB
corruption or accidental deletion would permanently wipe all local memories.

This module exports `schedule_daily_backup(scheduler)` which registers a daily
cron job to export the ChromaDB collection to a JSON snapshot in `exports/memory/`.
"""

from __future__ import annotations

import json
import time
import tempfile
from pathlib import Path


def _backup_chromadb(chroma_dir: str = ".jarvis_chroma", export_dir: str = "exports/memory") -> str:
    """Export all ChromaDB documents to a JSON snapshot.

    Returns the path of the written snapshot file.
    """
    try:
        import chromadb
        import os
        
        host = os.getenv("CHROMA_HOST")
        port = os.getenv("CHROMA_PORT")
        if host and port:
            client = chromadb.HttpClient(host=host, port=port)
        else:
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
        payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(out_dir),
            delete=False,
            suffix=".tmp",
        ) as tmp:
            tmp.write(payload)
            tmp.flush()
            tmp_path = Path(tmp.name)
        tmp_path.replace(out_path)

        # Keep only the last 7 snapshots including the newly written file.
        existing = sorted(out_dir.glob("memory_backup_*.json"))
        for old in existing[:-7]:
            old.unlink(missing_ok=True)

        return str(out_path)
    except Exception as exc:
        return f"backup_failed: {exc}"


def schedule_daily_backup(
    scheduler,
    chroma_dir: str = ".jarvis_chroma",
    docs_dir: str = ".jarvis_docs",
) -> None:
    """Register daily backup jobs for both memory and document Chroma stores."""
    def _run_memory():
        path = _backup_chromadb(chroma_dir=chroma_dir, export_dir="exports/memory")
        print(f"[memory_backup] Snapshot written: {path}")

    def _run_docs():
        path = _backup_chromadb(chroma_dir=docs_dir, export_dir="exports/docs")
        print(f"[docs_backup] Snapshot written: {path}")

    try:
        scheduler.add_from_text(_run_memory, "every day at 2:00 am", job_id="nova_memory_backup")
        scheduler.add_from_text(_run_docs, "every day at 2:15 am", job_id="nova_docs_backup")
    except Exception:
        # Non-fatal — best-effort
        pass


def restore_chromadb(snapshot_path: str, chroma_dir: str = ".jarvis_chroma") -> str:
    """Restore a ChromaDB snapshot produced by `_backup_chromadb`.

    Returns a status string: "ok:<collection_count>" or "restore_failed:<reason>".
    """
    try:
        import chromadb
        data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        collections = data.get("collections", {})
        if not isinstance(collections, dict):
            return "restore_failed:invalid_snapshot_format"

        import os
        host = os.getenv("CHROMA_HOST")
        port = os.getenv("CHROMA_PORT")
        if host and port:
            client = chromadb.HttpClient(host=host, port=port)
        else:
            client = chromadb.PersistentClient(path=chroma_dir)

        restored = 0
        for name, payload in collections.items():
            if not isinstance(payload, dict):
                continue
            ids = payload.get("ids") or []
            docs = payload.get("documents") or []
            metas = payload.get("metadatas") or []
            if not ids or not docs:
                continue
            collection = client.get_or_create_collection(name)
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            restored += 1
        return f"ok:{restored}"
    except Exception as exc:
        return f"restore_failed:{exc}"
