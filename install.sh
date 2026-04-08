#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# NOVA — Smart One-Command Installer  (Features 1 + 2)
#
# Usage:
#   chmod +x install.sh && ./install.sh
#   ./install.sh --no-optional      # skip heavy optional deps (torch, etc.)
#   ./install.sh --dry-run          # print what would be installed
#
# What it does:
#   1. Detects OS (macOS / Linux Debian-family / Linux Arch)
#   2. Runs the Python PC scanner to read config/pc_profile.json
#   3. Installs only the dependencies that make sense for this machine
#   4. Provides clear pass/fail output for every step
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}  ✓${RESET} $*"; }
warn() { echo -e "${YELLOW}  ⚠${RESET} $*"; }
info() { echo -e "${CYAN}  →${RESET} $*"; }
fail() { echo -e "${RED}  ✗ $*${RESET}"; }
section() { echo -e "\n${BOLD}── $* ──────────────────────────────────────────────${RESET}"; }

# ── flags ─────────────────────────────────────────────────────────────────────
NO_OPTIONAL=false
DRY_RUN=false
GUI_SETUP=false
for arg in "$@"; do
  case "$arg" in
    --no-optional) NO_OPTIONAL=true ;;
    --dry-run)     DRY_RUN=true ;;
    --gui)         GUI_SETUP=true ;;
  esac
done

run() {
  if $DRY_RUN; then
    info "[dry-run] $*"
  else
    "$@"
  fi
}

# ── detect OS ─────────────────────────────────────────────────────────────────
section "Detecting operating system"
OS="unknown"
DISTRO=""
if [[ "$OSTYPE" == "darwin"* ]]; then
  OS="macos"
  ok "macOS $(sw_vers -productVersion)"
elif [[ -f /etc/os-release ]]; then
  source /etc/os-release
  DISTRO="${ID:-unknown}"
  case "$DISTRO" in
    ubuntu|debian|linuxmint|pop) OS="debian" ;;
    arch|manjaro|endeavouros)    OS="arch"   ;;
    fedora|rhel|centos)          OS="fedora" ;;
    *)                           OS="linux"  ;;
  esac
  ok "Linux / $DISTRO"
else
  warn "Could not detect OS — proceeding as generic Linux"
  OS="linux"
fi

# ── check Python ─────────────────────────────────────────────────────────────
section "Python environment"
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    VER=$("$cmd" --version 2>&1 | awk '{print $2}')
    MAJOR=$(echo "$VER" | cut -d. -f1)
    MINOR=$(echo "$VER" | cut -d. -f2)
    if [[ "$MAJOR" -ge 3 && "$MINOR" -ge 10 ]]; then
      PYTHON="$cmd"
      ok "Found $cmd $VER"
      break
    else
      warn "$cmd $VER is too old (need 3.10+)"
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  fail "Python 3.10+ not found. Install it first:"
  case "$OS" in
    macos)  echo "  brew install python@3.12" ;;
    debian) echo "  sudo apt install python3.12 python3.12-venv" ;;
    arch)   echo "  sudo pacman -S python" ;;
  esac
  exit 1
fi

# ── virtual environment ───────────────────────────────────────────────────────
section "Virtual environment"
if [[ ! -d ".venv" ]]; then
  info "Creating .venv"
  run "$PYTHON" -m venv .venv
fi
if $DRY_RUN; then
  PIP="pip"
else
  PIP=".venv/bin/pip"
  source .venv/bin/activate
fi
run "$PIP" install --upgrade pip setuptools wheel -q
ok "Virtual environment ready"

# ── system packages ───────────────────────────────────────────────────────────
install_brew_pkg() {
  local pkg="$1"
  if ! command -v "$pkg" &>/dev/null; then
    info "Homebrew: $pkg"
    run brew install "$pkg"
  else
    ok "$pkg already installed"
  fi
}

install_apt_pkg() {
  local pkg="$1"
  if ! dpkg -s "$pkg" &>/dev/null 2>&1; then
    info "apt: $pkg"
    run sudo apt-get install -y --no-install-recommends "$pkg"
  else
    ok "$pkg already installed"
  fi
}

install_pacman_pkg() {
  local pkg="$1"
  if ! pacman -Q "$pkg" &>/dev/null; then
    info "pacman: $pkg"
    run sudo pacman -S --noconfirm "$pkg"
  else
    ok "$pkg already installed"
  fi
}

section "System dependencies"
case "$OS" in
  macos)
    if ! command -v brew &>/dev/null; then
      warn "Homebrew not found — skipping system packages. Install from https://brew.sh"
    else
      install_brew_pkg ffmpeg
      install_brew_pkg mpg123
    fi
    ;;
  debian)
    run sudo apt-get update -qq
    for pkg in ffmpeg mpg123 xdotool wmctrl xclip scrot espeak-ng; do
      install_apt_pkg "$pkg"
    done
    ;;
  arch)
    for pkg in ffmpeg mpg123 xdotool wmctrl xclip scrot espeak-ng; do
      install_pacman_pkg "$pkg"
    done
    ;;
  *)
    warn "Skipping system packages for OS=$OS (install ffmpeg, xdotool manually)"
    ;;
esac

# ── run PC scanner to read pc_profile.json ───────────────────────────────────
section "PC profile scan"
if $DRY_RUN; then
  info "[dry-run] Would run: $PYTHON -m config.pc_scanner"
else
  "$PYTHON" -m config.pc_scanner && ok "Profile written to config/pc_profile.json" \
    || warn "PC scan failed — continuing anyway"
fi

# Helper: read a value from pc_profile.json via Python
profile_get() {
  local key="$1"
  local default="${2:-}"
  "$PYTHON" -c "
import json, sys
try:
    d = json.load(open('config/pc_profile.json'))
    keys = '$key'.split('.')
    v = d
    for k in keys:
        v = v[k]
    print(v)
except Exception:
    print('$default')
" 2>/dev/null || echo "$default"
}

DISPLAY_SERVER=$(profile_get "display_server" "unknown")
INPUT_BACKEND=$(profile_get "input_backend"  "pyautogui")
SS_BACKEND=$(profile_get    "screenshot_backend" "pil")
HAS_GPU=$(profile_get       "gpu.available"  "false")
RAM_GB=$(profile_get        "ram_gb"         "4")

info "display=$DISPLAY_SERVER  input=$INPUT_BACKEND  screenshot=$SS_BACKEND  gpu=$HAS_GPU  ram=${RAM_GB}GB"

# ── core Python packages ──────────────────────────────────────────────────────
section "Core Python packages"
CORE_PACKAGES=(
  "openai"
  "anthropic"
  "pydantic>=2"
  "python-dotenv"
  "requests"
  "beautifulsoup4"
  "rich"
  "mem0ai"
  "chromadb"
  "apscheduler"
  "pynput"
  "pillow"
)
run "$PIP" install "${CORE_PACKAGES[@]}" -q
ok "Core packages installed"

# ── screenshot backend ────────────────────────────────────────────────────────
section "Screenshot backend"
if [[ "$SS_BACKEND" == "none" || "$DISPLAY_SERVER" == "wayland" ]]; then
  info "Installing mss (Wayland-compatible screenshot)"
  run "$PIP" install mss -q
  ok "mss installed"
else
  info "mss (safe fallback for all platforms)"
  run "$PIP" install mss -q
fi

# ── input backend ─────────────────────────────────────────────────────────────
section "Input automation"
if [[ "$INPUT_BACKEND" == "pyautogui" || "$OS" == "macos" || "$OS" == "unknown" ]]; then
  run "$PIP" install pyautogui -q
  ok "pyautogui installed"
else
  info "xdotool/ydotool detected as backend — pyautogui installed as fallback"
  run "$PIP" install pyautogui -q
fi

# ── playwright ────────────────────────────────────────────────────────────────
section "Browser automation (Playwright)"
run "$PIP" install playwright -q
if $DRY_RUN; then
  info "[dry-run] Would run: playwright install chromium"
else
  .venv/bin/playwright install chromium --with-deps 2>/dev/null \
    && ok "Chromium installed" || warn "playwright install chromium failed — browser tools won't work"
fi

# ── voice / TTS / STT ─────────────────────────────────────────────────────────
section "Voice stack"
VOICE_PACKAGES=(
  "openai-whisper"
  "sounddevice"
  "scipy"
)
run "$PIP" install "${VOICE_PACKAGES[@]}" -q
ok "Voice packages installed"

# ── optional heavy packages (skip with --no-optional) ─────────────────────────
if ! $NO_OPTIONAL; then
  section "Optional packages (skip with --no-optional)"

  # Torch — only if GPU or plenty of RAM
  if [[ "$HAS_GPU" == "True" ]] || [[ "${RAM_GB%.*}" -ge 8 ]]; then
    info "GPU or ≥8 GB RAM detected — installing PyTorch (CPU)"
    run "$PIP" install torch --index-url https://download.pytorch.org/whl/cpu -q \
      && ok "torch installed" || warn "torch install failed — skipping"
  else
    warn "Skipping torch (<8 GB RAM, no GPU)"
  fi

  # macOS Quartz (PyObjC) for native input
  if [[ "$OS" == "macos" ]]; then
    info "Installing PyObjC for macOS native input"
    run "$PIP" install pyobjc-framework-Quartz pyobjc-framework-AppKit -q \
      && ok "PyObjC installed" || warn "PyObjC install failed"
  fi
else
  info "Skipping optional packages (--no-optional)"
fi

# ── ADB (if available) ────────────────────────────────────────────────────────
if command -v adb &>/dev/null; then
  section "ADB support"
  run "$PIP" install pure-python-adb -q
  ok "pure-python-adb installed"
fi

# ── .env setup ────────────────────────────────────────────────────────────────
section "Environment file"
if [[ ! -f ".env" && -f ".env.example" ]]; then
  run cp .env.example .env
  ok "Copied .env.example → .env (edit it and add your API keys)"
elif [[ -f ".env" ]]; then
  ok ".env already exists"
else
  warn "No .env.example found — create .env manually"
fi

# ── done ──────────────────────────────────────────────────────────────────────
section "Done"
echo ""
echo -e "${GREEN}${BOLD}NOVA installed successfully!${RESET}"
echo ""
echo "  To activate the environment:  source .venv/bin/activate"
echo "  To start NOVA:                python main.py"
echo "  To reset onboarding:          python -m interfaces.onboarding --reset"
echo "  To rescan hardware:           python -m config.pc_scanner"
if $GUI_SETUP; then
  echo "  Launching GUI onboarding wizard..."
  if ! $DRY_RUN; then
    "$PYTHON" -m interfaces.onboarding --force || warn "GUI onboarding did not complete"
  fi
fi
echo ""
