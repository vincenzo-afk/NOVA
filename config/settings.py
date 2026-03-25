"""Environment configuration with startup validation."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


class SettingsError(RuntimeError):
    """Raised when startup configuration is invalid."""



def _csv_to_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass
class Settings:
    OPENAI_API_KEYS: list[str] = field(default_factory=list)
    OPENAI_BASE_URL: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"

    GEMINI_API_KEYS: list[str] = field(default_factory=list)
    MEM0_API_KEY: str = ""

    PORCUPINE_ACCESS_KEY: str = ""
    PORCUPINE_KEYWORD_PATH: str = "./assets/Hey-Jarvis_en_windows_v3_0_0.ppn"
    PORCUPINE_SENSITIVITY: float = 0.6

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    TAILSCALE_PHONE_IP: str = ""
    ADB_PORT: int = 5555

    OMNIPARSER_SERVER_URL: str = "http://localhost:8000"
    RISK_CONFIRM_THRESHOLD: int = 7

    DEFAULT_SESSION: str = "jarvis_personal"
    DAILY_TOKEN_ALERT_THRESHOLD: int = 100_000

    DEFAULT_LANG: str = "en"
    VAD_SILENCE_MS: int = 800
    WHISPER_MODEL: str = "base"

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
        else:
            example_path = Path(".env.example")
            if example_path.exists():
                load_dotenv(dotenv_path=example_path, override=False)

        def env(name: str, default: str = "") -> str:
            return os.getenv(name, default).strip()

        return cls(
            OPENAI_API_KEYS=_csv_to_list(env("OPENAI_API_KEYS")),
            OPENAI_BASE_URL=env("OPENAI_BASE_URL"),
            OLLAMA_BASE_URL=env("OLLAMA_BASE_URL", "http://localhost:11434"),
            OLLAMA_MODEL=env("OLLAMA_MODEL", "llama3"),
            GEMINI_API_KEYS=_csv_to_list(env("GEMINI_API_KEYS")),
            MEM0_API_KEY=env("MEM0_API_KEY"),
            PORCUPINE_ACCESS_KEY=env("PORCUPINE_ACCESS_KEY"),
            PORCUPINE_KEYWORD_PATH=env(
                "PORCUPINE_KEYWORD_PATH", "./assets/Hey-Jarvis_en_windows_v3_0_0.ppn"
            ),
            PORCUPINE_SENSITIVITY=float(env("PORCUPINE_SENSITIVITY", "0.6") or 0.6),
            TELEGRAM_BOT_TOKEN=env("TELEGRAM_BOT_TOKEN"),
            TELEGRAM_CHAT_ID=env("TELEGRAM_CHAT_ID"),
            TAILSCALE_PHONE_IP=env("TAILSCALE_PHONE_IP"),
            ADB_PORT=int(env("ADB_PORT", "5555") or 5555),
            OMNIPARSER_SERVER_URL=env("OMNIPARSER_SERVER_URL", "http://localhost:8000"),
            RISK_CONFIRM_THRESHOLD=int(env("RISK_CONFIRM_THRESHOLD", "7") or 7),
            DEFAULT_SESSION=env("DEFAULT_SESSION", "jarvis_personal"),
            DAILY_TOKEN_ALERT_THRESHOLD=int(
                env("DAILY_TOKEN_ALERT_THRESHOLD", "100000") or 100000
            ),
            DEFAULT_LANG=env("DEFAULT_LANG", "en"),
            VAD_SILENCE_MS=int(env("VAD_SILENCE_MS", "800") or 800),
            WHISPER_MODEL=env("WHISPER_MODEL", "base"),
        )

    def validate_startup(self, phase: str = "phase1") -> None:
        """Fail fast with clear errors for required startup keys."""
        errors: list[str] = []

        if not self.OLLAMA_BASE_URL:
            errors.append("OLLAMA_BASE_URL is required")
        if not self.OLLAMA_MODEL:
            errors.append("OLLAMA_MODEL is required")

        if phase == "phase1":
            if not self.OPENAI_BASE_URL:
                errors.append("OPENAI_BASE_URL is required for cloud primary LLM")
            if not self.OPENAI_API_KEYS:
                errors.append("OPENAI_API_KEYS must contain at least one API key")

        if phase in {"phase3", "all"}:
            if not self.PORCUPINE_ACCESS_KEY:
                errors.append("PORCUPINE_ACCESS_KEY is required for wake word")
            if not self.PORCUPINE_KEYWORD_PATH:
                errors.append("PORCUPINE_KEYWORD_PATH is required for wake word")

        if errors:
            bullets = "\n".join(f"- {msg}" for msg in errors)
            raise SettingsError(f"Startup validation failed:\n{bullets}")


settings = Settings.from_env()
