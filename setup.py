from __future__ import annotations

"""One-command installer for JARVIS."""

import os
import platform
import subprocess
import sys
from pathlib import Path
import shutil


REPO_ROOT = Path(__file__).resolve().parent


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(REPO_ROOT))


def ensure_assets_dir() -> Path:
    assets = REPO_ROOT / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    return assets


def ensure_env_file() -> Path:
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        print(".env already exists, skipping generation")
        return env_path

    example = REPO_ROOT / ".env.example"
    if example.exists():
        env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print("✓ Created .env from .env.example")
        return env_path

    print("Create .env (press Enter to skip optional values)")
    openai_keys = input("OPENAI_API_KEYS (comma separated): ").strip()
    openai_base = input("OPENAI_BASE_URL: ").strip() or "https://api.openai.com"

    env_path.write_text(
        (
            f"OPENAI_API_KEYS={openai_keys}\n"
            f"OPENAI_BASE_URL={openai_base}\n"
            "OLLAMA_BASE_URL=http://localhost:11434\n"
            "OLLAMA_MODEL=llama3\n"
            "DEFAULT_SESSION=jarvis_personal\n"
            "WHISPER_MODEL=base\n"
            "PORCUPINE_KEYWORD_PATH=./assets/Hey-Jarvis_en_windows_v3_0_0.ppn\n"
        ),
        encoding="utf-8",
    )
    print("✓ Wrote .env")
    return env_path


def load_env_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def ensure_env_key(env_path: Path, key: str, value: str) -> None:
    if not env_path.exists():
        return
    existing = load_env_values(env_path)
    if key in existing:
        return
    with env_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{key}={value}\n")


def install_dependencies() -> None:
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])


def install_playwright() -> None:
    if shutil.which("playwright"):
        run(["playwright", "install", "chromium"])
        return
    print(f"⚠️ Playwright CLI not found; run `{sys.executable} -m playwright install chromium` later.")


def _try_install(commands: list[list[str]]) -> bool:
    for cmd in commands:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            run(cmd)
            return True
        except Exception:
            continue
    return False


def ensure_system_command(command_name: str, commands_by_os: dict[str, list[list[str]]], hint: str) -> bool:
    if shutil.which(command_name):
        print(f"✓ {command_name} already available")
        return True

    system = platform.system()
    commands = commands_by_os.get(system, []) + commands_by_os.get("default", [])
    if commands and _try_install(commands):
        print(f"✓ Installed {command_name}")
        return True

    print(f"⚠️ {command_name} not found. {hint}")
    return False


def ensure_adb_available() -> bool:
    return ensure_system_command(
        "adb",
        {
            "Darwin": [["brew", "install", "android-platform-tools"]],
            "Windows": [
                ["winget", "install", "--id", "Google.PlatformTools", "-e", "--silent"],
                ["winget", "install", "--id", "AndroidSDK.PlatformTools", "-e", "--silent"],
                ["choco", "install", "adb", "-y"],
            ],
            "Linux": [
                ["sudo", "apt-get", "install", "-y", "android-tools-adb"],
                ["sudo", "apt-get", "install", "-y", "adb"],
                ["sudo", "dnf", "install", "-y", "android-tools"],
                ["sudo", "yum", "install", "-y", "android-tools"],
                ["sudo", "pacman", "-S", "--noconfirm", "android-tools"],
            ],
        },
        hint="Install Android Platform Tools (adb) for phone control.",
    )


def ensure_ffmpeg_available() -> bool:
    return ensure_system_command(
        "ffplay",
        {
            "Darwin": [["brew", "install", "ffmpeg"]],
            "Windows": [
                ["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--silent"],
                ["winget", "install", "--id", "FFmpeg", "-e", "--silent"],
                ["choco", "install", "ffmpeg", "-y"],
            ],
            "Linux": [
                ["sudo", "apt-get", "install", "-y", "ffmpeg"],
                ["sudo", "dnf", "install", "-y", "ffmpeg"],
                ["sudo", "yum", "install", "-y", "ffmpeg"],
                ["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"],
            ],
        },
        hint="Install FFmpeg for audio playback (ffplay).",
    )


def ensure_mpg123_available() -> bool:
    return ensure_system_command(
        "mpg123",
        {
            "Darwin": [["brew", "install", "mpg123"]],
            "Windows": [["choco", "install", "mpg123", "-y"]],
            "Linux": [
                ["sudo", "apt-get", "install", "-y", "mpg123"],
                ["sudo", "dnf", "install", "-y", "mpg123"],
                ["sudo", "yum", "install", "-y", "mpg123"],
                ["sudo", "pacman", "-S", "--noconfirm", "mpg123"],
            ],
        },
        hint="Install mpg123 for MP3 playback fallback.",
    )


def ensure_system_dependencies() -> None:
    ensure_adb_available()
    ensure_ffmpeg_available()
    ensure_mpg123_available()
    try:
        from control.adb.tailscale import ensure_tailscale_available  # fix 6.10
        if ensure_tailscale_available():
            print("✓ Tailscale available")
        else:
            print("⚠️ Tailscale not installed; remote ADB tunneling may be unavailable.")
    except ImportError:
        print("⚠️ Tailscale check skipped (dependencies not yet installed).")


def ensure_omniparser_repo(env_path: Path, env_values: dict[str, str]) -> Path | None:
    repo_dir = env_values.get("OMNIPARSER_REPO_DIR", "").strip()
    if repo_dir:
        repo_path = Path(repo_dir).expanduser()
    else:
        repo_path = REPO_ROOT / "vendor" / "OmniParser"
        ensure_env_key(env_path, "OMNIPARSER_REPO_DIR", str(repo_path))
        env_values["OMNIPARSER_REPO_DIR"] = str(repo_path)

    if repo_path.exists():
        print(f"✓ OmniParser repo found: {repo_path}")
    else:
        if shutil.which("git") is None:
            print("⚠️ git not found; cannot clone OmniParser repo.")
            return None
        print("Cloning OmniParser repository...")
        try:
            run(["git", "clone", "https://github.com/microsoft/OmniParser.git", str(repo_path)])
        except Exception as exc:
            print(f"⚠️ OmniParser clone failed: {exc}")
            return None

    requirements = repo_path / "requirements.txt"
    if requirements.exists():
        full_install = str(env_values.get("OMNIPARSER_FULL_REQUIREMENTS", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        if full_install:
            try:
                run([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
                print("✓ OmniParser requirements installed")
            except Exception as exc:
                print(f"⚠️ OmniParser full requirements install failed: {exc}")
                fallback = _build_omniparser_fallback_requirements(requirements)
                if fallback:
                    try:
                        run([sys.executable, "-m", "pip", "install", "-r", str(fallback)])
                        print("✓ OmniParser fallback requirements installed")
                    except Exception as exc2:
                        print(f"⚠️ OmniParser fallback install failed: {exc2}")
                else:
                    print("⚠️ OmniParser fallback requirements list empty; skipping dependency install.")
        else:
            fallback = _build_omniparser_fallback_requirements(requirements)
            if fallback:
                try:
                    run([sys.executable, "-m", "pip", "install", "-r", str(fallback)])
                    print("✓ OmniParser minimal requirements installed")
                except Exception as exc:
                    print(f"⚠️ OmniParser minimal install failed: {exc}")
            else:
                print("⚠️ OmniParser fallback requirements list empty; skipping dependency install.")
    else:
        print("⚠️ OmniParser requirements.txt not found; skipping dependency install.")

    return repo_path


def _build_omniparser_fallback_requirements(requirements_path: Path) -> Path | None:
    import re

    skip_prefixes = {
        "streamlit",
        "gradio",
        "ruff",
        "pre-commit",
        "pytest",
        "pytest-asyncio",
        "pyautogui",
        "uiautomation",
        "screeninfo",
        "dashscope",
        "groq",
        "anthropic",
        "boto3",
        "google-auth",
        "jsonschema",
        "pyarrow",
        "opencv-python",
        "opencv-python-headless",
        "paddlepaddle",
        "paddleocr",
    }
    lines = []
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        prefix = re.split(r"[<>=]", line, maxsplit=1)[0].strip().lower()
        prefix = prefix.split("[", 1)[0].strip()
        if prefix in skip_prefixes:
            continue
        lines.append(line)

    if not lines:
        return None
    fallback_path = requirements_path.parent / "requirements.jarvis.txt"
    fallback_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return fallback_path


def download_omniparser_weights(repo_path: Path | None) -> None:
    if repo_path is None:
        print("⚠️ OmniParser repo not available; skipping weights download.")
        return

    weights_dir = repo_path / "weights"
    weights_dir.mkdir(parents=True, exist_ok=True)
    expected = [
        weights_dir / "icon_detect" / "train_args.yaml",
        weights_dir / "icon_detect" / "model.pt",
        weights_dir / "icon_detect" / "model.yaml",
        weights_dir / "icon_caption_florence" / "config.json",
        weights_dir / "icon_caption_florence" / "generation_config.json",
        weights_dir / "icon_caption_florence" / "model.safetensors",
    ]
    if all(path.exists() for path in expected):
        print("✓ OmniParser weights already present")
        return

    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:
        print(f"⚠️ huggingface_hub not available; skipping OmniParser weights: {exc}")
        return

    files = [
        "icon_detect/train_args.yaml",
        "icon_detect/model.pt",
        "icon_detect/model.yaml",
        "icon_caption/config.json",
        "icon_caption/generation_config.json",
        "icon_caption/model.safetensors",
    ]
    print("Downloading OmniParser V2 weights...")
    for filename in files:
        hf_hub_download(
            repo_id="microsoft/OmniParser-v2.0",
            filename=filename,
            local_dir=str(weights_dir),
            local_dir_use_symlinks=False,
        )

    caption_dir = weights_dir / "icon_caption"
    florence_dir = weights_dir / "icon_caption_florence"
    if caption_dir.exists() and not florence_dir.exists():
        caption_dir.rename(florence_dir)

    print("✓ OmniParser weights ready")


def post_install_health_check(env_values: dict[str, str]) -> None:
    print("\nRunning post-install health checks...")

    try:
        import requests
    except Exception as exc:
        print(f"⚠️ requests unavailable; skipping health checks: {exc}")
        return

    ollama_base = env_values.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        resp = requests.get(f"{ollama_base}/api/tags", timeout=3)
        if resp.ok:
            print("✓ Ollama reachable")
        else:
            print(f"⚠️ Ollama responded with status {resp.status_code}")
    except Exception as exc:
        print(f"⚠️ Ollama not reachable at {ollama_base}: {exc}")

    omniparser_url = env_values.get("OMNIPARSER_SERVER_URL", "http://localhost:8000").rstrip("/")
    try:
        resp = requests.get(f"{omniparser_url}/health", timeout=3)
        if resp.ok:
            print("✓ OmniParser server reachable")
        else:
            print(f"⚠️ OmniParser responded with status {resp.status_code}")
    except Exception as exc:
        print(f"⚠️ OmniParser not reachable at {omniparser_url}: {exc}")

    if shutil.which("adb"):
        try:
            subprocess.check_output(["adb", "devices"], text=True)
            print("✓ ADB available")
        except Exception as exc:
            print(f"⚠️ ADB check failed: {exc}")
    else:
        print("⚠️ ADB not found; Android control will be unavailable until installed.")


def warmup_whisper_model(model_size: str) -> None:
    try:
        print(f"Downloading Whisper model: {model_size} ...")
        from faster_whisper import WhisperModel

        WhisperModel(model_size, device="cpu", compute_type="int8")
        print("✓ Whisper ready")
    except Exception as exc:
        print(f"⚠️ Whisper warmup skipped: {exc}")


def verify_wakeword_asset(env_values: dict[str, str]) -> None:
    asset_path = env_values.get("PORCUPINE_KEYWORD_PATH", "./assets/Hey-Jarvis_en_windows_v3_0_0.ppn")
    resolved = (REPO_ROOT / asset_path).resolve() if not Path(asset_path).is_absolute() else Path(asset_path)
    if resolved.exists():
        print(f"✓ Wake word asset found: {resolved}")
        return

    print("\n⚠️ Wake word setup required:")
    print("1. Go to console.picovoice.ai")
    print("2. Create custom 'Hey JARVIS' keyword")
    print(f"3. Put the .ppn file at: {resolved}")
    print("4. Confirm PORCUPINE_KEYWORD_PATH in .env")


def maybe_install_ollama_model(env_values: dict[str, str]) -> None:
    ollama_base = env_values.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = env_values.get("OLLAMA_MODEL") or "llama3"
    if not shutil.which("ollama"):
        print("⚠️ Ollama CLI not found; install Ollama separately if you want offline fallback.")
        return
    try:
        subprocess.run(["ollama", "list"], check=False, cwd=str(REPO_ROOT))
        run(["ollama", "pull", ollama_model])
        print(f"✓ Ollama present at {ollama_base} (model target: {ollama_model})")
    except Exception as exc:
        print(f"⚠️ Ollama check skipped: {exc}")


def register_startup_entry() -> None:
    try:
        from control.os_layer import register_startup, startup_command  # fix 6.10
        command = startup_command(str(REPO_ROOT), python_executable=sys.executable, entrypoint="main.py")
        location = register_startup(command, app_name="jarvis")
        print(f"✓ Startup registered: {location}")
    except ImportError:
        print("⚠️ Startup registration skipped (dependencies not yet installed).")
    except Exception as exc:
        print(f"⚠️ Startup registration skipped: {exc}")


def main() -> None:
    env_path = ensure_env_file()
    env_values = load_env_values(env_path)
    ensure_assets_dir()
    ensure_system_dependencies()
    install_dependencies()
    install_playwright()

    whisper_model = env_values.get("WHISPER_MODEL", "base") or "base"
    warmup_whisper_model(whisper_model)
    omniparser_repo = ensure_omniparser_repo(env_path, env_values)
    download_omniparser_weights(omniparser_repo)
    maybe_install_ollama_model(env_values)
    verify_wakeword_asset(env_values)
    register_startup_entry()
    post_install_health_check(env_values)

    print("\nSetup complete. Run: python3 main.py")


if __name__ == "__main__":
    main()
