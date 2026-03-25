from __future__ import annotations

import subprocess
from pathlib import Path
import shutil


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def write_env() -> None:
    if Path(".env").exists():
        print(".env already exists, skipping generation")
        return

    example = Path(".env.example")
    if example.exists():
        env_text = example.read_text(encoding="utf-8")
        Path(".env").write_text(env_text, encoding="utf-8")
        print("✓ Created .env from .env.example")
        return

    print("Create .env (press Enter to skip optional values)")
    openai_keys = input("OPENAI_API_KEYS (comma separated): ").strip()
    openai_base = input("OPENAI_BASE_URL: ").strip() or "https://api.openai.com"

    Path(".env").write_text(
        (
            f"OPENAI_API_KEYS={openai_keys}\n"
            f"OPENAI_BASE_URL={openai_base}\n"
            "OLLAMA_BASE_URL=http://localhost:11434\n"
            "OLLAMA_MODEL=llama3\n"
            "DEFAULT_SESSION=jarvis_personal\n"
            "WHISPER_MODEL=base\n"
        ),
        encoding="utf-8",
    )
    print("✓ Wrote .env")


def warmup_whisper_model() -> None:
    try:
        from dotenv import dotenv_values

        cfg = dotenv_values(".env")
        model_size = str(cfg.get("WHISPER_MODEL", "base") or "base")
        print(f"Downloading Whisper model: {model_size} ...")
        from faster_whisper import WhisperModel

        WhisperModel(model_size, device="cpu", compute_type="int8")
        print("✓ Whisper ready")
    except Exception as exc:
        print(f"⚠️ Whisper warmup skipped: {exc}")


def ensure_assets_dir() -> None:
    Path("assets").mkdir(parents=True, exist_ok=True)


def main() -> None:
    run(["python3", "-m", "pip", "install", "-r", "requirements.txt"])
    write_env()
    ensure_assets_dir()

    if shutil.which("playwright"):
        run(["playwright", "install", "chromium"])
    else:
        print("⚠️ Playwright CLI not found; run `python3 -m playwright install chromium` later.")

    warmup_whisper_model()

    print("\n⚠️ Wake word setup required:")
    print("1. Go to console.picovoice.ai")
    print("2. Create custom 'Hey JARVIS' keyword")
    print("3. Put .ppn in assets/ (default path in .env.example)")
    print("4. Confirm PORCUPINE_KEYWORD_PATH in .env")

    print("\nSetup complete. Run: python3 main.py")


if __name__ == "__main__":
    main()
