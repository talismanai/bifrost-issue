# Gemini File Upload MIME Type

Minimal reproduction for Gemini Files uploaded through Bifrost's GenAI-compatible route.

## What It Reproduces

When a client starts a Gemini resumable upload through:

```http
POST /genai/upload/v1beta/files
X-Goog-Upload-Header-Content-Type: application/pdf
```

Bifrost converts that upload into a Gemini provider `FileUpload` request.

Before the fix, the MIME type from `X-Goog-Upload-Header-Content-Type` was not sent to Gemini file metadata or the multipart file part. Gemini accepted the upload, but the uploaded file could come back without a useful `mimeType`, and a later `generateContent` request with that file URI failed with a generic 400:

```text
Request contains an invalid argument.
```

After the fix, Bifrost sends the uploaded file part with the caller-provided MIME type:

```http
Content-Type: application/pdf
```

Google may still return generic file metadata from the File API, but the later `generateContent` request no longer fails with the invalid-argument error.

## Run

From this folder:

```sh
BIFROST_URL="http://localhost:8080" \
BIFROST_API_KEY="..." \
uv run python repro.py
```

The script:

1. Starts a Gemini resumable upload through `POST /genai/upload/v1beta/files`.
2. Finalizes the upload with a tiny PDF containing `ok`.
3. Retrieves the uploaded file metadata and prints the observed `mimeType`.
4. Calls `POST /genai/v1beta/models/{model}:generateContent` with the uploaded file URI.
5. Deletes the uploaded file.

Optional:

```sh
MODEL="gemini-2.5-flash"
```

## Local Bifrost Config Used

For local validation, Bifrost was run with isolated app directories containing this `config.json`.
The Gemini key was passed through the environment; no secret value needs to be written to disk.

```json
{
  "$schema": "https://www.getbifrost.ai/schema",
  "source_of_truth": "config.json",
  "config_store": {
    "enabled": false
  },
  "logs_store": {
    "enabled": false
  },
  "providers": {
    "gemini": {
      "keys": [
        {
          "name": "gemini-env-key",
          "value": "env.GEMINI_API_KEY",
          "weight": 1,
          "models": ["*"],
          "use_for_batch_api": true
        }
      ],
      "network_config": {
        "default_request_timeout_in_seconds": 120
      }
    }
  }
}
```

The important settings are:

- `GEMINI_API_KEY` must be set in the process environment. In local validation, the downstream test env's Gemini key was mapped into this variable.
- `use_for_batch_api: true`, otherwise the upload continuation fails before it reaches Gemini with `no config found for batch apis`.
- `config_store.enabled: false` and `logs_store.enabled: false` keep the run ephemeral and avoid carrying state between unfixed and fixed binaries.
- `source_of_truth: config.json` makes the file config authoritative for the isolated app directory.

Example local runs:

```sh
export GEMINI_API_KEY="..."

mkdir -p /tmp/bifrost-gemini-dev-app /tmp/bifrost-gemini-fix-app

$BIFROST_DEV_BIN \
  -app-dir /tmp/bifrost-gemini-dev-app \
  -host 127.0.0.1 \
  -port 18080 \
  -log-level warn

$BIFROST_FIXED_BIN \
  -app-dir /tmp/bifrost-gemini-fix-app \
  -host 127.0.0.1 \
  -port 18081 \
  -log-level warn
```

Then, from this case folder:

```sh
BIFROST_URL=http://127.0.0.1:18080 \
BIFROST_API_KEY= \
MODEL=gemini-2.5-flash \
uv run python repro.py

BIFROST_URL=http://127.0.0.1:18081 \
BIFROST_API_KEY= \
MODEL=gemini-2.5-flash \
uv run python repro.py
```

## Expected Result

Before the fix, the upload/retrieve metadata shows an empty or generic MIME type, and `generateContent` returns:

```text
400 Request contains an invalid argument.
```

After the fix, `generateContent` can read the uploaded PDF. Google may still return generic file metadata from the File API, but the request no longer fails with the invalid-argument error.

Observed locally:

- Unfixed Bifrost finalized upload, returned generic file metadata, then returned `400 Request contains an invalid argument` from `generateContent`.
- Fixed Bifrost finalized upload, still returned generic file metadata, then returned `200` and extracted `ok` from the PDF.
