# Anthropic File ID Through OpenAI-Compatible Chat

Minimal reproduction for Anthropic uploaded files sent through Bifrost's OpenAI-compatible chat route.

## What It Reproduces

When the routed model is Anthropic and an OpenAI-compatible chat request contains:

```json
{
  "type": "file",
  "file": {
    "file_id": "file_abc123",
    "filename": "tiny.pdf"
  }
}
```

Bifrost converts that block into an Anthropic `document` block.

Before the fix, the Anthropic request looked like:

```json
{
  "type": "document",
  "title": "tiny.pdf",
  "source": {
    "type": ""
  }
}
```

Anthropic rejects that because `source.type` is empty.

After the fix, it becomes:

```json
{
  "type": "document",
  "title": "tiny.pdf",
  "source": {
    "type": "file",
    "file_id": "file_abc123"
  }
}
```

## Run

From this folder:

```sh
BIFROST_URL="http://localhost:8080" \
BIFROST_API_KEY="..." \
uv run python repro.py
```

The script:

1. Uploads a tiny PDF to `POST /v1/files?provider=anthropic`.
2. Calls `POST /litellm/v1/chat/completions` with an Anthropic model and the uploaded `file_id`.
3. Prints the chat response status and body.
4. Deletes the uploaded file.

To skip upload and use an existing file:

```sh
BIFROST_URL="http://localhost:8080" \
BIFROST_API_KEY="..." \
FILE_ID="file_abc123" \
uv run python repro.py
```

Optional:

```sh
MODEL="anthropic/claude-sonnet-4-5-20250929"
```

## Local Bifrost Config Used

For local validation, Bifrost was run with an isolated app directory containing this `config.json`.
The Anthropic key was passed through the environment; no secret value needs to be written to disk.

```json
{
  "$schema": "https://www.getbifrost.ai/schema",
  "config_store": {
    "enabled": false
  },
  "logs_store": {
    "enabled": false
  },
  "providers": {
    "anthropic": {
      "keys": [
        {
          "name": "anthropic-env-key",
          "value": "env.ANTHROPIC_API_KEY",
          "weight": 1,
          "models": ["*"],
          "use_for_batch_api": true
        }
      ],
      "network_config": {
        "default_request_timeout_in_seconds": 120,
        "extra_headers": {
          "anthropic-beta": "files-api-2025-04-14"
        }
      }
    }
  }
}
```

The important settings are:

- `use_for_batch_api: true`, otherwise `POST /v1/files?provider=anthropic` fails before the chat request.
- `network_config.extra_headers.anthropic-beta: files-api-2025-04-14`, otherwise Anthropic rejects `source.type=file` because the Files API beta is not enabled for the chat request.
- `MODEL=anthropic/claude-sonnet-4-5-20250929`; this was the model that succeeded in local validation.

Example local run:

```sh
export ANTHROPIC_API_KEY="..."

mkdir -p /tmp/bifrost-anthropic-fileid
$BIFROST_HTTP_BIN \
  -app-dir /tmp/bifrost-anthropic-fileid \
  -host 127.0.0.1 \
  -port 18082 \
  -log-level warn
```

Then, from this case folder:

```sh
BIFROST_URL=http://127.0.0.1:18082 \
MODEL=anthropic/claude-sonnet-4-5-20250929 \
uv run python repro.py
```

## Expected Result

Before the fix, the chat call returns a 400 from Anthropic with an error like:

```text
document.source: Input tag '' found using 'type'
```

After the fix, the request reaches Anthropic with `source.type=file`.

Observed locally:

- Unfixed Bifrost returned `Input tag '' found using 'type'`.
- Fixed Bifrost returned `200` and Claude read the tiny PDF content.
