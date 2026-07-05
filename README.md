# birdframe

Listen to the birds heard outside a window in Edinburgh with
[BirdNET](https://github.com/birdnet-team/birdnet), and each day turn the
detections into a stylised AI-generated picture posted to a shared
[Inky Frame](https://github.com/ddrayne/inky-frame) e-ink display and archived
locally.

See the design and implementation plan in `docs/plans/`.

## Quick start

```sh
brew install uv libsndfile
uv sync --extra dev
uv run pytest            # run the test suite
uv run birdframe         # run the app (grants mic access on first launch)
```

Dashboard: http://localhost:8355
