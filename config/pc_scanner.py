"""PC profile scanner — Feature 4.

Scans the host machine and writes config/pc_profile.json.
Every downstream feature (capability map, input backend, screenshot backend,
window manager, installer) reads from this single source of truth.

Run directly to force a rescan:
    python -m config.pc_scanner
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PROFILE_PATH = Path("config/pc_profile.json")
_SCHEMA_VERSION = 2

_CLI_TOOLS = [
    # Python ecosystem
    "python3", "python", "pip", "pip3", "uv",
    # JS
    "node", "npm", "npx",
    # VCS / containers
    "git", "docker", "docker-compose",
    # Android / media
    "adb", "ffmpeg", "ffprobe",
    # Network
    "curl", "wget",
    # Linux input tools
    "xdotool", "ydotool", "wmctrl", "xclip", "wl-copy", "wl-paste",
    # macOS
    "osascript", "afplay",
    # Windows
    "powershell",
    # Screenshot (Linux)
    "scrot", "gnome-screenshot", "import",
    # TTS offline
    "espeak", "espeak-ng", "flite",
    # Audio
    "mpg123", "ffplay",
    # Tailscale
    "tailscale",
]

_PYTHON_PACKAGES = [
    "pyautogui",
    "pynput",
    "mss",
    "PIL",         # Pillow
    "playwright",
    "requests",
    "openai",
    "pydantic",
    "torch",
    "cv2",         # opencv-python
    "psutil",
    "Quartz",      # macOS
    "AppKit",      # macOS
]


# ── helpers ────────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: float = 3.0) -> str:
    """Run a command, return stdout (first line) or '' on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


# ── display / input ─────────────────────────────────────────────────────────

def detect_display_server() -> str:
    """Return 'wayland' | 'x11' | 'quartz' | 'win32' | 'headless'."""
    system = platform.system()
    if system == "Windows":
        return "win32"
    if system == "Darwin":
        return "quartz"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "headless"


def detect_input_backend(display: str | None = None) -> str:
    """Return the best available input backend token."""
    display = display or detect_display_server()
    if display == "win32":
        return "pyautogui"
    if display == "quartz":
        try:
            import Quartz  # noqa: F401
            return "quartz"
        except ImportError:
            pass
        return "pyautogui"
    if display == "wayland":
        if shutil.which("ydotool"):
            return "ydotool"
        # ydotool missing — try xdotool via XWayland
        if shutil.which("xdotool"):
            return "xdotool"
        try:
            import pynput  # noqa: F401
            return "pynput"
        except ImportError:
            pass
        return "pyautogui"
    # x11 / headless
    if shutil.which("xdotool"):
        return "xdotool"
    return "pyautogui"


def detect_screenshot_backend() -> str:
    """Return the best available screenshot backend token."""
    try:
        import mss  # noqa: F401
        return "mss"
    except ImportError:
        pass
    try:
        from PIL import ImageGrab  # noqa: F401
        return "pil"
    except ImportError:
        pass
    display = detect_display_server()
    if display == "x11" and shutil.which("scrot"):
        return "scrot"
    return "none"


# ── hardware ─────────────────────────────────────────────────────────────────

def _detect_gpu() -> dict[str, Any]:
    gpu: dict[str, Any] = {"available": False, "vendor": None, "name": None}
    if shutil.which("nvidia-smi"):
        out = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader,nounits"])
        if out:
            gpu.update({"available": True, "vendor": "nvidia", "name": out.split("\n")[0].strip()})
            return gpu
    if shutil.which("rocm-smi"):
        gpu.update({"available": True, "vendor": "amd"})
        return gpu
    if platform.system() == "Darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"], timeout=8.0)
        if "Chipset" in out or "GPU" in out or "Metal" in out:
            gpu.update({"available": True, "vendor": "apple"})
    return gpu


def _detect_ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        pass
    try:
        text = Path("/proc/meminfo").read_text()
        for line in text.splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / (1024 ** 2), 1)
    except Exception:
        pass
    return 0.0


def _detect_cpu() -> dict[str, Any]:
    cpu: dict[str, Any] = {
        "name": platform.processor() or platform.machine(),
        "cores_physical": None,
        "cores_logical": os.cpu_count(),
    }
    try:
        import psutil
        cpu["cores_physical"] = psutil.cpu_count(logical=False)
        cpu["cores_logical"] = psutil.cpu_count(logical=True)
    except Exception:
        pass
    return cpu


# ── installed tools ──────────────────────────────────────────────────────────

def _probe_cli_tools() -> dict[str, str | None]:
    tools: dict[str, str | None] = {}
    for tool in _CLI_TOOLS:
        if not shutil.which(tool):
            tools[tool] = None
            continue
        ver = (
            _run([tool, "--version"])
            or _run([tool, "version"])
            or "found"
        )
        tools[tool] = ver.split("\n")[0][:100]
    return tools


def _probe_python_packages() -> dict[str, bool]:
    result: dict[str, bool] = {}
    for pkg in _PYTHON_PACKAGES:
        try:
            __import__(pkg)
            result[pkg] = True
        except ImportError:
            result[pkg] = False
    return result


# ── main scan ────────────────────────────────────────────────────────────────

def scan(force: bool = False, save: bool = True) -> dict[str, Any]:
    """Run a complete PC scan.  Returns profile dict and saves to PROFILE_PATH."""
    if not force and PROFILE_PATH.exists():
        try:
            existing = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            if int(existing.get("schema_version", 0)) >= _SCHEMA_VERSION:
                return existing
        except Exception:
            pass

    display = detect_display_server()
    profile: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "node": platform.node(),
        },
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "display_server": display,
        "input_backend": detect_input_backend(display),
        "screenshot_backend": detect_screenshot_backend(),
        "cpu": _detect_cpu(),
        "ram_gb": _detect_ram_gb(),
        "gpu": _detect_gpu(),
        "cli_tools": _probe_cli_tools(),
        "python_packages": _probe_python_packages(),
    }

    if save:
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_PATH.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return profile


def load() -> dict[str, Any]:
    """Load profile from disk, scanning first if it doesn't exist yet."""
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return scan()


if __name__ == "__main__":
    import pprint
    profile = scan(force=True)
    pprint.pprint(profile)
    print(f"\nProfile saved to {PROFILE_PATH}")
