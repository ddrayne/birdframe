#!/bin/bash
# birdframe bootstrap installer — from a fresh clone to running-forever in one go.
set -euo pipefail
cd "$(dirname "$0")"

echo "🐦  Installing birdframe"

# 1. Prerequisites
if ! command -v brew >/dev/null 2>&1; then
  echo "error: Homebrew is required — install it from https://brew.sh" >&2
  exit 1
fi
command -v uv >/dev/null 2>&1 || { echo "· installing uv…"; brew install uv; }
brew list libsndfile >/dev/null 2>&1 || { echo "· installing libsndfile…"; brew install libsndfile; }

# 2. Dependencies (Python 3.12 is fetched automatically by uv)
echo "· syncing dependencies…"
uv sync --extra dev

# 3. OpenAI key (optional — birdframe still runs without it)
if ! uv run python -c "from birdframe import secrets; import sys; sys.exit(0 if secrets.has_openai_key() else 1)" 2>/dev/null; then
  echo
  read -r -p "Add an OpenAI API key now for AI paintings? [y/N] " ans
  [[ "$ans" =~ ^[Yy] ]] && uv run birdframe set-key || echo "· skipped — set it later with 'uv run birdframe set-key'"
fi

# 4. Check, then install the background service + a clickable app
echo; uv run birdframe doctor || true
echo; echo "· installing the background service…"
uv run birdframe install
uv run birdframe make-app

cat <<EOF

✅  birdframe is installed and listening.
    Grant microphone access if macOS prompts you.
    Dashboard:  http://localhost:8355   (also on your phone via the LAN URL in the log)
    Manage it:  uv run birdframe [status|stop|start|restart|logs|uninstall]
EOF
