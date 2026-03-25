"""Tailscale helper utilities."""

from __future__ import annotations

import shutil
import subprocess


def is_tailscale_installed() -> bool:
    return shutil.which("tailscale") is not None


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
