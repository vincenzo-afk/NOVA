# JARVIS — Autonomous AI Agent · Build Roadmap v4

> One Python project. Every feature. Every gap filled. All fixes integrated. Built phase by phase, always testable.

---

## Tech Stack Reference

| Tool | Role |
|---|---|
| GPT OSS 120B (API) | Primary LLM |
| Ollama | Offline / Local fallback LLM |
| RoundRobin | Load balancing across LLM providers |
| Gemini Vision | Screen understanding, image analysis |
| Gemini STT | Speech to text (online) |
| faster-whisper | Speech to text (offline + Tamil support) |
| Gemini TTS | Text to speech (online) |
| pyttsx3 | TTS offline fallback |
| gTTS / IndicTTS | Tamil TTS fallback |
| silero-VAD | Voice activity detection (start/stop recording) |
| OmniParser V2 | OCR + UI element detection (runs as local HTTP server) |
| PyAutoGUI | Mouse & keyboard control |
| Win32 API | Deep PC / file system access |
| Porcupine | Wake word detection |
| mem0 | Persistent cloud memory layer |
| ChromaDB | Offline local vector memory + document RAG store |
| sentence-transformers | Local embeddings for ChromaDB |
| Tailscale | Remote ADB tunnel to Android |
| ADB | Android phone control |
| adb-wifi-py | QR-based ADB pairing |

---

## Project Structure

```
jarvis/
├── main.py                            # Entry point, bootstraps everything
├── assets/
│   └── Hey-Jarvis_en_windows_v3_0_0.ppn  # Download from console.picovoice.ai
├── config/
│   ├── settings.py                    # .env loader + startup validation (fail fast on missing keys)
│   └── constants.py
├── core/
│   ├── llm/
│   │   ├── engine.py                  # ask() + ask_stream() unified interface
│   │   ├── roundrobin.py              # Multi-key rotation + exponential backoff + TTL recovery
│   │   └── fallback.py                # Cloud → Ollama fallback
│   ├── think/
│   │   └── reasoning.py               # Chain-of-thought + ambiguity detection + Ask Questions
│   ├── memory/
│   │   ├── mem0_client.py             # mem0 cloud read/write/search
│   │   ├── local_store.py             # ChromaDB offline vector store
│   │   ├── memory_router.py           # Online→mem0, Offline→ChromaDB, dedup on write
│   │   └── context_trimmer.py         # Sliding window + LLM summary compression
│   ├── context/
│   │   └── environment.py             # OS state, foreground app, clipboard, etc.
│   ├── emotion/
│   │   └── engine.py                  # Emotional state machine
│   ├── session.py                     # Session ID, context reset, multi-session
│   ├── health.py                      # Heartbeat monitor for all subsystems + auto-restart
│   ├── plugin_loader.py               # Scans plugins/, registers tools into dispatcher
│   └── tools/
│       └── dispatcher.py              # LLM tool call parser + Pydantic validator + safety stub
├── voice/
│   ├── vad.py                         # silero-VAD: detect speech start/end
│   ├── stt.py                         # Gemini STT (online) — transcribe(audio, lang="en")
│   ├── stt_offline.py                 # faster-whisper (offline) — supports "ta" Tamil
│   ├── tts.py                         # Gemini TTS (online)
│   ├── tts_offline.py                 # pyttsx3 (offline fallback)
│   ├── tts_indic.py                   # gTTS / IndicTTS for Tamil output
│   └── wakeword.py                    # Porcupine wake word listener
├── vision/
│   ├── capture.py                     # Screenshot utilities
│   ├── gemini_vision.py               # Gemini Vision calls
│   ├── omniparser.py                  # OmniParser V2 HTTP client
│   └── omniparser_server.py           # Subprocess launcher for OmniParser server
├── control/
│   ├── mouse_keyboard.py              # PyAutoGUI smart wrapper
│   ├── win32_api.py                   # Deep Win32 access
│   ├── browser.py                     # Playwright browser automation (sync API only)
│   ├── os_layer.py                    # Cross-OS abstraction layer
│   └── adb/
│       ├── adb_client.py              # ADB commands
│       ├── tailscale.py               # Tailscale tunnel management
│       └── qr_pairing.py              # Auto QR-based ADB pairing (local + remote)
├── interfaces/
│   ├── cli.py                         # Rich terminal interface (streaming)
│   ├── gui/
│   │   └── app.py                     # PyQt6 GUI (streaming, image upload, session switcher)
│   ├── telegram_bot.py                # Telegram interface (auth whitelist + edit-based streaming)
│   ├── voice_interface.py             # Full voice loop (VAD → STT → LLM → TTS)
│   └── tray.py                        # System tray app
├── tasks/
│   ├── scheduler.py                   # APScheduler persistent task runner
│   └── goals.py                       # Goal decomposition + max_steps guard + cycle detection
├── web/
│   ├── search.py                      # Web search
│   ├── scraper.py                     # HTML scraping
│   ├── crawler.py                     # Multi-page crawling
│   └── hybrid_ranker.py               # BM25 + Semantic + RRF fusion
├── rag/
│   ├── doc_loader.py                  # PDF (pypdf), DOCX (python-docx), TXT
│   ├── chunker.py                     # Split docs into overlapping chunks
│   └── doc_store.py                   # Embed + store in ChromaDB, query by filename
├── mcp/
│   ├── master_mcp.py                  # Dynamic MCP server orchestrator
│   └── master_api.py                  # API key → service router
├── plugins/
│   └── (drop .py files here)          # Auto-loaded custom capability plugins
├── safety/
│   └── guardrails.py                  # Risk scoring, action confirmation, emergency stop
├── utils/
│   ├── logger.py                      # Structured logging (loguru)
│   ├── usage_tracker.py               # Token/cost tracker per provider/session
│   ├── exporter.py                    # Export session as JSON / Markdown backup
│   └── helpers.py
├── tests/
│   ├── test_llm_engine.py
│   ├── test_memory_router.py
│   ├── test_dispatcher.py
│   ├── test_hybrid_ranker.py
│   ├── test_guardrails.py
│   └── test_context_trimmer.py
├── setup.py                           # One-command installer
├── .env
└── requirements.txt
```

---

## Environment Variables (.env)

```env
# LLM — comma-separated keys for RoundRobin pool
OPENAI_API_KEYS=key1,key2,key3
OPENAI_BASE_URL=                       # your 120B endpoint
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# Gemini — comma-separated keys
GEMINI_API_KEYS=key_a,key_b

# Memory
MEM0_API_KEY=

# Wakeword
PORCUPINE_ACCESS_KEY=
PORCUPINE_KEYWORD_PATH=./assets/Hey-Jarvis_en_windows_v3_0_0.ppn  # download from console.picovoice.ai
PORCUPINE_SENSITIVITY=0.6

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=                      # whitelist — only this ID can message JARVIS

# ADB
TAILSCALE_PHONE_IP=
ADB_PORT=5555

# OmniParser
OMNIPARSER_SERVER_URL=http://localhost:8000

# Safety
RISK_CONFIRM_THRESHOLD=7               # 0–10, above this needs explicit confirm

# Sessions
DEFAULT_SESSION=jarvis_personal

# Usage
DAILY_TOKEN_ALERT_THRESHOLD=100000

# Voice
DEFAULT_LANG=en                        # "ta" for Tamil, "hi" for Hindi
VAD_SILENCE_MS=800                     # ms of silence before STT fires
WHISPER_MODEL=base                     # options: tiny / base / small / medium / large
```

---

## Build Phases

Each phase produces something **fully working and testable** before you move on.

---

### ✅ PHASE 1 — Core Engine (The Brain)
**Goal:** A working streaming CLI chatbot backed by your full LLM stack.

**Features built:**
- `[8]` Chat
- `[1]` Think (CoT reasoning)
- `[2]` Ask Questions (ambiguity detection)
- `[3]` Fallback (cloud → local)
- RoundRobin with multi-key support + exponential backoff
- Streaming output
- Config validation on startup

**What you build:**

1. **Project scaffolding** — all folders, `__init__.py` in every package, `assets/` directory

2. **`config/settings.py`** — `.env` loader with **startup validation**:
   - On boot, check every required key is present
   - If any required key missing → print clear error and exit immediately (no silent crashes)
   - Parse `OPENAI_API_KEYS` as comma-separated list → pass to RoundRobin pool
   - Same for `GEMINI_API_KEYS`

3. **`core/llm/engine.py`** — unified interface:
   ```python
   def ask(prompt, system, history) -> str
   def ask_stream(prompt, system, history) -> Generator[str, None, None]
   ```

4. **`core/llm/roundrobin.py`** — multi-key rotation:
   - Reads key pool from config (comma-separated, N keys)
   - Per-key state: `active`, `rate_limited (with TTL)`, `dead`
   - `mark_rate_limited(key, retry_after=60)` — TTL cooldown, **auto-recovers**, not permanently banned
   - Exponential backoff on repeated failures: 60s → 120s → 240s
   - `get_next()` — skips cooldown/dead keys, returns next active key

5. **`core/llm/fallback.py`** — if all cloud keys exhausted or offline → Ollama

6. **`core/think/reasoning.py`**:
   - CoT wrapper: silent step-by-step prefix on every LLM call
   - Ambiguity detector: score 0–1. Above 0.6 → return clarifying question instead of executing
   - Ask Questions: *"Did you mean X or Y?"* before any ambiguous action
   - **Tool schema injection point** — from Phase 5, append `dispatcher.get_tool_schema_prompt()` to every system prompt:
     ```python
     # reasoning.py — build_system_prompt()
     def build_system_prompt(base: str, dispatcher=None) -> str:
         prompt = base
         if dispatcher:
             prompt += "\n\n" + dispatcher.get_tool_schema_prompt()
         return prompt
     ```
     Wire this from day one with `dispatcher=None` — Phase 5 passes the real dispatcher in.

7. **`interfaces/cli.py`** — Rich streaming terminal:
   - Tokens print live as generator yields
   - Shows which provider answered (e.g., `[cloud • key_2]` or `[local • ollama]`)

**Testable milestone:** Tokens stream live. Ambiguous command → JARVIS asks before acting. Kill internet → Ollama takes over. Rate-limit a key → recovers after TTL without restart. Missing `.env` key → clear startup error, not a mysterious crash 10 minutes in.

---

### ✅ PHASE 2 — Memory Layer
**Goal:** JARVIS remembers everything and never overflows its context window.

**Features built:**
- `[9]` Memory (mem0 + ChromaDB)
- Context window management
- Hybrid memory search (BM25 + Semantic + RRF)
- Multi-session support

**What you build:**

1. **`core/memory/mem0_client.py`** — mem0 wrapper: `add()`, `search()`, `get_all()`

2. **`core/memory/local_store.py`** — ChromaDB with `sentence-transformers` local embeddings:
   - Identical interface to mem0_client
   - Works fully offline, zero internet

3. **`core/memory/memory_router.py`** — smart router:
   - Online → write to **both** mem0 + ChromaDB simultaneously
   - Offline → ChromaDB only
   - On reconnect → sync offline-written memories up to mem0
   - **Deduplication on write**: hash-check before adding — never store same memory twice

4. **`core/memory/context_trimmer.py`**:
   - Keep last N raw turns (default: 10)
   - Older turns → compress via LLM into a rolling summary paragraph
   - Final prompt structure every time:
     ```
     [system prompt]
     [world state JSON]
     [relevant memories top-5]
     [summary of older turns]
     [last N raw turns]
     ```
   - Never sends raw full history to LLM

5. **Hybrid memory search** in `memory_router.search()`:
   - Vector search → top-20 candidates
   - BM25 keyword re-rank those 20
   - RRF merge → final top-5 returned
   - Result: exact-term recall + semantic fuzzy recall together

6. **`core/context/environment.py`** — world state snapshot:
   - Foreground app, window title, clipboard, time/date, battery %, network status, last active file

7. **`core/session.py`**:
   - Every conversation has a `session_id` (UUID)
   - `reset_context()` — clear turn history, keep memories
   - Named sessions: `jarvis_work`, `jarvis_personal` — separate mem0 user IDs
   - Switch: *"switch to work mode"* → loads correct session memories

**Testable milestone:** Tell JARVIS your name → close and reopen → remembered. 100-turn conversation → no crash, no silent truncation. Search for something from turn 50 → exact recall via BM25 hybrid. Two sessions → memories properly isolated.

---

### ✅ PHASE 3 — Voice Layer
**Goal:** Talk to JARVIS hands-free. Works fully offline. Supports Tamil.

**Features built:**
- `[11]` STT (online + offline + multilingual)
- `[10]` TTS (online + offline + Tamil)
- `[12]` Wakeword
- `[13]` Voice interface
- VAD (voice activity detection)

**What you build:**

1. **`voice/vad.py`** — silero-VAD:
   - Listens to mic audio stream continuously
   - Detects **speech start** → begin buffering audio
   - Detects **silence >800ms** → stop buffering → return audio clip for STT
   - Without this, STT has no idea when you finished speaking

2. **`voice/wakeword.py`** — Porcupine background thread:
   - Wake word: *"Hey JARVIS"* loaded from `PORCUPINE_KEYWORD_PATH` in `.env`
   - **"Hey JARVIS" is NOT a built-in keyword** — requires a `.ppn` file downloaded from console.picovoice.ai
   - `setup.py` will remind you to download it; the file goes in `assets/`
   - On detection → fires callback to VAD → begin voice capture
   - Sensitivity controlled by `PORCUPINE_SENSITIVITY` (default: 0.6)
   ```python
   import pvporcupine, os
   from config.settings import settings

   porcupine = pvporcupine.create(
       access_key=settings.PORCUPINE_ACCESS_KEY,
       keyword_paths=[settings.PORCUPINE_KEYWORD_PATH],
       sensitivities=[settings.PORCUPINE_SENSITIVITY],
   )
   ```

3. **`voice/stt.py`** — Gemini STT (online):
   ```python
   def transcribe(audio_bytes, lang="en") -> str
   # lang="ta" for Tamil, "hi" for Hindi, etc.
   ```

4. **`voice/stt_offline.py`** — faster-whisper (offline):
   - Same interface: `transcribe(audio_bytes, lang="en")`
   - Model size read from `WHISPER_MODEL` env var (tiny/base/small/medium/large)
   - faster-whisper natively supports Tamil (`lang="ta"`) — no extra model needed
   ```python
   from faster_whisper import WhisperModel
   from config.settings import settings

   model = WhisperModel(settings.WHISPER_MODEL, device="cpu", compute_type="int8")
   ```

5. **`voice/tts.py`** — Gemini TTS (online):
   ```python
   def speak(text, emotion="neutral", lang="en")
   ```

6. **`voice/tts_offline.py`** — pyttsx3 (offline English fallback)

7. **`voice/tts_indic.py`** — Tamil TTS:
   - gTTS with `lang="ta"` for basic Tamil output
   - Upgrade path: IndicTTS API for higher quality
   - Auto-selected when `lang="ta"` and online; gTTS when offline

8. **`interfaces/voice_interface.py`** — full loop:
   - Wakeword → VAD captures until silence → STT (auto online/offline) → LLM stream → TTS (auto online/offline/Tamil)
   - Barge-in: hotkey mid-speech stops JARVIS and re-listens
   - Self-mute: wakeword disabled while JARVIS is speaking

**Testable milestone:** Say *"Hey JARVIS"* → speak freely → it waits for silence before responding. Speak Tamil → responds in Tamil. Offline → full voice loop on local models. Never cuts you off mid-sentence, never records forever.

---

### ✅ PHASE 4 — Eyes (Screen Vision + Prediction)
**Goal:** JARVIS sees your screen and acts proactively. OmniParser managed automatically.

**Features built:**
- `[14]` Screen access
- `[16]` Context & environment understanding (full)
- `[4]` Prediction + proactive behavior
- Multi-modal image input

**What you build:**

1. **`vision/omniparser_server.py`** — OmniParser lifecycle manager:
   - On JARVIS boot → check if OmniParser server is running
   - If not → launch as subprocess automatically
   - Configured via `OMNIPARSER_SERVER_URL=http://localhost:8000`
   - `core/health.py` pings it every 60s → auto-restarts if down
   - `setup.py` downloads OmniParser weights and registers it

2. **`vision/capture.py`** — full screen, active window, custom region, periodic loop

3. **`vision/gemini_vision.py`** — structured screen analysis:
   - Returns JSON: `{scene_type, detected_errors, active_app, notable_elements, suggested_actions}`

4. **`vision/omniparser.py`** — HTTP client to OmniParser server:
   - OCR: extract all visible text
   - UI element map: buttons/inputs with bounding box coordinates
   - Element map fed to `mouse_keyboard.py` for name-based clicking

5. **Proactive watcher loop** (background thread):
   - Runs every N seconds, analyzes screen
   - Detects: error dialogs, stuck loading spinners, login screens, crash reports
   - Rate-limited: max 1 unsolicited interrupt per 2 minutes
   - *"I see a Python error — want me to fix it?"*

6. **Multi-modal user input** (GUI + Telegram):
   - User can send/upload an image → Gemini Vision analyzes it → enters conversation context
   - *"Here's a screenshot of the bug"* → JARVIS reasons about it

**Testable milestone:** Boot JARVIS → OmniParser starts automatically. Kill its process → health monitor restarts it. Open an error dialog → JARVIS proactively speaks up. Send a screenshot in Telegram → JARVIS analyzes it.

---

### ✅ PHASE 5 — Hands + Documents (PC Control + RAG)
**Goal:** JARVIS operates your PC and reads your documents intelligently.

**Features built:**
- `[17]` Mouse & keyboard
- `[19]` File & PC access
- `[25]` Deep Win32 API
- `[26]` Browser control
- `[22]` Web access
- Tool call dispatcher (Pydantic validated)
- Document RAG

**What you build:**

1. **`core/tools/dispatcher.py`** — critical glue layer:

   **Tool schema injection** (fixes Gap #2 — LLM must know what tools exist):
   ```python
   import json
   from pydantic import BaseModel

   class Dispatcher:
       def __init__(self):
           self.registry: dict[str, callable] = {}
           self.schemas: dict[str, type[BaseModel]] = {}

       def register(self, name: str, fn: callable, schema: type[BaseModel]):
           self.registry[name] = fn
           self.schemas[name] = schema

       def get_tool_schema_prompt(self) -> str:
           """Injected into every LLM system prompt so it knows available tools."""
           tools = [
               {"tool": name, "args": model.schema()}
               for name, model in self.schemas.items()
           ]
           return f"""To use a tool, output ONLY valid JSON in this exact format:
   {{"tool": "<tool_name>", "args": {{...}}}}

   Available tools:
   {json.dumps(tools, indent=2)}

   For regular responses, output plain text. Never mix JSON and text in one response."""
   ```

   **Safety stub** (fixes Gap #5 — blocks destructive calls before Phase 11):
   ```python
   ALWAYS_CONFIRM = {
       "win32_api.delete",
       "win32_api.registry_write",
       "win32_api.kill_process",
       "adb.send_sms",
       "adb.delete_file",
       "browser.fill",           # could submit forms
   }

   def execute(self, tool_call: ToolCall):
       # Safety stub — replaced by full guardrails.py in Phase 11
       if tool_call.tool in ALWAYS_CONFIRM:
           print(f"\n⚠️  [SAFETY STUB] About to run: {tool_call.tool}")
           print(f"   Args: {tool_call.args}")
           confirm = input("   Confirm? (y/n): ").strip().lower()
           if confirm != "y":
               return {"status": "cancelled", "reason": "user declined"}

       fn = self.registry.get(tool_call.tool)
       if not fn:
           return {"error": f"unknown tool: {tool_call.tool}"}

       # Log before execution
       logger.info(f"Executing tool: {tool_call.tool} | args: {tool_call.args}")
       return fn(**tool_call.args)
   ```

   On Pydantic validation failure → return structured error to LLM, ask it to retry.

2. **`control/mouse_keyboard.py`** — smart PyAutoGUI:
   - `click_element(name)` — uses OmniParser element map, no hardcoded coords
   - `type_text()`, `hotkey()`, `scroll()`, `drag()`

3. **`control/win32_api.py`** — deep PC access:
   - File: read, write, move, delete, search by name/content
   - Process: list, kill, launch
   - Window: focus, resize, close by title
   - Registry: read/write
   - Clipboard: get/set
   - Notifications: Windows toast
   - Disk: free space, connected drives

4. **`control/browser.py`** — Playwright with **sync API only**:
   - **Always use `sync_playwright`** — async variant causes silent failures inside non-async threads
   ```python
   from playwright.sync_api import sync_playwright  # ALWAYS this — never async_playwright

   class Browser:
       def __init__(self):
           self._pw = sync_playwright().start()
           self.browser = self._pw.chromium.launch(headless=True)
           self.page = self.browser.new_page()

       def open(self, url: str):
           self.page.goto(url)

       def click(self, selector: str):
           self.page.click(selector)

       def fill(self, selector: str, value: str):
           self.page.fill(selector, value)

       def extract_text(self) -> str:
           return self.page.inner_text("body")

       def get_links(self) -> list[str]:
           return self.page.eval_on_selector_all("a", "els => els.map(e => e.href)")

       def screenshot(self) -> bytes:
           return self.page.screenshot()

       def close(self):
           self.browser.close()
           self._pw.stop()
   ```

5. **`web/search.py`**, **`web/scraper.py`**, **`web/crawler.py`**, **`web/hybrid_ranker.py`**

6. **`rag/doc_loader.py`** — document ingestion:
   - PDF → `pypdf`
   - DOCX → `python-docx`
   - TXT → plain read
   - Returns clean text + metadata (filename, page count, modification date)

7. **`rag/chunker.py`** — smart splitting:
   - Overlapping chunks (default: 512 tokens, 64 overlap)
   - Respects sentence boundaries — never cuts mid-sentence

8. **`rag/doc_store.py`** — ChromaDB document collection:
   - `ingest(filepath)` — load → chunk → embed → store with filename metadata
   - `query(question, filename=None)` — retrieve relevant chunks
   - `list_docs()` — show all ingested documents
   - *"Read this PDF and summarize section 3"* → fully handled end-to-end

**Testable milestone:** *"Open Chrome and find the asyncio docs"* → fully autonomous. *"Read my project_brief.pdf and tell me the key requirements"* → JARVIS ingests, queries, and answers. Dangerous command (e.g., delete a folder) → safety stub prompts for confirmation.

---

### ✅ PHASE 6 — Interfaces, Tray & Startup
**Goal:** JARVIS on every surface, always running, with full visibility.

**Features built:**
- `[13]` GUI, CLI, Telegram, Voice interfaces
- `[18]` System Tray
- `[7]` 24/7 startup
- Usage tracker
- Session management UI
- Conversation export

**What you build:**

1. **`interfaces/gui/app.py`** — PyQt6:
   - Streaming output, image upload, mic button, session switcher
   - Emotion + status indicator, today's token usage widget

2. **`interfaces/telegram_bot.py`** — python-telegram-bot:
   - **Auth whitelist**: every handler checks `update.effective_user.id` against `TELEGRAM_CHAT_ID` — reject anyone else with no response
   - **Edit-based streaming** (Telegram has no real token streaming — this simulates it):
     ```python
     import time

     async def handle_message(update, context):
         # Guard: only respond to whitelisted chat ID
         if str(update.effective_user.id) != settings.TELEGRAM_CHAT_ID:
             return

         msg = await update.message.reply_text("⏳")
         buffer = ""
         last_edit = 0

         async for token in jarvis.ask_stream(update.message.text):
             buffer += token
             now = time.time()
             if now - last_edit > 1.5:          # ~40 edits/min max — stays under Telegram rate limit
                 await context.bot.edit_message_text(
                     buffer + " ▌",
                     chat_id=update.effective_chat.id,
                     message_id=msg.message_id
                 )
                 last_edit = now

         await context.bot.edit_message_text(   # final message without cursor
             buffer,
             chat_id=update.effective_chat.id,
             message_id=msg.message_id
         )
     ```
   - Supports: `/screenshot`, `/session work`, `/status`, `/export`, image input

3. **`interfaces/tray.py`** — pystray:
   - Tooltip: *"Today: 42k tokens · 3 keys active · Online"*
   - Menu: Open GUI, Switch Session, Mute, Health, Export Session, Quit

4. **`utils/usage_tracker.py`** — per provider/session:
   - Daily/weekly summaries on request
   - Alert if daily spend crosses `DAILY_TOKEN_ALERT_THRESHOLD`

5. **`utils/exporter.py`** — session backup:
   - Export as JSON (raw) or Markdown (human-readable)
   - Triggered via Telegram `/export`, tray menu, or voice command

6. **Startup**: Win32 registry + watchdog process

**Testable milestone:** Boot PC → JARVIS in tray. Telegram only responds to your chat ID. The "typing" cursor effect appears in Telegram as JARVIS generates. Export conversation → readable Markdown file. Tray tooltip shows live usage.

---

### ✅ PHASE 7 — Scheduler, Goals & Autonomy
**Goal:** JARVIS works while you're away.

**Features built:**
- `[20]` Scheduled tasks
- `[21]` Goals & Tasks
- `[23]` Personal Assistant autonomy loop

**What you build:**

1. **`tasks/scheduler.py`** — APScheduler (SQLite backend, survives restarts):
   - Natural language → LLM → cron expression
   - Register, list, cancel jobs

2. **`tasks/goals.py`** — with hard loop guards:
   - Goal → LLM decomposition → subtask list with dependencies
   - **`max_steps` hard limit** (default: 20) per goal execution run
   - Steps exhausted → pause + notify: *"Reached step limit on goal X — continue?"*
   - **Cycle detection**: if same tool + same args appear twice in one run → abort immediately, report to user
   - Re-planning on subtask failure

3. **Autonomous agent loop**:
   - Picks up pending goals without prompting
   - Reports completion via TTS (local) or Telegram (away)
   - Configurable max autonomy depth (how many steps before checking in)

**Testable milestone:** *"Every morning at 8 summarize my emails"* → runs next morning unattended. Long-running goal hits step limit → JARVIS pauses and asks, doesn't loop forever.

---

### ✅ PHASE 8 — Android Control + QR Pairing
**Goal:** JARVIS controls your Android from anywhere. Pair with a single QR scan.

**Features built:**
- `[5]` ADB with Tailscale
- QR-based auto-pairing (local + remote)

**What you build:**

1. **`control/adb/tailscale.py`** — tunnel management:
   - Verify Tailscale is installed; if not → auto-download and install silently
   - Get phone's Tailscale IP (`tailscale ip -4`)
   - Reconnect if tunnel drops

2. **`control/adb/qr_pairing.py`** — smart ADB pairing:
   - Run `adb tcpip 5555` on JARVIS PC
   - **Mode detection**:
     - Same network → use local DHCP IP (`socket.connect("8.8.8.8")`)
     - Remote network → use Tailscale IP
   - Generate QR code containing `adb_connect://<ip>:5555`
   - Show QR in GUI + save as PNG + display in terminal
   - You scan from Android (Termux or companion app) → ADB connects instantly
   - **Background service mode**: runs on boot, always exposes itself, QR always available in tray

3. **`control/adb/adb_client.py`** — full phone control:
   - Screenshot → Gemini Vision analysis
   - Tap, swipe, type
   - Launch apps by package name
   - SMS read/send via `content query` / `am start`
   - Answer call: `KEYCODE_CALL`, reject: `KEYCODE_ENDCALL`
   - Notification dump: `adb shell dumpsys notification`
   - File pull/push

4. **Proactive phone watcher**:
   - Periodic phone screenshot → vision
   - Incoming call detected → TTS: *"Incoming call from X — answer?"*
   - New notifications → summarized proactively

**Testable milestone:** Open tray → *"Show ADB QR"* → scan with phone → connected. *"Send WhatsApp to [contact] saying I'll be late"* → done. Incoming call → JARVIS announces it.

---

### ✅ PHASE 9 — Emotion Engine
**Goal:** JARVIS has a personality that feels alive.

**Features built:**
- `[15]` Engine with emotion

**What you build:**

1. **`core/emotion/engine.py`** — state machine:
   - States: `neutral`, `focused`, `concerned`, `enthusiastic`, `cautious`, `empathetic`, `urgent`
   - Transitions from: conversation tone, error detection, time of day, task urgency, user stress signals
   - Emotion injected into every LLM system prompt

2. Emotion affects: TTS prosody, response length/style, proactivity frequency, GUI status color

**Testable milestone:** Error screen → tone goes urgent. Late night casual chat → warm and relaxed. Completing a long goal → genuinely enthusiastic.

---

### ✅ PHASE 10 — Master MCP, Master API & Plugins
**Goal:** Give JARVIS any API key and it figures out the rest.

**Features built:**
- `[24]` Master MCP
- `[29]` Master API
- Plugin architecture

**What you build:**

1. **`mcp/master_api.py`** — API key registry with auto-detection

2. **`mcp/master_mcp.py`** — dynamic MCP orchestrator:
   - Connect to any MCP server by service name
   - `mcp.list_tools()` → LLM discovers capabilities at runtime
   - Built-in: GitHub, Notion, Slack, Linear, Google Drive, Jira

3. **`core/plugin_loader.py`** — Python plugin system:
   - Scans `plugins/` at startup
   - Standard interface:
     ```python
     PLUGIN_NAME = "my_tool"
     PLUGIN_TOOLS = [{"name": "...", "description": "...", "args": {...}}]
     def my_tool_function(**kwargs): ...
     ```
   - Auto-registers into dispatcher — no core edits needed

**Testable milestone:** Give GitHub token → *"List my open PRs"* → done. Drop a custom plugin file → restart → new tool available automatically.

---

### ✅ PHASE 11 — Safety Layer
**Goal:** JARVIS never acts destructively without explicit confirmation.

**Features built:**
- `[28]` Safety

**What you build:**

1. **`safety/guardrails.py`** — replaces the Phase 5 safety stub entirely:
   - Risk scorer 0–10 on every tool call
   - Low (0–3): silent execution
   - Medium (4–6): show plan, 5s countdown, auto-confirm
   - High (7–10): explicit confirmation, no timeout
   - Destructive action list: always High regardless of context
   - Dry-run mode: full plan explained without any execution
   - Emergency stop: voice *"JARVIS stop"* or `Ctrl+Shift+X`
   - Full action log: timestamp, tool, args, risk, who confirmed, result

2. **Retrofit**: remove the safety stub from `dispatcher.py` and replace with:
   ```python
   from safety.guardrails import guardrails

   def execute(self, tool_call: ToolCall):
       risk = guardrails.check(tool_call)    # scores 0–10, may block or prompt
       if risk.blocked:
           return {"status": "blocked", "reason": risk.reason}
       logger.info(f"Executing tool: {tool_call.tool} | risk: {risk.score}")
       fn = self.registry.get(tool_call.tool)
       result = fn(**tool_call.args)
       guardrails.log(tool_call, risk, result)
       return result
   ```

**Testable milestone:** *"Delete Downloads folder"* → reads back full list, waits for *"confirm"*. Emergency stop mid-execution → immediate halt.

---

### ✅ PHASE 12 — Offline Polish & Health Monitor
**Goal:** Nothing silently breaks. Full parity offline.

**Features built:**
- `[6]` Offline (complete)
- Self-diagnostic health monitor

**What you build:**

1. **Network monitor** — detects loss → switches all services:
   - LLM → Ollama
   - STT → faster-whisper
   - TTS → pyttsx3 / gTTS
   - Memory → ChromaDB (dedup-checked)
   - Vision → OmniParser-only
   - On reconnect → sync offline memories to mem0 (dedup before upload)
   - Tray icon reflects current mode

2. **`core/health.py`** — watchdog:
   - Heartbeats every 60s: Porcupine thread, mem0, OmniParser server, Ollama, scheduler, watcher, ADB, VAD
   - Dead thread → auto-restart
   - Critical failure → Telegram alert: *"⚠️ OmniParser is down. Restarting..."*
   - `/status` command returns full subsystem health table

**Testable milestone:** Kill any subsystem manually → health monitor restarts it in <60s. Unplug ethernet → all features continue on local models. Reconnect → syncs without duplicates.

---

### ✅ PHASE 13 — Cross-OS, Tests & Final Hardening
**Goal:** Linux/Mac-ready foundation. One-command install. Full test coverage.

**Features built:**
- `[27]` All OS Support (foundation)

**What you build:**

1. **`control/os_layer.py`** — OS abstraction:
   - `get_foreground_app()`, `send_notification()`, `register_startup()` — each with Win32 / xdotool / AppKit implementations

2. **Cross-platform startup**: Task Scheduler (Win) / systemd (Linux) / launchd (Mac)

3. **`setup.py`** — one-command installer:
   ```python
   # Key steps in setup.py

   # 1. Install Python deps
   subprocess.run(["pip", "install", "-r", "requirements.txt"])

   # 2. Prompt for API keys → write .env
   # ...

   # 3. Install Playwright browser
   subprocess.run(["playwright", "install", "chromium"])

   # 4. Download OmniParser weights
   # ...

   # 5. Download Ollama + pull default model
   # ...

   # 6. Download Whisper model
   from faster_whisper import WhisperModel
   model_size = os.getenv("WHISPER_MODEL", "base")
   print(f"Downloading Whisper model: {model_size} ...")
   WhisperModel(model_size, device="cpu", compute_type="int8")
   print("✓ Whisper ready")

   # 7. Porcupine wake word reminder
   print("\n⚠️  Wake word setup required:")
   print("   1. Go to console.picovoice.ai")
   print("   2. Create a custom 'Hey JARVIS' keyword for your OS")
   print("   3. Download the .ppn file")
   print("   4. Place it at: assets/Hey-Jarvis_en_windows_v3_0_0.ppn")
   print("   5. Confirm the path matches PORCUPINE_KEYWORD_PATH in your .env")

   # 8. Register startup entry for current OS
   # ...

   # 9. Run health check
   # ...
   ```
   - Total time target: <5 minutes on fresh machine

4. **`tests/`** — full pytest suite:
   - Unit: LLM engine, memory router, dispatcher, hybrid ranker, guardrails, context trimmer
   - Integration: full conversation loop, tool call → validation → safety check → execution
   - Run: `pytest tests/ -v`

**Testable milestone:** `python setup.py` on fresh Windows machine → JARVIS running in <5 minutes. Full test suite passes.

---

## Complete Build Order

```
Phase 1  →  Core Engine + CLI + Streaming + Ask Questions + Multi-key RoundRobin + Config Validation
             └─ Wire tool schema injection point in reasoning.py (dispatcher=None stub)
Phase 2  →  Memory (mem0 + ChromaDB) + Context Trimmer + Hybrid Search + Sessions + Dedup
Phase 3  →  Voice (VAD + STT + TTS) + Tamil Support + Offline Voice Fallback
             └─ Porcupine: download .ppn from console.picovoice.ai → assets/ before testing
Phase 4  →  Vision + OmniParser Lifecycle + Proactive Watcher + Multi-modal Input
Phase 5  →  PC Control + Tool Dispatcher (with schema injection + safety stub) + Browser (sync) + Web + RAG
Phase 6  →  GUI + Telegram (auth + edit-based streaming) + Tray + Startup + Usage Tracker + Exporter
Phase 7  →  Scheduler + Goals + Autonomy (max_steps guard + cycle detection)
Phase 8  →  Android (ADB + Tailscale + QR Pairing + Phone Watcher)
Phase 9  →  Emotion Engine
Phase 10 →  Master MCP + Master API + Plugin Architecture
Phase 11 →  Full Safety Layer (replace dispatcher safety stub with guardrails.py)
Phase 12 →  Offline Polish + Memory Sync + Health Monitor
Phase 13 →  Cross-OS Abstraction + Full Test Suite + One-command Installer
```

---

## Integrated Fixes Summary

All 5 gaps from the v3 audit have been fixed directly into this plan:

| Gap | Fix Location | When It Matters |
|---|---|---|
| Missing `PORCUPINE_KEYWORD_PATH` in `.env` | `.env` template + `voice/wakeword.py` + `setup.py` | Phase 3 |
| Tool schema never injected into LLM prompt | `dispatcher.get_tool_schema_prompt()` + `reasoning.py` hook | Phase 1 (stub) / Phase 5 (live) |
| Telegram "streaming" is architecturally impossible | `telegram_bot.py` edit-based batching | Phase 6 |
| Playwright sync vs async not decided | `control/browser.py` locked to `sync_playwright` | Phase 5 |
| No safety stub before Phase 11 safety layer | `dispatcher.execute()` `ALWAYS_CONFIRM` stub | Phase 5 |

Minor fixes also integrated:
- `WHISPER_MODEL=base` added to `.env` + downloaded in `setup.py`
- `control/os_layer.py` added to project structure tree
- `assets/` directory added to project structure tree

---

## Full Requirements

```txt
# LLM
openai
ollama
google-generativeai

# Voice
pvporcupine
pyaudio
sounddevice
silero-vad
faster-whisper
pyttsx3
gTTS

# Vision
Pillow
opencv-python
numpy

# Control
pyautogui
pywin32
playwright

# Web & Search
requests
beautifulsoup4
duckduckgo-search
rank-bm25

# Memory
mem0ai
chromadb
sentence-transformers

# Documents (RAG)
pypdf
python-docx

# ADB & Networking
pure-python-adb
adb-wifi-py
qrcode[pil]

# Interfaces
rich
pyqt6
python-telegram-bot
pystray

# Tasks
apscheduler

# Validation
pydantic

# Utils
python-dotenv
loguru
pytest
```

---

## The 6 Laws of Building JARVIS

1. **Never skip the test milestone** — if the milestone doesn't pass, the next phase breaks harder
2. **LLM is the orchestrator, not the executor** — LLM decides what to do, modules do the actual work. Never execute raw LLM-generated Python
3. **All tool calls go through dispatcher.py** — no module callable directly by LLM, only through validated dispatcher with schema injection
4. **memory_router is always on from Phase 2** — every phase reads/writes memories from day one
5. **World state is always in the prompt** — environment snapshot + session memories in every single LLM call
6. **One engine, many interfaces** — CLI, GUI, Voice, Telegram all call the same `core/` modules. Zero logic duplication across interfaces

---

*Phase 1 → smarter terminal chatbot than most people have ever built.*
*Phase 5 → genuinely autonomous PC operator.*
*Phase 8 → controls your phone from anywhere on Earth.*
*Phase 10 → infinitely extensible with any service or custom capability.*
*Phase 12 → production-reliable, self-healing, 24/7.*
*All 13 → JARVIS.*