from __future__ import annotations

import json
import types
import pathlib
import sys

from core.memory import backup as backup_mod


class _FakeCollection:
    name = "memory"

    @staticmethod
    def get(include=None):
        _ = include
        return {
            "ids": ["1"],
            "documents": ["hello"],
            "metadatas": [{"session_id": "s1"}],
            "embeddings": [[0.1, 0.2, 0.3]],
        }


class _FakeClient:
    def __init__(self, path: str):
        self.path = path

    @staticmethod
    def list_collections():
        return [_FakeCollection()]


def test_backup_chromadb_writes_snapshot(monkeypatch, tmp_path):
    fake_module = types.SimpleNamespace(PersistentClient=lambda path: _FakeClient(path))
    monkeypatch.setitem(sys.modules, "chromadb", fake_module)

    out = backup_mod._backup_chromadb(chroma_dir=str(tmp_path / "chroma"), export_dir=str(tmp_path / "exports"))
    content = json.loads((tmp_path / "exports" / pathlib.Path(out).name).read_text(encoding="utf-8"))
    assert "collections" in content
    assert "memory" in content["collections"]
    assert content["collections"]["memory"]["embeddings"] == [[0.1, 0.2, 0.3]]


def test_backup_chromadb_retains_last_7(monkeypatch, tmp_path):
    fake_module = types.SimpleNamespace(PersistentClient=lambda path: _FakeClient(path))
    monkeypatch.setitem(sys.modules, "chromadb", fake_module)
    out_dir = tmp_path / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 10):
        (out_dir / f"memory_backup_{i}.json").write_text("{}", encoding="utf-8")

    backup_mod._backup_chromadb(chroma_dir=str(tmp_path / "chroma"), export_dir=str(out_dir))
    files = sorted(out_dir.glob("memory_backup_*.json"))
    assert len(files) <= 7


def test_restore_chromadb_restores_embeddings(monkeypatch, tmp_path):
    upserts = []

    class _RestoreCollection:
        def upsert(self, **kwargs):
            upserts.append(kwargs)

    class _RestoreClient:
        def __init__(self, path: str):
            self.path = path

        @staticmethod
        def get_or_create_collection(name):
            _ = name
            return _RestoreCollection()

    fake_module = types.SimpleNamespace(PersistentClient=lambda path: _RestoreClient(path))
    monkeypatch.setitem(sys.modules, "chromadb", fake_module)

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "collections": {
                    "memory": {
                        "ids": ["1"],
                        "documents": ["hello"],
                        "metadatas": [{"session_id": "s1"}],
                        "embeddings": [[0.1, 0.2, 0.3]],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = backup_mod.restore_chromadb(str(snapshot_path), chroma_dir=str(tmp_path / "chroma"))
    assert result == "ok:1"
    assert len(upserts) == 1
    assert upserts[0]["embeddings"] == [[0.1, 0.2, 0.3]]
