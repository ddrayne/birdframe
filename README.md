# birdframe

Listen to the birds outside your window, identify them with
[BirdNET](https://github.com/birdnet-team/birdnet), and turn each day's birdlife
into a stylised AI painting — posted to a shared
[Inky Frame](https://github.com/ddrayne/inky-frame) e-ink display and kept as
your own growing bird census.

It runs quietly in the background on a Mac: a menu-bar app plus a local web
dashboard, with a continuous *audio → BirdNET → SQLite → gpt-image → frame*
pipeline. Audio is analysed in memory and never written to disk (only short
best-of clips per species are kept, so you can listen back).

## What it does

- **Listens continuously** and identifies birds, filtered to species plausible
  at your location and season (BirdNET's geo model).
- **Judges its own confidence.** Every detection is weighed on three axes —
  how clearly it was heard, how likely it is here, and how often — into a
  **confirmed / probable / tentative** tier with plain-language reasons.
  Doubtful detections are shown but cordoned off, and kept out of the artwork.
- **Records a clip** of the best detection per species per day — press play and
  hear the actual bird (and tell real ones from a mishearing).
- **Paints the day.** Once a day (or on demand) it composes the day's confident
  birds into a picture with OpenAI gpt-image, in a rotating, fully editable art
  style, captioned with the date and species, and posts it to the frame.
- **Builds a census.** A life list with first-heard dates, an all-time daily
  rhythm chart, totals, and CSV export.
- **Tells the story.** A short LLM-written line about each day's birdsong.
- **Stays out of your way, tells you when it matters** — menu bar status, a
  health panel, and macOS notifications for a new life-list bird, a lost mic, or
  a frame it can't reach.

The dashboard is installable as a PWA and reachable from your phone on the same
network.

## Setup

```sh
brew install uv libsndfile
uv sync --extra dev

# Store your OpenAI key (hidden prompt → macOS Keychain, never on disk):
uv run birdframe set-key

# Check everything's ready (location, key, mic, frame):
uv run birdframe doctor

# Run it (grants microphone access on first launch):
uv run birdframe
```

Open the dashboard at **http://localhost:8355** (or the LAN URL printed at
startup, from your phone). Set your **location** and everything else in the
**Settings** tab — the OpenAI key can also be supplied via the `OPENAI_API_KEY`
environment variable.

Without an OpenAI key birdframe still runs and posts a tidy text poster instead
of a painting.

## Run forever

```sh
bash packaging/install.sh
```

Installs a LaunchAgent that starts birdframe at login and restarts it on crash.
Logs: `~/Library/Logs/birdframe.log`. Data (SQLite, images, clips):
`~/.local/share/birdframe/`. Settings: `~/.config/birdframe/config.toml`.

## Tips

- Detection quality is capped by the microphone. Through double glazing it only
  catches loud, close birds — a cheap USB mic near or outside the window helps
  more than any setting.
- Heard a surprising bird? Play its clip. If it's a mishearing, click **not
  here** to veto it.

## Tests

```sh
uv run pytest                 # full suite (no model download or API spend needed)
BIRDFRAME_SMOKE=1 uv run pytest tests/test_smoke.py -s   # opt-in real-model check
```

CI runs the suite on macOS via GitHub Actions.
