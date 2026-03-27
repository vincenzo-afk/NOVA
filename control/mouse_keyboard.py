"""PyAutoGUI control wrapper."""

from __future__ import annotations

from typing import Any

import pyautogui


class MouseKeyboard:
    def __init__(self, pause: float = 0.05):
        pyautogui.PAUSE = pause
        pyautogui.FAILSAFE = True

    def click(self, x: int, y: int) -> None:
        pyautogui.click(x, y)

    def find_element(self, name: str, elements: list[dict[str, Any]]) -> dict[str, Any] | None:
        target = name.lower().strip()
        for element in elements:
            label = str(element.get("name") or element.get("text") or "").lower().strip()
            if target and target in label:
                return element
        return None

    def click_element(self, name: str, elements: list[dict[str, Any]]) -> bool:
        element = self.find_element(name, elements)
        if not element:
            return False
        box = element.get("bbox") or element.get("box") or {}
        x = int(box.get("x", 0))
        y = int(box.get("y", 0))
        w = int(box.get("w", box.get("width", 1)))
        h = int(box.get("h", box.get("height", 1)))
        pyautogui.click(x + max(1, w) // 2, y + max(1, h) // 2)
        return True

    def click_element_result(self, name: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
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

    def type_text(self, text: str) -> None:
        pyautogui.write(text)

    def hotkey(self, *keys: str) -> None:
        pyautogui.hotkey(*keys)

    def scroll(self, clicks: int) -> None:
        pyautogui.scroll(clicks)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.25) -> None:
        pyautogui.moveTo(start_x, start_y)
        pyautogui.dragTo(end_x, end_y, duration=duration)
