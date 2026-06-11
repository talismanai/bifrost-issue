# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#   "aiohttp",
#   "google-genai",
#   "rich",
# ]
# ///
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from google.genai import Client
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

LOG_FORMAT = "rich"
console = Console()

WATCH_HEADERS = {
    "authorization",
    "content-type",
    "x-bf-vk",
    "x-goog-api-key",
    "x-goog-upload-command",
    "x-model-provider",
    "x-operation-id",
}


@dataclass(frozen=True)
class RuntimeConfig:
    text_file: Path | None
    bifrost_api_key: str | None = None
    bifrost_base_url: str | None = None
    google_api_key: str | None = None
    upload_delay_seconds: float = 0.0


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    run: Callable[[RuntimeConfig, str], Awaitable[None]]


@dataclass(frozen=True)
class ScenarioResult:
    iteration: int
    scenario: str
    description: str
    operation_id: str
    status: str
    error_type: str | None = None
    error: str | None = None


def _emit(event: dict[str, Any]) -> None:
    if LOG_FORMAT == "events":
        print(event)
        return

    kind = event.get("event")
    match kind:
        case "scenario_start":
            title = Text(str(event["scenario"]), style="bold cyan")
            body = Text()
            body.append(str(event["description"]), style="white")
            body.append("\noperation_id: ", style="dim")
            body.append(str(event["operation_id"]), style="yellow")
            console.print()
            console.print(Panel(body, title=title, border_style="cyan", expand=False))
        case "request":
            query = "?" if event.get("has_query") else ""
            console.print(
                "  [bold blue]->[/bold blue] "
                f"[blue]{event['method']}[/blue] "
                f"[white]{event['host']}[/white][dim]{event['path']}{query}[/dim] "
                f"[dim]headers={event['effective_headers']}[/dim]"
            )
        case "response":
            query = "?" if event.get("has_query") else ""
            status = int(event["status"])
            status_style = (
                "green"
                if 200 <= status < 300
                else "yellow"
                if 300 <= status < 500
                else "red"
            )
            console.print(
                "  [bold magenta]<-[/bold magenta] "
                f"[bold {status_style}]{status}[/bold {status_style}] "
                f"[magenta]{event['method']}[/magenta] "
                f"[dim]{event['path']}{query}[/dim] "
                f"[dim]headers={event['headers']}[/dim]"
            )
        case "upload_delay":
            console.print(
                "  [bold yellow]~[/bold yellow] "
                f"delaying resumable upload continuation for "
                f"[yellow]{event['seconds']}s[/yellow]"
            )
        case "uploaded":
            console.print(
                f"  [green]uploaded[/green]: [white]{event['name']}[/white] "
                f"[dim]({event['size_bytes']} bytes)[/dim]"
            )
        case "deleted":
            console.print("  [green]deleted[/green] uploaded file")
        case "scenario_result":
            if event["status"] == "passed":
                console.print(
                    f"  result: [bold green]PASSED[/bold green] {event['scenario']}"
                )
            else:
                console.print(
                    f"  result: [bold red]FAILED[/bold red] {event['scenario']}"
                )
                console.print(
                    f"  [red]error[/red]: {event['error_type']}: {event['error']}"
                )
        case "iteration_start":
            console.rule(
                f"Iteration {event['iteration']}/{event['repeat']}", style="bold blue"
            )
        case "summary":
            failed = int(event["failed"])
            style = "green" if failed == 0 else "red"
            console.print()
            console.print(
                Panel(
                    f"[bold]total[/bold]={event['total']}  "
                    f"[bold green]passed[/bold green]={event['passed']}  "
                    f"[bold red]failed[/bold red]={event['failed']}",
                    title=Text("Summary", style=f"bold {style}"),
                    border_style=style,
                    expand=False,
                )
            )
        case "summary_item":
            status_style = "green" if event["status"] == "passed" else "red"
            console.print(
                f"- [bold {status_style}]{event['status'].upper()}[/bold {status_style}] "
                f"iteration {event['iteration']}: [cyan]{event['scenario']}[/cyan]"
            )
            console.print(f"  [dim]description:[/dim] {event['description']}")
            console.print(
                f"  [dim]operation_id:[/dim] [yellow]{event['operation_id']}[/yellow]"
            )
            if event.get("error_type"):
                console.print(
                    f"  [red]error:[/red] {event['error_type']}: {event['error']}"
                )
        case _:
            console.print(event)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    return None


def _with_genai_prefix(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    path = urlsplit(stripped).path.rstrip("/")
    if path.endswith("/genai"):
        return stripped
    return f"{stripped}/genai"


def _required_bifrost_api_key(runtime: RuntimeConfig) -> str:
    if not runtime.bifrost_api_key:
        raise RuntimeError("BIFROST_API_KEY is required")
    return runtime.bifrost_api_key


def _required_bifrost_base_url(runtime: RuntimeConfig) -> str:
    if not runtime.bifrost_base_url:
        raise RuntimeError("BIFROST_BASE_URL is required")
    return runtime.bifrost_base_url


def _missing_env_vars(runtime: RuntimeConfig, scenarios: list[Scenario]) -> list[str]:
    names = {scenario.name for scenario in scenarios}
    missing: list[str] = []

    if "direct-gemini" in names and not runtime.google_api_key:
        missing.append("GEMINI_API_KEY")

    bifrost_scenarios = {"bifrost-api-key", "bifrost-session-x-bf-vk"}
    if names & bifrost_scenarios:
        if not runtime.bifrost_api_key:
            missing.append("BIFROST_API_KEY")
        if not runtime.bifrost_base_url:
            missing.append("BIFROST_BASE_URL")

    return missing


def _header_names(headers: Any) -> list[str]:
    if not headers:
        return []
    return sorted(str(key) for key in headers if str(key).lower() in WATCH_HEADERS)


def _interesting_response_headers(headers: Any) -> dict[str, str]:
    if not headers:
        return {}
    return {
        str(key): str(headers[key])
        for key in headers
        if str(key).lower()
        in {
            "x-bf-request-id",
            "x-bifrost-request-id",
            "x-envoy-upstream-service-time",
            "x-operation-id",
            "x-request-id",
        }
    }


def _install_aiohttp_trace(
    scenario_name: str, upload_delay_seconds: float
) -> Callable[[], None]:
    original_request = aiohttp.ClientSession._request

    async def traced_request(
        self: aiohttp.ClientSession, method: str, url: str, **kwargs: Any
    ):
        parsed = urlsplit(str(url))
        effective_headers = dict(getattr(self, "headers", {}) or {})
        effective_headers.update(dict(kwargs.get("headers") or {}))
        _emit(
            {
                "scenario": scenario_name,
                "event": "request",
                "method": method,
                "host": parsed.netloc,
                "path": parsed.path,
                "has_query": bool(parsed.query),
                "request_headers": _header_names(kwargs.get("headers")),
                "effective_headers": _header_names(effective_headers),
            }
        )
        if upload_delay_seconds > 0 and "upload_id=" in parsed.query:
            _emit(
                {
                    "scenario": scenario_name,
                    "event": "upload_delay",
                    "seconds": upload_delay_seconds,
                    "path": parsed.path,
                }
            )
            await asyncio.sleep(upload_delay_seconds)

        response = await original_request(self, method, url, **kwargs)
        _emit(
            {
                "scenario": scenario_name,
                "event": "response",
                "method": method,
                "path": parsed.path,
                "has_query": bool(parsed.query),
                "status": response.status,
                "headers": _interesting_response_headers(response.headers),
            }
        )
        return response

    aiohttp.ClientSession._request = traced_request

    def restore() -> None:
        aiohttp.ClientSession._request = original_request

    return restore


def _operation_headers(operation_id: str) -> dict[str, str]:
    return {"X-Operation-ID": operation_id}


async def _upload_with_client(client: Client, runtime: RuntimeConfig) -> None:
    if runtime.text_file:
        uploaded = await client.aio.files.upload(
            file=str(runtime.text_file),
            config={"mime_type": "text/plain"},
        )
        _emit(
            {
                "event": "uploaded",
                "name": uploaded.name,
                "size_bytes": uploaded.size_bytes,
            }
        )
        if uploaded.name:
            deleted = await client.aio.files.delete(name=uploaded.name)
            _emit({"event": "deleted", "result": str(deleted)})
        return

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
        tmp.write("Bifrost Gemini file upload diagnostic.\n")
        file_path = Path(tmp.name)
    try:
        uploaded = await client.aio.files.upload(
            file=str(file_path),
            config={"mime_type": "text/plain"},
        )
        _emit(
            {
                "event": "uploaded",
                "name": uploaded.name,
                "size_bytes": uploaded.size_bytes,
            }
        )
        if uploaded.name:
            deleted = await client.aio.files.delete(name=uploaded.name)
            _emit({"event": "deleted", "result": str(deleted)})
    finally:
        file_path.unlink(missing_ok=True)


async def _direct_gemini(runtime: RuntimeConfig, operation_id: str) -> None:
    if not runtime.google_api_key:
        raise RuntimeError("GEMINI_API_KEY is required")

    client = Client(
        api_key=runtime.google_api_key,
        http_options={"headers": _operation_headers(operation_id)},
    )
    await _upload_with_client(client, runtime)


async def _bifrost_api_key(runtime: RuntimeConfig, operation_id: str) -> None:
    client = Client(
        api_key=_required_bifrost_api_key(runtime),
        http_options={
            "base_url": _required_bifrost_base_url(runtime),
            "headers": _operation_headers(operation_id),
        },
    )
    await _upload_with_client(client, runtime)


async def _bifrost_session_x_bf_vk(runtime: RuntimeConfig, operation_id: str) -> None:
    client = Client(
        api_key="dummy-key",
        http_options={
            "base_url": _required_bifrost_base_url(runtime),
            "headers": _operation_headers(operation_id),
        },
    )
    session = await client._api_client._get_aiohttp_session()
    session.headers.update(
        {
            "x-bf-vk": _required_bifrost_api_key(runtime),
            **_operation_headers(operation_id),
        }
    )
    await _upload_with_client(client, runtime)


SCENARIOS = {
    scenario.name: scenario
    for scenario in (
        Scenario(
            "direct-gemini",
            "Direct Google GenAI SDK call with a real Gemini API key and no Bifrost base_url.",
            _direct_gemini,
        ),
        Scenario(
            "bifrost-api-key",
            "Bifrost /genai base_url with the virtual key passed as the GenAI api_key.",
            _bifrost_api_key,
        ),
        Scenario(
            "bifrost-session-x-bf-vk",
            "Bifrost /genai base_url with x-bf-vk installed on the SDK aiohttp session.",
            _bifrost_session_x_bf_vk,
        ),
    )
}


async def _run_scenario(
    scenario: Scenario, runtime: RuntimeConfig, *, iteration: int
) -> ScenarioResult:
    operation_id = f"gemini-file-{scenario.name}-{uuid.uuid4()}"
    _emit(
        {
            "event": "scenario_start",
            "scenario": scenario.name,
            "description": scenario.description,
            "operation_id": operation_id,
        }
    )
    restore_trace = _install_aiohttp_trace(scenario.name, runtime.upload_delay_seconds)
    try:
        await scenario.run(runtime, operation_id)
        _emit(
            {"event": "scenario_result", "scenario": scenario.name, "status": "passed"}
        )
        return ScenarioResult(
            iteration=iteration,
            scenario=scenario.name,
            description=scenario.description,
            operation_id=operation_id,
            status="passed",
        )
    except Exception as err:
        _emit(
            {
                "event": "scenario_result",
                "scenario": scenario.name,
                "status": "failed",
                "error_type": type(err).__name__,
                "error": str(err),
            }
        )
        return ScenarioResult(
            iteration=iteration,
            scenario=scenario.name,
            description=scenario.description,
            operation_id=operation_id,
            status="failed",
            error_type=type(err).__name__,
            error=str(err),
        )
    finally:
        restore_trace()


def _print_summary(results: list[ScenarioResult]) -> None:
    passed = sum(result.status == "passed" for result in results)
    failed = sum(result.status == "failed" for result in results)

    _emit(
        {
            "event": "summary",
            "total": len(results),
            "passed": passed,
            "failed": failed,
        }
    )
    if LOG_FORMAT != "events":
        table = Table(
            title="Scenario Results",
            box=box.SIMPLE_HEAVY,
            header_style="bold cyan",
            show_lines=True,
        )
        table.add_column("Iteration", justify="right", style="dim")
        table.add_column("Status")
        table.add_column("Scenario", style="cyan")
        table.add_column("Description", overflow="fold")
        table.add_column("Operation ID", style="yellow", overflow="fold")
        table.add_column("Error", overflow="fold")

        for result in results:
            status_style = "green" if result.status == "passed" else "red"
            error = (
                f"{result.error_type}: {result.error}"
                if result.error_type and result.error
                else ""
            )
            table.add_row(
                str(result.iteration),
                f"[bold {status_style}]{result.status.upper()}[/bold {status_style}]",
                result.scenario,
                result.description,
                result.operation_id,
                error,
            )

        console.print(table)
        return

    for result in results:
        row = {
            "event": "summary_item",
            "iteration": result.iteration,
            "scenario": result.scenario,
            "description": result.description,
            "operation_id": result.operation_id,
            "status": result.status,
        }
        if result.error_type:
            row["error_type"] = result.error_type
        if result.error:
            row["error"] = result.error
        _emit(row)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Gemini File API upload behavior for direct Google and Bifrost."
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Env file with Bifrost and/or direct Gemini credentials.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override Bifrost base URL. Defaults to BIFROST_BASE_URL; /genai is appended when missing.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Optional file to upload. Defaults to a temporary text file.",
    )
    parser.add_argument(
        "--scenario",
        choices=["all", *SCENARIOS.keys()],
        default="all",
        help="Scenario to run.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of times to run the selected scenario set.",
    )
    parser.add_argument(
        "--upload-delay-seconds",
        type=float,
        default=0.0,
        help="Sleep before the resumable upload continuation request. Useful for testing Bifrost cross-pod KV propagation.",
    )
    parser.add_argument(
        "--log-format",
        choices=["rich", "events"],
        default="rich",
        help="Use rich terminal output or raw event dictionaries.",
    )
    return parser.parse_args()


async def _main() -> None:
    global LOG_FORMAT
    args = _parse_args()
    LOG_FORMAT = args.log_format
    _load_env_file(Path(args.env_file))
    if args.upload_delay_seconds < 0:
        raise RuntimeError("--upload-delay-seconds must be non-negative")

    raw_bifrost_base_url = args.base_url or _optional_env("BIFROST_BASE_URL")
    bifrost_base_url = (
        _with_genai_prefix(raw_bifrost_base_url) if raw_bifrost_base_url else None
    )
    runtime = RuntimeConfig(
        text_file=args.file,
        bifrost_api_key=_optional_env("BIFROST_API_KEY"),
        bifrost_base_url=bifrost_base_url,
        google_api_key=_optional_env("GEMINI_API_KEY"),
        upload_delay_seconds=args.upload_delay_seconds,
    )

    if args.scenario == "all":
        scenarios = list(SCENARIOS.values())
    else:
        scenarios = [SCENARIOS[args.scenario]]

    missing = _missing_env_vars(runtime, scenarios)
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    results: list[ScenarioResult] = []
    for iteration in range(1, args.repeat + 1):
        if args.repeat > 1:
            _emit(
                {
                    "event": "iteration_start",
                    "iteration": iteration,
                    "repeat": args.repeat,
                }
            )
        for scenario in scenarios:
            results.append(await _run_scenario(scenario, runtime, iteration=iteration))

    _print_summary(results)


def main() -> None:
    try:
        asyncio.run(_main())
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        raise SystemExit(2) from err


if __name__ == "__main__":
    main()
