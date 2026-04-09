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


def test_detect_backend_prefers_xdotool_on_linux_x11(monkeypatch):
    fake_pyautogui = types.SimpleNamespace(
        PAUSE=0.0,
        FAILSAFE=False,
        click=lambda x, y: None,
        write=lambda text: None,
        hotkey=lambda *keys: None,
        scroll=lambda clicks: None,
        moveTo=lambda x, y: None,
        dragTo=lambda x, y, duration=0.25: None,
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/xdotool" if cmd == "xdotool" else None)

    mouse_keyboard = importlib.import_module("control.mouse_keyboard")
    mouse_keyboard = importlib.reload(mouse_keyboard)
    assert mouse_keyboard._detect_backend() == "xdotool"


def test_pynput_backend_builds_when_available(monkeypatch):
    class _MouseController:
        def __init__(self):
            self.position = (0, 0)

        def click(self, _button, _count):
            return None

        def scroll(self, _x, _y):
            return None

        def press(self, _button):
            return None

        def release(self, _button):
            return None

    class _KeyboardController:
        def type(self, _text):
            return None

        def press(self, _k):
            return None

        def release(self, _k):
            return None

    fake_mouse_mod = types.SimpleNamespace(Button=types.SimpleNamespace(left=1), Controller=_MouseController)
    fake_key_mod = types.SimpleNamespace(
        Controller=_KeyboardController,
        Key=types.SimpleNamespace(ctrl="ctrl", shift="shift", alt="alt", cmd="cmd"),
    )
    fake_root = types.SimpleNamespace(mouse=fake_mouse_mod, keyboard=fake_key_mod)

    monkeypatch.setitem(sys.modules, "pynput", fake_root)
    monkeypatch.setitem(sys.modules, "pynput.mouse", fake_mouse_mod)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", fake_key_mod)
    fake_pyautogui = types.SimpleNamespace(
        PAUSE=0.0,
        FAILSAFE=False,
        click=lambda x, y: None,
        write=lambda text: None,
        hotkey=lambda *keys: None,
        scroll=lambda clicks: None,
        moveTo=lambda x, y: None,
        dragTo=lambda x, y, duration=0.25: None,
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    mouse_keyboard = importlib.import_module("control.mouse_keyboard")
    mouse_keyboard = importlib.reload(mouse_keyboard)
    controller = mouse_keyboard.MouseKeyboard()
    controller.click(10, 20)
