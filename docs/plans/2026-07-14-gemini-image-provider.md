# Gemini Image Provider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let birdframe paint the daily picture with Gemini (Nano Banana Pro) as a config-selected alternative to OpenAI gpt-image — no cross-provider fallback.

**Architecture:** A new `GeminiImageClient` sits beside `OpenAIImageClient` behind the existing duck-typed `.generate(prompt) -> bytes` seam. `config.image_provider` picks the backend at wiring time in `app.py`; `secrets.py` generalises to per-provider keys (env var, then Keychain). Everything else (Artist, compose, publisher) is untouched.

**Tech Stack:** Python 3.12 (always `uv run`), `google-genai` SDK, `keyring`, pytest with `mocker` fakes (no network, no API spend in tests).

**Design doc:** `docs/plans/2026-07-14-gemini-image-provider-design.md`

---

### Task 1: Config fields

**Files:**
- Modify: `birdframe/config.py` (DEFAULTS dict ~line 30, dataclass fields ~line 63)
- Test: `tests/test_config.py`

**Step 1: Write the failing test** — append to `tests/test_config.py`:

```python
def test_image_provider_defaults(tmp_path):
    cfg = Config.load(tmp_path / "config.toml")
    assert cfg.image_provider == "openai"
    assert cfg.gemini_model == "gemini-3-pro-image"


def test_image_provider_from_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('image_provider = "gemini"\n')
    assert Config.load(p).image_provider == "gemini"
```

(Match the existing imports in that file — it already imports `Config`.)

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `TypeError` / `AttributeError` (unknown field `image_provider`).

**Step 3: Implement** — in `birdframe/config.py`:

In `DEFAULTS`, directly under the `"openai_model"` line, add:

```python
    "image_provider": "openai",    # openai | gemini — which paid painter to use
    "gemini_model": "gemini-3-pro-image",  # Nano Banana Pro
```

In the `Config` dataclass, directly under `openai_model: str`, add:

```python
    image_provider: str
    gemini_model: str
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: all PASS.

**Step 5: Commit**

```bash
git add birdframe/config.py tests/test_config.py
git commit -m "feat: add image_provider and gemini_model config fields"
```

---

### Task 2: Per-provider secrets

**Files:**
- Modify: `birdframe/secrets.py` (whole file — small)
- Test: `tests/test_secrets.py`

**Step 1: Write the failing tests** — append to `tests/test_secrets.py`:

```python
def test_gemini_key_roundtrip(mocker):
    store = {}
    mocker.patch.object(secretmod.keyring, "set_password",
                        side_effect=lambda s, u, p: store.__setitem__((s, u), p))
    mocker.patch.object(secretmod.keyring, "get_password",
                        side_effect=lambda s, u: store.get((s, u)))
    mocker.patch.dict(secretmod.os.environ, {}, clear=False)
    secretmod.os.environ.pop("GEMINI_API_KEY", None)
    secretmod.set_key("gemini", "AIza-test")
    assert secretmod.get_key("gemini") == "AIza-test"
    assert ("birdframe", "gemini_api_key") in store


def test_openai_keychain_entry_name_unchanged(mocker):
    """Existing users' Keychain entries must keep working."""
    store = {}
    mocker.patch.object(secretmod.keyring, "set_password",
                        side_effect=lambda s, u, p: store.__setitem__((s, u), p))
    secretmod.set_key("openai", "sk-abc")
    assert ("birdframe", "openai_api_key") in store


def test_gemini_env_var_precedence(mocker):
    mocker.patch.object(secretmod.keyring, "get_password", return_value="from-keychain")
    mocker.patch.dict(secretmod.os.environ, {"GEMINI_API_KEY": "from-env"})
    assert secretmod.get_key("gemini") == "from-env"


def test_unknown_provider_raises():
    import pytest
    with pytest.raises(ValueError):
        secretmod.get_key("dalle")
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: new tests FAIL with `AttributeError: ... has no attribute 'set_key'`.

**Step 3: Implement** — replace the body of `birdframe/secrets.py` below the imports with:

```python
_SERVICE = "birdframe"
_PROVIDERS = {
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
}


def _provider(provider: str) -> tuple[str, str]:
    try:
        return _PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"unknown image provider: {provider!r}") from None


def set_key(provider: str, key: str) -> None:
    """Persist a provider's key in the macOS Keychain."""
    user, _ = _provider(provider)
    keyring.set_password(_SERVICE, user, key.strip())


def get_key(provider: str) -> str | None:
    """Resolve a provider's key: environment variable first, then the Keychain."""
    user, env_var = _provider(provider)
    env = os.environ.get(env_var)
    if env:
        return env.strip()
    return keyring.get_password(_SERVICE, user)


def set_openai_key(key: str) -> None:
    set_key("openai", key)


def get_openai_key() -> str | None:
    return get_key("openai")


def has_openai_key() -> bool:
    return bool(get_openai_key())
```

Update the module docstring to say keys are per-provider (OpenAI / Gemini), env var wins, never written to disk. Keep the existing wrappers — other modules import them.

**Step 4: Run tests**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: all PASS.

**Step 5: Commit**

```bash
git add birdframe/secrets.py tests/test_secrets.py
git commit -m "feat: per-provider API key storage (openai, gemini)"
```

---

### Task 3: Add google-genai dependency

**Step 1:** In `pyproject.toml` `dependencies`, after `"openai>=1.30",` add:

```toml
    "google-genai>=1.0",
```

**Step 2:** Run: `uv sync --extra dev`
Expected: resolves and installs `google-genai`.

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add google-genai dependency"
```

---

### Task 4: GeminiImageClient

**Files:**
- Modify: `birdframe/image_client.py` (append class)
- Test: `tests/test_image_client.py`

**Step 1: Write the failing tests** — append to `tests/test_image_client.py`. Note the fake mirrors the google-genai response shape: `resp.candidates[0].content.parts[i].inline_data.data`.

```python
from birdframe.image_client import GeminiImageClient


def _gemini_resp(mocker, parts):
    return mocker.Mock(candidates=[mocker.Mock(content=mocker.Mock(parts=parts))])


def _image_part(mocker, data):
    return mocker.Mock(inline_data=mocker.Mock(data=data))


def _text_part(mocker):
    return mocker.Mock(inline_data=None)


def test_gemini_returns_image_bytes(mocker):
    fake = mocker.Mock()
    fake.models.generate_content.return_value = _gemini_resp(
        mocker, [_text_part(mocker), _image_part(mocker, b"PNGDATA")])
    client = GeminiImageClient(api_key="AIza-test", sdk=fake)
    assert client.generate("a robin in a garden") == b"PNGDATA"
    kwargs = fake.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3-pro-image"
    assert kwargs["config"]["image_config"]["aspect_ratio"] == "4:5"
    assert kwargs["config"]["image_config"]["image_size"] == "2K"


def test_gemini_quality_maps_to_size(mocker):
    fake = mocker.Mock()
    fake.models.generate_content.return_value = _gemini_resp(
        mocker, [_image_part(mocker, b"x")])
    GeminiImageClient(api_key="k", quality="medium", sdk=fake).generate("p")
    kwargs = fake.models.generate_content.call_args.kwargs
    assert kwargs["config"]["image_config"]["image_size"] == "1K"


def test_gemini_base64_string_data(mocker):
    fake = mocker.Mock()
    fake.models.generate_content.return_value = _gemini_resp(
        mocker, [_image_part(mocker, base64.b64encode(b"PNGDATA").decode())])
    client = GeminiImageClient(api_key="k", sdk=fake)
    assert client.generate("p") == b"PNGDATA"


def test_gemini_no_image_part_raises_without_retry_burn(mocker):
    """A 200 with only text (e.g. a refusal) is a hard error, and must not
    burn paid retries."""
    fake = mocker.Mock()
    fake.models.generate_content.return_value = _gemini_resp(
        mocker, [_text_part(mocker)])
    client = GeminiImageClient(api_key="k", sdk=fake, max_retries=3, backoff=0)
    with pytest.raises(RuntimeError):
        client.generate("p")
    assert fake.models.generate_content.call_count == 1


def test_gemini_retries_then_raises(mocker):
    fake = mocker.Mock()
    fake.models.generate_content.side_effect = RuntimeError("boom")
    client = GeminiImageClient(api_key="k", sdk=fake, max_retries=3, backoff=0)
    with pytest.raises(RuntimeError):
        client.generate("p")
    assert fake.models.generate_content.call_count == 3
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_image_client.py -v`
Expected: FAIL with `ImportError: cannot import name 'GeminiImageClient'`.

**Step 3: Implement** — append to `birdframe/image_client.py`:

```python
class GeminiImageClient:
    # 4:5 exactly fills the frame's 1200x1500 art area (no letterbox bars).
    ASPECT_RATIO = "4:5"

    def __init__(self, api_key: str, model: str = "gemini-3-pro-image",
                 quality: str = "high", sdk=None, max_retries: int = 3,
                 backoff: float = 2.0, timeout: float = 300.0):
        self.model = model
        self.image_size = "2K" if quality == "high" else "1K"
        self.max_retries = max_retries
        self.backoff = backoff
        if sdk is not None:
            self._client = sdk
        else:
            from google import genai
            # google-genai takes its HTTP timeout in milliseconds.
            self._client = genai.Client(
                api_key=api_key,
                http_options={"timeout": int(timeout * 1000)})

    def _image_bytes(self, resp) -> bytes:
        for part in resp.candidates[0].content.parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                data = inline.data
                if isinstance(data, str):
                    return base64.b64decode(data)
                return data
        # A 200 with no image (e.g. a text-only safety refusal) is a bug or a
        # blocked prompt, not a transient error — don't burn paid retries on it.
        raise RuntimeError("Gemini response contained no image part")

    def generate(self, prompt: str) -> bytes:
        last = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=prompt,
                    config={
                        "response_modalities": ["TEXT", "IMAGE"],
                        "image_config": {
                            "aspect_ratio": self.ASPECT_RATIO,
                            "image_size": self.image_size,
                        },
                    },
                )
                return self._image_bytes(resp)
            except Exception as exc:
                last = exc
                if isinstance(exc, RuntimeError) and "no image part" in str(exc):
                    raise
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (attempt + 1))
        raise last
```

Also update the module docstring (line 1) from "Concrete image backend: OpenAI gpt-image family" to mention both backends.

**Step 4: Run tests**

Run: `uv run pytest tests/test_image_client.py -v`
Expected: all PASS.

**Step 5: Commit**

```bash
git add birdframe/image_client.py tests/test_image_client.py
git commit -m "feat: GeminiImageClient (Nano Banana Pro) image backend"
```

---

### Task 5: Wiring in app.py (+ testable factory)

**Files:**
- Modify: `birdframe/app.py:88-96` (extract factory), `_set_key_interactive` (~line 227), `_doctor` (~line 241), `main` help text (~line 304)
- Test: `tests/test_app_wiring.py` (create)

**Step 1: Write the failing test** — create `tests/test_app_wiring.py`:

```python
"""The image-client factory picks the backend from config.image_provider."""
from birdframe.app import _make_image_client
from birdframe.config import Config
from birdframe.image_client import GeminiImageClient, OpenAIImageClient


def _config(tmp_path, provider):
    cfg = Config.load(tmp_path / "config.toml")
    cfg.image_provider = provider
    return cfg


def test_openai_selected(tmp_path, mocker):
    mocker.patch("birdframe.secrets.get_key", return_value="sk-test")
    client = _make_image_client(_config(tmp_path, "openai"))
    assert isinstance(client, OpenAIImageClient)


def test_gemini_selected(tmp_path, mocker):
    mocker.patch("birdframe.secrets.get_key", return_value="AIza-test")
    client = _make_image_client(_config(tmp_path, "gemini"))
    assert isinstance(client, GeminiImageClient)
    assert client.model == "gemini-3-pro-image"


def test_missing_key_returns_none(tmp_path, mocker):
    mocker.patch("birdframe.secrets.get_key", return_value=None)
    assert _make_image_client(_config(tmp_path, "gemini")) is None
```

Note: constructing the clients with a real-looking key builds a real SDK object but makes **no network call** — both SDKs are lazy. That's fine in tests.

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_wiring.py -v`
Expected: FAIL with `ImportError: cannot import name '_make_image_client'`.

**Step 3: Implement** — in `birdframe/app.py`:

Add a module-level factory (near the top-level functions, before `build_runtime`'s caller):

```python
def _make_image_client(config):
    """The paid painter selected by config.image_provider, or None if that
    provider's key is missing (the day then gets the free fallback poster)."""
    key = secrets.get_key(config.image_provider)
    if not key:
        log.warning(
            "No %s key set — pictures will use the fallback poster. "
            "Set one with: birdframe set-key %s",
            config.image_provider, config.image_provider)
        return None
    if config.image_provider == "gemini":
        from birdframe.image_client import GeminiImageClient
        return GeminiImageClient(api_key=key, model=config.gemini_model,
                                 quality=config.image_quality)
    from birdframe.image_client import OpenAIImageClient
    return OpenAIImageClient(api_key=key, model=config.openai_model,
                             quality=config.image_quality)
```

Replace the existing block at lines 88–96:

```python
    api_key = secrets.get_openai_key()
    image_client = None
    if api_key:
        from birdframe.image_client import OpenAIImageClient
        image_client = OpenAIImageClient(api_key=api_key, model=config.openai_model,
                                         quality=config.image_quality)
    else:
        log.warning("No OpenAI key set — pictures will use the fallback poster. "
                    "Set one with: birdframe set-key")
```

with:

```python
    image_client = _make_image_client(config)
```

Update `_set_key_interactive` to take the provider from argv:

```python
def _set_key_interactive(provider: str = "openai") -> int:
    """`birdframe set-key [openai|gemini]` — prompt for the key without echoing
    it or leaving it in shell history, then store it in the macOS Keychain."""
    import getpass

    if provider not in ("openai", "gemini"):
        print(f"Unknown provider {provider!r} — use 'openai' or 'gemini'.")
        return 1
    label = {"openai": "OpenAI", "gemini": "Gemini"}[provider]
    key = getpass.getpass(f"{label} API key (input hidden): ").strip()
    if not key:
        print("No key entered — nothing changed.")
        return 1
    secrets.set_key(provider, key)
    print("Saved to the macOS Keychain. birdframe will use it on next run.")
    return 0
```

In `main()`, change the dispatch line to pass the optional provider:

```python
    if argv and argv[0] == "set-key":
        raise SystemExit(_set_key_interactive(argv[1] if len(argv) > 1 else "openai"))
```

In `_doctor()`, replace the OpenAI-key lines (248–250) with both providers, flagging the configured one:

```python
    for provider, label in (("openai", "OpenAI key"), ("gemini", "Gemini key")):
        key = secrets.get_key(provider)
        active = provider == config.image_provider
        if key:
            print(f"  {ok} {label:<14} set" + ("  (selected painter)" if active else ""))
        elif active:
            print(f"  {warn} {label:<14} missing — run 'birdframe set-key {provider}' "
                  "(art uses a text poster without it)")
        else:
            print(f"    {label:<14} not set (not selected)")
```

In the `--help` text, change the set-key line to:

```
  set-key [openai|gemini]  store an API key in the macOS Keychain (default: openai)
```

**Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS (139+ tests).

**Step 5: Commit**

```bash
git add birdframe/app.py tests/test_app_wiring.py
git commit -m "feat: select image provider from config; set-key/doctor know gemini"
```

---

### Task 6: Real end-to-end verification (one paid call, ~$0.13)

The Gemini key is already in the Keychain (`birdframe`/`gemini_api_key`).
This is the only step that spends money; the user authorized it by providing
the key for this purpose.

**Step 1:** Write a throwaway script in the scratchpad (NOT the repo) that:
- builds `GeminiImageClient(api_key=<from keyring>, model="gemini-3-pro-image")`
- calls `.generate("A watercolour of a European Robin in an Edinburgh garden, soft morning light")`
- asserts the bytes start with `\x89PNG` or `\xff\xd8` (JPEG), opens them with Pillow, prints size/format
- runs `compose_final(art_bytes, datetime.now(), ["European Robin"])` and writes the 1200×1600 result to the scratchpad

Run with `uv run python <script>`.

**Step 2:** If the API rejects the config (modalities/image_size naming can
drift between SDK versions), fix `GeminiImageClient` to match the real API,
re-run unit tests, amend the Task 4 commit message convention (new commit,
`fix:`), and re-verify.

**Step 3:** Send the composed image to the user for a visual check.

**Step 4:** Update CLAUDE.md: in the architecture section mention the two
image backends and `image_provider`; in secrets mention `GEMINI_API_KEY` /
`set-key gemini`. Commit as `docs: document gemini image provider`.

---

### Task 7: Finish

Run the full suite one last time (`uv run pytest -q`), then use
superpowers:finishing-a-development-branch to merge/PR per the user's choice.
