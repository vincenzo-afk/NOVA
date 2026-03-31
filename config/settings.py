"""Environment configuration with startup validation."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


class SettingsError(RuntimeError):
    """Raised when startup configuration is invalid — JARVIS cannot run."""


def _csv_to_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass
class Settings:
    # LLM — cloud
    OPENAI_API_KEYS: list[str] = field(default_factory=list)
    OPENAI_BASE_URL: str = ""
    # LLM — local
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"

    # Vision / multi-modal
    GEMINI_API_KEYS: list[str] = field(default_factory=list)

    # Memory
    MEM0_API_KEY: str = ""

    # Wake word
    PORCUPINE_ACCESS_KEY: str = ""
    PORCUPINE_KEYWORD_PATH: str = "./assets/Hey-Nova_en_windows_v3_0_0.ppn"
    PORCUPINE_SENSITIVITY: float = 0.6

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # ADB / Android
    TAILSCALE_PHONE_IP: str = ""
    ADB_PORT: int = 5555
    ALLOWED_PHONE_NUMBERS: list[str] = field(default_factory=list)  # Fix 17

    # OmniParser
    OMNIPARSER_SERVER_URL: str = "http://localhost:8000"
    OMNIPARSER_REPO_DIR: str = ""

    # Safety
    RISK_CONFIRM_THRESHOLD: int = 7

    # Sessions
    DEFAULT_SESSION: str = "nova_personal"
    MAX_SESSION_HISTORY_TURNS: int = 500

    # Usage alerts
    DAILY_TOKEN_ALERT_THRESHOLD: int = 100_000
    DAILY_TOKEN_HARD_CAP: int = 500000  # 0 = disabled; set e.g. 500000 to hard-cap spend
    DAILY_TOKEN_HARD_CAP_WARNING_PCT: int = 80

    # Ambiguity / reasoning (fix 6.1)
    AMBIGUITY_THRESHOLD: float = 0.6

    # Privacy / context injection (fix 2.13)
    INCLUDE_CLIPBOARD_IN_CONTEXT: bool = False

    # Voice
    DEFAULT_LANG: str = "en"
    VAD_SILENCE_MS: int = 800
    WHISPER_MODEL: str = "base"
    GEMINI_TTS_MODEL: str = "gemini-2.5-flash-preview-tts"
    GEMINI_TTS_VOICE: str = "Kore"
    GEMINI_TTS_TIMEOUT_SECONDS: int = 45
    TTS_OFFLINE_WATCHDOG_SECONDS: int = 10
    VOICE_BARGEIN_HOTKEY: str = "ctrl+shift+x"
    VOICE_BARGEIN_ENABLED: bool = True

    # Proactive screen watcher
    PROACTIVE_WATCHER_ENABLED: bool = True
    PROACTIVE_WATCHER_INTERVAL: float = 30.0
    HEALTH_MONITOR_INTERVAL: float = 60.0
    PROACTIVE_WATCHER_COOLDOWN: float = 120.0

    # Phone watcher
    PHONE_WATCHER_ENABLED: bool = False

    # Autonomy loop
    AUTONOMY_ENABLED: bool = False
    AUTONOMY_POLL_SECONDS: float = 20.0
    AUTONOMY_MAX_STEPS: int = 20
    AUTONOMY_NOTIFY_TELEGRAM: bool = True
    AUTONOMY_NOTIFY_TTS: bool = False
    GOAL_STEP_TIMEOUT_SECONDS: float = 60.0
    AUTONOMY_STEP_DELAY_SECONDS: float = 0.5
    NOVA_HEALTH_BIND_HOST: str = "127.0.0.1"
    PLUGINS_ENABLED: bool = False

    # Paths / data
    DATA_DIR: str = "~/.jarvis/data"
    EMERGENCY_STOP_FILE: str = ".jarvis/emergency_stop"
    NOVA_HEALTH_PORT: int = 8765
    NOVA_STARTUP_DELAY_SECONDS: float = 0.0

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        """Load from .env file; warn prominently if missing."""
        import os
        if os.environ.get("JARVIS_ENV") == "test" or os.environ.get("NOVA_ENV") == "test":
            # Sec 6: skip .env loading for tests to avoid loading live keys
            return cls(OPENAI_API_KEYS=[], GEMINI_API_KEYS=[])

        env_path = Path(env_file)
        if not env_path.exists():
            # Bug fix (Deployment/2): Log a clear warning instead of silently starting degraded
            import sys
            print(
                "[NOVA] WARNING: .env file not found. Running with defaults only. "
                "Cloud services (OpenAI, Gemini, Telegram, mem0) will be unavailable. "
                "Create a .env file from .env.example to configure NOVA.",
                file=sys.stderr,
            )
        else:
            load_dotenv(dotenv_path=env_path, override=False)

        def env(name: str, default: str = "") -> str:
            return os.getenv(name, default).strip()

        def env_bool(name: str, default: str = "false") -> bool:
            value = os.getenv(name, default).strip().lower()
            return value in {"1", "true", "yes", "y", "on"}

        def env_float(name: str, default: float) -> float:
            raw = os.getenv(name, "").strip()
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        def env_int(name: str, default: int) -> int:
            raw = os.getenv(name, "").strip()
            try:
                return int(raw) if raw else default
            except ValueError:
                return default

        return cls(
            OPENAI_API_KEYS=_csv_to_list(env("OPENAI_API_KEYS")),
            OPENAI_BASE_URL=env("OPENAI_BASE_URL"),
            OLLAMA_BASE_URL=env("OLLAMA_BASE_URL", "http://localhost:11434"),
            OLLAMA_MODEL=env("OLLAMA_MODEL", "llama3"),
            GEMINI_API_KEYS=_csv_to_list(env("GEMINI_API_KEYS")),
            MEM0_API_KEY=env("MEM0_API_KEY"),
            PORCUPINE_ACCESS_KEY=env("PORCUPINE_ACCESS_KEY"),
            PORCUPINE_KEYWORD_PATH=env(
                "PORCUPINE_KEYWORD_PATH", "./assets/Hey-Nova_en_windows_v3_0_0.ppn"
            ),
            PORCUPINE_SENSITIVITY=env_float("PORCUPINE_SENSITIVITY", 0.6),
            TELEGRAM_BOT_TOKEN=env("TELEGRAM_BOT_TOKEN"),
            TELEGRAM_CHAT_ID=env("TELEGRAM_CHAT_ID"),
            TAILSCALE_PHONE_IP=env("TAILSCALE_PHONE_IP"),
            ADB_PORT=env_int("ADB_PORT", 5555),
            ALLOWED_PHONE_NUMBERS=_csv_to_list(env("ALLOWED_PHONE_NUMBERS")),
            OMNIPARSER_SERVER_URL=env("OMNIPARSER_SERVER_URL", "http://localhost:8000"),
            OMNIPARSER_REPO_DIR=env("OMNIPARSER_REPO_DIR", ""),
            RISK_CONFIRM_THRESHOLD=env_int("RISK_CONFIRM_THRESHOLD", 7),
            DEFAULT_SESSION=env("DEFAULT_SESSION", "nova_personal"),
            MAX_SESSION_HISTORY_TURNS=max(50, env_int("MAX_SESSION_HISTORY_TURNS", 500)),
            DAILY_TOKEN_ALERT_THRESHOLD=env_int("DAILY_TOKEN_ALERT_THRESHOLD", 100_000),
            DAILY_TOKEN_HARD_CAP=env_int("DAILY_TOKEN_HARD_CAP", 500000),
            DAILY_TOKEN_HARD_CAP_WARNING_PCT=max(0, min(100, env_int("DAILY_TOKEN_HARD_CAP_WARNING_PCT", 80))),
            AMBIGUITY_THRESHOLD=env_float("AMBIGUITY_THRESHOLD", 0.6),
            INCLUDE_CLIPBOARD_IN_CONTEXT=env_bool("INCLUDE_CLIPBOARD_IN_CONTEXT", "false"),
            DEFAULT_LANG=env("DEFAULT_LANG", "en"),
            VAD_SILENCE_MS=env_int("VAD_SILENCE_MS", 800),
            WHISPER_MODEL=env("WHISPER_MODEL", "base"),
            GEMINI_TTS_MODEL=env("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts"),
            GEMINI_TTS_VOICE=env("GEMINI_TTS_VOICE", "Kore"),
            GEMINI_TTS_TIMEOUT_SECONDS=env_int("GEMINI_TTS_TIMEOUT_SECONDS", 45),
            TTS_OFFLINE_WATCHDOG_SECONDS=env_int("TTS_OFFLINE_WATCHDOG_SECONDS", 10),
            VOICE_BARGEIN_HOTKEY=env("VOICE_BARGEIN_HOTKEY", "ctrl+shift+x"),
            VOICE_BARGEIN_ENABLED=env_bool("VOICE_BARGEIN_ENABLED", "true"),
            PROACTIVE_WATCHER_ENABLED=env_bool("PROACTIVE_WATCHER_ENABLED", "true"),
            PROACTIVE_WATCHER_INTERVAL=env_float("PROACTIVE_WATCHER_INTERVAL", 30.0),
            HEALTH_MONITOR_INTERVAL=env_float("HEALTH_MONITOR_INTERVAL", 60.0),
            PROACTIVE_WATCHER_COOLDOWN=env_float("PROACTIVE_WATCHER_COOLDOWN", 120.0),
            PHONE_WATCHER_ENABLED=env_bool("PHONE_WATCHER_ENABLED", "false"),
            AUTONOMY_ENABLED=env_bool("AUTONOMY_ENABLED", "false"),
            AUTONOMY_POLL_SECONDS=env_float("AUTONOMY_POLL_SECONDS", 20.0),
            AUTONOMY_MAX_STEPS=env_int("AUTONOMY_MAX_STEPS", 20),
            AUTONOMY_NOTIFY_TELEGRAM=env_bool("AUTONOMY_NOTIFY_TELEGRAM", "true"),
            AUTONOMY_NOTIFY_TTS=env_bool("AUTONOMY_NOTIFY_TTS", "false"),
            GOAL_STEP_TIMEOUT_SECONDS=env_float("GOAL_STEP_TIMEOUT_SECONDS", 60.0),
            AUTONOMY_STEP_DELAY_SECONDS=max(0.0, env_float("AUTONOMY_STEP_DELAY_SECONDS", 0.5)),
            NOVA_HEALTH_BIND_HOST=env("NOVA_HEALTH_BIND_HOST", "127.0.0.1"),
            PLUGINS_ENABLED=env_bool("PLUGINS_ENABLED", "false"),
            DATA_DIR=env("DATA_DIR", "~/.jarvis/data"),
            EMERGENCY_STOP_FILE=env("EMERGENCY_STOP_FILE", ".jarvis/emergency_stop"),
            NOVA_HEALTH_PORT=env_int("NOVA_HEALTH_PORT", 8765),
            NOVA_STARTUP_DELAY_SECONDS=env_float("NOVA_STARTUP_DELAY_SECONDS", 0.0),
        )

    _PLACEHOLDER_KEYS = {"key1", "key2", "key3", "key_a", "key_b", "ghp_test_key", "your_key_here", ""}
    _MIN_REAL_KEY_LENGTH = 20  # Real API keys are typically 20+ characters

    def _is_placeholder_key(self, key: str) -> bool:
        """Return True if a key looks like a placeholder.

        Bug fix (Minor/2): Static allowlist missed novel placeholders like CHANGE_ME or xxx.
        Now also rejects keys that are too short or have insufficient entropy.
        """
        k = key.strip()
        if k.lower() in self._PLACEHOLDER_KEYS:
            return True
        if len(k) < self._MIN_REAL_KEY_LENGTH:
            return True
        # Entropy check: real keys have varied characters.
        # A simple unique-char count misses low-entropy repeated patterns.
        from collections import Counter
        import math
        probs = [count / len(k) for count in Counter(k).values()]
        entropy = -sum(p * math.log2(p) for p in probs if p > 0.0)
        if entropy < 2.5:
            return True
        return False

    def validate_startup(self, phase: str = "minimal") -> None:
        """Fail fast with clear errors for required startup keys.

        Phases:
          minimal – only Ollama required (offline mode, no cloud LLM)
          cloud   – cloud LLM keys required (OPENAI_*)
          phase3  – additionally requires Porcupine wake-word keys
          all     – all subsystems required
        """
        errors: list[str] = []

        # Ollama is always required as the fallback LLM
        if not self.OLLAMA_BASE_URL:
            errors.append("OLLAMA_BASE_URL is required (used as fallback LLM)")
        if not self.OLLAMA_MODEL:
            errors.append("OLLAMA_MODEL is required (e.g. 'llama3')")

        if phase in {"cloud", "phase1", "all"}:
            if not self.OPENAI_BASE_URL:
                errors.append(
                    "OPENAI_BASE_URL is required for cloud primary LLM "
                    "(leave empty to run fully offline via Ollama)"
                )
            real_keys = [k for k in self.OPENAI_API_KEYS if not self._is_placeholder_key(k)]
            if not real_keys and self.OPENAI_API_KEYS:
                errors.append(
                    "OPENAI_API_KEYS must contain at least one real API key — "
                    "placeholder values were detected"
                )

            # Validate Gemini keys too
            real_gemini = [k for k in self.GEMINI_API_KEYS if not self._is_placeholder_key(k)]
            if not real_gemini and self.GEMINI_API_KEYS:
                errors.append(
                    "GEMINI_API_KEYS must contain at least one real API key — "
                    "placeholder values were detected"
                )

            # Bug fix (Connectivity): Validate Telegram credentials if bot token is set
            if self.TELEGRAM_BOT_TOKEN and not self.TELEGRAM_CHAT_ID:
                errors.append(
                    "TELEGRAM_CHAT_ID must be set when TELEGRAM_BOT_TOKEN is configured. "
                    "An empty TELEGRAM_CHAT_ID makes the bot permanently deaf to all messages."
                )

        if phase in {"phase3", "all"}:
            if not self.PORCUPINE_ACCESS_KEY:
                errors.append("PORCUPINE_ACCESS_KEY is required for wake word")
            if not self.PORCUPINE_KEYWORD_PATH:
                errors.append("PORCUPINE_KEYWORD_PATH is required for wake word")

        if errors:
            bullets = "\n".join(f"  - {msg}" for msg in errors)
            raise SettingsError(f"Startup validation failed:\n{bullets}")

    @property
    def has_cloud_llm(self) -> bool:
        """True if cloud LLM is configured."""
        real_keys = [k for k in self.OPENAI_API_KEYS if not self._is_placeholder_key(k)]
        return bool(real_keys and self.OPENAI_BASE_URL)

    @property
    def has_gemini(self) -> bool:
        """True if any Gemini API key is present."""
        real_keys = [k for k in self.GEMINI_API_KEYS if not self._is_placeholder_key(k)]
        return bool(real_keys)

    @property
    def has_telegram(self) -> bool:
        """True if Telegram bot is configured."""
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)

    @property
    def has_wakeword(self) -> bool:
        """True if Porcupine wake word is configured."""
        return bool(self.PORCUPINE_ACCESS_KEY and self.PORCUPINE_KEYWORD_PATH)


settings = Settings.from_env()
