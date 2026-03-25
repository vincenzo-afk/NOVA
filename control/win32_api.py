"""Cross-platform-safe subset of system control utilities."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable


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


def launch_process(command: list[str] | str) -> int:
    if isinstance(command, str):
        proc = subprocess.Popen(command, shell=True)
    else:
        proc = subprocess.Popen(command)
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
