from __future__ import annotations

from utils.notifier import build_goal_status_message, notify_background_event, send_telegram_text


def test_build_goal_status_message_for_paused_goal():
    message = build_goal_status_message(
        goal_id="goal_123",
        goal="Ship release",
        status="paused",
        reason="Reached max_steps=20",
        next_index=20,
        total_steps=35,
    )
    assert "goal_123" in message
    assert "paused" in message
    assert "goal.resume" in message


def test_send_telegram_text_success(monkeypatch):
    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "result": {"message_id": 1}}

    def fake_post(url, json, timeout):
        assert "api.telegram.org" in url
        assert json["chat_id"] == "12345"
        assert json["text"] == "hello"
        assert timeout == 12
        return DummyResponse()

    monkeypatch.setattr("utils.notifier.requests.post", fake_post)
    result = send_telegram_text("token", "12345", "hello")
    assert result.get("ok") is True


def test_send_telegram_text_missing_config():
    result = send_telegram_text("", "", "hello")
    assert result["ok"] is False
    assert "missing_bot_token_or_chat_id" in result["error"]


def test_notify_background_event_routes_to_both_channels():
    calls: list[tuple[str, str]] = []

    def notify_telegram(text: str):
        calls.append(("telegram", text))
        return True

    def notify_tts(text: str):
        calls.append(("tts", text))
        return True

    result = notify_background_event(
        "Screen alert: error dialog found",
        muted=False,
        notify_telegram=notify_telegram,
        notify_tts=notify_tts,
    )

    assert result == {"telegram": True, "tts": True}
    assert ("telegram", "Screen alert: error dialog found") in calls
    assert ("tts", "Screen alert: error dialog found") in calls
