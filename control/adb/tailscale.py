"""Tailscale helper utilities."""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Callable


def is_tailscale_installed() -> bool:
    return shutil.which("tailscale") is not None


def install_tailscale(
    *,
    system_name: str | None = None,
    run_fn: Callable[..., object] = subprocess.run,
    which_fn: Callable[[str], str | None] = shutil.which,
) -> bool:
    if is_tailscale_installed():
        return True

    system_name = (system_name or platform.system()).strip()
    commands: list[list[str]]
    if system_name == "Darwin":
        commands = [
            ["brew", "install", "--cask", "tailscale"],
            ["brew", "install", "tailscale"],
        ]
    elif system_name == "Windows":
        commands = [
            ["winget", "install", "--id", "Tailscale.Tailscale", "-e", "--silent"],
            ["choco", "install", "tailscale", "-y"],
        ]
    else:
        commands = [
            ["sudo", "apt-get", "install", "-y", "tailscale"],
            ["sudo", "dnf", "install", "-y", "tailscale"],
            ["sudo", "yum", "install", "-y", "tailscale"],
            ["sudo", "pacman", "-S", "--noconfirm", "tailscale"],
        ]

    for cmd in commands:
        executable = cmd[0]
        if which_fn(executable) is None:
            continue
        try:
            run_fn(cmd, check=True)
            return True
        except Exception:
            continue
    return False


def ensure_tailscale_available() -> bool:
    return is_tailscale_installed() or install_tailscale()


def reconnect_tailscale(run_fn: Callable[..., object] = subprocess.run) -> bool:
    if not ensure_tailscale_available():
        return False
    try:
        run_fn(["tailscale", "up"], check=True)
        return True
    except Exception:
        return False


def tailscale_ip_v4() -> str:
    if not is_tailscale_installed():
        return ""
    try:
        output = subprocess.check_output(["tailscale", "ip", "-4"], text=True).strip().splitlines()
        return output[0].strip() if output else ""
    except Exception:
        return ""


def tailscale_status() -> str:
    if not is_tailscale_installed():
        return "not_installed"
    try:
        out = subprocess.check_output(["tailscale", "status"], text=True, timeout=8).strip()
        return out or "unknown"
    except Exception:
        return "down"


def ensure_tailscale_connected() -> bool:
    status = tailscale_status()
    if status == "not_installed":
        if not ensure_tailscale_available():
            return False
        status = tailscale_status()
    if status == "down":
        if not reconnect_tailscale():
            return False
        status = tailscale_status()
    return status not in {"down", "not_installed"}
