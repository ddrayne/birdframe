# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**birdframe** — a macOS app that listens continuously to birds outside a window
in Edinburgh (BirdNET), and each day paints the detected species with an image
model (OpenAI gpt-image or Gemini, chosen by `image_provider` in config),
posting a 1200×1600 picture to a shared Inky Frame e-ink display
and archiving it locally. Design and the task-by-task implementation plan live
in `docs/plans/2026-07-05-birdframe-*.md`.

## Commands

```sh
uv sync --extra dev                 # install (Python 3.12 — see constraint below)
uv run pytest                       # full suite; needs no model download or API spend
uv run pytest tests/test_store.py -v            # one file
uv run pytest tests/test_scheduler.py::test_daily_fires_once_at_post_time -v   # one test
BIRDFRAME_SMOKE=1 uv run pytest tests/test_smoke.py -s   # opt-in real-model check (needs tests/fixtures/robin.wav)
uv run birdframe                    # run the app (menu bar + dashboard); grants mic access on first launch
uv run birdframe set-key            # store the OpenAI key in the Keychain (hidden prompt)
uv run birdframe set-key gemini     # same, for the Gemini key
bash packaging/install.sh           # install the LaunchAgent to run forever
```

There is no separate lint/typecheck step configured; pytest is the gate.

## Hard constraints (these will bite you)

- **Python must be 3.12.** `birdnet` on macOS ARM64 supports 3.11/3.12/3.13 but
  NOT 3.14 (often the machine default). `pyproject.toml` pins `>=3.12,<3.13`;
  always invoke via `uv run` so the pinned interpreter is used.
- **BirdNET models auto-download from Zenodo** (record 15050749) on the first
  `birdnet.load(...)`, cached under `~/.cache`. First run is slow; Zenodo
  outages surface as `Failed to download ... Status code: 500` — that's their
  server, not the code.
- **Secrets never touch disk.** `secrets.get_key(provider)` resolves each
  provider's key from its env var first (`OPENAI_API_KEY` / `GEMINI_API_KEY`),
  then the macOS Keychain. Users set them with `birdframe set-key [openai|gemini]`
  (hidden `getpass` prompt → Keychain). Config TOML holds everything else.
  Don't add a config field for keys. Narration (`narrator.py`) always needs the
  OpenAI key, regardless of `image_provider`. Keychain items MUST be created via
  `birdframe set-key` (Python keyring), never the `security` CLI — an item
  created by `security` isn't on Python's ACL, so `keyring.get_password` blocks
  forever on a GUI authorization prompt the headless app can never answer.

## Architecture

Single process. `rumps` owns the macOS main thread (menu bar); the audio
listener, BirdNET detector, scheduler, and a `uvicorn`/FastAPI dashboard run on
worker threads, all sharing one WAL-mode SQLite store. Audio is analysed in
memory in ~15s chunks and **never written to disk**. `birdframe/app.py:main` is
the wiring seam — read it first to see how the pieces connect.

Data flow: `listener → detector → store → artist → publisher → Inky Frame`, with
the `menubar` and `web` dashboard both driving a shared `runtime.Runtime`.

Key design boundaries worth preserving:

- **`detector.py` is the only file that imports `birdnet`.** Everything else is
  testable without the model — tests mock the detector. It uses
  `predict_arrays((ndarray, sample_rate))` so audio never hits disk, resolves
  the result's `species_name`/`confidence` columns dynamically from the array
  dtype (field names have varied across birdnet versions — don't hard-code
  them), and filters detections against an **Edinburgh geo whitelist** built
  from BirdNET's geo model (lat 55.95, lon −3.19). The whitelist kills most
  false positives.
- **Pure logic is separated from I/O for testability.** `scheduler.decide()`,
  `rollup.build_scene()`, `listener.Chunker`, `compose.compose_final()` are
  pure functions with no clock, network, or device access — the timing/stream
  wrappers around them are thin. When adding behaviour, put the decision in the
  pure function and keep the wrapper dumb. Injectable seams: `now=` callables,
  `http_get`/`http_post`, and `sdk=`/`image_client=` parameters — use them in
  tests instead of patching globals.
- **The frame is shared** with other people/clients. The `publisher` posts
  politely: `source=birdframe`, a modest `hold_minutes`, **never** `force`, and
  treats HTTP 409 (held by someone else) as "leave it be". Every image is
  archived locally first, so an unreachable frame loses nothing. Don't add retry
  logic that would re-stomp the frame hours later.
- **Artist always produces an image.** The paid painter is duck-typed
  (`image_client.py`: `OpenAIImageClient` or `GeminiImageClient`, selected by
  `config.image_provider` in `app._make_image_client`). If it fails (or no key
  is set), `artist.generate()` falls back to a pure-Pillow typographic poster
  and labels the style `"<name> (fallback)"`. The frame never misses its daily
  report.

Output is always exactly **1200×1600** (`compose.FRAME_W/FRAME_H`): art fills
the top 1500px, a caption strip (date + species) the bottom 100px.

## Reliability & false positives

`reliability.py` is the general treatment of false positives — do NOT add
per-species hacks. `assess(best_confidence, geo_plausibility, count)` returns a
confirmed/probable/tentative tier + reasons. "Confirmed" is reserved for birds
genuinely expected here (geo≥0.30) and clearly heard (≥0.70); regionally
uncommon or modest-confidence birds are capped at probable. `for_artwork()` is
stricter still — it keeps confident-but-implausible clusters (hallucinated water
birds) out of the picture. The dashboard shows tentative detections but
collapses them into a "doubtful" section. Per-species geo plausibility comes
from `detector.geo_by_scientific` (built with the whitelist). Users can still
hard-veto a species via the "not here" blocklist (`config.blocked_species`).

## Other subsystems

- **Audio clips** (`runtime._save_clip`): best clip per species/day as OGG under
  the data dir; `store.clips` table; served at `/api/clip`, played inline.
- **Census** (`store.life_list/hour_histogram/totals`, `/api/census`): life
  list, all-time rhythm, CSV export.
- **Narration** (`narrator.py`, `/api/narration`): one-line day story via
  `gpt-4.1-mini`, cached per day, template fallback.
- **Health** (`/api/health`) + macOS notifications (`app._notify`): mic loss,
  unreachable frame, life-list firsts.
- **Icon/PWA** (`icon.py` renders the app icon; manifest + `sw.js`).
- CLI: `birdframe set-key | doctor | --help`.

## Styles

Art styles are editable markdown files in `styles/` (`# name`, `## Prompt` with a
`{scene}` placeholder, optional `## Avoid`). `styles.load_styles()` reads them;
`choose_style()` rotates daily by ordinal or honours a pinned style. Adding a
style is just dropping in a new `.md` file — no code change.

## Config & data locations

- Settings: `~/.config/birdframe/config.toml` (`config.DEFAULTS` is the schema;
  unknown keys are ignored, missing keys fall back to defaults).
- Data: `~/.local/share/birdframe/` (SQLite + image archive).
- Logs: `~/Library/Logs/birdframe.log`.
- Dashboard: http://localhost:8355.
