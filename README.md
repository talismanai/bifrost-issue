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
# or GOOGLE_API_KEY=...
# or BIFROST_DIRECT_GEMINI_API_KEY=...
```

For Bifrost:

```bash
export BIFROST_BASE_URL=https://...
export BIFROST_API_KEY=...
# Optional:
export BIFROST_GEMINI_FILE_BASE_URL=https://.../genai
```

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

Rich terminal output is the default. Raw event output:

```bash
uv run gemini_file_upload_diagnostic.py --scenario all --log-format events
```

Use a custom file:

```bash
uv run gemini_file_upload_diagnostic.py --scenario all --file /path/to/file.txt
```
