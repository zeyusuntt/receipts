"""Command-line entry points for running and inspecting Receipts."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import os
import re
import signal
import shutil
import tempfile
import uuid
from collections.abc import Awaitable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel
from daytona import AsyncDaytona, DaytonaConfig

from receipts.agent.worker import WorkerBudget
from receipts.cost import CostMeter, price_table
from receipts.llm import (
    ModelClient,
    TokenFactoryClient,
    _parse_dotenv,
    load_config,
)
from receipts.orchestrate import ProgressEvent, RunBudgets, RunResult, fix
from receipts.pilot.cleanup import cleanup_manifests, render_cleanup
from receipts.pilot.replay import summary_line as replay_summary_line
from receipts.pilot.replay import write_replay
from receipts.pilot.runner import (
    _complete_shielded,
    _shield_cleanup_methods,
    run_pilot,
)
from receipts.pilot.screen import screen_candidates
from receipts.pilot.watch import watch_pilot
from receipts.preflight import run_preflight
from receipts.receipt_text import render
from receipts.sandbox.busybox import load_busybox
from receipts.sandbox.daytona import AsyncDaytonaApi, DaytonaExecutor
from receipts.sandbox.docker import DockerExecutor
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import ImageSource, RepoAtCommit
from receipts.sandbox.sink import MemorySink, RunSink
from receipts.sandbox.tokenfactory import TokenFactoryExecutor
from receipts.sandbox.tokenfactory_api import TokenFactorySandboxApi
from receipts.swerebench import (
    Instance,
    _spec_paths_from_test_patch,
    _test_patch_setup_commands,
)
from receipts.verify.review import REVIEWER_SETTINGS


_REQUIRED_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "NEMOTRON_MODEL")
_PILOT_ROWS_PATH = Path("data/rebench-v2-python.jsonl")
_FIX_LINE_LIMIT = 100
_FIX_LABEL_WIDTH = 16
# The gate's checks, named for the receipt page.
_CHECK_LABELS = {
    "R1": "spec passes",
    "R2": "nothing breaks",
    "R3": "none removed",
    "R4": "tests untouched",
    "R5": "hash chain",
    "R7": "no shortcuts",
    "R8": "review",
}
_ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_LOCAL_ABSOLUTE_PATH = re.compile(r"(?<![:/\w.])/(?!/)[^\s;]+")


class _DoctorResponse(BaseModel):
    ok: bool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="receipts")
    commands = parser.add_subparsers(dest="command", required=True)

    fix_parser = commands.add_parser("fix", help="run an agent and verify its patch")
    fix_parser.add_argument("--repo", help="repository path or URL")
    fix_parser.add_argument("--commit", help="commit to check out")
    fix_parser.add_argument("--image", help="container image for a sandbox executor")
    fix_parser.add_argument("--workdir", help="repository path inside the sandbox image")
    fix_parser.add_argument("--python", default="python", help="Python executable in the image")
    fix_parser.add_argument(
        "--test",
        action="append",
        required=True,
        dest="tests",
        help="pytest node id that must fail before the fix",
    )
    fix_parser.add_argument("--issue-file", required=True, type=Path)
    fix_parser.add_argument(
        "--test-patch",
        type=Path,
        help="unified diff that adds or changes the failing test in a sandbox",
    )
    fix_parser.add_argument("--install", default="true", help="installation command")
    fix_parser.add_argument("--suite", default="tests", help="pytest suite arguments")
    fix_parser.add_argument(
        "--executor",
        choices=("local", "docker", "daytona", "tokenfactory"),
        default="local",
    )
    fix_parser.add_argument("--out", required=True, type=Path)
    review = fix_parser.add_mutually_exclusive_group()
    review.add_argument(
        "--no-review",
        dest="review",
        action="store_const",
        const="off",
        help="skip R8, the independent Nemotron review of a passing patch",
    )
    review.add_argument(
        "--review-veto",
        dest="review",
        action="store_const",
        const="veto",
        help="let R8 reject a passing patch when both reviews object (by default it is advisory)",
    )
    fix_parser.set_defaults(review="advisory")

    doctor_parser = commands.add_parser("doctor", help="check local configuration")
    doctor_parser.add_argument(
        "--live",
        action="store_true",
        help="also call the configured model and check Docker",
    )

    preflight_parser = commands.add_parser(
        "preflight",
        help="write the launch preflight JSON",
    )
    preflight_parser.add_argument("--out", type=Path)
    preflight_parser.add_argument(
        "--executor",
        choices=("daytona", "tokenfactory"),
        default="daytona",
    )

    show_parser = commands.add_parser("show", help="print a run's Markdown receipt")
    show_parser.add_argument("run_dir", type=Path)

    site_parser = commands.add_parser("site", help="build a static receipt website")
    site_parser.add_argument("pilot_dirs", nargs="+", type=Path)
    site_parser.add_argument("--out", required=True, type=Path)
    site_parser.add_argument("--title", default="Receipts")
    site_parser.add_argument(
        "--strip-prefix",
        action="append",
        default=[],
        dest="strip_prefixes",
        type=Path,
        help="another checkout path to remove from raw record copies; may be repeated",
    )
    site_parser.add_argument(
        "--featured",
        help="instance id of a run in the first pilot to open the index with: a claimed done, rejected, then verified",
    )

    export_parser = commands.add_parser("export", help="export portable final-attempt receipt bundles")
    export_parser.add_argument("pilot_dir", type=Path)
    export_parser.add_argument("--rows", required=True, type=Path, help="SWE-rebench row JSONL")
    export_parser.add_argument("--out", required=True, type=Path)

    reverify_parser = commands.add_parser(
        "reverify", help="re-check a published receipt on fresh sandboxes",
        description=("Re-check patch digest, gate and official grade. SWE-rebench images are "
                     "linux/amd64 and run under emulation on Apple Silicon (slower)."),
    )
    reverify_parser.add_argument("bundle", type=Path)
    reverify_parser.add_argument("--executor", choices=("docker", "tokenfactory"), default="docker",
                                 help="sandbox executor; tokenfactory requires .env credentials")

    pilot_parser = commands.add_parser("pilot", help="run or report on the pilot")
    pilot_commands = pilot_parser.add_subparsers(
        dest="pilot_command",
        required=True,
    )
    pilot_run = pilot_commands.add_parser("run", help="run pilot instances")
    pilot_run.add_argument(
        "--candidates",
        required=True,
        type=Path,
        help="ordered candidate id file",
    )
    pilot_run.add_argument(
        "--rows",
        required=True,
        type=Path,
        help="SWE-rebench row JSONL",
    )
    pilot_run.add_argument("--n", type=int, default=50)
    pilot_run.add_argument(
        "--executor",
        choices=("daytona", "tokenfactory"),
        default="daytona",
    )
    pilot_run.add_argument("--out", required=True, type=Path)
    pilot_run.add_argument("--concurrency", type=int, default=1)
    pilot_run.add_argument(
        "--model",
        help="model id for both the planner and worker",
    )

    pilot_screen = pilot_commands.add_parser(
        "screen",
        help="screen pilot candidates without running a model",
    )
    pilot_screen.add_argument("--candidates", required=True, type=Path)
    pilot_screen.add_argument("--start", required=True, type=int)
    pilot_screen.add_argument("--exclude", required=True, type=Path)
    pilot_screen.add_argument("--want", required=True, type=int)
    pilot_screen.add_argument("--out", required=True, type=Path)
    pilot_screen.add_argument("--concurrency", type=int, default=1)
    pilot_screen.add_argument(
        "--executor",
        choices=("daytona", "tokenfactory"),
        default="daytona",
    )

    pilot_report = pilot_commands.add_parser(
        "report",
        help="build the report from pilot records",
    )
    pilot_report.add_argument("pilot_dir", type=Path)
    pilot_report.add_argument(
        "--screen-ledger",
        action="append",
        default=[],
        dest="screen_ledgers",
        type=Path,
        help="screening JSONL to include; may be repeated",
    )
    pilot_watch = pilot_commands.add_parser(
        "watch",
        help="stop a pilot process on a terminal failure",
    )
    pilot_watch.add_argument("pilot_dir", type=Path)
    pilot_watch.add_argument("pid", type=int)
    pilot_watch.add_argument("--interval", type=float, default=20.0)
    pilot_watch.add_argument("--model-budget-usd", type=float)
    pilot_cleanup = pilot_commands.add_parser(
        "cleanup",
        help="list or retry pending Daytona snapshot cleanup",
    )
    pilot_cleanup.add_argument("--root", required=True, type=Path)
    pilot_cleanup.add_argument("--yes", action="store_true")
    pilot_replay = pilot_commands.add_parser(
        "replay",
        help="replay the current gate over stored pilot attempts",
    )
    pilot_replay.add_argument("run_dirs", nargs="+", type=Path)
    pilot_replay.add_argument("--data", required=True, type=Path)
    pilot_replay.add_argument("--out", required=True, type=Path)
    return parser


async def _docker_ready(timeout_s: float = 10) -> tuple[bool, str]:
    executable = shutil.which("docker")
    if executable is None:
        return False, "docker executable not found"
    process = await asyncio.create_subprocess_exec(
        executable,
        "info",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return False, (
            f"docker info did not answer within {timeout_s:.0f} seconds; "
            "is Docker Desktop running and finished starting?"
        )
    if process.returncode != 0:
        detail = (stderr or stdout).decode(errors="replace").strip().splitlines()
        return False, detail[0] if detail else f"docker info exited {process.returncode}"
    return True, ""


async def docker_ready(timeout_s: float = 60) -> tuple[bool, str]:
    """Expose the CLI's Docker readiness check for standalone re-verification.

    Re-verification waits longer than `receipts fix`: a judge may have just started
    Docker Desktop, whose first `docker info` can take tens of seconds.
    """
    return await _docker_ready(timeout_s)


def _fix_model_id(model: ModelClient) -> str:
    config = getattr(model, "config", None)
    if isinstance(config, BaseModel):
        value = config.model_dump().get("model")
    elif isinstance(config, dict):
        value = config.get("model")
    else:
        value = None
    return str(value or type(model).__name__)


def _fix_executor_name(executor: str) -> str:
    return {
        "tokenfactory": "Nebius Token Factory Sandboxes",
        "daytona": "Daytona",
        "docker": "Docker",
        "local": "the local executor",
    }[executor]


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"[:limit]
    return text[: limit - 1].rstrip() + "…"


def _hide_local_paths(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        trailing = ""
        while value and value[-1] in ",.)]":
            trailing = value[-1] + trailing
            value = value[:-1]
        return (PurePosixPath(value).name or "~") + trailing

    return _LOCAL_ABSOLUTE_PATH.sub(replace, text)


def _console_text(text: str) -> str:
    """Make external text safe to render as one terminal line."""

    without_ansi = _ANSI_ESCAPE.sub("", text)
    return _hide_local_paths(" ".join(without_ansi.split()))


def _fix_duration(seconds: float) -> str:
    rounded = int(seconds + 0.5)
    minutes, remaining = divmod(rounded, 60)
    if minutes:
        return f"{minutes}m {remaining}s"
    return f"{remaining}s"


def _display_receipt_path(path: Path) -> str:
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return f"…/{path.parent.name}/{path.name}"


def _compact_path_list(value: str) -> str:
    if value == "none":
        return value
    paths = [PurePosixPath(item.strip()).name for item in value.split(",")]
    if len(paths) <= 2:
        return ", ".join(paths)
    return f"{paths[0]}, +{len(paths) - 1}"


def _compact_witness_message(message: str) -> str:
    """"w1; fresh sandbox from checkpoint 632189ea; files applied a.py; dropped none"
    becomes "fresh fork of 632189ea · applied a.py"."""

    parts: list[str] = []
    for index, part in enumerate(message.split(";")):
        part = part.strip()
        if index == 0 and " " not in part:
            continue  # the branch id
        if part.startswith("fresh sandbox from checkpoint "):
            part = "fresh fork of " + part.removeprefix("fresh sandbox from checkpoint ")
        elif part.startswith("witness not provisioned from checkpoint "):
            part = "not provisioned from checkpoint " + part.removeprefix(
                "witness not provisioned from checkpoint ",
            )
        elif part.startswith("files applied "):
            part = "applied " + _compact_path_list(part.removeprefix("files applied "))
        elif part == "dropped none":
            continue
        elif part.startswith("dropped "):
            part = "dropped " + _compact_path_list(part.removeprefix("dropped "))
        parts.append(part)
    return " · ".join(parts)


def _token_cost(dollars: float | None) -> str:
    """The run's model cost; under a cent it keeps three decimals, so a cheap run never reads $0.00."""

    if dollars is None:
        return "token cost unavailable"
    value = float(dollars)
    return f"${value:.3f} of Nemotron tokens" if value < 0.01 else f"${value:.2f} of Nemotron tokens"


class _FixProgressRenderer:
    def __init__(self, issue: str, model: ModelClient, executor: str) -> None:
        first_line = issue.splitlines()[0].strip() if issue.splitlines() else "issue"
        first_line = _console_text(first_line)
        model_id = _console_text(_fix_model_id(model))
        executor_name = _fix_executor_name(executor)
        print(_clip(f"Fixing: {first_line}", _FIX_LINE_LIMIT))
        model_limit = max(_FIX_LINE_LIMIT - len(f"with  on {executor_name}"), 1)
        print(f"with {_clip(model_id, model_limit)} on {executor_name}")
        print()

    @staticmethod
    def _mark(event: ProgressEvent) -> str:
        from receipts.reverify import _color

        if event.kind == "check" and event.check_id == "R6 advisory":
            return _color("!", "33")
        if event.kind == "check" or event.kind == "verdict":
            if event.passed:
                return _color("✓", "32")
            return _color("✗", "31")
        return "·"

    @staticmethod
    def _label(event: ProgressEvent) -> str:
        if event.kind == "agent_tool":
            return {"read": "reads", "edit": "edits", "write": "writes", "run": "runs"}.get(
                event.action or "", "agent",
            )
        if event.kind == "agent_finish":
            return "says done"
        if event.kind == "check":
            if event.check_id == "R6 advisory":
                return "agent's claim"
            return _CHECK_LABELS.get((event.check_id or "").split("_", 1)[0], "check")
        return event.kind

    @staticmethod
    def _body(event: ProgressEvent) -> str:
        if event.kind == "agent_tool" and event.action == "run":
            from receipts.site import _display_command

            body = _display_command(
                {
                    "kind": "command",
                    "cmd": event.message,
                    "exit_code": event.exit_code,
                },
            )
        elif event.kind == "agent_tool" and event.message.startswith("/"):
            body = PurePosixPath(event.message).name
        elif event.kind == "witness":
            body = _compact_witness_message(event.message)
        else:
            body = event.message
        return _console_text(body)

    def __call__(self, event: ProgressEvent) -> None:
        if event.kind == "verdict":
            return  # the summary line after the run says it
        label = self._label(event)
        mark = self._mark(event)
        plain_prefix = f"  · {label:<{_FIX_LABEL_WIDTH}} "
        rendered_prefix = f"  {mark} {label:<{_FIX_LABEL_WIDTH}} "
        suffix = ""
        if event.exit_code is not None:
            suffix += f" · exit {event.exit_code}"
        if event.duration_s is not None:
            suffix += f" ({event.duration_s:.1f}s)"
        available = _FIX_LINE_LIMIT - len(plain_prefix) - len(suffix)
        print(rendered_prefix + _clip(self._body(event), max(available, 1)) + suffix)

    def finish(self, result: RunResult, receipt_path: Path) -> None:
        elapsed = _fix_duration(result.wall_time_s)
        cost = _token_cost(result.cost.get("estimated_dollars"))
        if result.final_verdict.status == "PASS":
            summary = f"VERIFIED in {elapsed} · {cost}"
        elif result.final_verdict.status == "REJECTED":
            failed = result.final_verdict.failed_predicate_ids()
            suffix = f" at {', '.join(item.split('_', 1)[0] for item in failed)}" if failed else ""
            summary = f"REJECTED{suffix} in {elapsed} · {cost}"
        else:
            summary = f"ERROR in {elapsed} · {cost}"
        print("\n" + _clip(summary, _FIX_LINE_LIMIT))
        print(
            _clip(
                f"receipt: {_display_receipt_path(receipt_path)}",
                _FIX_LINE_LIMIT,
            ),
        )


async def _doctor(live: bool, model: ModelClient | None) -> int:
    env_path = Path(".env")
    values = _parse_dotenv(env_path)
    for name in _REQUIRED_ENV:
        if not values.get(name, "").strip():
            print(f"MISSING {name}")
            return 1

    if live:
        live_model = model or TokenFactoryClient(
            load_config(env_path=env_path),
            env_path=env_path,
        )
        try:
            response = await live_model.complete_json(
                "Return a JSON object with ok set to true.",
                "This is a Receipts doctor connectivity check.",
                _DoctorResponse,
            )
        except Exception as exc:
            print(f"MODEL CHECK FAILED: {exc}")
            return 1
        if not response.ok:
            print("MODEL CHECK FAILED: model returned ok=false")
            return 1

        docker_ok, detail = await _docker_ready()
        if not docker_ok:
            print(f"DOCKER NOT READY: {detail}")
            return 1

    print("READY")
    return 0


async def _run_fix(args: argparse.Namespace, model: ModelClient | None) -> int:
    issue = args.issue_file.read_text(encoding="utf-8").strip()
    setup: list[str] = []
    spec_paths: list[str] | None = None
    if args.test_patch is not None:
        if args.executor in {"local", "docker"}:
            raise ValueError(
                "--test-patch is only supported with tokenfactory or daytona; "
                "commit the test for local or docker",
            )
        test_patch = args.test_patch.read_text(encoding="utf-8")
        setup = _test_patch_setup_commands(
            test_patch,
            PurePosixPath("/tmp/receipts-cli-test.patch"),
        )
        spec_paths = _spec_paths_from_test_patch(test_patch, context="--test-patch")
    selected_model = model or TokenFactoryClient(
        load_config(env_path=Path(".env")),
        env_path=Path(".env"),
    )
    reviewer = model or TokenFactoryClient(
        load_config(env_path=Path(".env")).model_copy(update=REVIEWER_SETTINGS),
        env_path=Path(".env"),
        meter=CostMeter(),  # counts every review call, including retries after invalid JSON
    )
    progress = _FixProgressRenderer(issue, selected_model, args.executor)
    if args.executor in {"daytona", "tokenfactory"}:
        if not args.image or not args.workdir:
            raise ValueError(
                "--image and --workdir are required for sandbox executors",
            )
        source = ImageSource(
            image=args.image,
            workdir=args.workdir,
            python=args.python,
            setup=setup,
        )
    else:
        if not args.repo or not args.commit:
            raise ValueError("--repo and --commit are required for local and Docker executors")
        source = RepoAtCommit(
            url=args.repo,
            commit=args.commit,
            install_cmd=args.install,
        )
    run_id = f"receipts-{uuid.uuid4().hex[:12]}"
    budgets = _default_run_budgets()
    fix_options: dict[str, Any] = {
        "budgets": budgets,
        "progress": progress,
        "review": getattr(args, "review", "advisory"),
        "reviewer": reviewer,
    }
    if spec_paths is not None:
        fix_options["spec_paths"] = spec_paths

    async def run_and_persist(executor: Any) -> RunResult:
        result = await fix(
            executor,
            selected_model,
            source,
            issue,
            args.tests,
            args.suite,
            args.out,
            **fix_options,
        )
        receipt_path = args.out / "receipt.md"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(render(result), encoding="utf-8")
        progress.finish(result, receipt_path)
        return result

    with tempfile.TemporaryDirectory(prefix="receipts-executor-") as executor_root:
        sink = RunSink(args.out)
        if args.executor == "local":
            executor: Any = LocalExecutor(Path(executor_root), sink, run_id)
            result = await run_and_persist(executor)
        elif args.executor == "docker":
            executor = DockerExecutor(Path(executor_root), sink, run_id)
            try:
                result = await run_and_persist(executor)
            finally:
                await executor.close()
        elif args.executor == "daytona":
            dotenv = _parse_dotenv(Path(".env"))
            api_key = os.environ.get("DAYTONA_API_KEY") or dotenv.get("DAYTONA_API_KEY")
            if not api_key:
                raise ValueError("DAYTONA_API_KEY is required for the Daytona executor")
            api = AsyncDaytonaApi(AsyncDaytona(DaytonaConfig(api_key=api_key)))
            executor = DaytonaExecutor(Path(executor_root), sink, run_id, api)
            try:
                result = await run_and_persist(executor)
            finally:
                await executor.close()
        else:
            api = TokenFactorySandboxApi.from_env()
            try:
                busybox = load_busybox()
                executor = TokenFactoryExecutor(
                    Path(executor_root),
                    sink,
                    run_id,
                    api,
                    busybox=busybox,
                )
                if getattr(executor, "api", None) is api:
                    executor.api = _BorrowedTokenFactorySandboxApi(api)
                try:
                    result = await run_and_persist(executor)
                finally:
                    await executor.close()
            finally:
                await api.aclose()

    return 0 if result.verified_fix else 1


def _show(run_dir: Path) -> int:
    result_path = run_dir / "result.json"
    result = RunResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    print(render(result), end="")
    return 0


def _load_pilot_candidates(candidates_path: Path, rows_path: Path) -> list[Instance]:
    candidate_ids = [
        line.strip().split(maxsplit=1)[0]
        for line in candidates_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate ids must be unique")

    wanted = set(candidate_ids)
    by_id: dict[str, Instance] = {}
    for line_number, line in enumerate(
        rows_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"row {line_number} is not a JSON object")
        row.pop("patch", None)
        instance_id = row.get("instance_id")
        if instance_id not in wanted:
            continue
        if instance_id in by_id:
            raise ValueError(f"duplicate dataset row for {instance_id}")
        by_id[instance_id] = Instance.model_validate(row)

    missing = [instance_id for instance_id in candidate_ids if instance_id not in by_id]
    if missing:
        raise ValueError("candidate ids missing from rows: " + ", ".join(missing))
    return [by_id[instance_id] for instance_id in candidate_ids]


def load_pilot_candidates(candidates_path: Path, rows_path: Path) -> list[Instance]:
    """Expose the pilot row loader for portable receipt export."""
    return _load_pilot_candidates(candidates_path, rows_path)


def _load_id_file(path: Path) -> list[str]:
    return [
        line.strip().split(maxsplit=1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


class _ScreenCleanupExecutor:
    """Keep screening cleanup atomic with respect to task cancellation."""

    def __init__(self, executor: Any) -> None:
        object.__setattr__(self, "_screen_executor", executor)
        object.__setattr__(self, "_screen_closed", False)
        object.__setattr__(self, "_screen_usage", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._screen_executor, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_screen_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._screen_executor, name, value)

    async def _close_and_collect(self) -> tuple[bool, BaseException | None]:
        if self._screen_closed:
            return False, None
        cancelled = False
        error: BaseException | None = None
        try:
            close = getattr(self._screen_executor, "close", None)
            if close is not None:
                result = close()
                if inspect.isawaitable(result):
                    _, cancelled, error = await _complete_shielded(result)
        except BaseException as exc:
            error = exc
        finally:
            try:
                usage = getattr(self._screen_executor, "sandbox_usage", None)
                self._screen_usage = list(usage()) if usage is not None else []
            except BaseException as exc:
                if error is None:
                    error = exc
            finally:
                self._screen_closed = True
        return cancelled, error

    async def release(self, branch: Any) -> None:
        if self._screen_closed:
            return
        result = self._screen_executor.release(branch)
        if inspect.isawaitable(result):
            _, cancelled, error = await _complete_shielded(result)
        else:
            cancelled = False
            error = None
        if cancelled:
            await self._close_and_collect()
            raise asyncio.CancelledError
        if error is not None:
            raise error

    async def close(self) -> None:
        cancelled, error = await self._close_and_collect()
        if cancelled:
            raise asyncio.CancelledError
        if error is not None:
            raise error

    def sandbox_usage(self) -> list[dict[str, Any]]:
        if self._screen_usage is not None:
            return list(self._screen_usage)
        usage = getattr(self._screen_executor, "sandbox_usage", None)
        return list(usage()) if usage is not None else []


def _daytona_executor_factory(
    executor_root: Path,
    api_key: str,
    *,
    shield_cleanup: bool = False,
):
    def make_executor(run_id: str) -> Any:
        client = AsyncDaytona(DaytonaConfig(api_key=api_key))
        api = AsyncDaytonaApi(client)
        executor = DaytonaExecutor(
            executor_root / run_id,
            MemorySink(),
            run_id,
            api,
        )
        if shield_cleanup:
            return _ScreenCleanupExecutor(executor)
        return executor

    return make_executor


class _BorrowedTokenFactorySandboxApi:
    """Delegate API calls while keeping invocation-level ownership of close."""

    def __init__(self, api: Any) -> None:
        self._api = api

    def __getattr__(self, name: str) -> Any:
        return getattr(self._api, name)

    async def aclose(self) -> None:
        return None


def _tokenfactory_executor_factory(
    executor_root: Path,
    api: Any,
    busybox: bytes,
    *,
    shield_cleanup: bool = False,
):
    borrowed_api = _BorrowedTokenFactorySandboxApi(api)

    def make_executor(run_id: str) -> Any:
        executor = TokenFactoryExecutor(
            executor_root / run_id,
            MemorySink(),
            run_id,
            api,
            busybox=busybox,
        )
        if getattr(executor, "api", None) is api:
            executor.api = borrowed_api
        if shield_cleanup:
            return _ScreenCleanupExecutor(executor)
        return executor

    return make_executor


def tokenfactory_executor_factory(executor_root: Path, api: Any, busybox: bytes):
    """Expose the pilot's Token Factory executor construction for re-verification."""
    return _tokenfactory_executor_factory(executor_root, api, busybox)


def _default_run_budgets() -> RunBudgets:
    return RunBudgets(
        baseline_limit_s=600,
        verification_timeout_s=600,
        worker=WorkerBudget(
            max_turns=60,
            max_wall_seconds=1_500,
            max_completion_tokens=96_000,
            prompt_token_budget=160_000,
        ),
    )


async def _run_pilot(args: argparse.Namespace, model: ModelClient | None) -> int:
    if args.n < 0:
        raise ValueError("--n must be non-negative")
    if args.concurrency < 1:
        raise ValueError("--concurrency must be at least 1")
    candidates = _load_pilot_candidates(args.candidates, args.rows)
    if model is None:
        model_config = load_config(env_path=Path(".env"))
        if args.model is not None:
            if args.model not in price_table:
                raise ValueError(
                    f"--model {args.model} has no listed price in "
                    "receipts.cost.price_table, so its spend could not be "
                    "counted against the budget",
                )
            model_config = model_config.model_copy(
                update={"model": args.model},
            )
        selected_model = TokenFactoryClient(
            model_config,
            env_path=Path(".env"),
        )
    else:
        selected_model = model
    with tempfile.TemporaryDirectory(prefix="receipts-pilot-executor-") as root:
        executor_root = Path(root)
        if args.executor == "daytona":
            dotenv = _parse_dotenv(Path(".env"))
            api_key = os.environ.get("DAYTONA_API_KEY") or dotenv.get("DAYTONA_API_KEY")
            if not api_key:
                raise ValueError("DAYTONA_API_KEY is required for the Daytona executor")
            records = await run_pilot(
                _daytona_executor_factory(executor_root, api_key),
                selected_model,
                candidates,
                args.out,
                n=args.n,
                concurrency=args.concurrency,
                budgets=_default_run_budgets(),
            )
        else:
            api = TokenFactorySandboxApi.from_env()
            try:
                records = await run_pilot(
                    _tokenfactory_executor_factory(
                        executor_root,
                        api,
                        load_busybox(),
                    ),
                    selected_model,
                    candidates,
                    args.out,
                    n=args.n,
                    concurrency=args.concurrency,
                    budgets=_default_run_budgets(),
                )
            finally:
                await api.aclose()

    ran = sum(record.status == "ran" for record in records)
    excluded = sum(record.status == "excluded" for record in records)
    infra_errors = sum(record.status == "infra_error" for record in records)
    print(f"PILOT ran={ran} excluded={excluded} infra_error={infra_errors}")
    return 0


async def _run_pilot_screen(args: argparse.Namespace) -> int:
    candidates = _load_pilot_candidates(args.candidates, _PILOT_ROWS_PATH)
    exclusions = set(_load_id_file(args.exclude))
    with tempfile.TemporaryDirectory(prefix="receipts-screen-executor-") as root:
        if args.executor == "daytona":
            dotenv = _parse_dotenv(Path(".env"))
            api_key = os.environ.get("DAYTONA_API_KEY") or dotenv.get("DAYTONA_API_KEY")
            if not api_key:
                raise ValueError("DAYTONA_API_KEY is required for the Daytona executor")
            included = await screen_candidates(
                _daytona_executor_factory(
                    Path(root),
                    api_key,
                    shield_cleanup=True,
                ),
                candidates,
                args.out,
                start=args.start,
                exclude=exclusions,
                want=args.want,
                concurrency=args.concurrency,
            )
        else:
            api = TokenFactorySandboxApi.from_env()
            try:
                included = await screen_candidates(
                    _tokenfactory_executor_factory(
                        Path(root),
                        api,
                        load_busybox(),
                        shield_cleanup=True,
                    ),
                    candidates,
                    args.out,
                    start=args.start,
                    exclude=exclusions,
                    want=args.want,
                    concurrency=args.concurrency,
                )
            finally:
                await api.aclose()

    print(f"SCREEN included={len(included)}")
    return 0


async def _run_pilot_cleanup(args: argparse.Namespace) -> int:
    api: AsyncDaytonaApi | None = None
    dotenv = _parse_dotenv(Path(".env"))
    api_key = os.environ.get("DAYTONA_API_KEY") or dotenv.get("DAYTONA_API_KEY", "")
    if args.yes:
        if not api_key:
            raise ValueError("DAYTONA_API_KEY is required with --yes")
        api = AsyncDaytonaApi(AsyncDaytona(DaytonaConfig(api_key=api_key)))
    try:
        result = await cleanup_manifests(
            args.root,
            api,
            yes=args.yes,
            secrets=(api_key,),
        )
    finally:
        if api is not None:
            await api.close()
    print(render_cleanup(result), end="")
    return 1 if result.failed else 0


def _run_pilot_report(
    pilot_dir: Path,
    screen_ledgers: Sequence[Path] = (),
) -> int:
    try:
        report_module = importlib.import_module("receipts.pilot.report")
    except ModuleNotFoundError as exc:
        if exc.name == "receipts.pilot.report":
            raise RuntimeError("pilot reporting is not available until Task P4") from exc
        raise

    report = report_module.build_report_from_directory(
        pilot_dir,
        screen_ledgers=screen_ledgers,
    )
    markdown = report_module.render(report)
    (pilot_dir / "REPORT.md").write_text(markdown, encoding="utf-8")
    (pilot_dir / "report.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(pilot_dir / "REPORT.md")
    return 0


def _cancel_task(task: asyncio.Task[Any]) -> None:
    """Signal handler callback for gracefully cancelling a pilot operation."""

    if not task.done():
        task.cancel()


async def _run_with_signal_cancellation(awaitable: Awaitable[int]) -> int:
    task = asyncio.ensure_future(awaitable)
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _cancel_task, task)
        except (NotImplementedError, RuntimeError):
            continue
        installed.append(sig)
    try:
        return await task
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)


async def _dispatch(args: argparse.Namespace, model: ModelClient | None) -> int:
    if args.command == "export":
        from receipts.reverify import export_bundles

        paths = export_bundles(args.pilot_dir, args.rows, args.out)
        print(f"Exported {len(paths)} bundle(s) to {args.out}")
        return 0
    if args.command == "reverify":
        from receipts.reverify import reverify

        return await _run_with_signal_cancellation(reverify(args.bundle, executor=args.executor))
    if args.command == "doctor":
        return await _doctor(args.live, model)
    if args.command == "preflight":
        return await run_preflight(args.out, executor=args.executor)
    if args.command == "fix":
        return await _run_fix(args, model)
    if args.command == "show":
        return _show(args.run_dir)
    if args.command == "site":
        from receipts.site import build_site

        summary = build_site(
            args.pilot_dirs, args.out, repo_root=Path.cwd(), title=args.title,
            strip_prefixes=args.strip_prefixes, featured=args.featured,
        )
        print(f"SITE {summary.out_dir / 'index.html'} pilots={summary.pilots} instances={summary.instances}")
        return 0
    if args.command == "pilot" and args.pilot_command == "run":
        return await _run_with_signal_cancellation(_run_pilot(args, model))
    if args.command == "pilot" and args.pilot_command == "screen":
        return await _run_with_signal_cancellation(_run_pilot_screen(args))
    if args.command == "pilot" and args.pilot_command == "watch":
        return watch_pilot(
            args.pilot_dir,
            args.pid,
            interval=args.interval,
            model_budget_usd=args.model_budget_usd,
        )
    if args.command == "pilot" and args.pilot_command == "cleanup":
        return await _run_pilot_cleanup(args)
    if args.command == "pilot" and args.pilot_command == "replay":
        report = write_replay(args.run_dirs, args.data, args.out)
        print(replay_summary_line(report))
        return 1 if report.summary.new_gate_looser else 0
    if args.command == "pilot" and args.pilot_command == "report":
        return _run_pilot_report(args.pilot_dir, args.screen_ledgers)
    raise AssertionError(f"unknown command: {args.command}")


def main(
    argv: Sequence[str] | None = None,
    *,
    model: ModelClient | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_dispatch(args, model))
    except (asyncio.CancelledError, KeyboardInterrupt):
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
