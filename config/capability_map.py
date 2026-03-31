"""Capability map — Feature 7.

Reads config/pc_profile.json and produces a short, human-readable summary of
what NOVA can do on this specific machine.  The summary is injected into every
system prompt so the LLM doesn't hallucinate missing capabilities.
"""
from __future__ import annotations

from typing import Any


def build_capability_summary(profile: dict[str, Any]) -> str:
    """Return a concise capability block for injection into the system prompt."""
    lines: list[str] = ["## System Capabilities (auto-detected)"]

    # OS
    os_info = profile.get("os", {})
    system = os_info.get("system", "Unknown")
    release = os_info.get("release", "")
    lines.append(f"- OS: {system} {release}".strip())

    # Hardware
    ram = profile.get("ram_gb", 0)
    cpu = profile.get("cpu", {})
    cores = cpu.get("cores_logical") or cpu.get("cores_physical")
    if ram:
        lines.append(f"- RAM: {ram} GB" + (f", CPU cores: {cores}" if cores else ""))
    gpu = profile.get("gpu", {})
    if gpu.get("available"):
        gpu_label = gpu.get("name") or gpu.get("vendor", "GPU")
        lines.append(f"- GPU: {gpu_label}")

    # Display / Input
    display = profile.get("display_server", "unknown")
    input_be = profile.get("input_backend", "unknown")
    lines.append(f"- Display: {display} | Input backend: {input_be}")

    # Screenshot
    ss_be = profile.get("screenshot_backend", "none")
    lines.append(f"- Screenshot backend: {ss_be}")

    # Key CLI tools present
    cli = profile.get("cli_tools", {})
    present = [t for t, v in cli.items() if v is not None]
    if present:
        lines.append(f"- CLI tools: {', '.join(sorted(present))}")

    # Key Python packages present
    pkgs = profile.get("python_packages", {})
    present_pkgs = [p for p, v in pkgs.items() if v]
    if present_pkgs:
        lines.append(f"- Python packages: {', '.join(sorted(present_pkgs))}")

    # Derived capabilities (boolean flags the LLM can use)
    caps: list[str] = []
    if cli.get("adb"):
        caps.append("android-adb")
    if cli.get("ffmpeg"):
        caps.append("ffmpeg-media")
    if cli.get("docker"):
        caps.append("docker")
    if cli.get("git"):
        caps.append("git")
    if pkgs.get("playwright"):
        caps.append("browser-automation")
    if pkgs.get("torch") or pkgs.get("cv2"):
        caps.append("local-ml")
    if system == "Darwin" and cli.get("osascript"):
        caps.append("macos-scripting")
    if system == "Windows":
        caps.append("windows-api")
    if display in {"wayland", "x11"} and (cli.get("xdotool") or cli.get("ydotool")):
        caps.append("linux-input-automation")
    if caps:
        lines.append(f"- Derived capabilities: {', '.join(caps)}")

    # Unavailable features worth mentioning
    missing: list[str] = []
    if not cli.get("adb"):
        missing.append("adb (Android bridge unavailable)")
    if ss_be == "none":
        missing.append("screen capture (install mss or Pillow)")
    if missing:
        lines.append(f"- NOT available: {'; '.join(missing)}")

    return "\n".join(lines)


def filter_dispatcher_tools(
    dispatcher,
    profile: dict[str, Any],
) -> list[str]:
    """Return names of tools that should be HIDDEN from the LLM schema prompt.

    Tools are hidden (not disabled) when the underlying capability is absent so
    the LLM doesn't try to call tools that will certainly fail.
    """
    cli = profile.get("cli_tools", {})
    pkgs = profile.get("python_packages", {})
    os_sys = profile.get("os", {}).get("system", "")

    hidden: list[str] = []

    if not cli.get("adb"):
        hidden += [t for t in dispatcher.registry if t.startswith("adb.")]

    if not pkgs.get("playwright"):
        hidden += [t for t in dispatcher.registry if t.startswith("browser.")]

    if os_sys != "Windows":
        hidden += [t for t in dispatcher.registry if t.startswith("registry.") or t.startswith("win32.")]

    if os_sys != "Darwin":
        pass  # osascript tools are fine to advertise (they gracefully fail)

    return list(set(hidden))
