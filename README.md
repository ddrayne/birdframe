# birdframe

Listen to the birds heard outside a window in Edinburgh with
[BirdNET](https://github.com/birdnet-team/birdnet), and each day turn the
detections into a stylised AI-generated picture posted to a shared
[Inky Frame](https://github.com/ddrayne/inky-frame) e-ink display and archived
locally.

It runs permanently on a Mac: a menu bar app plus a local web dashboard, with a
continuous audio → BirdNET → SQLite → gpt-image-1 → Inky Frame pipeline. Audio is
analysed in memory and never written to disk. See `docs/plans/` for the full
design and implementation plan.

## What it does

- Listens continuously on a configurable input device and identifies birds with
  BirdNET, filtered to species actually plausible in Edinburgh for the time of
  year (BirdNET's geo model), which kills most false positives.
- Records every detection in SQLite so you build up your window's own bird
  census — species over time, first-heard "life list", activity by hour.
- Once a day (configurable), rolls the day up into a rich prompt — the
  most-heard bird, who opened the dawn chorus, the season, that day's Edinburgh
  weather — paints it in a rotating art style with OpenAI gpt-image-1, adds a
  caption, and posts the 1200×1600 picture to the shared frame.
- Posting modes: **daily** (fixed time), **live** (re-post when a new species
  turns up, rate-limited), or **manual** — plus **Post now** any time. It never
  fights other people posting to the shared frame.

## Setup

```sh
brew install uv libsndfile
uv sync --extra dev

# Store your OpenAI key in the macOS Keychain (never written to disk):
uv run python -c "from birdframe import secrets; secrets.set_openai_key('sk-...')"

# Run once in the foreground to grant microphone access and watch it work:
uv run birdframe
```

The dashboard is at http://localhost:8355 (today's birds, gallery, Post now).

Settings live in `~/.config/birdframe/config.toml` (mic device, confidence
threshold, post mode/time, frame URL, styles). Art styles are editable markdown
files in `styles/`.

## Run forever

```sh
bash packaging/install.sh
```

This installs a LaunchAgent that starts birdframe at login and restarts it on
crash. Logs: `~/Library/Logs/birdframe.log`.

## Tests

```sh
uv run pytest                 # full suite (no model download or API spend needed)
BIRDFRAME_SMOKE=1 uv run pytest tests/test_smoke.py -s   # opt-in real-model check
```
