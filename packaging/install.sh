#!/bin/bash
# Install birdframe as a background service that restarts if it ever stops:
# a LaunchAgent on macOS (runs at login), a systemd user service on Linux —
# a Raspberry Pi — (runs at boot).
set -euo pipefail

WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || true)"

if [ "$(uname -s)" = "Linux" ]; then
  # On Linux (a Raspberry Pi) the one-line installer does it all: PortAudio,
  # uv, dependencies, and a systemd user service that starts at boot.
  exec "$WORKDIR/install.sh"
fi

if [ -z "$UV" ]; then
  echo "error: 'uv' not found on PATH. Install it first: brew install uv" >&2
  exit 1
fi

PLIST_DST="$HOME/Library/LaunchAgents/com.birdframe.plist"
mkdir -p "$HOME/Library/LaunchAgents"

sed -e "s#__UV__#$UV#g" \
    -e "s#__WORKDIR__#$WORKDIR#g" \
    -e "s#__HOME__#$HOME#g" \
    "$WORKDIR/packaging/com.birdframe.plist" > "$PLIST_DST"

launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "Installed and loaded $PLIST_DST"
echo
echo "NOTE: the first run will prompt for microphone access — grant it for the"
echo "user running this agent, or run 'uv run birdframe' once in the foreground"
echo "first to approve the mic. Logs: ~/Library/Logs/birdframe.log"
echo "Dashboard: http://localhost:8355"
echo
echo "To stop:    launchctl unload $PLIST_DST"
echo "To restart: launchctl unload $PLIST_DST && launchctl load $PLIST_DST"
