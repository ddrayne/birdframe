#!/bin/bash
# birdframe bootstrap installer — from a fresh clone to running-forever in one go,
# on a Mac (Homebrew) or on Linux such as Raspberry Pi OS (apt).
set -euo pipefail
cd "$(dirname "$0")"

echo "🐦  Installing birdframe"
LINUX=false
[ "$(uname -s)" = "Linux" ] && LINUX=true

# 1. Prerequisites
if $LINUX; then
  if command -v dpkg-query >/dev/null 2>&1; then
    # PortAudio for the microphone, a serif font for captions, curl for uv.
    missing=()
    for pkg in libportaudio2 fonts-dejavu-core curl; do
      dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed" || missing+=("$pkg")
    done
    if [ ${#missing[@]} -gt 0 ]; then
      echo "· installing ${missing[*]} (asks for your password)…"
      sudo apt-get update -qq
      sudo apt-get install -y --no-install-recommends "${missing[@]}"
    fi
  else
    echo "· note: install PortAudio (libportaudio2 or portaudio) with your package manager"
  fi
  if ! command -v uv >/dev/null 2>&1; then
    echo "· installing uv…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
else
  if ! command -v brew >/dev/null 2>&1; then
    echo "error: Homebrew is required — install it from https://brew.sh" >&2
    exit 1
  fi
  command -v uv >/dev/null 2>&1 || { echo "· installing uv…"; brew install uv; }
  brew list libsndfile >/dev/null 2>&1 || { echo "· installing libsndfile…"; brew install libsndfile; }
fi

# 2. Dependencies (Python 3.12 is fetched automatically by uv)
echo "· syncing dependencies…"
uv sync --extra dev

# 3. OpenAI key (optional — birdframe still runs without it)
if ! uv run python -c "from birdframe import secrets; import sys; sys.exit(0 if secrets.has_openai_key() else 1)" 2>/dev/null; then
  echo
  read -r -p "Add an OpenAI API key now for AI paintings? [y/N] " ans
  [[ "$ans" =~ ^[Yy] ]] && uv run birdframe set-key || echo "· skipped — set it later with 'uv run birdframe set-key'"
fi

# 4. Check, then install the background service (+ a clickable app on a Mac)
echo; uv run birdframe doctor || true
echo; echo "· installing the background service…"
if $LINUX; then
  # Start at boot, not at login: let this user's services run without a session.
  loginctl show-user "$USER" --property=Linger 2>/dev/null | grep -q "=yes" \
    || sudo loginctl enable-linger "$USER" || true
  uv run birdframe install
  cat <<EOF

✅  birdframe is installed and listening.
    Dashboard:  http://$(hostname).local:8355   (from your phone, on the same network)
    Manage it:  uv run birdframe [status|stop|start|restart|logs|uninstall]
EOF
else
  uv run birdframe install
  uv run birdframe make-app
  cat <<EOF

✅  birdframe is installed and listening.
    Grant microphone access if macOS prompts you.
    Dashboard:  http://localhost:8355   (also on your phone via the LAN URL in the log)
    Manage it:  uv run birdframe [status|stop|start|restart|logs|uninstall]
EOF
fi
