# Bifrost Issues Reproductions

Small, self-contained reproductions for Bifrost provider issues.

Each case lives in its own folder with a local `pyproject.toml` and `uv.lock`.

## Index

| Case | Description |
| --- | --- |
| [`gemini-file-upload-diagnostic`](cases/gemini-file-upload-diagnostic/) | Compares Gemini File API uploads directly against Google and through Bifrost `/genai`. |
| [`anthropic-file-id-openai-route`](cases/anthropic-file-id-openai-route/) | Reproduces Anthropic uploaded `file_id` failures through Bifrost OpenAI-compatible chat routes. |

## Usage

Open the case folder and run the command documented in that folder's README:

```bash
cd cases/<case-name>
uv run ...
```
