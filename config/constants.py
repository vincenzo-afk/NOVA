"""Project-wide constants used across modules.

Minor fix: updated agent identity constants from JARVIS → NOVA so that
changing the project name requires only editing this single file.
"""

# ── Agent identity ─────────────────────────────────────────────────────────
AGENT_NAME = "NOVA"
DEFAULT_SESSION_PERSONAL = "nova_personal"
DEFAULT_SESSION_WORK = "nova_work"

DEFAULT_SYSTEM_PROMPT = (
    f"You are {AGENT_NAME}, an autonomous AI assistant. "
    "Be concise, safe, and action-oriented."
)

# ── Context / memory ───────────────────────────────────────────────────────
DEFAULT_HISTORY_WINDOW = 10
DEFAULT_AMBIGUITY_THRESHOLD = 0.6
DEFAULT_MEMORY_TOP_K = 5
DEFAULT_RATE_LIMIT_TTL = 60
DEFAULT_HEARTBEAT_SECONDS = 60
MAX_CONTEXT_TOKENS = 12000

# Auth / security
CLI_PIN_HASH_FILE = ".jarvis/cli_pin_hash"
CLI_PIN_LEGACY_FILE = ".jarvis/cli_pin"
CLI_PIN_LOCK_FILE = ".jarvis/cli_pin.lock"
