from __future__ import annotations

from interfaces.telegram_bot import format_status_message, telegram_photo_from_png


def test_format_status_message_renders_table_like_summary():
    text = format_status_message(
        """
        {
          "session": "jarvis_work",
          "session_id": "sess-1",
          "provider_last": "cloud • key_1",
          "memory_mode": "online",
          "emotion": "focused",
          "active_cloud_keys": 2,
          "muted": false,
          "tailscale_ip": "100.70.1.2",
          "health_summary": {"ok": 3, "down": 1, "restarting": 0, "restart_failed": 0},
          "usage_today": "input=12 output=34 total=46"
        }
        """
    )
    assert "NOVA Status" in text
    assert "Session            | jarvis_work" in text
    assert "Health             | ok=3 down=1" in text
    assert "Usage Today" in text


def test_telegram_photo_from_png_creates_named_buffer():
    buffer = telegram_photo_from_png(b"fake-png", filename="screen.png")
    assert buffer.name == "screen.png"
    assert buffer.read() == b"fake-png"
