"""Cross-platform mouse/keyboard control — Feature 11.

Backend selection priority (resolved from pc_profile.json if available):
  win32   → PyAutoGUI  (Windows, most reliable)
  quartz  → Quartz CoreGraphics + AppKit (macOS native, no Accessibility issues)
  x11     → PyAutoGUI  (Linux X11, fast)
  wayland → ydotool → xdotool → pynput → PyAutoGUI fallback

The backend is transparent to callers — they always use the MouseKeyboard class.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from typing import Any

log = logging.getLogger(__name__)


# ── backend helpers ───────────────────────────────────────────────────────────

def _detect_backend() -> str:
    """Return the best available input backend token."""
    # Try to read from pc_profile.json first
    try:
        import json
        from pathlib import Path
        profile_path = Path("config/pc_profile.json")
        if profile_path.exists():
            profile = json.loads(profile_path.read_text())
            backend = str(profile.get("input_backend") or "").strip().lower()
            if backend in {"pyautogui", "quartz", "xdotool", "ydotool", "pynput"}:
                return backend
    except Exception:
        pass

    # Runtime detection fallback
    system = platform.system()
    if system == "Windows":
        return "pyautogui"
    if system == "Darwin":
        try:
            import Quartz  # noqa: F401
            return "quartz"
        except ImportError:
            return "pyautogui"
    # Linux
    if os.environ.get("WAYLAND_DISPLAY"):
        if shutil.which("ydotool"):
            return "ydotool"
        if shutil.which("xdotool"):
            return "xdotool"
        try:
            import pynput  # noqa: F401
            return "pynput"
        except ImportError:
            pass
    else:
        if shutil.which("xdotool"):
            return "xdotool"
        try:
            import pynput  # noqa: F401
            return "pynput"
        except ImportError:
            pass
    return "pyautogui"


_BACKEND = _detect_backend()
log.debug("[mouse_keyboard] backend: %s", _BACKEND)


# ── backend implementations ───────────────────────────────────────────────────

class _PyAutoGUIBackend:
    def __init__(self, pause: float = 0.05):
        import pyautogui
        pyautogui.PAUSE = pause
        pyautogui.FAILSAFE = True
        self._pag = pyautogui

    def click(self, x: int, y: int) -> None:
        self._pag.click(x, y)

    def type_text(self, text: str) -> None:
        self._pag.write(text, interval=0.01)

    def hotkey(self, *keys: str) -> None:
        self._pag.hotkey(*keys)

    def scroll(self, clicks: int) -> None:
        self._pag.scroll(clicks)

    def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.25
    ) -> None:
        self._pag.moveTo(start_x, start_y)
        self._pag.dragTo(end_x, end_y, duration=duration)


class _QuartzBackend:
    """macOS Quartz/CoreGraphics backend — no Accessibility permission needed for clicks."""

    def _post_event(self, event_type, x: int, y: int):
        import Quartz  # type: ignore[import]
        event = Quartz.CGEventCreateMouseEvent(
            None, event_type, (x, y), Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def click(self, x: int, y: int) -> None:
        try:
            import Quartz  # type: ignore[import]
            self._post_event(Quartz.kCGEventLeftMouseDown, x, y)
            self._post_event(Quartz.kCGEventLeftMouseUp, x, y)
        except Exception as exc:
            log.warning("[quartz] click failed (%s) — falling back to pyautogui", exc)
            import pyautogui
            pyautogui.click(x, y)

    def type_text(self, text: str) -> None:
        try:
            from AppKit import NSPasteboard, NSStringPboardType  # type: ignore[import]
            import Quartz  # type: ignore[import]
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(text, NSStringPboardType)
            # Cmd+V paste
            for evt_type, flags, key in [
                (Quartz.kCGEventKeyDown, Quartz.kCGEventFlagMaskCommand, 9),
                (Quartz.kCGEventKeyUp, Quartz.kCGEventFlagMaskCommand, 9),
            ]:
                e = Quartz.CGEventCreateKeyboardEvent(None, key, evt_type == Quartz.kCGEventKeyDown)
                Quartz.CGEventSetFlags(e, flags)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
        except Exception as exc:
            log.warning("[quartz] type_text failed (%s) — falling back to pyautogui", exc)
            import pyautogui
            pyautogui.write(text, interval=0.01)

    def hotkey(self, *keys: str) -> None:
        # Delegate to pyautogui for complex hotkeys
        import pyautogui
        pyautogui.hotkey(*keys)

    def scroll(self, clicks: int) -> None:
        try:
            import Quartz  # type: ignore[import]
            event = Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitLine, 1, clicks
            )
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        except Exception:
            import pyautogui
            pyautogui.scroll(clicks)

    def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.25
    ) -> None:
        import pyautogui
        pyautogui.moveTo(start_x, start_y)
        pyautogui.dragTo(end_x, end_y, duration=duration)


class _XdotoolBackend:
    """Linux X11/Wayland-via-XWayland backend using xdotool."""

    def _run(self, cmd: list[str]) -> None:
        subprocess.run(cmd, timeout=5, check=False)

    def click(self, x: int, y: int) -> None:
        self._run(["xdotool", "mousemove", str(x), str(y)])
        self._run(["xdotool", "click", "1"])

    def type_text(self, text: str) -> None:
        self._run(["xdotool", "type", "--clearmodifiers", "--", text])

    def hotkey(self, *keys: str) -> None:
        combo = "+".join(keys)
        self._run(["xdotool", "key", combo])

    def scroll(self, clicks: int) -> None:
        btn = "4" if clicks > 0 else "5"
        for _ in range(abs(clicks)):
            self._run(["xdotool", "click", btn])

    def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.25
    ) -> None:
        self._run(["xdotool", "mousemove", str(start_x), str(start_y)])
        self._run(["xdotool", "mousedown", "1"])
        self._run(["xdotool", "mousemove", str(end_x), str(end_y)])
        self._run(["xdotool", "mouseup", "1"])


class _YdotoolBackend:
    """Wayland-native backend using ydotool (requires ydotoold daemon)."""

    def _run(self, cmd: list[str]) -> None:
        subprocess.run(["ydotool"] + cmd, timeout=5, check=False)

    def click(self, x: int, y: int) -> None:
        self._run(["mousemove", "--absolute", "-x", str(x), "-y", str(y)])
        self._run(["click", "0x40001"])  # left button down+up

    def type_text(self, text: str) -> None:
        self._run(["type", "--", text])

    def hotkey(self, *keys: str) -> None:
        # ydotool key takes X keysyms
        combo = "+".join(k.capitalize() for k in keys)
        self._run(["key", combo])

    def scroll(self, clicks: int) -> None:
        for _ in range(abs(clicks)):
            btn = "0x80008" if clicks > 0 else "0x80010"
            self._run(["click", btn])

    def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.25
    ) -> None:
        self._run(["mousemove", "--absolute", "-x", str(start_x), "-y", str(start_y)])
        self._run(["click", "--", "0x40001"])
        self._run(["mousemove", "--absolute", "-x", str(end_x), "-y", str(end_y)])


class _PynputBackend:
    """Cross-platform fallback backend via pynput."""

    def __init__(self):
        from pynput.keyboard import Controller as KeyboardController, Key  # type: ignore[import]
        from pynput.mouse import Button, Controller as MouseController  # type: ignore[import]

        self._mouse = MouseController()
        self._keyboard = KeyboardController()
        self._button_left = Button.left
        self._key_mods = {
            "ctrl": Key.ctrl,
            "shift": Key.shift,
            "alt": Key.alt,
            "cmd": Key.cmd,
            "command": Key.cmd,
            "win": Key.cmd,
        }

    def click(self, x: int, y: int) -> None:
        self._mouse.position = (int(x), int(y))
        self._mouse.click(self._button_left, 1)

    def type_text(self, text: str) -> None:
        self._keyboard.type(str(text or ""))

    def hotkey(self, *keys: str) -> None:
        normalized = [str(k).strip().lower() for k in keys if str(k).strip()]
        pressed = []
        try:
            for k in normalized[:-1]:
                key_obj = self._key_mods.get(k, k)
                self._keyboard.press(key_obj)
                pressed.append(key_obj)
            if normalized:
                last = normalized[-1]
                self._keyboard.press(last)
                self._keyboard.release(last)
        finally:
            for key_obj in reversed(pressed):
                try:
                    self._keyboard.release(key_obj)
                except Exception:
                    pass

    def scroll(self, clicks: int) -> None:
        self._mouse.scroll(0, int(clicks))

    def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.25
    ) -> None:
        self._mouse.position = (int(start_x), int(start_y))
        self._mouse.press(self._button_left)
        self._mouse.position = (int(end_x), int(end_y))
        self._mouse.release(self._button_left)


def _build_backend(backend: str):
    if backend == "quartz":
        try:
            return _QuartzBackend()
        except Exception:
            log.warning("[mouse_keyboard] Quartz unavailable — falling back to pyautogui")
    if backend == "ydotool" and shutil.which("ydotool"):
        return _YdotoolBackend()
    if backend == "xdotool" and shutil.which("xdotool"):
        return _XdotoolBackend()
    if backend == "pynput":
        try:
            return _PynputBackend()
        except Exception:
            log.warning("[mouse_keyboard] pynput unavailable — falling back to pyautogui")
    return _PyAutoGUIBackend()


# ── public class ──────────────────────────────────────────────────────────────

class MouseKeyboard:
    """Unified mouse/keyboard controller — routes to the right OS backend."""

    def __init__(self, pause: float = 0.05):
        self._impl = _build_backend(_BACKEND)

    # ── mouse ─────────────────────────────────────────────────────────────────

    def click(self, x: int, y: int) -> None:
        self._impl.click(x, y)

    def scroll(self, clicks: int) -> None:
        self._impl.scroll(clicks)

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.25,
    ) -> None:
        self._impl.drag(start_x, start_y, end_x, end_y, duration)

    # ── keyboard ──────────────────────────────────────────────────────────────

    def type_text(self, text: str) -> None:
        self._impl.type_text(text)

    def hotkey(self, *keys: str) -> None:
        self._impl.hotkey(*keys)

    # ── element-based helpers (OmniParser output) ─────────────────────────────

    def find_element(
        self, name: str, elements: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        target = name.lower().strip()
        for element in elements:
            label = str(element.get("name") or element.get("text") or "").lower().strip()
            if target and target in label:
                return element
        return None

    def click_element(
        self, name: str, elements: list[dict[str, Any]]
    ) -> bool:
        element = self.find_element(name, elements)
        if not element:
            return False
        box = element.get("bbox") or element.get("box") or {}
        x = int(box.get("x", 0))
        y = int(box.get("y", 0))
        w = int(box.get("w", box.get("width", 1)))
        h = int(box.get("h", box.get("height", 1)))
        self.click(x + max(1, w) // 2, y + max(1, h) // 2)
        return True

    def click_element_result(
        self, name: str, elements: list[dict[str, Any]]
    ) -> dict[str, Any]:
        element = self.find_element(name, elements)
        if not element:
            return {"clicked": False, "name": name}
        clicked = self.click_element(name, elements)
        return {
            "clicked": bool(clicked),
            "name": name,
            "matched_element": str(element.get("name") or element.get("text") or ""),
            "bbox": element.get("bbox") or element.get("box") or {},
        }
