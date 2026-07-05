# birdframe — design

*2026-07-05 · validated with Dan via brainstorming session*

## What it is

A macOS app that runs permanently on Dan's Mac in Edinburgh, listens to the
outside world through a configurable microphone, identifies bird species with
BirdNET, and turns each day's birdlife into a stylised AI-generated picture
that is posted to the shared Inky Frame (a Pi at
`http://pi-inky-impression.local:5000/display`, 1200×1600 portrait, Spectra 6
six-colour e-ink) and archived locally forever.

## Architecture

```
 mic ──▶ Listener ──▶ Detector ──▶ Store ──▶ Artist ──▶ Publisher ──▶ Inky Frame
        (audio       (BirdNET      (SQLite    (gpt-image-1  (HTTP POST)
         capture)     + Edinburgh   + image     + caption)
                      geo filter)   archive)
                          ▲
              Menu bar app │ Web dashboard
              (rumps)      │ (FastAPI, localhost:8355)
```

Single Python 3.12 process (managed with `uv`): rumps owns the macOS main
thread; listener, detector, scheduler, and uvicorn run on worker threads
sharing a WAL-mode SQLite store.

## Components

### Listener (`listener.py`)
- `sounddevice` (PortAudio) stream from the configured input device, 48 kHz mono
  (BirdNET's native rate). Device selectable in settings; defaults to system default.
- Emits ~15 s numpy chunks with 1.5 s overlap so songs straddling a boundary
  aren't missed. Raw audio is never written to disk — analysed and discarded.
- Mic unplugged → log, ⚠️ in menu bar, retry every 30 s, auto-resume.
- Holds a power assertion (`caffeinate -i` child process) so the Mac never
  sleeps through the dawn chorus; display sleep unaffected.
- First launch triggers the standard macOS microphone permission prompt.

### Detector (`detector.py`)
- `birdnet` library acoustic model (TFLite backend, Apple Silicon native).
  Scores 3 s windows inside each chunk; sub-second per chunk, few % CPU.
- Two gates for a detection to count:
  1. confidence ≥ 0.55 (configurable; per-species overrides possible later)
  2. Edinburgh whitelist from BirdNET's geo model (lat 55.95, lon −3.19,
     current week, plausibility floor 0.03), refreshed weekly — migrants come
     and go with the seasons.

### Store (`store.py`)
- SQLite: `detections(timestamp, species_code, common_name, scientific_name,
  confidence)`; `images(generated_at, path, style, prompt, species_json,
  posted_at)`.
- Species-day aggregate view: first heard, last heard, count, peak hour, best
  confidence — consumed by Artist and dashboard.
- Generated images archived as PNGs under the data dir.

### Artist (`artist.py`)
- Rollup of the last 24 h (or midnight-to-now in live mode): species ranked by
  count, dawn-chorus opener, latest singer, first-ever species (celebrated in
  the prompt), Edinburgh weather that day (Open-Meteo, free, no key), season.
- Styles = markdown files in `styles/` (name, prompt template, optional
  negative guidance). Ships with six suited to Spectra 6 e-ink (bold flat
  colour, no subtle gradients): Japanese woodblock (ukiyo-e), vintage
  field-guide plate, Art Nouveau poster, Scottish folk-art, children's book
  illustration, linocut print. Sequential daily rotation by default, pinnable,
  editable in the dashboard.
- Generation: OpenAI gpt-image-1, 1024×1536 portrait, quality high
  (≈ $0.17/image → ~£4/month on daily mode).
- Pillow post-process: resize to 1200×1500 + 100 px caption strip (date +
  species common names) → exactly 1200×1600.
- Fallback: if OpenAI fails after 3 retries, render a pure-Pillow typographic
  poster of the species list — the frame never misses its bird report.

### Publisher (`publisher.py`)
- Honours the inky-frame contract exactly (multipart POST of the image to
  `/display`). The frame is shared with other people/clients — post once per
  trigger, never fight for the display.
- Pi unreachable → retry a few times over 10 minutes, then give up gracefully
  and flag in the menu bar (image is already archived; no surprise late posts).

### Scheduler (`scheduler.py`) — posting modes
- **Daily** (default): generate + post at a fixed time, default 21:00.
- **Live**: on a new-for-today species, regenerate + post; rate-limited to one
  post per 2 h, only 08:00–22:00; the 21:00 "final edition" still posts.
- **Manual**: only Post Now.
- **Post Now** works in every mode (menu bar + dashboard). Dashboard can also
  re-post any archived image.

### Menu bar (`menubar.py`, rumps)
Bird glyph icon (⚠️ variant on trouble). Menu: "🐦 N species today", last three
species with times, Post Now, Pause/Resume listening, mode picker, Open
Dashboard.

### Dashboard (`web/`, FastAPI + plain HTML/JS, localhost:8355)
- **Today**: live species list, detections-by-hour chart
- **History**: day calendar, species-over-time, first-heard "life list",
  hour×species heatmap
- **Gallery**: every image with prompt + species; re-post button
- **Styles**: edit/add/pin
- **Settings**: mic device, thresholds, mode, post time, frame URL, API key

## Config & secrets
- Settings: TOML at `~/.config/birdframe/config.toml`.
- OpenAI key: macOS Keychain via `keyring`, never in files.
- Data dir (SQLite + image archive): `~/.local/share/birdframe/`.

## Testing
- Pure-function unit tests: rollup, prompt assembly, caption rendering,
  whitelist filtering.
- Detector integration: bundled real recordings (robin, blackbird) must yield
  the right species — catches BirdNET API changes.
- Artist/Publisher with mocked HTTP; optional `--live` smoke test that spends
  one real API call.

## Running forever
- LaunchAgent plist: start at login, restart on crash.
- Logs: `~/Library/Logs/birdframe.log`, rotated.
- Menu bar icon is the health indicator.

## Decisions log
- Output: Inky Frame + permanent local archive.
- Image gen: OpenAI gpt-image-1 (single backend for now).
- Cadence: all three modes (daily / live / manual) + Post Now.
- App form: menu bar (rumps) + web dashboard (FastAPI).
- Mic: system default, selectable in settings.
- Extras in scope: rich image context, stats & history, caption strip.
- Explicitly out of scope for now: saved audio clips of detections,
  multiple image-gen backends, LLM-invented styles.
