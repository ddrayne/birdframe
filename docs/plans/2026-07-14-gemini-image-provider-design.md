# Gemini as an alternative image provider

## Goal

Let birdframe paint the daily picture with Google's Gemini image models
(default: Nano Banana Pro, `gemini-3-pro-image`) as an alternative to OpenAI
gpt-image. The provider is a config choice; there is **no cross-provider
fallback** — if the selected provider fails or has no key, the existing
pure-Pillow fallback poster is used, exactly as today.

## Config

New keys in `config.DEFAULTS`:

```toml
image_provider = "openai"          # openai | gemini
gemini_model = "gemini-3-pro-image"  # Nano Banana Pro
```

- `openai_model` is unchanged; each provider remembers its own model, so
  switching provider is a one-line edit.
- `image_quality` is shared: for Gemini, `"high"` → 2K output, anything else
  → 1K.
- Aspect ratio for Gemini is fixed at `4:5`, which exactly matches the frame's
  1200×1500 art area (`compose_final` letterboxes anything else, so this is a
  strict improvement over OpenAI's 2:3).

## Wiring (`app.py`)

The image-client block reads `config.image_provider`, resolves that provider's
key via `secrets.get_key(provider)`, and constructs `OpenAIImageClient`
(unchanged) or the new `GeminiImageClient`. Missing key → same warning style
as today, naming the right command (`birdframe set-key gemini`), and the
fallback poster path. `Artist` is untouched — it already accepts any object
with `.generate(prompt) -> bytes`.

## GeminiImageClient (`image_client.py`)

Mirrors `OpenAIImageClient`'s shape:

- `__init__(api_key, model="gemini-3-pro-image", quality="high", sdk=None,
  max_retries=3, backoff=2.0, timeout=300.0)` — `sdk=` is the injectable test
  seam; without it, construct `google.genai.Client(api_key=...)`.
- `generate(prompt) -> bytes` calls `client.models.generate_content` with
  `response_modalities=["IMAGE"]` and
  `ImageConfig(aspect_ratio="4:5", image_size="2K"|"1K")`.
- Image bytes come from the response's `inline_data` part. A 200 with no image
  part (e.g. a text-only safety refusal) raises — never return garbage bytes.
- Same retry/backoff loop as the OpenAI client.

New dependency: `google-genai` in `pyproject.toml`.

## Secrets (`secrets.py`)

Generalise to per-provider keys:

- `set_key(provider, key)` / `get_key(provider)`; env var wins
  (`OPENAI_API_KEY` / `GEMINI_API_KEY`), then Keychain entry
  (`openai_api_key` / `gemini_api_key` under the existing `birdframe`
  service). Existing OpenAI Keychain entries keep working untouched.
- `get_openai_key()` stays as a thin wrapper so existing imports don't churn.
- Keys still never touch disk.

## CLI

- `birdframe set-key [openai|gemini]` — provider argument, default `openai`
  (muscle memory and existing docs stay valid); same hidden `getpass` prompt.
- `birdframe doctor` reports both keys' presence and flags when the
  *configured* provider's key is the missing one.

## Testing

- `GeminiImageClient` unit tests with a fake `sdk`: happy path,
  retry-then-succeed, no-image-part raises, quality→size mapping.
- Secrets tests for per-provider resolution and env-var precedence.
- Wiring test: `image_provider = "gemini"` constructs a `GeminiImageClient`.
- No test downloads models or spends API money (project rule).

## Out of scope (YAGNI)

- Cross-provider fallback chains.
- Per-style or per-day provider routing.
- Exposing provider choice in the dashboard/Studio UI.
