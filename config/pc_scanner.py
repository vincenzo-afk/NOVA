"""PC profile scanner — deep system inventory (schema v3).

Runs a cross-platform hardware/software/network scan and writes
`config/pc_profile.json`.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

PROFILE_PATH = Path("config/pc_profile.json")
_SCHEMA_VERSION = 3

_CLI_TOOLS = [
    "python3",
    "python",
    "pip",
    "pip3",
    "uv",
    "node",
    "npm",
    "npx",
    "git",
    "docker",
    "docker-compose",
    "adb",
    "ffmpeg",
    "ffprobe",
    "curl",
    "wget",
    "xdotool",
    "ydotool",
    "wmctrl",
    "xclip",
    "wl-copy",
    "wl-paste",
    "osascript",
    "afplay",
    "powershell",
    "scrot",
    "gnome-screenshot",
    "import",
    "espeak",
    "espeak-ng",
    "flite",
    "mpg123",
    "ffplay",
    "tailscale",
    "winget",
    "brew",
    "flatpak",
    "snap",
]

_PYTHON_PACKAGES = [
    "pyautogui",
    "pynput",
    "mss",
    "PIL",
    "playwright",
    "requests",
    "openai",
    "pydantic",
    "torch",
    "cv2",
    "psutil",
    "Quartz",
    "AppKit",
]


def _run(cmd: list[str], timeout: float = 4.0) -> str:
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


def _run_lines(cmd: list[str], timeout: float = 6.0, max_lines: int = 300) -> list[str]:
    out = _run(cmd, timeout=timeout)
    if not out:
        return []
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return lines[:max_lines]


def detect_display_server() -> str:
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
    display = display or detect_display_server()
    if display == "win32":
        return "pyautogui"
    if display == "quartz":
        try:
            import Quartz  # noqa: F401

            return "quartz"
        except ImportError:
            return "pyautogui"
    if display == "wayland":
        if shutil.which("ydotool"):
            return "ydotool"
        if shutil.which("xdotool"):
            return "xdotool"
        try:
            import pynput  # noqa: F401

            return "pynput"
        except ImportError:
            return "pyautogui"
    if shutil.which("xdotool"):
        return "xdotool"
    return "pyautogui"


def detect_screenshot_backend() -> str:
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
    if display in {"x11", "wayland"} and shutil.which("scrot"):
        return "scrot"
    return "none"


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

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        pass
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / (1024**2), 1)
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


def _probe_cli_tools() -> dict[str, str | None]:
    tools: dict[str, str | None] = {}
    for tool in _CLI_TOOLS:
        if not shutil.which(tool):
            tools[tool] = None
            continue
        ver = _run([tool, "--version"]) or _run([tool, "version"]) or "found"
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


def _windows_inventory() -> dict[str, Any]:
    apps_registry: list[str] = []
    feature_flags: dict[str, bool] = {}
    winget_packages: list[str] = []
    windows_version = {}

    if platform.system() != "Windows":
        return {
            "winget_packages": winget_packages,
            "registry_apps": apps_registry,
            "feature_flags": feature_flags,
            "windows_version": windows_version,
        }

    if shutil.which("winget"):
        winget_raw = _run_lines(["winget", "list"], timeout=12.0, max_lines=500)
        winget_packages = winget_raw[2:] if len(winget_raw) > 2 else winget_raw

    if shutil.which("powershell"):
        reg_cmd = (
            "Get-ItemProperty "
            "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,"
            "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* "
            "| Select-Object DisplayName,DisplayVersion "
            "| Where-Object { $_.DisplayName } "
            "| ForEach-Object { \"$($_.DisplayName) [$($_.DisplayVersion)]\" }"
        )
        apps_registry = _run_lines(
            ["powershell", "-NoProfile", "-Command", reg_cmd],
            timeout=20.0,
            max_lines=700,
        )
        feat_cmd = (
            "Get-WindowsOptionalFeature -Online "
            "| Where-Object { $_.State -eq 'Enabled' } "
            "| Select-Object -ExpandProperty FeatureName"
        )
        features = _run_lines(
            ["powershell", "-NoProfile", "-Command", feat_cmd],
            timeout=20.0,
            max_lines=300,
        )
        feature_flags = {name: True for name in features}
        ver_cmd = (
            "Get-ComputerInfo | Select-Object WindowsVersion,WindowsBuildLabEx,OsName | ConvertTo-Json -Compress"
        )
        raw_ver = _run(["powershell", "-NoProfile", "-Command", ver_cmd], timeout=10.0)
        try:
            windows_version = json.loads(raw_ver) if raw_ver else {}
        except Exception:
            windows_version = {}

    return {
        "winget_packages": winget_packages,
        "registry_apps": apps_registry,
        "feature_flags": feature_flags,
        "windows_version": windows_version,
    }


def _mac_inventory() -> dict[str, Any]:
    apps: list[str] = []
    brew_formula: list[str] = []
    xcode_tools = {"xcode_select": False, "xcodebuild": False}

    if platform.system() != "Darwin":
        return {
            "applications": apps,
            "brew_formula": brew_formula,
            "xcode_tools": xcode_tools,
        }

    apps_raw = _run_lines(["system_profiler", "SPApplicationsDataType"], timeout=20.0, max_lines=1000)
    apps = apps_raw
    if shutil.which("brew"):
        brew_formula = _run_lines(["brew", "list", "--formula"], timeout=10.0, max_lines=500)
    xcode_tools["xcode_select"] = bool(_run(["xcode-select", "-p"], timeout=2.0))
    xcode_tools["xcodebuild"] = bool(shutil.which("xcodebuild"))

    return {
        "applications": apps,
        "brew_formula": brew_formula,
        "xcode_tools": xcode_tools,
    }


def _linux_inventory() -> dict[str, Any]:
    if platform.system() != "Linux":
        return {
            "dpkg": [],
            "rpm": [],
            "pacman": [],
            "snap": [],
            "flatpak": [],
        }

    packages = {
        "dpkg": _run_lines(["dpkg", "-l"], timeout=12.0, max_lines=1200) if shutil.which("dpkg") else [],
        "rpm": _run_lines(["rpm", "-qa"], timeout=12.0, max_lines=1200) if shutil.which("rpm") else [],
        "pacman": _run_lines(["pacman", "-Q"], timeout=12.0, max_lines=1200) if shutil.which("pacman") else [],
        "snap": _run_lines(["snap", "list"], timeout=8.0, max_lines=300) if shutil.which("snap") else [],
        "flatpak": _run_lines(["flatpak", "list"], timeout=8.0, max_lines=300) if shutil.which("flatpak") else [],
    }
    return packages


def _detect_ssid() -> str:
    system = platform.system()
    if system == "Darwin":
        out = _run(
            [
                "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport",
                "-I",
            ],
            timeout=2.5,
        )
        for line in out.splitlines():
            if " SSID:" in line:
                return line.split(":", 1)[1].strip()
        out2 = _run(["networksetup", "-getairportnetwork", "en0"], timeout=2.5)
        if ":" in out2:
            return out2.split(":", 1)[1].strip()
        return ""
    if system == "Windows":
        out = _run(["netsh", "wlan", "show", "interfaces"], timeout=4.0)
        for line in out.splitlines():
            raw = line.strip()
            if raw.lower().startswith("ssid") and "bssid" not in raw.lower() and ":" in raw:
                return raw.split(":", 1)[1].strip()
        return ""
    if shutil.which("nmcli"):
        out = _run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], timeout=3.0)
        for line in out.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1].strip()
    return ""


def _network_context_guess(ssid: str) -> str:
    name = (ssid or "").lower()
    if not name:
        return "unknown"
    if any(token in name for token in ("corp", "office", "work", "enterprise")):
        return "work"
    return "home"


def _detect_loopback_open_ports() -> list[int]:
    common_ports = [22, 53, 80, 443, 3000, 5000, 5432, 6379, 8000, 8080, 8765, 11434]
    open_ports: list[int] = []
    for port in common_ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.05)
        try:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                open_ports.append(port)
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass
    return open_ports


def _network_inventory() -> dict[str, Any]:
    interfaces: list[str] = []
    lan_neighbors: list[str] = []
    ssid = _detect_ssid()

    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None)
        for info in infos:
            addr = info[4][0]
            if addr not in interfaces:
                interfaces.append(addr)
    except Exception:
        pass

    if shutil.which("arp"):
        lan_neighbors = _run_lines(["arp", "-a"], timeout=3.0, max_lines=200)

    return {
        "ssid": ssid,
        "network_context_guess": _network_context_guess(ssid),
        "interfaces": interfaces,
        "lan_neighbors": lan_neighbors,
        "loopback_open_ports": _detect_loopback_open_ports(),
    }


def _software_inventory() -> dict[str, Any]:
    return {
        "windows": _windows_inventory(),
        "macos": _mac_inventory(),
        "linux": _linux_inventory(),
    }


def scan(force: bool = False, save: bool = True) -> dict[str, Any]:
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
        "software_inventory": _software_inventory(),
        "network": _network_inventory(),
    }

    if save:
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

    return profile


def load() -> dict[str, Any]:
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
