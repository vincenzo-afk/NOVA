from __future__ import annotations

import importlib
import sys
import types


def test_mouse_keyboard_finds_and_clicks_element(monkeypatch):
    calls: list[tuple[int, int]] = []
    fake_pyautogui = types.SimpleNamespace(
        PAUSE=0.0,
        FAILSAFE=False,
        click=lambda x, y: calls.append((x, y)),
        write=lambda text: None,
        hotkey=lambda *keys: None,
        scroll=lambda clicks: None,
        moveTo=lambda x, y: None,
        dragTo=lambda x, y, duration=0.25: None,
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)

    mouse_keyboard = importlib.import_module("control.mouse_keyboard")
    mouse_keyboard = importlib.reload(mouse_keyboard)

    controller = mouse_keyboard.MouseKeyboard()
    elements = [
        {"name": "Cancel", "bbox": {"x": 10, "y": 20, "width": 50, "height": 20}},
        {"text": "Submit form", "bbox": {"x": 100, "y": 40, "w": 80, "h": 30}},
    ]

    found = controller.find_element("submit", elements)
    clicked = controller.click_element("submit", elements)

    assert found == elements[1]
    assert clicked is True
    assert calls == [(140, 55)]


def test_mouse_click_element_result_reports_match(monkeypatch):
    calls: list[tuple[int, int]] = []
    fake_pyautogui = types.SimpleNamespace(
        PAUSE=0.0,
        FAILSAFE=False,
        click=lambda x, y: calls.append((x, y)),
        write=lambda text: None,
        hotkey=lambda *keys: None,
        scroll=lambda clicks: None,
        moveTo=lambda x, y: None,
        dragTo=lambda x, y, duration=0.25: None,
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)

    mouse_keyboard = importlib.import_module("control.mouse_keyboard")
    mouse_keyboard = importlib.reload(mouse_keyboard)

    controller = mouse_keyboard.MouseKeyboard()
    result = controller.click_element_result(
        "submit",
        [
            {"text": "Submit report", "bbox": {"x": 12, "y": 34, "width": 70, "height": 24}},
        ],
    )

    assert result["clicked"] is True
    assert result["matched_element"] == "Submit report"
    assert result["bbox"]["x"] == 12
    assert calls == [(47, 46)]
