# NOVA — Autonomous AI Agent · Build Roadmap v5

> One Python project. Every feature. Every gap filled. All fixes integrated. All new features planned. Built phase by phase, always testable, always autonomous.

---

## ✅ Status: What's Already Built vs. What's Needed

### Already Implemented (Codebase Confirmed)

| Module | Status | Notes |
|---|---|---|
| `core/llm/engine.py` | ✅ Complete | Streaming, cloud→Ollama fallback, [ERROR] tagging |
| `core/llm/roundrobin.py` | ✅ Complete | TTL cooldown, backoff cap at 1h, failure tracking |
| `core/llm/fallback.py` | ✅ Complete | NetworkState online/offline probe |
| `core/think/reasoning.py` | ✅ Complete | CoT, ambiguity, prompt injection detection, SOUL.md loader |
| `core/memory/mem0_client.py` | ✅ Complete | Remote + local fallback, SDK variant probing |
| `core/memory/local_store.py` | ✅ Complete | ChromaDB + in-memory fallback, dedup, disk guard |
| `core/memory/memory_router.py` | ✅ Complete | Thread-safe sync, dedup, injection sanitization |
| `core/memory/context_trimmer.py` | ✅ Complete | Sliding window + LLM rolling summary |
| `core/memory/backup.py` | ✅ Complete | Daily ChromaDB snapshots, 7-file rotation |
| `core/session.py` | ✅ Complete | Atomic persist, crash recovery, multi-session isolation |
| `core/health.py` | ✅ Complete | Heartbeat registry, auto-restart with backoff |
| `core/emotion/engine.py` | ✅ Complete | State machine + trajectory prediction |
| `core/tools/dispatcher.py` | ✅ Complete | Schema injection, Pydantic validation, rate limiter |
| `core/plugin_loader.py` | ✅ Complete | AST sandbox, restricted namespace, conflict detection |
| `core/plugin_generator.py` | ✅ Complete | LLM-generated plugins with human approval gate |
| `core/context/environment.py` | ✅ Complete | OS snapshot, stale-cache background refresh |
| `core/context/fs_watcher.py` | ✅ Complete | Watchdog file/git monitor, debounce |
| `core/llm/network_context.py` | ✅ Complete | Work/home/unknown network detection |
| `core/goals/template_library.py` | ✅ Complete | Learned goal templates, Jaccard matching |
| `core/goals/proactive_goal_engine.py` | ✅ Complete | Proposed goals, grace period, auto-approval |
| `core/think/prompt_evolver.py` | ✅ Complete | A/B prompt variants, SOUL.md graduation |
| `safety/guardrails.py` | ✅ Complete | Risk 0-10, emergency stop persistence, log rotation |
| `voice/vad.py` | ✅ Complete | Silero-VAD + energy fallback |
| `voice/stt.py` | ✅ Complete | Gemini STT online |
| `voice/stt_offline.py` | ✅ Complete | faster-whisper offline, Tamil support |
| `voice/tts.py` | ✅ Complete | Gemini TTS, gTTS fallback, pyttsx3 final fallback |
| `voice/tts_offline.py` | ✅ Complete | pyttsx3 single-thread worker, watchdog |
| `voice/tts_indic.py` | ✅ Complete | Tamil gTTS |
| `voice/wakeword.py` | ✅ Complete | Porcupine background listener |
| `vision/capture.py` | ✅ Complete | mss/PIL/scrot backend selection |
| `vision/gemini_vision.py` | ✅ Complete | Structured screen analysis |
| `vision/omniparser.py` | ✅ Complete | HTTP client, TTL element cache |
| `vision/omniparser_server.py` | ✅ Complete | Auto-start subprocess, secret-free env, auth token |
| `vision/watcher.py` | ✅ Complete | Proactive screen watcher, injection guard |
| `control/mouse_keyboard.py` | ✅ Complete | Backend auto-select: PyAutoGUI/Quartz/xdotool/ydotool |
| `control/win32_api.py` | ✅ Complete | Files, processes, registry, clipboard, windows |
| `control/browser.py` | ✅ Complete | Playwright sync, auto-reinit on error |
| `control/os_layer.py` | ✅ Complete | Cross-OS startup, notification, app focus |
| `control/window_manager.py` | ✅ Complete | Win32/osascript/xdotool/wmctrl backends |
| `control/macos_permissions.py` | ✅ Complete | Accessibility + Screen Recording checks |
| `control/adb/adb_client.py` | ✅ Complete | Per-device lock, safe SMS |
| `control/adb/tailscale.py` | ✅ Complete | Auto-install, reconnect, IP resolve |
| `control/adb/qr_pairing.py` | ✅ Complete | Local + remote QR generation |
| `control/adb/watcher.py` | ✅ Complete | Phone notification/SMS polling, vision alerts |
| `interfaces/cli.py` | ✅ Complete | PBKDF2 PIN auth, lockout, streaming |
| `interfaces/gui/app.py` | ✅ Complete | PyQt6 streaming, voice loop, health panel |
| `interfaces/telegram_bot.py` | ✅ Complete | Whitelist, edit-streaming, rate limit |
| `interfaces/voice_interface.py` | ✅ Complete | Full loop, barge-in, wakeword, Tamil |
| `interfaces/tray.py` | ✅ Complete | Live tooltip, session/mute/export menu |
| `interfaces/onboarding.py` | ✅ Complete | First-run SOUL.md personalization |
| `mcp/master_mcp.py` | ✅ Complete | HTTP+local, GitHub/Slack/Notion/Linear/HA built-ins |
| `mcp/master_api.py` | ✅ Complete | Auto-detect service from key prefix |
| `tasks/scheduler.py` | ✅ Complete | APScheduler SQLite, cron + interval |
| `tasks/goals.py` | ✅ Complete | Cycle detection, step limit, per-step guardrails |
| `tasks/maintenance.py` | ✅ Complete | Nightly disk/log/export/backup/health |
| `rag/doc_loader.py` | ✅ Complete | PDF/DOCX/TXT, 50MB limit |
| `rag/chunker.py` | ✅ Complete | Sentence-safe overlap chunking |
| `rag/doc_store.py` | ✅ Complete | ChromaDB + keyword fallback, injection filter |
| `web/search.py` | ✅ Complete | DDGS + HTML fallback |
| `web/scraper.py` | ✅ Complete | SSRF guard, L1/L3/L4 scraping levels |
| `web/crawler.py` | ✅ Complete | BFS crawl, robots.txt, SSRF per-link |
| `web/hybrid_ranker.py` | ✅ Complete | BM25 + Jaccard + RRF fusion |
| `utils/behavior_model.py` | ✅ Complete | Temporal activity pattern, provider tracking |
| `utils/commitment_extractor.py` | ✅ Complete | Deadline extraction, memory injection |
| `utils/insight_extractor.py` | ✅ Complete | Weekly cross-session LLM insight |
| `utils/tool_profiler.py` | ✅ Complete | Reliability stats, sequence detection |
| `utils/presence_manager.py` | ✅ Complete | Multi-channel routing by urgency |
| `utils/usage_tracker.py` | ✅ Complete | Daily/weekly per-provider/session, persist |
| `utils/exporter.py` | ✅ Complete | JSON/Markdown export with secret redaction |
| `utils/notifier.py` | ✅ Complete | Telegram + TTS dual-channel notify |
| `utils/embeddings.py` | ✅ Complete | Lazy SentenceTransformer, async preload |
| `config/settings.py` | ✅ Complete | Fail-fast validation, placeholder detection |
| `config/pc_scanner.py` | ✅ Complete | Full HW/SW inventory, schema versioned |
| `config/capability_map.py` | ✅ Complete | Derived capabilities, tool hiding |
| `core/memory/intent_graph.py` | ✅ Complete | Co-occurrence graph, hot topics |
| `setup.py` | ✅ Complete | Full one-command installer |
| `install.sh` | ✅ Complete | Bash smart installer with OS detection |
| `docker-compose.yml` | ✅ Complete | Ollama + ChromaDB + OmniParser + NOVA |

### Needs to Be Built (New Features v5)

| Feature | Priority | Phase |
|---|---|---|
| One-command installer upgrade (`install.sh` → universal GUI wizard) | HIGH | P14 |
| Interactive Setup Wizard (5-question first-run GUI) | HIGH | P14 |
| System Deep Scan — winget/registry/brew/apt full inventory | HIGH | P14 |
| Full Windows/Linux/Mac feature parity audit + fixes | HIGH | P14 |
| VirusTotal API integration + local heuristic scanner | MEDIUM | P15 |
| Privacy-First Config (per-session local-only mode toggle) | HIGH | P14 |
| BYOK UI — in-app key manager for OpenAI/Gemini/Groq/Cerebras | HIGH | P14 |
| STT/TTS Config UI (engine picker per language) | MEDIUM | P15 |
| Model Manager UI (Ollama model pull/delete + cloud key pool) | MEDIUM | P15 |
| Self-Learning Feedback Loop (post-task silent rating) | HIGH | P16 |
| Dynamic UI Skin Engine (time/task/mood themes) | LOW | P17 |
| Ambient Audio Monitor (passive keyword/alarm detection) | MEDIUM | P16 |
| Scheduled Autonomous Missions (recurring, no wake word) | HIGH | P16 (partial — scheduler exists, needs mission UI) |
| Proactive Nudge Engine (stuck-task detection + break reminders) | MEDIUM | P16 |
| Agent-to-Agent (A2A) Team Collaboration over LAN/Tailscale | HIGH | P17 |
| Virus Scan deep integration | LOW | P17 |

### Needs Upgrade (Existing but Incomplete)

| Module | Gap | Fix Needed |
|---|---|---|
| `fix.txt` bugs 1–20 | All 20 documented bugs | Full fix pass (see Phase 15) |
| `interfaces/onboarding.py` | Text-only, no GUI | Add PyQt6 wizard flow |
| `config/pc_scanner.py` | Missing winget/registry scan on Windows | Extend with Windows deep inventory |
| `install.sh` | Windows parity was missing | `install.bat` now included with `--gui`, `--dry-run`, `--no-onboarding` |
| `interfaces/gui/app.py` | Static theme | Add Dynamic UI Skin Engine hooks |
| `tasks/scheduler.py` | No recurring mission management UI | Add mission builder |
| `core/plugin_generator.py` | CLI confirm only | Add GUI approval dialog |
| `voice/vad.py` | No ambient/passive mode | Add always-on background listener |
| `mcp/master_mcp.py` | No A2A peer discovery | Add peer registry + shared memory bus |

---

## Tech Stack Reference

| Tool | Role |
|---|---|
| GPT OSS 120B / OpenAI-compatible API | Primary cloud LLM |
| Ollama | Offline / local fallback LLM |
| Groq / Cerebras | Optional ultra-fast inference keys (BYOK) |
| RoundRobin | Load balancing + backoff across all LLM providers |
| Gemini Vision | Screen understanding, image analysis |
| Gemini STT | Speech-to-text (online) |
| faster-whisper | STT (offline, multilingual including Tamil) |
| Gemini TTS | Text-to-speech (online) |
| pyttsx3 | TTS offline fallback |
| gTTS / IndicTTS | Tamil TTS fallback |
| PicoVoice Porcupine | Wake word detection |
| silero-VAD | Voice activity detection (speech start/stop) |
| OmniParser V2 | OCR + UI element detection (local HTTP server) |
| PyAutoGUI / Quartz / xdotool / ydotool | Mouse & keyboard (platform-specific) |
| Win32 API | Deep Windows file/process/registry/window access |
| Playwright (sync) | Browser automation |
| Porcupine | Wake word |
| mem0 | Persistent cloud memory |
| ChromaDB | Offline vector memory + document RAG |
| sentence-transformers | Local embeddings |
| Tailscale | Remote ADB tunnel |
| ADB | Android phone control |
| VirusTotal API | Cloud threat scanning (NEW v5) |
| Home Assistant | Smart home control via MCP |
| APScheduler + SQLite | Persistent job scheduling |
| loguru | Rotating structured logs |
| Pydantic v2 | Schema validation |
| FastAPI | OmniParser server wrapper |
| Python 3.10+ | Runtime |

---

## Project Structure

```
nova/
├── main.py                            # Entry point — NOVAApp bootstrap + CLI
├── SOUL.md                            # Persona file — auto-filled by onboarding
├── assets/
│   └── Hey-Nova_en_windows_v3_0_0.ppn  # Wake word (download from picovoice.ai)
├── config/
│   ├── settings.py                    # .env loader, startup validation, placeholder detection
│   ├── constants.py                   # AGENT_NAME, session names, context limits
│   ├── pc_scanner.py                  # Full HW/SW inventory → config/pc_profile.json
│   └── capability_map.py              # Derived capability summary for system prompt
├── core/
│   ├── llm/
│   │   ├── engine.py                  # ask() + ask_stream() — cloud + Ollama unified
│   │   ├── roundrobin.py              # Multi-key rotation, TTL recovery, backoff cap
│   │   ├── fallback.py                # NetworkState online/offline probe
│   │   └── network_context.py         # Work/home/unknown network classifier
│   ├── think/
│   │   ├── reasoning.py               # CoT, ambiguity score, injection detection, SOUL.md
│   │   └── prompt_evolver.py          # A/B variant testing, SOUL.md auto-graduation
│   ├── memory/
│   │   ├── mem0_client.py             # mem0 SDK wrapper + local fallback
│   │   ├── local_store.py             # ChromaDB + in-memory fallback
│   │   ├── memory_router.py           # Online→mem0+ChromaDB, Offline→ChromaDB, dedup
│   │   ├── context_trimmer.py         # Sliding window + async LLM summary compression
│   │   ├── intent_graph.py            # Co-occurrence topic graph (Tier 2)
│   │   └── backup.py                  # Daily ChromaDB snapshot + rotation
│   ├── context/
│   │   ├── environment.py             # OS snapshot with stale-cache async refresh
│   │   └── fs_watcher.py              # Watchdog doc/git monitor
│   ├── emotion/
│   │   └── engine.py                  # State machine + trajectory prediction (Tier 2)
│   ├── goals/
│   │   ├── template_library.py        # Learned goal templates (Tier 5)
│   │   └── proactive_goal_engine.py   # Proposed goals, grace period, auto-approval (Tier 3)
│   ├── session.py                     # Atomic persist, crash recovery, multi-session
│   ├── health.py                      # Subsystem heartbeat + auto-restart
│   ├── plugin_loader.py               # AST sandbox plugin loader
│   ├── plugin_generator.py            # LLM plugin synthesis with human approval
│   └── tools/
│       └── dispatcher.py              # Schema prompt injection, validation, rate limiter
├── voice/
│   ├── vad.py                         # silero-VAD (speech start/end) + energy fallback
│   ├── wakeword.py                    # Porcupine background listener
│   ├── stt.py                         # Gemini STT (online)
│   ├── stt_offline.py                 # faster-whisper (offline, multilingual)
│   ├── tts.py                         # Gemini TTS → gTTS → pyttsx3 chain
│   ├── tts_offline.py                 # pyttsx3 single-thread worker + watchdog
│   └── tts_indic.py                   # Tamil gTTS / IndicTTS
├── vision/
│   ├── capture.py                     # Screenshot: mss → PIL → scrot fallback chain
│   ├── gemini_vision.py               # Gemini Vision structured screen analysis
│   ├── omniparser.py                  # OmniParser HTTP client + TTL element cache
│   ├── omniparser_server.py           # Lifecycle manager, auth token, secret-free env
│   ├── omniparser_app.py              # FastAPI OmniParser wrapper
│   └── watcher.py                     # Proactive screen watcher + injection guard
├── control/
│   ├── mouse_keyboard.py              # Platform-aware: PyAutoGUI/Quartz/xdotool/ydotool
│   ├── win32_api.py                   # File/process/registry/clipboard/window/notification
│   ├── browser.py                     # Playwright sync, auto-reinit on crash
│   ├── os_layer.py                    # Cross-OS: notifications, startup, foreground app
│   ├── window_manager.py              # Win32/osascript/xdotool/wmctrl backends
│   ├── macos_permissions.py           # Accessibility + Screen Recording checks
│   └── adb/
│       ├── adb_client.py              # ADB commands, per-device lock, safe SMS
│       ├── tailscale.py               # Tunnel auto-install + reconnect
│       ├── qr_pairing.py              # Local + remote QR ADB pairing
│       └── watcher.py                 # Phone notification/SMS polling + vision
├── interfaces/
│   ├── cli.py                         # Rich streaming CLI, PBKDF2 PIN, lockout
│   ├── gui/
│   │   └── app.py                     # PyQt6 streaming, voice loop, health, goals
│   ├── telegram_bot.py                # Whitelist auth, edit-streaming, rate limiting
│   ├── voice_interface.py             # VAD→STT→LLM→TTS full loop, barge-in
│   ├── tray.py                        # pystray: status, session, mute, export
│   └── onboarding.py                  # First-run SOUL.md + PC scan wizard
├── tasks/
│   ├── scheduler.py                   # APScheduler SQLite backend, cron + interval
│   ├── goals.py                       # GoalRunner: step limit, cycle detection, guardrails
│   ├── phase_verify.py                # 13-phase build verification runner
│   └── maintenance.py                 # Nightly: disk/log/export/backup/health (Tier 4)
├── mcp/
│   ├── master_mcp.py                  # HTTP + local, GitHub/Slack/Notion/Linear/HA/Jira
│   └── master_api.py                  # API key registry with service auto-detection
├── rag/
│   ├── doc_loader.py                  # PDF/DOCX/TXT loader, 50MB guard
│   ├── chunker.py                     # Sentence-safe overlap chunker
│   └── doc_store.py                   # ChromaDB embed+store+query, injection filter
├── web/
│   ├── search.py                      # DuckDuckGo DDGS + HTML fallback
│   ├── scraper.py                     # SSRF-guarded L1/L3/L4 scraping
│   ├── crawler.py                     # BFS crawler + robots.txt + per-link SSRF
│   └── hybrid_ranker.py               # BM25 + Jaccard + RRF fusion ranker
├── safety/
│   └── guardrails.py                  # Risk 0-10, confirmation, log rotation, emergency stop
├── utils/
│   ├── logger.py                      # loguru rotating logger, auto-init
│   ├── usage_tracker.py               # Per-session/provider daily+weekly tracking
│   ├── exporter.py                    # JSON/MD export with secret redaction
│   ├── notifier.py                    # Telegram + TTS dual-channel
│   ├── events.py                      # Event log formatter
│   ├── goals.py                       # Goal list formatter
│   ├── health.py                      # Health table formatter
│   ├── helpers.py                     # pretty_json
│   ├── embeddings.py                  # Lazy SentenceTransformer + async preload
│   ├── token_estimator.py             # ~4 chars/token estimator
│   ├── behavior_model.py              # Temporal activity model (Tier 2)
│   ├── commitment_extractor.py        # Deadline extraction from conversation (Tier 3)
│   ├── insight_extractor.py           # Weekly cross-session LLM insight (Tier 2)
│   ├── tool_profiler.py               # Tool reliability stats + sequence detection (Tier 5)
│   └── presence_manager.py            # Multi-channel notification routing (Tier 4)
├── plugins/
│   └── (drop .py files here)          # Auto-loaded plugins (sandboxed)
├── tests/                             # Full pytest suite
├── vendor/                            # OmniParser submodule
├── exports/                           # Session exports
├── logs/                              # Rotating logs
├── assets/                            # Wake word .ppn, QR images
├── .jarvis/                           # Runtime state: sessions, goals, emergency stop
├── .jarvis_chroma/                    # ChromaDB memory
├── .jarvis_docs/                      # ChromaDB document store
├── setup.py                           # Python one-command installer
├── install.sh                         # Universal bash installer
├── docker-compose.yml                 # Ollama + ChromaDB + OmniParser + NOVA
├── Dockerfile                         # Multi-stage Linux build
├── .env                               # API keys (never committed)
└── requirements.txt / requirements.lock
```

---

## Environment Variables (.env)

```env
# ── LLM ────────────────────────────────────────────────────────────────────
OPENAI_API_KEYS=key1,key2,key3          # comma-separated pool, round-robin rotated
OPENAI_BASE_URL=                        # OpenAI-compatible endpoint URL
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# ── Additional cloud providers (BYOK) ──────────────────────────────────────
# GROQ_API_KEYS=gsk_key1,gsk_key2       # Groq ultra-fast inference (future)
# CEREBRAS_API_KEY=csk_...              # Cerebras inference (future)

# ── Gemini (vision, STT, TTS) ──────────────────────────────────────────────
GEMINI_API_KEYS=key_a,key_b             # comma-separated

# ── Memory ─────────────────────────────────────────────────────────────────
MEM0_API_KEY=                           # leave blank for local-only mode

# ── Wake Word ──────────────────────────────────────────────────────────────
PORCUPINE_ACCESS_KEY=
PORCUPINE_KEYWORD_PATH=./assets/Hey-Nova_en_windows_v3_0_0.ppn
PORCUPINE_SENSITIVITY=0.6

# ── Telegram ───────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=                       # your numeric chat ID (whitelist)

# ── ADB / Android ──────────────────────────────────────────────────────────
TAILSCALE_PHONE_IP=
ADB_PORT=5555
ALLOWED_PHONE_NUMBERS=+1234567890       # comma-separated SMS allowlist

# ── OmniParser ─────────────────────────────────────────────────────────────
OMNIPARSER_SERVER_URL=http://localhost:8000
OMNIPARSER_REPO_DIR=                    # path to cloned OmniParser repo

# ── Safety ─────────────────────────────────────────────────────────────────
RISK_CONFIRM_THRESHOLD=7                # 0-10; above this needs confirm

# ── Sessions ───────────────────────────────────────────────────────────────
DEFAULT_SESSION=nova_personal
MAX_SESSION_HISTORY_TURNS=500

# ── Usage Limits ───────────────────────────────────────────────────────────
DAILY_TOKEN_ALERT_THRESHOLD=100000
DAILY_TOKEN_HARD_CAP=500000             # 0 = disabled; blocks all LLM at cap
DAILY_TOKEN_HARD_CAP_WARNING_PCT=80

# ── Privacy ────────────────────────────────────────────────────────────────
INCLUDE_CLIPBOARD_IN_CONTEXT=false      # set true to include clipboard in every prompt

# ── Voice ──────────────────────────────────────────────────────────────────
DEFAULT_LANG=en                         # ta = Tamil, hi = Hindi, etc.
VAD_SILENCE_MS=800
WHISPER_MODEL=base                      # tiny/base/small/medium/large
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts
GEMINI_TTS_VOICE=Kore
GEMINI_TTS_TIMEOUT_SECONDS=45
TTS_OFFLINE_WATCHDOG_SECONDS=10
VOICE_BARGEIN_HOTKEY=ctrl+shift+x
VOICE_BARGEIN_ENABLED=true

# ── Proactive Watchers ─────────────────────────────────────────────────────
PROACTIVE_WATCHER_ENABLED=true
PROACTIVE_WATCHER_INTERVAL=30           # seconds between screen captures
PROACTIVE_WATCHER_COOLDOWN=120          # minimum seconds between alerts
PHONE_WATCHER_ENABLED=false

# ── Autonomy ───────────────────────────────────────────────────────────────
AUTONOMY_ENABLED=false
AUTONOMY_POLL_SECONDS=20
AUTONOMY_MAX_STEPS=20
AUTONOMY_NOTIFY_TELEGRAM=true
AUTONOMY_NOTIFY_TTS=false
GOAL_STEP_TIMEOUT_SECONDS=60
AUTONOMY_STEP_DELAY_SECONDS=0.5

# ── Health Probe ───────────────────────────────────────────────────────────
NOVA_HEALTH_PORT=8765
NOVA_HEALTH_BIND_HOST=127.0.0.1

# ── Misc ───────────────────────────────────────────────────────────────────
PLUGINS_ENABLED=false
DATA_DIR=~/.jarvis/data
NOVA_STARTUP_DELAY_SECONDS=0
WORK_NETWORK_DOMAINS=                   # comma-separated DNS suffixes for work detection
```

---

## Complete Build Roadmap

### ✅ PHASE 1 — Core Engine + CLI
**Status: COMPLETE**

The brain: streaming chatbot backed by the full LLM stack.

- `core/llm/engine.py` — `ask()` + `ask_stream()` unified interface
- `core/llm/roundrobin.py` — N-key rotation, per-key TTL cooldown, exponential backoff capped at 1 hour, auto-recovery on TTL expiry
- `core/llm/fallback.py` — cloud keys exhausted or offline → Ollama seamlessly
- `core/think/reasoning.py` — silent chain-of-thought prefix on every LLM call; ambiguity scorer 0.0–1.0; if score ≥ 0.6 returns clarifying question before acting; tool schema injected into every system prompt
- `config/settings.py` — `.env` loader, fail-fast on startup with clear error messages, placeholder key detection using entropy analysis, per-phase validation
- `interfaces/cli.py` — Rich streaming terminal; PBKDF2 PIN auth with lockout; shows provider label e.g. `[cloud • key_2]` or `[local • ollama]`

**Milestone:** Tokens stream live. Ambiguous command → NOVA asks first. Rate-limited key → recovers after TTL without restart. Missing `.env` → clear startup error immediately.

---

### ✅ PHASE 2 — Memory Layer
**Status: COMPLETE**

NOVA remembers everything and never overflows the context window.

- `core/memory/mem0_client.py` — mem0 SDK probe (tries 4 import variants), remote + local fallback, dedup by sha256
- `core/memory/local_store.py` — ChromaDB PersistentClient + in-memory fallback, disk-space guard before writes, connection retry with 60s cooldown
- `core/memory/memory_router.py` — Online: writes to both mem0 + ChromaDB simultaneously. Offline: ChromaDB only, pending queue. On reconnect: thread-safe sync with only-remove-on-success guarantee (fix 2.14). Injection sanitization strips prompt-injection patterns before storage.
- `core/memory/context_trimmer.py` — Keep last 10 raw turns; older turns compressed into rolling summary via async background LLM call (never blocks the main thread); session-scoped summaries prevent bleed-through between sessions
- `core/memory/intent_graph.py` — Co-occurrence graph over conversation keywords, persisted to `.jarvis/intent_graph.json`. Powers speculative RAG pre-loading and proactive topic detection.
- `core/memory/backup.py` — Scheduled daily ChromaDB snapshot at 2am and 2:15am (memory + docs separately), keeps last 7 files, atomic temp-file write
- Hybrid search in `MemoryRouter.search()`: vector search → top-20 candidates → BM25 keyword re-rank → RRF fusion → top-5 returned
- `core/context/environment.py` — World state snapshot: foreground app, window title, clipboard content type classification (CODE_BLOCK/ERROR_TRACE/URL/PLAIN_TEXT), time, OS, hostname, battery %, network status, last active file. Stale-cache async refresh — never blocks caller.
- `core/session.py` — UUID session IDs, atomic persist via temp-file-rename, crash recovery from `.jarvis_sessions/`, named sessions (nova_work, nova_personal) with isolated histories and memories

**Milestone:** Close and reopen → name remembered. 100-turn conversation → no crash, no truncation. Exact-term recall via BM25 hybrid. Two sessions → fully isolated.

---

### ✅ PHASE 3 — Voice Layer
**Status: COMPLETE**

Full hands-free voice loop. Works fully offline. Supports Tamil and other languages.

- `voice/vad.py` — silero-VAD primary: detects speech start → buffers audio → detects 800ms silence → returns clip for STT. Energy fallback with pre-roll buffer when silero unavailable.
- `voice/wakeword.py` — Porcupine background thread. Wake word `.ppn` downloaded from picovoice.ai and placed in `assets/`. Self-mutes while NOVA is speaking to prevent echo feedback.
- `voice/stt.py` — Gemini STT online. Sends base64 audio with language hint. Falls back on non-200 response.
- `voice/stt_offline.py` — faster-whisper local. Model size configured via `WHISPER_MODEL`. Retries without language hint if code unrecognized.
- `voice/tts.py` — Priority chain: Gemini TTS → gTTS → pyttsx3. All paths support `stop_event` for barge-in interrupt. Audio played via afplay/mpg123/ffplay auto-selected.
- `voice/tts_offline.py` — pyttsx3 on single dedicated background thread with 10-second watchdog. Prevents runaway audio blocking shutdown.
- `voice/tts_indic.py` — Tamil gTTS with temp file output.
- `interfaces/voice_interface.py` — Full loop: wakeword → VAD captures until silence → STT (online/offline) → LLM stream → TTS (online/offline/Tamil). Barge-in via `ctrl+shift+x` hotkey stops speech and re-listens immediately. Capture thread join before restarting prevents audio device exhaustion.

**Milestone:** Say "Hey NOVA" → speak → responds after silence. Tamil → responds in Tamil. Offline → all local. Never cuts you off mid-sentence.

---

### ✅ PHASE 4 — Eyes (Screen Vision + Proactive)
**Status: COMPLETE**

NOVA sees your screen and acts before you notice problems.

- `vision/omniparser_server.py` — Lifecycle manager: on boot checks if OmniParser is running, auto-starts subprocess if not. Secret-free subprocess environment (only PATH/PYTHONPATH passed, never API keys). Random auth token generated per session. Exponential backoff polling up to 120s for startup. Auto-restart via health monitor.
- `vision/capture.py` — Backend selection at import time: mss (Wayland-compatible) → PIL.ImageGrab → scrot. `capture_periodic_png()` generator for continuous loop.
- `vision/gemini_vision.py` — Sends base64 screenshot to Gemini. Returns structured JSON: `{scene_type, detected_errors, active_app, notable_elements, suggested_actions}`.
- `vision/omniparser.py` — HTTP client to OmniParser `/parse/` endpoint. Returns UI elements with bounding boxes. 500ms TTL cache keyed by image hash to avoid redundant round-trips.
- `vision/watcher.py` — Background thread captures screen every 30s (configurable). Detects error keywords, crash dialogs, prompt injection in OCR text. Rate-limited: max 1 alert per 2 minutes. Calls `on_screen_state` callback for behavior model recording.
- Proactive phone watcher in `control/adb/watcher.py` — Screenshot + vision analysis + notification dump + SMS dump, all with SHA256 change-detection to avoid re-alerting on the same content.

**Milestone:** Boot → OmniParser auto-starts. Kill its process → health monitor restarts it within 60s. Error dialog appears → NOVA speaks up. Send screenshot to Telegram → analyzed.

---

### ✅ PHASE 5 — Hands + Documents (PC Control + RAG)
**Status: COMPLETE**

NOVA operates your PC autonomously and reads your documents intelligently.

- `core/tools/dispatcher.py` — Central tool hub. Every LLM tool call goes through here. Schema injection into every system prompt so LLM always knows available tools. Pydantic validation on every call — validation errors returned as structured JSON for LLM to retry. Non-blocking token bucket rate limiter (120 rpm default). Markdown fence stripping so LLM JSON wrapped in ```json still parses. Dry-run mode explains plan without executing.
- `control/mouse_keyboard.py` — Platform detection from `pc_profile.json` first, then runtime fallback. Windows: PyAutoGUI. macOS: Quartz CoreGraphics (no Accessibility permission needed for clicks). Linux X11: xdotool. Linux Wayland: ydotool → xdotool → pynput → PyAutoGUI. `click_element(name)` uses OmniParser bounding boxes — no hardcoded coordinates ever.
- `control/win32_api.py` — File read/write/move/delete/copy/search. Process list/kill/launch (shlex.split, no shell=True). Window list/focus/resize/close. Registry read/write. Clipboard get/set. Disk info. Cross-platform notifications.
- `control/browser.py` — Playwright sync only. `Browser` class with auto-reinit on any unexpected exception. Supports open/click/fill/extract_text/get_links/screenshot/wait_for_text. Context manager support.
- `web/search.py` / `web/scraper.py` / `web/crawler.py` — DuckDuckGo search, L1 HTML scraping, L3 JS-rendered (Playwright), L4 visual (screenshot + OmniParser). All protected by SSRF guard resolving hostnames against RFC1918 private IP ranges.
- `web/hybrid_ranker.py` — BM25 keyword score + Jaccard semantic score + RRF fusion. Returns re-ranked document list.
- `rag/doc_loader.py` / `rag/chunker.py` / `rag/doc_store.py` — PDF (pypdf), DOCX, TXT. Sentence-safe chunking with 64-token overlap. ChromaDB storage with filename metadata. Query by semantic similarity or keyword. Prompt-injection filtered chunks tagged `[Content from document (unverified)]`. Auto-ingested by FSWatcher on file change.

**Milestone:** "Open Chrome and find asyncio docs" → fully autonomous. "Read this PDF and summarize section 3" → ingests, queries, answers. Dangerous command → safety stub prompts for confirmation.

---

### ✅ PHASE 6 — Interfaces, Tray & Startup
**Status: COMPLETE**

NOVA on every surface, always running, with full visibility.

- `interfaces/gui/app.py` — PyQt6 streaming chat with PBKDF2 PIN auth. Image upload → Gemini Vision analysis → conversation context. One-shot mic capture and persistent voice loop with start/stop buttons. Session switcher, health panel, goal manager, alert log. 3-second status refresh timer. Input guard at 50,000 characters.
- `interfaces/telegram_bot.py` — Strict integer whitelist (`TELEGRAM_CHAT_ID`). Edit-based streaming simulates real-time output within Telegram rate limits (max 40 edits/min). Per-user rate limiting (12 commands/min, 2 heavy commands/min). Commands: `/status`, `/health`, `/session`, `/export`, `/goals`, `/goal`, `/resume_goal`, `/cancel_goal`, `/mute`, `/unmute`, `/usage`, `/usage_week`, `/screenshot`, `/qr`. Every rejected auth attempt is logged.
- `interfaces/tray.py` — pystray system tray with live tooltip: "Today: 42k tokens · 3 keys active · Online · Live · Goals: ...". Refreshed every 10 seconds. Menu: Open GUI, Switch Session (Work/Personal), Mute/Unmute, Goals, Alerts, Health, Export, Quit. OS notification via `os_layer`.
- `interfaces/voice_interface.py` — Complete VAD→STT→LLM→TTS pipeline. Configurable barge-in hotkey. Works offline with full feature parity.
- `utils/usage_tracker.py` — Per-provider, per-session, per-day tracking. 8-day rolling window. Debounced persistence every 2 seconds. Daily hard cap blocks all LLM calls when reached and resets at midnight. 80% warning alert via Telegram.
- `utils/exporter.py` — JSON and Markdown export. Regex-based secret redaction for `api_key`, `token`, `password`, `secret`, `access_key`, `auth_token` before writing.

**Milestone:** Boot → tray appears. Telegram only responds to your ID. "Typing cursor" effect in Telegram. Export → readable Markdown. Tray tooltip shows live usage.

---

### ✅ PHASE 7 — Scheduler, Goals & Autonomy
**Status: COMPLETE**

NOVA works for you while you're away.

- `tasks/scheduler.py` — APScheduler with SQLiteJobStore (survives restarts). Natural language → schedule via `parse_schedule_text`: "every 5 minutes", "daily at 8:00 am", "every Monday at 9:00 am". Add, list, cancel jobs.
- `tasks/goals.py` — `GoalRunner`: executes tool step lists with hard `max_steps` limit (default 20). Cycle detection via tool+args hash. Per-step risk check via guardrails — high-risk steps without `confirm_callback` are blocked. Configurable `step_delay_seconds` to prevent API hammering. Step timeout via `ThreadPoolExecutor` future with configurable deadline.
- Autonomous agent loop in `main.py::NOVAApp._autonomy_loop` — Polls pending goals, runs them via `autonomy_runner` with `force_confirm_medium=True` (all medium-risk steps require explicit confirm). On completion: saves outcome to memory, records to template library for future reuse, notifies via Telegram + TTS. On failure: attempts LLM replanning once, escalates to human on second failure.
- Background goal planning: LLM plan generation runs in `ThreadPoolExecutor` (never blocks the main thread). Inflight counter prevents queue exhaustion.
- `_plan_goal` with template shortcut: before calling LLM, checks `GoalTemplateLibrary` for a Jaccard-matched template (≥0.60 similarity). If found, skips LLM entirely.

**Milestone:** "Every morning at 8 summarize my emails" → runs next morning unattended. Long goal hits step limit → pauses and asks. Cycle detected → immediate abort with explanation.

---

### ✅ PHASE 8 — Android Control + QR Pairing
**Status: COMPLETE**

NOVA controls your Android from anywhere. Pair with a single QR scan.

- `control/adb/tailscale.py` — Detects if Tailscale is installed. If not → auto-installs via brew/winget/apt/dnf/pacman. Gets phone's Tailscale IP. Reconnects if tunnel drops.
- `control/adb/qr_pairing.py` — Mode detection: same network → local DHCP IP; remote → Tailscale IP. Generates `adb_connect://<ip>:5555` QR in terminal and as PNG. `enable_tcpip()` sets the ADB port.
- `control/adb/adb_client.py` — Full phone control: screenshot, tap, swipe, type (safe character escaping), launch app by package, keyevent, SMS send (ALLOWED_PHONE_NUMBERS allowlist), notifications dump, SMS dump. Per-device threading lock prevents concurrent ADB commands.
- `control/adb/watcher.py` — Background thread screenshots phone every 12s. Gemini Vision analyzes for calls, errors, notifications. SHA256 change detection avoids repeat alerts. `_poll_notifications()` and `_poll_sms()` track content changes independently. Cooldown 120s between alerts.

**Milestone:** Tray → "Show ADB QR" → scan → connected. "Send WhatsApp to [contact]" → done. Incoming call → NOVA announces it.

---

### ✅ PHASE 9 — Emotion Engine
**Status: COMPLETE**

NOVA has a personality that adapts to context.

- `core/emotion/engine.py` — 7 states: neutral, focused, concerned, enthusiastic, cautious, empathetic, urgent. Transitions from: conversation keywords (error/crash → urgent; stressed/sad → empathetic; great/success → enthusiastic). `predict_from_context()`: late-night long session → empathetic; 3+ recent errors → urgent; Monday/Tuesday 9-11am → focused; midday 12-2pm → cautious. `proactive_update()` applies trajectory prediction only when in neutral state.
- Emotion injected into every system prompt via `build_system_prompt(emotion=self.emotion.state)`.
- TTS prosody adapts via `_emotion_hint()` mapping in `voice/tts.py` (e.g. urgent → "urgent but controlled", empathetic → "warm and empathetic").
- Error detection counter tracked per hour; feeds into trajectory prediction.

**Milestone:** Error screen → tone goes urgent. Late-night casual chat → warm and relaxed. Completed long goal → genuinely enthusiastic.

---

### ✅ PHASE 10 — Master MCP, Master API & Plugins
**Status: COMPLETE**

Give NOVA any API key and it figures out the rest.

- `mcp/master_api.py` — API key auto-detection from prefix: `ghp_/github_pat_` → GitHub, `xoxb-` → Slack, `ntn_/secret_` → Notion, `sk-` → OpenAI, `AIza` → Google. `register()`, `get()`, `masked()`, `list_services()`.
- `mcp/master_mcp.py` — Connect to any MCP server: `connect_http()` with optional tool discovery, `connect_builtin()` for pre-wired services (GitHub, Notion, Slack, Linear, Google Drive, Jira, Home Assistant). Retry with exponential backoff on 429/5xx. Tool calling via `/tools/{name}/invoke`. Security: refuses Authorization header injection over plain HTTP to non-private addresses.
- Home Assistant connector — `get_state()`, `list_entities(domain)`, `call_service()`, `get_history()`. Connected via `<base_url>|<token>` format.
- `core/plugin_loader.py` — Scans `plugins/` on startup. AST checker blocks: `eval`, `exec`, `__import__`, `getattr`, `setattr`, `vars`, `locals`, `globals`, `__subclasses__`, and all `_`-prefixed modules. Runtime sandbox with restricted `__builtins__`. Tool name conflict detection with logging.
- `core/plugin_generator.py` — Full pipeline: LLM generates code → AST check → saved to pending dir → human approval (CLI or GUI) → written to `plugins/` → hot-loaded via `load_plugins()`. AST check runs twice (before and after approval).

**Milestone:** Give GitHub token → "List my open PRs" → done. Drop a plugin file → restart → new tool available. "Turn on living room lights" → Home Assistant executes.

---

### ✅ PHASE 11 — Safety Layer
**Status: COMPLETE**

NOVA never acts destructively without explicit confirmation.

- `safety/guardrails.py` — Risk scorer 0-10 on every tool call. Score built from: base 2, +1 for win32_api/adb/browser tools, +1 for write/move/send keywords in name or args, +3 for delete/kill/format/registry keywords, +capped at 9 for system path writes (System32, /etc, /usr/bin), max 9 for destructive tool list.
- Registry allowlist: `win32_api.registry_write` only allowed to `HKEY_CURRENT_USER\SOFTWARE\NOVA` and `HKEY_CURRENT_USER\ENVIRONMENT`. All other paths → blocked=True.
- Low (0-3): silent execution. Medium (4-6): show plan, 5s countdown, auto-confirm. High (7-10): explicit confirmation required, no timeout.
- Emergency stop: `guardrails.emergency_stop()` persists flag to `.jarvis/emergency_stop` file. Survives restarts. `NOVA stop` voice/text command activates it. `Ctrl+Shift+X` hotkey also triggers it. Cleared by `guardrails.clear_emergency_stop()` or `/safety clear_stop` command.
- Action log: every tool call logged as JSONL to `logs/guardrails_actions.jsonl` via loguru with 10MB rotation and 7-day retention. Sensitive args (`api_key`, `token`, `password`, etc.) scrubbed to `***REDACTED***` before writing.

**Milestone:** "Delete Downloads folder" → reads full plan, waits for "confirm". Emergency stop mid-execution → immediate halt. Registry write to Run key → permanently blocked.

---

### ✅ PHASE 12 — Offline Polish & Health Monitor
**Status: COMPLETE**

Nothing silently breaks. Full parity offline.

- `core/health.py` — `HealthMonitor` with `register_subsystem(name, check_fn, restart_fn)`. Polls every 60s. Dead → restart_fn called. Recovery verification after 5s wait. Max 3 restart attempts before marking `restart_failed`. Cooldown period of 300s before retrying after max attempts. `on_change` callback fires only on status transitions (not on every poll). `status_table()` returns snapshot.
- Registered subsystems in `main.py`: nova, network, memory_router, mem0_client, scheduler, tailscale, omniparser, llm_engine, screen_watcher, phone_watcher, autonomy_loop, probe_server, adb.
- LLM engine health check: tries `/api/tags`, `/health`, `/v1/models` on Ollama base URL. On failure: spawns `ollama serve` subprocess if not already running (prevents duplicates via pgrep check).
- Network monitor: `memory.set_online()` updated before every `ask_stream` call. Memory router queues writes offline and syncs on reconnect.
- Health HTTP probe server on `127.0.0.1:8765` (configurable). `/health` and `/ready` return `{"status":"ok"}`. Used by Docker HEALTHCHECK.

**Milestone:** Kill any subsystem → restarted within 60s. Unplug ethernet → all features continue locally. Reconnect → syncs without duplicates.

---

### ✅ PHASE 13 — Cross-OS, Tests & Hardening
**Status: COMPLETE**

Linux/Mac-ready foundation. One-command install. Full test coverage.

- `control/os_layer.py` — `get_foreground_app()` on Win32/macOS/Linux. Windows now uses Win32 foreground-window title first, then PowerShell fallback. `send_notification()` via win10toast (preferred) or PowerShell fallback on Windows, osascript on macOS, notify-send on Linux. `startup_command()` builds shell wrapper. `register_startup()` writes systemd service / launchd plist / Windows schtask.
- `control/window_manager.py` — Backend routing: Win32 (pywin32) / macOS (osascript) / Linux (xdotool → wmctrl) / NoOp. `list_windows()`, `focus()`, `resize()`, `close()` all return uniform dict.
- `control/mouse_keyboard.py` — Runtime routing finalized:
  - Windows: `pyautogui`
  - macOS: Quartz CoreGraphics
  - Linux X11: `xdotool` (preferred)
  - Linux Wayland: `ydotool` → `xdotool` → `pynput` → `pyautogui`
  - Cross-platform fallback: `pynput` backend implemented and wired.
- `control/macos_permissions.py` — Checks `AXIsProcessTrusted()` for Accessibility and `CGWindowListCopyWindowInfo()` for Screen Recording. Logs clear warning with System Settings path if missing.
- `setup.py` — Installs Python deps, Playwright Chromium, faster-whisper model, OmniParser (clone + weights from Hugging Face), Ollama model pull, wake word reminder, startup registration, post-install health checks.
- `install.sh` — Detects macOS/Debian/Arch/Fedora. Installs system packages (including `xdotool`, `ydotool`, `wmctrl`, and Linux notify dependencies), creates venv, runs PC scanner, installs core + optional packages based on profile.
- Test suite: 40+ unit and integration tests covering LLM engine, memory router, dispatcher, hybrid ranker, guardrails, context trimmer, session manager, goals, usage tracker, health, events, tray, GUI status, voice TTS, ADB tools, screen watcher, master MCP, master API, and more.

**Milestone:** `python setup.py` on fresh machine → NOVA running in <5 minutes. All tests pass.

---

### 🔲 PHASE 14 — Universal Installer, BYOK UI & Privacy Config
**Status: PLANNED**

Zero-friction setup for non-technical users on any OS.

**One-Command Universal Installer:**

- `install.sh` already handles macOS/Linux. New: `install.bat` (PowerShell) for Windows that auto-installs Python 3.12 via winget if missing, creates venv, runs all setup steps.
- GUI installer option: if `--gui` flag passed (or detected as desktop environment), launch a minimal tkinter/PyQt6 wizard instead of terminal prompts.
- Automatic dependency conflict resolution: compare installed packages against `requirements.lock`, report mismatches with `pip install --upgrade` fix suggestions.
- Progress bar with per-step status (Python ✓, Ollama ✓, Whisper ✓, etc.).

**Interactive Setup Wizard (5 Questions):**

Upgrade `interfaces/onboarding.py` to a PyQt6 wizard with 5 screens:

1. **Who are you?** — Name, occupation/context, timezone.
2. **How do you want to talk?** — Text only / Voice with wake word / Voice always-on.
3. **Which language?** — Dropdown: English, Tamil, Hindi, etc. Auto-configures `DEFAULT_LANG` + Whisper model size.
4. **Privacy level?** — Local-only (no mem0, no Gemini, Ollama only) / Balanced (local memory + cloud LLM) / Full cloud. Writes `MEM0_API_KEY` based on choice.
5. **Which apps do you use?** — Checkboxes for GitHub, Slack, Notion, Home Assistant, Telegram. Pre-fills BYOK fields.

Writes SOUL.md, `.env`, and saves `config/onboarding_complete` flag.

**BYOK In-App Key Manager:**

New `interfaces/key_manager.py` with PyQt6 dialog and Telegram `/keys` command:

- Add/remove keys for: OpenAI, Gemini, Groq, Cerebras, Anthropic (future), mem0, Telegram, Porcupine, VirusTotal.
- Keys stored encrypted in `.jarvis/keystore.enc` using Fernet (user-set master password hashed with PBKDF2).
- Shows masked key values (`sk-...abc123`).
- "Test key" button: makes a minimal API call and shows latency + status.
- "Round-robin pool" builder: add multiple keys per provider, NOVA load-balances automatically.

**Privacy-First Config:**

Add `PRIVACY_MODE` enum to `config/settings.py`:

- `local_only` — disables all cloud calls (no Gemini, no mem0, no Telegram). Forces Ollama + ChromaDB + pyttsx3 + faster-whisper.
- `balanced` — cloud LLM + local memory (no mem0 cloud sync).
- `full_cloud` — all services enabled (current default).

Per-session override: `NOVA use local mode` or `NOVA use cloud mode` text command switches mode for the current session without changing the global setting.

**System Deep Scan Upgrade:**

Extend `config/pc_scanner.py` with:

- Windows: winget package list, registry-detected installed software, Windows version and feature flags.
- macOS: `system_profiler SPApplicationsDataType`, `brew list --formula`, available Xcode tools.
- Linux: `dpkg -l`, `rpm -qa`, `pacman -Q`, snap list, flatpak list.
- Network: detect home/work SSID, LAN topology, open ports on loopback.
- Full results written to `config/pc_profile.json` schema v3.

**STT/TTS Config UI:**

New settings panel in GUI for voice engine selection per language:

- STT: Gemini (online) / faster-whisper base/small/medium/large / PicoVoice (premium).
- TTS: Gemini (online, voice selector) / gTTS / pyttsx3 (offline, speed/pitch) / IndicTTS (Tamil premium).
- Voice test button plays a sample phrase through the selected engine.

**Milestone:** `curl -fsSL https://nova.sh/install | bash` on any OS → wizard opens → 5 questions → fully running. Non-technical user never touches a config file. Local-only mode: zero bytes leave the machine.

---

### 🔲 PHASE 15 — Bug Fixes, VirusTotal & Model Manager
**Status: PLANNED**

All 20 documented bugs fixed. Threat scanning. Model management UI.

**All 20 Documented Bugs from fix.txt:**

1. `ask_stream` finally block double-appends history turn — gate on `not user_added`
2. `_hard_cap_hit` never resets next day — `_is_hard_cap_active_today()` compares date, already partially fixed, complete the fix
3. `_goal_plan_jobs_inflight` only decremented on exception — move decrement outside `if exc` to `finally`
4. `session._persist_session` called inside `session._lock` with disk I/O — move persist call outside lock entirely
5. `_summarize_history_background` calls LLM while holding `trimmer._lock` — release lock before LLM call
6. Two concurrent `ensure_running` calls spawn duplicate OmniParser processes — acquire `_proc_lock` at function entry
7. `shutdown` calls `_autonomy_execution_lock.release()` unconditionally — check acquire return value first
8. `background_plan` sets goal to `pending` without checking if `cancelled` — add cancelled status guard
9. `json.dumps(result)` crashes on non-serializable tool output — try/except with `str()` fallback
10. `_plan_goal` calls `engine.ask` after hard cap hit — add cap check inside retry loop
11. `LocalMemoryStore.add` dedup check and insert not atomic — hold `_insert_lock` across both operations
12. `switch_session` browser close miss on `_browser_needs_reset` when timeout — fix the flag setting
13. `export_session` two exports same second overwrite — nonce already in filename, ensure session_id in name
14. `_usage_alerted_day` never resets between days — compare against `date.today()` each call
15. `GoalRunner.close` races with `run` submit — wrap submit in try/except RuntimeError
16. `_notify_telegram` inside `_interactive_confirm` can block executor — add explicit timeout=3 to that call
17. `capture_screen_png` returns empty bytes wasting Gemini quota — guard with `if not image_bytes: return`
18. `_sync_all_inflight` stays True if executor submit raises — reset flag in except block
19. `run_voice_loop` spawns capture thread without joining previous — join previous before starting new
20. `background_plan` in `_resume_goal` never decrements counter — add finally block with decrement

**VirusTotal Integration:**

New `safety/virus_scanner.py`:

- Online mode: VirusTotal API v3. `scan_file(path)` → uploads file hash first (`/files/{hash}`), if not cached → uploads file → polls report until complete. Returns `{safe: bool, detections: int, total_engines: int, permalink: str}`.
- Offline mode: local heuristic engine. Checks file entropy (high entropy = likely packed/encrypted), suspicious PE section names, embedded URLs in executables, hardcoded IP addresses, known bad string patterns.
- Integration points: `_doc_ingest()` scans uploaded documents before RAG ingest. `plugin_generator.py` scans generated plugin code as a text buffer before writing to disk. `win32_api.write()` optionally scans content if `VIRUSTOTAL_SCAN_WRITES=true`.
- New tool: `safety.scan_file(path)` — LLM can request a file scan explicitly.
- Config: `VIRUSTOTAL_API_KEY` in `.env`. If empty, online scan silently skipped, local heuristic still runs.

**Model Manager:**

New `interfaces/model_manager.py` with GUI panel and CLI `/models` command:

- List installed Ollama models with size, last used, parameter count.
- Pull new model: shows progress via `ollama pull --stream` output.
- Delete model: with confirmation dialog.
- Cloud key pool manager: add/remove/test keys per provider (OpenAI/Gemini/Groq). Shows per-key status (active/rate_limited/dead) from `RoundRobinPool.snapshot()`.
- Benchmark: sends a standard test prompt to each provider, measures latency and token rate, shows comparison table.
- Auto-switch recommendation: based on `tool_profiler.py` latency stats, suggests the fastest reliable provider for the current use case.

**Milestone:** All 20 bugs fixed. VirusTotal blocks a malicious file from being ingested. Model manager shows all keys with health status. Benchmark identifies the fastest provider.

---

### 🔲 PHASE 16 — Self-Learning, Ambient Audio & Proactive Missions
**Status: PLANNED**

NOVA gets smarter with every interaction and runs autonomously on schedules.

**Self-Learning Feedback Loop:**

New `core/think/self_evaluator.py`:

- After every `ask_stream` call completes, silently rates the response quality on 3 dimensions: relevance (did it address the question?), actionability (are there concrete next steps?), conciseness (is it appropriately brief?).
- Rating is a short LLM call with a structured prompt that returns a JSON score 0-10 for each dimension plus a one-sentence improvement note.
- Scores stored in `.jarvis/response_ratings.jsonl` with session ID, prompt hash, and ratings.
- Weekly aggregation: average scores per dimension per session type, fed into `PromptEvolver.propose_variant()` as additional signal alongside `InsightExtractor` output.
- Threshold: only rates responses longer than 50 tokens to avoid wasting tokens on short answers.
- Budget aware: skipped if today's token usage > 90% of `DAILY_TOKEN_ALERT_THRESHOLD`.

**Proactive Nudge Engine:**

New `core/think/nudge_engine.py`:

- Tracks time spent on the same task type (detected from `IntentGraph` dominant topic and screen watcher `active_app`).
- After 2 continuous hours on the same task type: sends gentle break reminder via TTS + Telegram.
- After 4 hours: more insistent, offers to save context summary and resume later.
- Break detection: if screen goes idle (no clicks/keypresses for 5 minutes) or app switches to music/browser/video, resets the timer.
- User can disable nudges: `NOVA no nudges today` command sets a daily mute flag.
- Context preservation: before nudging, auto-exports current session to `exports/` as backup.

**Ambient Audio Monitor:**

New `voice/ambient_listener.py`:

- Always-on background thread (lower than VAD sensitivity — not waiting for speech, just listening for audio events).
- Keyword patterns: configurable list of trigger words in `.env` (`AMBIENT_KEYWORDS=doorbell,alarm,phone`).
- Sound event detection: phone ring pattern (periodic tones), alarm beep patterns, doorbell chime.
- Alert routing: detected event → `_handle_proactive_alert()` with event type and confidence.
- Privacy guarantee: audio is never recorded or stored; only real-time pattern matching with no buffering beyond one frame.
- Activated only when `AMBIENT_MONITOR_ENABLED=true` in `.env` and microphone is available.

**Scheduled Autonomous Missions:**

Upgrade `tasks/scheduler.py` with a Mission concept:

- A Mission is a named recurring goal: `{"name": "morning_brief", "schedule": "daily at 8:00 am", "goal": "Summarize last night's emails, check weather for today, and give me a 2-minute briefing.", "enabled": true}`.
- Missions stored in `.jarvis/missions.json`.
- New commands: `NOVA schedule mission [name] every [schedule] to [goal description]`, `/mission list`, `/mission enable morning_brief`, `/mission disable morning_brief`.
- On trigger: creates a goal via `_add_goal()` which triggers full autonomous planning and execution. No wake word needed; NOVA acts proactively.
- Mission results delivered via Telegram + TTS when complete.
- Built-in mission templates: morning_brief, daily_backup, weekly_summary, code_review_check.

**Milestone:** NOVA silently rates its own responses and improves over time. After 2 hours on the same task → "Want to take a break?". Phone rings in background → NOVA announces it. "Every morning at 8 brief me" → runs autonomously forever.

---

### 🔲 PHASE 17 — A2A Collaboration, Dynamic UI & Smart Home
**Status: PLANNED**

Teams of NOVAs working together. Adaptive interface. Full smart home control.

**Agent-to-Agent (A2A) Team Collaboration:**

New `core/a2a/` module:

- `peer_registry.py` — Discovers other NOVA instances on LAN via mDNS (`_nova._tcp.local`). Each peer advertises: agent name, current session, available tools, and a capabilities hash. Tailscale peers auto-discovered via Tailscale API.
- `shared_memory_bus.py` — Redis (optional) or file-based shared memory bus at `.jarvis/shared_bus.jsonl`. Peers can write `{from, to, type, payload}` messages. Types: `context_sync`, `tool_delegation`, `status_update`, `conflict_alert`.
- `role_manager.py` — Each peer self-assigns a role based on capabilities: Developer (has Python REPL + git), Reviewer (has code analysis tools), Tester (has pytest + coverage), Documenter (has RAG + export). Roles are advisory — any peer can perform any action.
- `conflict_resolver.py` — Detects when two peers are about to modify the same file. Sends a `conflict_alert` to both, pauses the lower-priority action (alphabetically by agent name for determinism), notifies both users.
- Tool delegation: if peer A doesn't have a required tool (e.g., ADB) but peer B does, peer A can delegate the tool call to peer B via `mcp.call_tool("peer_b", "adb.tap", {...})`.
- Shared context sync: after each conversation turn, hash of last 3 turns pushed to shared bus. Peers can query current context of any teammate.
- Daily standup generation: each peer summarizes its last 24h activity log; one designated peer aggregates and posts the full team standup to Slack/Telegram.
- Privacy: personal memories are NEVER shared on the bus. Only task context and tool results are shared. Opt-in with `A2A_ENABLED=true` in `.env`.

**Dynamic UI Skin Engine:**

Upgrade `interfaces/gui/app.py` with a theme manager:

- `utils/theme_engine.py` — computes the current theme based on: hour of day (dark mode after 8pm, light mode 8am-6pm), detected task type from IntentGraph dominant topic (focus/deep work → minimal distraction mode, coding → solarized dark, reading → warm/sepia), emotion state (urgent → high-contrast red accent, empathetic → soft blue).
- Theme applied via PyQt6 stylesheet injection at a 30-second check interval.
- Themes: `default`, `focus`, `coding`, `reading`, `evening`, `urgent`.
- User can lock a theme: `/theme focus` disables auto-switching.

**Enhanced Smart Home (Home Assistant):**

Extend `mcp/master_mcp.py` Home Assistant connector:

- `list_automations()` — lists HA automations.
- `trigger_automation(automation_id)` — fires an automation.
- `set_climate(entity_id, temperature)` — sets thermostat.
- `get_energy_stats(period)` — fetches energy dashboard data.
- Context-aware actions: if "leaving home" intent detected in conversation → NOVA offers to lock doors, set alarm, adjust thermostat.
- Presence integration: if ADB confirms phone is on home WiFi → NOVA knows user is home and adjusts notifications accordingly.

**Milestone:** Two NOVA instances on a team LAN collaborate on a coding task: Dev NOVA writes code, Reviewer NOVA reviews it, Tester NOVA runs tests, Documenter NOVA updates README. No file conflicts. Daily standup auto-posted to Slack. NOVA changes to calm blue theme at night and switches to high-contrast red when an error is detected.

---

## The 6 Laws of Building NOVA

1. **Never skip the test milestone** — if the milestone doesn't pass, the next phase breaks harder
2. **LLM is the orchestrator, not the executor** — LLM decides what to do, modules do the actual work. Never execute raw LLM-generated Python
3. **All tool calls go through dispatcher.py** — no module callable directly by LLM, only through validated dispatcher with schema injection
4. **memory_router is always on from Phase 2** — every phase reads/writes memories from day one
5. **World state is always in the prompt** — environment snapshot + session memories in every single LLM call
6. **One engine, many interfaces** — CLI, GUI, Voice, Telegram all call the same `core/` modules. Zero logic duplication across interfaces

---

## Proactive Intelligence Architecture (5 Tiers)

NOVA's proactive intelligence layer runs entirely in background threads and scheduled jobs. It has 5 tiers, all of which are already partially or fully implemented.

### Tier 1 — Real-Time Context Sensing
These fire on every event without LLM calls:
- **FSWatcher** (`core/context/fs_watcher.py`) — Detects file changes and git commits. Auto-re-ingests changed docs. Stores commit messages as memories.
- **NetworkContextDetector** (`core/llm/network_context.py`) — Every 5 minutes checks DNS suffix to determine work vs home network. Auto-switches session on change.
- **Process Monitor** (in `main.py` scheduler job) — Every 60 seconds, detects newly launched processes. Zoom/Teams → mutes NOVA, sets `cautious` emotion. OBS → recording context. Docker → containerized workload context.
- **ScreenWatcher** (`vision/watcher.py`) — Captures and analyzes screen every 30s. Reports errors, crashes, injection attempts.
- **ClipboardClassifier** (`core/context/environment.py`) — Classifies clipboard content as CODE_BLOCK/ERROR_TRACE/URL/PLAIN_TEXT on every world state snapshot.

### Tier 2 — Behavioral Pattern Learning
These learn over time using lightweight ML:
- **BehaviorModel** (`utils/behavior_model.py`) — Tracks LLM call patterns by weekday + hour. Predicts next likely activity with confidence score.
- **IntentGraph** (`core/memory/intent_graph.py`) — Co-occurrence graph of conversation keywords. Identifies hot topics. Powers speculative RAG pre-loading.
- **EmotionEngine trajectory** (`core/emotion/engine.py`) — `predict_from_context()` uses hour, weekday, error count, session length to predict emotional state.
- **InsightExtractor** (`utils/insight_extractor.py`) — Sunday 2:30am: cross-session analysis via LLM → 5 recurring themes. Surfaced Monday morning on first activity.
- **CommitmentExtractor** (`utils/commitment_extractor.py`) — Extracts deadlines from every user message using 5 regex patterns. Stores in memory with `deadline_ts` metadata. Reminder job fires daily at 9am.

### Tier 3 — Proactive Assistance
These take actions before being asked:
- **ProactiveGoalEngine** (`core/goals/proactive_goal_engine.py`) — Proposes goals from BehaviorModel predictions, git commits, and context transitions. 5-minute grace period before auto-approval (if risk < 4 and AUTONOMY_ENABLED). User can cancel via Telegram.
- **AttentionQueue** (in `main.py`) — Non-urgent alerts during focus time go to `_queued_alerts` deque instead of immediate notification. Drained every 60 seconds if user seems available.
- **SpeculativePrefetch** (in `main.py`) — `IntentGraph.build_rag_query_hints()` generates keywords → `docs.query()` pre-loads likely relevant documents into memory before user asks.
- **CommitmentReminder** — Scheduler job fires daily at 9am. Checks memory for commitments with `deadline_ts` within 48 hours.

### Tier 4 — Autonomous Self-Maintenance
These keep NOVA healthy without any user interaction:
- **MaintenanceOrchestrator** (`tasks/maintenance.py`) — Nightly at 3am: disk check, export cleanup (30-day retention), log compression (>50MB → gzip), memory sync, ChromaDB backup, health verification.
- **GoalOutcomeLearning** (in `main.py::_auto_document_goal_outcome`) — After every completed multi-step goal: stores a 2-sentence summary in memory for future context.
- **GoalFailureReplanning** (in `main.py::_handle_goal_failure`) — On first failure: generates one alternative step via LLM and inserts it. On second failure: escalates to human via Telegram.
- **PresenceManager** (`utils/presence_manager.py`) — Routes notifications by urgency: high → all channels (Telegram + Slack), medium → Telegram only, low → internal event log only. Per-channel rate limiting.

### Tier 5 — Continuous Self-Improvement
These improve NOVA's capabilities over time without manual intervention:
- **GoalTemplateLibrary** (`core/goals/template_library.py`) — Records successful goal executions. After 2 successes for a similar goal, creates a template. Future similar goals skip LLM planning entirely.
- **ToolProfiler** (`utils/tool_profiler.py`) — Tracks per-tool success rate, latency, failure reasons from guardrails action log. Injects reliability warnings into the goal planner prompt. Detects frequently co-occurring tool sequences as candidates for plugin synthesis.
- **PromptEvolver** (`core/think/prompt_evolver.py`) — After weekly insights, proposes a SOUL.md suffix variant. A/B tests it on 1-in-5 sessions. If +5% goal success rate → graduates to SOUL.md permanently. If -10% → retired immediately.
- **SelfEvaluator** (PLANNED `core/think/self_evaluator.py`) — Silent post-turn response rating. Feeds into weekly insight pipeline.

---

## Autonomy Loop — How It Works End-to-End

```
User says: "Every morning at 8 summarize my emails and brief me"
  ↓
task.schedule tool → scheduler adds daily cron job
  ↓
Next morning at 8am, scheduler fires _run() callback
  ↓
_add_goal("Summarize emails and brief me") called
  ↓
background_plan() → LLM generates step list (or template match skips LLM)
  ↓
Goal status: planning → pending
  ↓
_autonomy_loop() picks up pending goal
  ↓
autonomy_runner.run() executes each step:
  - guardrails.check() per step (risk score)
  - If medium → force confirm (autonomy mode)
  - If high → pauses, notifies Telegram, waits for /approve_goal
  - If low → executes immediately
  ↓
Each step result stored, cursor advanced
  ↓
On completion:
  - _auto_document_goal_outcome() stores 2-sentence memory
  - _template_library.record_success() saves step sequence
  - _prompt_evolver.record_goal_outcome() records success signal
  - Telegram + TTS notification sent
  ↓
Next morning: template match skips LLM planning entirely
```

---

## Complete Build Order (All 17 Phases)

```
Phase  1  →  Core Engine + CLI + Streaming + Ask Questions + Multi-key RoundRobin + Config Validation ✅
Phase  2  →  Memory (mem0 + ChromaDB) + Context Trimmer + Hybrid Search + Sessions + Dedup ✅
Phase  3  →  Voice (VAD + STT + TTS) + Tamil Support + Offline Voice Fallback ✅
Phase  4  →  Vision + OmniParser Lifecycle + Proactive Watcher + Multi-modal Input ✅
Phase  5  →  PC Control + Tool Dispatcher + Browser (sync) + Web + RAG ✅
Phase  6  →  GUI + Telegram (auth + streaming) + Tray + Startup + Usage Tracker + Exporter ✅
Phase  7  →  Scheduler + Goals + Autonomy (max_steps guard + cycle detection) ✅
Phase  8  →  Android (ADB + Tailscale + QR Pairing + Phone Watcher) ✅
Phase  9  →  Emotion Engine + trajectory prediction ✅
Phase 10  →  Master MCP + Master API + Plugin Architecture + HA connector ✅
Phase 11  →  Full Safety Layer (guardrails + registry allowlist + emergency stop persistence) ✅
Phase 12  →  Offline Polish + Memory Sync + Health Monitor + Nightly Maintenance ✅
Phase 13  →  Cross-OS Abstraction + Full Test Suite + One-command Installer ✅
Phase 14  →  Universal Installer + BYOK UI + Privacy Config + STT/TTS Config + Deep System Scan 🔲
Phase 15  →  All 20 Bug Fixes + VirusTotal Scanner + Model Manager UI 🔲
Phase 16  →  Self-Learning Feedback + Proactive Nudge + Ambient Audio + Mission Scheduler 🔲
Phase 17  →  A2A Team Collaboration + Dynamic UI Skin Engine + Enhanced Smart Home 🔲
```

---

## Proactive Intelligence Scheduled Jobs

| Job ID | Schedule | What It Does |
|---|---|---|
| `emotion_traj` | Every 10 min | Updates emotion state from hour/weekday/errors/session length |
| `proc_mon` | Every 60 sec | Detects newly launched processes, adjusts context |
| `maint_daily` | Daily 3:00 AM | Disk check, log compress, export cleanup, backup, health |
| `insight_weekly` | Sundays 2:30 AM | Cross-session LLM analysis → 5 recurring themes |
| `drain_alerts` | Every 60 sec | Flushes queued non-urgent alerts if user seems available |
| `commit_remind` | Daily 9:00 AM | Checks commitment deadlines within 48 hours |
| `nova_memory_backup` | Daily 2:00 AM | ChromaDB memory snapshot → exports/memory/ |
| `nova_docs_backup` | Daily 2:15 AM | ChromaDB docs snapshot → exports/docs/ |

---

## All Registered Tools (Dispatcher Schema)

### Web & Search
| Tool | Args | Description |
|---|---|---|
| `web.search` | `query, max_results=5` | DuckDuckGo search |
| `web.scrape` | `url` | L1 HTML text scrape (SSRF guarded) |
| `web.scrape_js` | `url` | L3 Playwright JS-rendered scrape |
| `web.scrape_visual` | `url` | L4 Screenshot + OmniParser UI elements |
| `web.crawl` | `seed_url, max_pages, max_depth` | BFS crawl with robots.txt |

### Documents (RAG)
| Tool | Args | Description |
|---|---|---|
| `doc.ingest` | `filepath` | Load PDF/DOCX/TXT into ChromaDB |
| `doc.query` | `question, filename?, top_k` | Semantic + keyword search |
| `doc.list` | — | List all ingested documents |

### File System
| Tool | Args | Description |
|---|---|---|
| `win32_api.read` | `path` | Read file text |
| `win32_api.write` | `path, content` | Write file (creates dirs) |
| `win32_api.move` | `src, dst` | Move/rename file |
| `win32_api.delete` | `path` | Delete file or directory |
| `win32_api.copy` | `src, dst` | Copy file |
| `win32_api.search` | `root, name_pattern, content_query, max_depth, max_results` | Search files |

### Process & System
| Tool | Args | Description |
|---|---|---|
| `win32_api.list_processes` | — | List running processes |
| `win32_api.kill_process` | `name_or_pid` | Kill process |
| `win32_api.launch_process` | `command` | Launch (shlex, no shell=True) |
| `win32_api.get_clipboard` | — | Read clipboard |
| `win32_api.set_clipboard` | `text` | Write clipboard |
| `win32_api.disk_info` | `paths?` | Disk usage stats |
| `win32_api.send_notification` | `title, message` | OS toast notification |

### Windows (Windows-only)
| Tool | Args | Description |
|---|---|---|
| `win32_api.list_windows` | — | List visible windows |
| `win32_api.focus_window` | `title` | Bring window to foreground |
| `win32_api.resize_window` | `title, width, height` | Resize window |
| `win32_api.close_window` | `title` | Close window |
| `win32_api.registry_read` | `path, name` | Read registry value |
| `win32_api.registry_write` | `path, name, value, value_type` | Write registry (allowlisted paths only) |

### Cross-Platform Window Manager
| Tool | Args | Description |
|---|---|---|
| `window.list` | — | List windows (all platforms) |
| `window.focus` | `title` | Focus window (all platforms) |
| `window.resize` | `title, width, height` | Resize window (all platforms) |
| `window.close` | `title` | Close window (all platforms) |

### Mouse & Keyboard
| Tool | Args | Description |
|---|---|---|
| `mouse.click` | `x, y` | Click at coordinates |
| `mouse.click_element` | `name` | Click element by name (OmniParser) |
| `mouse.scroll` | `clicks` | Scroll wheel |
| `mouse.drag` | `start_x, start_y, end_x, end_y, duration` | Drag |
| `keyboard.type_text` | `text` | Type text |
| `keyboard.hotkey` | `keys` | Press hotkey combination |

### Browser
| Tool | Args | Description |
|---|---|---|
| `browser.open` | `url` | Navigate to URL |
| `browser.click` | `selector` | Click CSS/XPath selector |
| `browser.fill` | `selector, value` | Fill form field |
| `browser.extract_text` | — | Get page body text |
| `browser.get_links` | — | Get all page links |
| `browser.wait_for_text` | `text, timeout_ms` | Wait for text to appear |
| `browser.screenshot` | `path` | Screenshot current page |
| `browser.close` | — | Close browser |

### ADB / Android
| Tool | Args | Description |
|---|---|---|
| `adb.connect` | `host, port` | Connect ADB to device |
| `adb.devices` | — | List connected devices |
| `adb.tap` | `x, y` | Tap screen |
| `adb.swipe` | `x1, y1, x2, y2, duration_ms` | Swipe |
| `adb.type_text` | `text` | Type text on device |
| `adb.launch_app` | `package_name` | Launch Android app |
| `adb.keyevent` | `key_code` | Send key event |
| `adb.pull` | `remote_path, local_path` | Pull file from device |
| `adb.push` | `local_path, remote_path` | Push file to device |
| `adb.send_sms` | `phone_number, body` | Send SMS (allowlisted numbers only) |
| `adb.notifications_dump` | — | Dump Android notifications |
| `adb.sms_dump` | — | Dump recent SMS |
| `adb.screenshot_to_local` | — | Screenshot phone to local file |
| `adb.qr_generate` | `out_path, prefer_remote` | Generate ADB QR code |
| `adb.qr_terminal` | `prefer_remote` | Show QR in terminal |
| `adb.reload_tools` | — | Re-detect ADB and register tools |

### Scheduling & Goals
| Tool | Args | Description |
|---|---|---|
| `task.schedule` | `schedule_text, prompt, job_id?` | Schedule recurring LLM task |
| `task.list` | — | List scheduled jobs |
| `task.cancel` | `job_id` | Cancel scheduled job |
| `goal.run` | `goal, steps, max_steps, dry_run` | Run goal immediately |
| `goal.add` | `goal, max_steps` | Queue goal for autonomous execution |
| `goal.list` | — | List all goals |
| `goal.cancel` | `goal_id` | Cancel goal |
| `goal.resume` | `goal_id` | Resume paused/failed goal |

### MCP / Integrations
| Tool | Args | Description |
|---|---|---|
| `mcp.register_api_key` | `service, api_key` | Register API key |
| `mcp.connect` | `service, endpoint?, api_key?, headers?, timeout_seconds, discover` | Connect MCP service |
| `mcp.services` | — | List connected services |
| `mcp.tools` | `service?` | List tools for service |
| `mcp.call_tool` | `service, tool_name, args` | Call MCP tool |

### Safety
| Tool | Args | Description |
|---|---|---|
| `safety.emergency_stop` | — | Activate emergency stop |
| `safety.clear_stop` | — | Clear emergency stop |
| `safety.status` | — | Check emergency stop state |

### Session & Assistant
| Tool | Args | Description |
|---|---|---|
| `session.switch` | `name` | Switch to named session |
| `session.export` | `format` | Export session (md/json) |
| `assistant.set_mute` | `muted` | Set mute state |
| `assistant.mute_status` | — | Check mute state |

### Proactive Intelligence
| Tool | Args | Description |
|---|---|---|
| `behavior.profile` | — | Behavioral rhythm prediction |
| `tool.stats` | — | Tool reliability statistics |
| `intent.graph` | — | Intent co-occurrence graph summary |
| `goal.templates` | — | Learned goal templates list |
| `insight.weekly` | — | Trigger weekly cross-session analysis |

### Plugin System
| Tool | Args | Description |
|---|---|---|
| `plugin.generate` | `description` | Generate + approve + load new plugin |

---

## Security Model

### Tool Call Security
- Every tool call validated through Pydantic schema before execution
- Risk scoring 0-10 on every call; high-risk requires explicit confirmation
- Registry writes blocked except to NOVA's own allowlisted paths
- System path writes (System32, /etc) always score 9+ regardless of tool name
- Sensitive args scrubbed from all logs (`api_key`, `token`, `password`, `secret`)

### Prompt Injection Defense
- `detect_prompt_injection()` in `core/think/reasoning.py` checks 11 patterns
- Applied to: user messages (before LLM), web scraped content (before RAG), screen OCR text (before watcher alert), memory writes (before storage)
- Injection detected → content flagged with `[filtered]` prefix, never executed

### Plugin Sandbox
- AST check before exec: blocks `eval`, `exec`, `__import__`, `getattr`, `setattr`, `vars`, `locals`, `globals`, `__subclasses__`, all `_`-prefixed imports
- Runtime restricted `__builtins__` (30 safe functions only)
- Human approval required before any generated plugin is written to disk
- Second AST check at runtime during `exec`

### API Key Security
- Keys never passed to subprocess environments (OmniParser server gets PATH only)
- Keys masked in all logs and status outputs
- Encrypted keystore in Phase 14 (PBKDF2 + Fernet)
- No keys hardcoded anywhere — all loaded from `.env` at startup

### Network Security
- SSRF guard on all outbound web requests: resolves hostname, checks against RFC1918 ranges
- MCP connections over plain HTTP with API keys rejected unless host is localhost/private
- ADB SMS blocked unless recipient is in `ALLOWED_PHONE_NUMBERS` allowlist
- Telegram bot rejects all messages not from `TELEGRAM_CHAT_ID`

### Data Privacy
- Clipboard included in context only if `INCLUDE_CLIPBOARD_IN_CONTEXT=true`
- Session exports redact all detected secrets with regex
- Behavior model, intent graph, and commitment data stored only in `.jarvis/` (never sent to cloud unless user configures mem0)
- `PRIVACY_MODE=local_only` (Phase 14) ensures zero data leaves machine

---

## Requirements

```txt
# LLM
openai==1.3.5
ollama
google-generativeai==0.3.0

# Voice
pvporcupine==3.0.0
pyaudio==0.2.13
sounddevice==0.4.6
silero-vad==5.1.2
faster-whisper==1.0.0
pyttsx3==2.90
gTTS==2.3.2
pynput==1.7.6

# Vision
Pillow==11.3.0
opencv-python==4.8.1.78
numpy==1.26.4
mss

# Control
pyautogui==0.9.54
pywin32              # Windows only
playwright==1.40.0

# Web & Search
requests==2.32.5
beautifulsoup4==4.12.3
duckduckgo-search==5.3.0
rank-bm25==0.2.2

# Memory
mem0ai==0.1.0
chromadb==0.5.0
sentence-transformers==3.0.0

# Documents (RAG)
pypdf==4.0.0
python-docx==1.1.2

# ADB
pure-python-adb==0.3.0.dev0
qrcode[pil]==7.4.2

# Interfaces
rich==14.3.3
pyqt6
python-telegram-bot
pystray==0.19.5

# Tasks
APScheduler==3.10.4
SQLAlchemy==2.0.29
watchdog==4.0.1

# Security (Phase 14+)
cryptography==46.0.5  # for BYOK keystore encryption

# Validation
pydantic==2.12.5

# Utils
python-dotenv==1.0.1
loguru==0.7.2
psutil==5.9.3
pytest==8.4.2
huggingface_hub==0.36.2
```

---

## Running NOVA

```bash
# One-command install (Linux/macOS)
chmod +x install.sh && ./install.sh

# Windows
install.bat

# Docker
cp .env.example .env && nano .env
docker compose up -d

# Direct
cp .env.example .env
python setup.py
python main.py

# Voice mode (after startup)
# Say: "Hey NOVA" → speak → NOVA responds

# Telegram
# All commands available via your configured bot

# CLI shortcuts
/status           → full system status JSON
/health           → subsystem health table
/goals            → list all goals
/goal <desc>      → add a goal for autonomous execution
/resume_goal <id> → resume a paused goal
/cancel_goal <id> → cancel a pending goal
/session <name>   → switch to named session
/reset            → clear current session history
/usage            → today's token usage
/usage week       → this week's token usage
/alerts           → recent proactive alerts
/export           → export session as Markdown
/mute             → silence all proactive alerts
/unmute           → re-enable proactive alerts
NOVA stop         → emergency stop (blocks all tools)
NOVA resume       → clear emergency stop
/exit             → quit
```

---

*Phase 1  → smarter terminal chatbot than most people have ever built.*
*Phase 5  → genuinely autonomous PC operator.*
*Phase 8  → controls your phone from anywhere on Earth.*
*Phase 10 → infinitely extensible with any service or custom capability.*
*Phase 12 → production-reliable, self-healing, 24/7.*
*Phase 14 → zero-friction setup for anyone, privacy-first, keys always yours.*
*Phase 16 → gets smarter every week, acts before you ask, runs missions while you sleep.*
*Phase 17 → a team of NOVAs that collaborate, adapt, and evolve together.*
*All 17   → NOVA.*
