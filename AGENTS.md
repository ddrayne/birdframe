# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this is

**birdframe** — an app that listens continuously to birds outside a window
in Edinburgh (BirdNET), and each day paints the detected species with an image
model (OpenAI gpt-image or Gemini, chosen by `image_provider` in config),
posting a 1200×1600 picture to a shared Inky Frame e-ink display (optional)
and archiving it locally, and optionally publishing a read-only public site.
It runs on macOS (menu bar + dashboard) or headless on Linux, e.g. a
Raspberry Pi (dashboard only). Design and the task-by-task implementation plan live
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
uv run birdframe set-key cloudflare # the Cloudflare Pages token for the public site
uv run birdframe publish            # build (and deploy, if configured) the public site now
uv run birdframe install            # run forever: LaunchAgent on macOS, systemd user service on Linux
./install.sh                        # one-line setup from a fresh clone (Mac or Raspberry Pi)
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
- **birdnet ≥ 1.1 needs TensorFlow for `"tf"` models by default**, and nothing
  installs it (Pis never have it). `detector.model_options()` passes
  `library="litert"` (ai-edge-litert, a birdnet dependency) when TensorFlow is
  absent; don't drop it or the detector fails to load.
- **Secrets never touch the config file or logs.** `secrets.get_key(provider)`
  resolves each key from its env var first (`OPENAI_API_KEY` / `GEMINI_API_KEY`
  / `CLOUDFLARE_API_TOKEN`), then the macOS Keychain on a Mac, or on Linux
  `~/.config/birdframe/secrets.env` (created 0600, written atomically). Linux
  deliberately skips `keyring`: a headless Pi has no keychain, and a desktop
  keyring can block forever on an unlock prompt. Users set keys with
  `birdframe set-key [openai|gemini|cloudflare]` (hidden `getpass` prompt).
  Config TOML holds everything else. Don't add a config field for keys. Narration (`narrator.py`) always needs the
  OpenAI key, regardless of `image_provider`. Keychain items MUST be created via
  `birdframe set-key` (Python keyring), never the `security` CLI — an item
  created by `security` isn't on Python's ACL, so `keyring.get_password` blocks
  forever on a GUI authorization prompt the headless app can never answer.

## Architecture

Single process. On macOS `rumps` owns the main thread (menu bar), which only
displays state; on Linux there is no menu bar and the main thread waits in
`app._serve_headless` for SIGTERM, then releases the mic and exits with
`os._exit(0)`. `host.py` holds the few other platform differences (log path,
keep-awake, notifications) and `service.py` the service manager (launchd or a
systemd user service). The audio listener, BirdNET detector, scheduler
(`app._start_scheduler`, which also performs the nightly restart), watchdog and
a `uvicorn`/FastAPI dashboard run on worker threads, all sharing one WAL-mode
SQLite store. Never do slow work (renders, frame posts) on the AppKit thread.
Audio is analysed in memory in ~15s chunks and **never written to disk**.
`birdframe/app.py:main` is the wiring seam — read it first to see how the
pieces connect.

Every public `Store` method holds one lock that the detector thread also needs
for each chunk, so dashboard queries must stay index-backed and cheap. A slow
query stalls detection, and a long enough stall trips the watchdog's
"cannot keep up" restart. `/api/now` is polled every 5s while Today is open.

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
  politely: `source=birdframe`, a modest `hold_minutes`, never `force` for
  automatic posts (an explicit user "send"/"post now" does force), one
  `Idempotency-Key` per publish (shared by its retries), and treats HTTP 409
  (held by someone else) as "leave it be". Every image is archived locally
  first, so an unreachable frame loses nothing. Don't add retry logic that
  would re-stomp the frame hours later.
- **Artist always produces an image.** The paid painter is duck-typed
  (`image_client.py`: `OpenAIImageClient` or `GeminiImageClient`, selected by
  `config.image_provider` in `app._make_image_client`). If it fails (or no key
  is set), `artist.generate()` falls back to a pure-Pillow typographic poster
  and labels the style `"<name> (fallback)"`. The frame never misses its daily
  report.

Output is always exactly **1200×1600** (`compose.FRAME_W/FRAME_H`): art fills
the top 1500px, a caption strip (date + species) the bottom 100px. gpt-image-2
and later render natively at 1200×1504; `compose` fills the art area with any
render within 3% of 4:5 and letterboxes a real mismatch (never crops birds).
The frame (github.com/ddrayne/inky-frame) Floyd–Steinberg-dithers everything
onto six inks whose "white" is light grey, so caption text is pure black (grey
text prints as speckles); `compose.eink_preview` reproduces that pipeline for
the dashboard's "On the frame" view. Prompts must not contain numbers — counts
come back as printed digits or as that many birds.

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
- **Acoustic analytics + MCP** (`acoustics.py`, `/api/detections`,
  `/api/rankings`, `birdframe-mcp`): read-only cursor-based access to detection
  events and segment-level sound metrics. Counts are calls, not individual birds.
- **Narration** (`narrator.py`, `/api/narration`): one-line day story via
  `gpt-4.1-mini`, cached per day, template fallback.
- **Health** (`/api/health`) + notifications (`host.notify`: macOS
  notifications, log lines on Linux): mic loss, unreachable frame, life-list firsts.
- **Icon/PWA** (`icon.py` renders the app icon; manifest + `sw.js`). The shell
  and ES modules are served `Cache-Control: no-cache` (modules are imported
  without version stamps); bump `?v=` in `index.html`/`sw.js` with UI changes.
- **Public site** (`public_site.py`, `public_template/`, `birdframe publish`):
  a static, read-only edition built from aggregates only: confirmed/probable
  species, real paintings (no fallback posters), no audio, coordinates, raw
  detections or frame address. `SitePublisher` rebuilds it on its own thread
  after new paintings and hourly. Uploads (`public_deploy_command`, or
  Cloudflare Pages via `cloudflare.py`) follow a stricter schedule: a new
  painting goes up at once, other changes (the build's `fingerprint`) at most
  every 6h, failures back off 30 min, and the last upload is persisted in
  `public-site.json` so restarts and crash loops never re-upload. Cloudflare:
  the project is looked up and created over the REST API (Wrangler won't
  create one without a TTY), and the files go up with `npx wrangler@4 pages
  deploy` (Node 22+). The token goes only in Wrangler's environment, never in
  argv. `public_*`/`cloudflare_*` settings are config-file only (the
  LAN dashboard must never choose a folder to write or a command to run).
  Routes are plain anchors (`#birds`, `#p-<id>`, `#b-<slug>`, `#frame`).
  `frame_url = ""` disables the frame cleanly (`Publisher.enabled`).
- **Dashboard images**: lists use `/api/image/{id}?w=` (cached JPEGs in
  `images/derived/`), never the 3 MB originals; `/api/image/{id}/eink` is the
  simulated frame print. State-changing requests labelled
  `Sec-Fetch-Site: cross-site` are refused (the dashboard is LAN-wide, unauthenticated).
- CLI: `birdframe set-key | doctor | backup | publish | install | status | logs | --help`.

## Styles

Art styles are editable markdown files in `styles/` (`# name`, `## Prompt` with a
`{scene}` placeholder, optional `## Avoid`). `styles.load_styles()` reads them;
`choose_style()` rotates daily by ordinal or honours a pinned style. Adding a
style is just dropping in a new `.md` file — no code change.

## Config & data locations

- Settings: `~/.config/birdframe/config.toml` (`config.DEFAULTS` is the schema;
  unknown keys are ignored, missing keys fall back to defaults).
- Data: `~/.local/share/birdframe/` (SQLite + image archive).
- Logs: `~/Library/Logs/birdframe.log` on macOS;
  `~/.local/state/birdframe/birdframe.log` on Linux.
- Keys on Linux: `~/.config/birdframe/secrets.env` (0600).
- Dashboard: http://localhost:8355.
