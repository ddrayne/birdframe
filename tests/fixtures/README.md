# Test fixtures

To run the opt-in end-to-end smoke test (`tests/test_smoke.py`), drop a short
recording of a bird here named `robin.wav` (a few seconds of a clearly-singing
common British garden bird works well — e.g. a robin or blackbird from a
public-domain source such as xeno-canto's CC0 recordings).

Then:

```sh
BIRDFRAME_SMOKE=1 uv run pytest tests/test_smoke.py -s
```

The `-s` flag lets you eyeball the printed species/confidence so you can confirm
BirdNET is identifying sensibly. The test is skipped automatically when the
fixture is absent or `BIRDFRAME_SMOKE` is unset, so the normal suite never needs
it.
