"""Session lifecycle and history isolation."""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid


@dataclass
class SessionState:
    name: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    history: list[dict] = field(default_factory=list)


class SessionManager:
    def __init__(self, default_name: str = "jarvis_personal"):
        self._sessions: dict[str, SessionState] = {}
        self._current = self._get_or_create(default_name)

    @property
    def current(self) -> SessionState:
        return self._current

    def switch(self, name: str) -> SessionState:
        self._current = self._get_or_create(name)
        return self._current

    def add_turn(self, role: str, content: str) -> None:
        self._current.history.append({"role": role, "content": content})

    def reset_context(self) -> None:
        self._current.history.clear()

    def _get_or_create(self, name: str) -> SessionState:
        if name not in self._sessions:
            self._sessions[name] = SessionState(name=name)
        return self._sessions[name]
