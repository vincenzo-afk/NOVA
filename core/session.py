"""Session lifecycle and history isolation."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import uuid


@dataclass
class SessionState:
    name: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    history: list[dict] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class SessionManager:
    _SCHEMA_VERSION = 1

    def __init__(self, default_name: str = "jarvis_personal", max_history_turns: int = 500):
        self._sessions: dict[str, SessionState] = {}
        self._max_history_turns = max(50, int(max_history_turns))
        self._current = self._get_or_create(default_name)

    @property
    def current(self) -> SessionState:
        return self._current

    def switch(self, name: str) -> SessionState:
        self._current = self._get_or_create(name)
        return self._current

    def reset_context(self) -> None:
        with self._current._lock:
            self._current.history.clear()
        self._persist_session(self._current)

    def add_turn(self, role: str, content: str) -> None:
        with self._current._lock:
            self._current.history.append({"role": role, "content": content})
            if len(self._current.history) > self._max_history_turns:
                self._current.history = self._current.history[-self._max_history_turns :]
        self._persist_session(self._current)

    def _persist_session(self, session: SessionState) -> None:
        """Serialize session history to a JSON file for crash recovery (fix 2.6)."""
        try:
            import json
            import hashlib
            from pathlib import Path
            import tempfile
            import shutil
            sessions_dir = Path(".jarvis_sessions")
            sessions_dir.mkdir(exist_ok=True)
            base_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in session.name)
            suffix = hashlib.sha256(session.name.encode("utf-8")).hexdigest()[:8]
            safe_name = f"{base_name}_{suffix}"
            path = sessions_dir / f"{safe_name}.json"
            backup_path = sessions_dir / f"{safe_name}.json.bak"
            with session._lock:
                history_snapshot = list(session.history)
                session_name = session.name
                session_id = session.session_id
            data = {"name": session_name, "session_id": session_id, "history": history_snapshot}
            data["schema_version"] = self._SCHEMA_VERSION
            payload = json.dumps(data, ensure_ascii=False, indent=2)
            if path.exists():
                try:
                    shutil.copy2(path, backup_path)
                except Exception:
                    pass
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(sessions_dir),
                delete=False,
                suffix=".tmp",
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                tmp_path = Path(tmp.name)
            try:
                tmp_dev = tmp_path.stat().st_dev
                dst_dev = sessions_dir.stat().st_dev
            except OSError:
                tmp_dev = dst_dev = None
            if tmp_dev is not None and dst_dev is not None and tmp_dev != dst_dev:
                import logging
                logging.getLogger(__name__).warning(
                    "Session persist cross-device mismatch for %s (%s -> %s).",
                    session.name,
                    tmp_dev,
                    dst_dev,
                )
                try:
                    shutil.copy2(tmp_path, path)
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    raise OSError("cross-device fallback copy failed")
            else:
                tmp_path.replace(path)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Session persist failed for %s: %s",
                getattr(session, "name", "unknown"),
                exc,
            )

    def _load_session(self, name: str) -> SessionState | None:
        """Load session history from JSON file if it exists (fix 2.6)."""
        try:
            import json
            import hashlib
            from pathlib import Path
            import logging
            sessions_dir = Path(".jarvis_sessions")
            base_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
            suffix = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
            safe_name = f"{base_name}_{suffix}"
            path = sessions_dir / f"{safe_name}.json"
            backup_path = sessions_dir / f"{safe_name}.json.bak"
            candidates = [path, backup_path]
            for candidate in candidates:
                if not candidate.exists():
                    continue
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    version = int(data.get("schema_version", 0) or 0)
                    if version <= 0:
                        # Migration from legacy format: inject default schema_version.
                        data["schema_version"] = self._SCHEMA_VERSION
                    session = SessionState(name=data["name"], session_id=data["session_id"])
                    session.history = data.get("history", [])
                    return session
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "Failed to load session file %s: %s",
                        candidate,
                        exc,
                    )
        except Exception:
            pass
        return None

    def _get_or_create(self, name: str) -> SessionState:
        if name not in self._sessions:
            # Fix 2.6: Try to load from disk first
            loaded = self._load_session(name)
            if loaded:
                self._sessions[name] = loaded
            else:
                self._sessions[name] = SessionState(name=name)
        return self._sessions[name]
