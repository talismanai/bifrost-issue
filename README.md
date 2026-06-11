# Gemini File Upload Diagnostic

Standalone diagnostic for comparing Gemini File API uploads:

- Direct Google GenAI SDK
- Bifrost `/genai` with the virtual key as `api_key`
- Bifrost `/genai` with `x-bf-vk` on the SDK aiohttp session

The directory has its own `pyproject.toml`, so uv creates an isolated environment for it.
The Python file also keeps inline uv metadata, so direct script execution still works.

## Env

For direct Google:

```bash
export GEMINI_API_KEY=...
```

For Bifrost:

```bash
export BIFROST_API_KEY=...
export BIFROST_BASE_URL=https://...
```

The script appends `/genai` to `BIFROST_BASE_URL` when it is missing.

## Run

From this directory:

```bash
uv run gemini-file-upload-diagnostic --scenario all
```

From the repo root:

```bash
uv run gemini-file-upload-diagnostic \
  gemini-file-upload-diagnostic --env-file .env --scenario all
```

Direct script mode:

```bash
uv run gemini_file_upload_diagnostic.py --scenario all
```

With an env file:

```bash
uv run gemini_file_upload_diagnostic.py --env-file /path/to/.env --scenario all
```

Repeat the Bifrost session-header scenario:

```bash
uv run gemini_file_upload_diagnostic.py --scenario bifrost-session-x-bf-vk --repeat 10
```

Add a delay before the resumable upload continuation request:

```bash
uv run gemini_file_upload_diagnostic.py \
  --scenario bifrost-session-x-bf-vk \
  --repeat 10 \
  --upload-delay-seconds 1
```

Rich terminal output is the default. Raw event output:

```bash
uv run gemini_file_upload_diagnostic.py --scenario all --log-format events
```

Use a custom file:

```bash
uv run gemini_file_upload_diagnostic.py --scenario all --file /path/to/file.txt
```

## Scenario call shapes

All scenarios run the same file lifecycle after creating the client:

```python
uploaded = await client.aio.files.upload(
    file="/path/to/file.txt",
    config={"mime_type": "text/plain"},
)

if uploaded.name:
    await client.aio.files.delete(name=uploaded.name)
```

### `direct-gemini`

Calls Google Gemini directly. There is no Bifrost `base_url`.

```python
import os

from google import genai

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options={
        "headers": {"X-Operation-ID": operation_id},
    },
)
```

### `bifrost-api-key`

Calls Bifrost's Gemini-compatible endpoint and passes the Bifrost virtual key as the
GenAI SDK `api_key`.

```python
import os

from google import genai

bifrost_base_url = os.environ["BIFROST_BASE_URL"].rstrip("/")
if not bifrost_base_url.endswith("/genai"):
    bifrost_base_url = f"{bifrost_base_url}/genai"

client = genai.Client(
    api_key=os.environ["BIFROST_API_KEY"],
    http_options={
        "base_url": bifrost_base_url,
        "headers": {"X-Operation-ID": operation_id},
    },
)
```

### `bifrost-session-x-bf-vk`

Calls Bifrost's Gemini-compatible endpoint with a dummy GenAI SDK key, then installs
the Bifrost virtual key on the SDK's underlying aiohttp session.

```python
import os

from google import genai

bifrost_base_url = os.environ["BIFROST_BASE_URL"].rstrip("/")
if not bifrost_base_url.endswith("/genai"):
    bifrost_base_url = f"{bifrost_base_url}/genai"

client = genai.Client(
    api_key="dummy-key",
    http_options={
        "base_url": bifrost_base_url,
        "headers": {"X-Operation-ID": operation_id},
    },
)

session = await client._api_client._get_aiohttp_session()
session.headers.update(
    {
        "x-bf-vk": os.environ["BIFROST_API_KEY"],
        "X-Operation-ID": operation_id,
    }
)
```
