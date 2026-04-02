"""File System Event Watcher — Proactive Intelligence Tier 1.

Watches directories for file changes and automatically re-ingests docs
into DocumentStore. Also monitors .git/COMMIT_EDITMSG to auto-store
commit messages as memories.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

_MAX_WATCHED_PATHS = 50
_DEBOUNCE_SECONDS = 30.0   # min time between re-ingests of the same file
_MAX_FILE_LINES = 500       # only auto-doc files under this threshold


class _DebounceMap:
    """Thread-safe per-path debounce timer."""

    def __init__(self, cooldown: float = _DEBOUNCE_SECONDS):
        self._cooldown = cooldown
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def ok(self, path: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(path, 0.0)
            if now - last >= self._cooldown:
                self._last[path] = now
                return True
        return False


class NOVAFSWatcher:
    """Watchdog-based file system watcher for NOVA's DocumentStore.

    Usage (from NOVAApp.__init__):
        self._fs_watcher = NOVAFSWatcher(
            watched_paths=list(self.docs._doc_meta.keys()),
            on_file_changed=self._on_doc_file_changed,
            on_git_commit=self._on_git_commit,
        )
        self._fs_watcher.start()
    """

    def __init__(
        self,
        watched_paths: list[str],
        on_file_changed: Callable[[str], None] | None = None,
        on_git_commit: Callable[[str], None] | None = None,
        cwd: str | None = None,
    ):
        self._on_file_changed = on_file_changed
        self._on_git_commit = on_git_commit
        self._cwd = Path(cwd) if cwd else Path.cwd()
        self._debounce = _DebounceMap()
        self._observer: Any | None = None
        self._started = False

        # Collect unique parent directories (capped)
        dirs: set[str] = set()
        for raw in watched_paths[:_MAX_WATCHED_PATHS]:
            p = Path(raw).expanduser().resolve()
            dirs.add(str(p.parent))

        # Always watch current working dir for git commits
        dirs.add(str(self._cwd))
        self._watched_dirs = list(dirs)

        # Track which files belong to doc store
        self._doc_files: set[str] = {
            str(Path(p).expanduser().resolve())
            for p in watched_paths[:_MAX_WATCHED_PATHS]
        }
        self._git_commit_file = str(self._cwd / ".git" / "COMMIT_EDITMSG")

    def start(self) -> None:
        if self._started:
            return
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler, FileModifiedEvent

            watcher = self  # closure

            class _Handler(FileSystemEventHandler):
                def on_modified(self, event):
                    if event.is_directory:
                        return
                    src = str(Path(event.src_path).expanduser().resolve())
                    if src == watcher._git_commit_file:
                        watcher._on_commit_file_changed(src)
                    elif src in watcher._doc_files:
                        if watcher._debounce.ok(src) and watcher._on_file_changed:
                            try:
                                watcher._on_file_changed(src)
                            except Exception as exc:
                                log.warning("[fs_watcher] re-ingest failed for %s: %s", src, exc)

                def on_created(self, event):
                    if event.is_directory:
                        return
                    src = str(Path(event.src_path).expanduser().resolve())
                    # New code/doc file — add to doc store if under line limit
                    if src.endswith((".py", ".md", ".txt", ".rst")) and watcher._debounce.ok(src):
                        if watcher._on_file_changed:
                            try:
                                watcher._on_file_changed(src)
                            except Exception as exc:
                                log.warning("[fs_watcher] new-file ingest failed for %s: %s", src, exc)

            observer = Observer()
            handler = _Handler()
            for d in self._watched_dirs:
                if Path(d).is_dir():
                    observer.schedule(handler, d, recursive=False)

            observer.start()
            self._observer = observer
            self._started = True
            log.info("[fs_watcher] started, watching %d dirs", len(self._watched_dirs))
        except ImportError:
            log.warning("[fs_watcher] 'watchdog' not installed — file watching disabled. Run: pip install watchdog")
        except Exception as exc:
            log.warning("[fs_watcher] failed to start: %s", exc)

    def stop(self) -> None:
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=3)
            except Exception:
                pass
        self._started = False

    def add_path(self, filepath: str) -> None:
        """Dynamically add a new file to the watch list (after startup)."""
        resolved = str(Path(filepath).expanduser().resolve())
        self._doc_files.add(resolved)

    # ── internal ──────────────────────────────────────────────────────────────

    def _on_commit_file_changed(self, path: str) -> None:
        if not self._debounce.ok(path):
            return
        try:
            msg = Path(path).read_text(encoding="utf-8", errors="ignore").strip()
            if msg and not msg.startswith("#"):
                if self._on_git_commit:
                    self._on_git_commit(msg)
        except Exception:
            pass
