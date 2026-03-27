"""Cross-platform-safe subset of system control utilities."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable

from control import os_layer


def read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_file(path: str, content: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target)


def move_file(src: str, dst: str) -> str:
    shutil.move(src, dst)
    return dst


def delete_file(path: str) -> bool:
    p = Path(path)
    if p.is_file():
        p.unlink()
        return True
    if p.is_dir():
        shutil.rmtree(p)
        return True
    return False


def list_processes() -> list[str]:
    if sys.platform.startswith("win"):
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", "Get-Process | Select-Object -ExpandProperty ProcessName"],
            text=True,
        )
    else:
        out = subprocess.check_output(["ps", "-A", "-o", "comm="], text=True)
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def launch_process(command: str) -> int:
    """Launch a process by command string. Returns PID.
    
    Fix 1.3: Removed shell=True to prevent shell injection. Uses shlex.split() for safe parsing.
    """
    import shlex
    args = shlex.split(command)
    proc = subprocess.Popen(args)
    return int(proc.pid)


def kill_process(name_or_pid: str | int) -> bool:
    try:
        if isinstance(name_or_pid, int) or str(name_or_pid).isdigit():
            pid = int(name_or_pid)
            if sys.platform.startswith("win"):
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True)
            else:
                subprocess.run(["kill", "-9", str(pid)], check=True)
            return True

        name = str(name_or_pid)
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/IM", f"{name}.exe", "/F"], check=True)
        else:
            subprocess.run(["pkill", "-f", name], check=True)
        return True
    except Exception:
        return False


def search_files(root: str, name_pattern: str = "*", content_query: str | None = None) -> list[str]:
    base = Path(root)
    if not base.exists():
        return []

    matches: list[str] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if not fnmatch(path.name, name_pattern):
            continue
        if content_query:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if content_query.lower() not in text.lower():
                continue
        matches.append(str(path))
    return matches


def copy_file(src: str, dst: str) -> str:
    target = Path(dst)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(target)


def get_clipboard() -> str:
    try:
        if sys.platform.startswith("darwin"):
            return subprocess.check_output(["pbpaste"], text=True).strip()
        if sys.platform.startswith("linux"):
            return subprocess.check_output(["xclip", "-o", "-selection", "clipboard"], text=True).strip()
        if sys.platform.startswith("win"):
            return subprocess.check_output(["powershell", "Get-Clipboard"], text=True).strip()
    except Exception:
        return ""
    return ""


def set_clipboard(text: str) -> bool:
    try:
        if sys.platform.startswith("darwin"):
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
            proc.communicate(text)
            return proc.returncode == 0
        if sys.platform.startswith("linux"):
            proc = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE, text=True)
            proc.communicate(text)
            return proc.returncode == 0
        if sys.platform.startswith("win"):
            subprocess.run(["powershell", "-Command", f"Set-Clipboard -Value @'\n{text}\n'@"], check=True)
            return True
    except Exception:
        return False
    return False


def disk_info(paths: Iterable[str] | None = None) -> list[dict]:
    targets = list(paths or ["/"])
    info = []
    for item in targets:
        try:
            usage = shutil.disk_usage(item)
            info.append(
                {
                    "path": item,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                }
            )
        except Exception:
            continue
    return info


def list_windows() -> list[str]:
    if not sys.platform.startswith("win"):
        return []
    try:
        import win32gui

        titles: list[str] = []

        def _handler(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    titles.append(title)

        win32gui.EnumWindows(_handler, None)
        return titles
    except Exception:
        return []


def _find_window_handles(title_substring: str) -> list[int]:
    if not sys.platform.startswith("win"):
        return []
    try:
        import win32gui

        matches: list[int] = []
        needle = title_substring.lower()

        def _handler(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and needle in title.lower():
                    matches.append(hwnd)

        win32gui.EnumWindows(_handler, None)
        return matches
    except Exception:
        return []


def focus_window(title_substring: str) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import win32gui

        handles = _find_window_handles(title_substring)
        if not handles:
            return False
        win32gui.SetForegroundWindow(handles[0])
        return True
    except Exception:
        return False


def close_window(title_substring: str) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import win32con
        import win32gui

        handles = _find_window_handles(title_substring)
        if not handles:
            return False
        for hwnd in handles:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return True
    except Exception:
        return False


def resize_window(title_substring: str, width: int, height: int) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import win32gui

        handles = _find_window_handles(title_substring)
        if not handles:
            return False
        hwnd = handles[0]
        left, top, _, _ = win32gui.GetWindowRect(hwnd)
        win32gui.MoveWindow(hwnd, left, top, int(width), int(height), True)
        return True
    except Exception:
        return False


def registry_read(path: str, name: str) -> str | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg

        root, subkey = _parse_registry_path(path)
        with winreg.OpenKey(root, subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
        return str(value)
    except Exception:
        return None


def registry_write(path: str, name: str, value: str, value_type: str = "REG_SZ") -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg

        root, subkey = _parse_registry_path(path)
        with winreg.CreateKey(root, subkey) as key:
            reg_type = _registry_type(value_type)
            payload: object = value
            if reg_type in {winreg.REG_DWORD, winreg.REG_QWORD}:
                try:
                    payload = int(value)
                except Exception:
                    payload = 0
            winreg.SetValueEx(key, name, 0, reg_type, payload)
        return True
    except Exception:
        return False


def _parse_registry_path(path: str):
    key = path.strip().replace("/", "\\")
    parts = key.split("\\", 1)
    root_name = parts[0].upper()
    subkey = parts[1] if len(parts) > 1 else ""
    return _registry_root(root_name), subkey


def _registry_root(root_name: str):
    import winreg

    mapping = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
        "HKCR": winreg.HKEY_CLASSES_ROOT,
        "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        "HKU": winreg.HKEY_USERS,
        "HKEY_USERS": winreg.HKEY_USERS,
    }
    return mapping.get(root_name, winreg.HKEY_CURRENT_USER)


def _registry_type(type_name: str):
    import winreg

    lookup = {
        "REG_SZ": winreg.REG_SZ,
        "REG_DWORD": winreg.REG_DWORD,
        "REG_QWORD": winreg.REG_QWORD,
        "REG_BINARY": winreg.REG_BINARY,
    }
    return lookup.get(type_name.upper(), winreg.REG_SZ)


def send_notification(title: str, message: str) -> None:
    os_layer.send_notification(title, message)
