"""Dynamic GUI theme selection based on time/task/emotion."""

from __future__ import annotations

from dataclasses import dataclass


THEMES: dict[str, str] = {
    "default": """
        QWidget { background: #f4efe8; color: #1f2933; }
        QTextEdit, QLineEdit { background: #fffaf2; color: #1f2933; border: 1px solid #d1c7b7; }
        QPushButton { background: #d46a4d; color: #fff9f2; border: none; padding: 6px 10px; }
        QPushButton:hover { background: #b9563e; }
    """,
    "focus": """
        QWidget { background: #eef4f0; color: #102a1f; }
        QTextEdit, QLineEdit { background: #f9fffb; color: #102a1f; border: 1px solid #9fb9ab; }
        QPushButton { background: #2d6a4f; color: #f7fff9; border: none; padding: 6px 10px; }
        QPushButton:hover { background: #245740; }
    """,
    "coding": """
        QWidget { background: #f2f7ff; color: #10243f; }
        QTextEdit, QLineEdit { background: #ffffff; color: #10243f; border: 1px solid #9db4d6; }
        QPushButton { background: #1f4ea3; color: #f4f8ff; border: none; padding: 6px 10px; }
        QPushButton:hover { background: #1a4189; }
    """,
    "reading": """
        QWidget { background: #f9f4e8; color: #322615; }
        QTextEdit, QLineEdit { background: #fffaf0; color: #322615; border: 1px solid #d7c7a6; }
        QPushButton { background: #a46a2a; color: #fff9ed; border: none; padding: 6px 10px; }
        QPushButton:hover { background: #8e5b24; }
    """,
    "evening": """
        QWidget { background: #1f2a36; color: #e6edf5; }
        QTextEdit, QLineEdit { background: #2b3a4a; color: #f3f8ff; border: 1px solid #4d647d; }
        QPushButton { background: #3f7ab5; color: #f5fbff; border: none; padding: 6px 10px; }
        QPushButton:hover { background: #35689b; }
    """,
    "urgent": """
        QWidget { background: #2b1e1e; color: #fff1ef; }
        QTextEdit, QLineEdit { background: #3a2626; color: #fff7f5; border: 1px solid #b57878; }
        QPushButton { background: #b33f3f; color: #fff7f7; border: none; padding: 6px 10px; }
        QPushButton:hover { background: #9c3535; }
    """,
}


@dataclass
class ThemeDecision:
    name: str
    stylesheet: str


def choose_theme(hour: int, topic: str = "", emotion: str = "neutral", locked_theme: str = "") -> ThemeDecision:
    locked = (locked_theme or "").strip().lower()
    if locked and locked in THEMES:
        return ThemeDecision(name=locked, stylesheet=THEMES[locked])

    topic_l = (topic or "").strip().lower()
    emotion_l = (emotion or "").strip().lower()
    if emotion_l == "urgent":
        name = "urgent"
    elif 20 <= int(hour) or int(hour) < 8:
        name = "evening"
    elif "code" in topic_l or "dev" in topic_l:
        name = "coding"
    elif any(t in topic_l for t in ("read", "doc", "article", "paper")):
        name = "reading"
    elif any(e in emotion_l for e in ("focused", "cautious")):
        name = "focus"
    else:
        name = "default"
    return ThemeDecision(name=name, stylesheet=THEMES[name])
