"""Command-line entry points for running and inspecting Receipts."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import os
import signal
import shutil
import tempfile
import uuid
from collections.abc import Awaitable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from daytona import AsyncDaytona, DaytonaConfig

from receipts.agent.worker import WorkerBudget
from receipts.cost import price_table
from receipts.llm import (
    ModelClient,
    TokenFactoryClient,
    _parse_dotenv,
    load_config,
)
from receipts.orchestrate import RunBudgets, RunResult, fix
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
from receipts.swerebench import Instance


_REQUIRED_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "NEMOTRON_MODEL")
_PILOT_ROWS_PATH = Path("data/rebench-v2-python.jsonl")


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
    fix_parser.add_argument("--install", default="true", help="installation command")
    fix_parser.add_argument("--suite", default="tests", help="pytest suite arguments")
    fix_parser.add_argument(
        "--executor",
        choices=("local", "docker", "daytona", "tokenfactory"),
        default="local",
    )
    fix_parser.add_argument("--out", required=True, type=Path)

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


async def _docker_ready() -> tuple[bool, str]:
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
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return False, "docker info timed out"
    if process.returncode != 0:
        detail = (stderr or stdout).decode(errors="replace").strip().splitlines()
        return False, detail[0] if detail else f"docker info exited {process.returncode}"
    return True, ""


async def docker_ready() -> tuple[bool, str]:
    """Expose the CLI's Docker readiness check for standalone re-verification."""
    return await _docker_ready()


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
    selected_model = model or TokenFactoryClient(
        load_config(env_path=Path(".env")),
        env_path=Path(".env"),
    )
    if args.executor in {"daytona", "tokenfactory"}:
        if not args.image or not args.workdir:
            raise ValueError(
                "--image and --workdir are required for sandbox executors",
            )
        source = ImageSource(
            image=args.image,
            workdir=args.workdir,
            python=args.python,
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

    with tempfile.TemporaryDirectory(prefix="receipts-executor-") as executor_root:
        sink = RunSink(args.out)
        if args.executor == "local":
            executor: Any = LocalExecutor(Path(executor_root), sink, run_id)
            result = await fix(
                executor,
                selected_model,
                source,
                issue,
                args.tests,
                args.suite,
                args.out,
                budgets=budgets,
            )
        elif args.executor == "docker":
            executor = DockerExecutor(Path(executor_root), sink, run_id)
            try:
                result = await fix(
                    executor,
                    selected_model,
                    source,
                    issue,
                    args.tests,
                    args.suite,
                    args.out,
                    budgets=budgets,
                )
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
                result = await fix(
                    executor,
                    selected_model,
                    source,
                    issue,
                    args.tests,
                    args.suite,
                    args.out,
                    budgets=budgets,
                )
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
                    result = await fix(
                        executor,
                        selected_model,
                        source,
                        issue,
                        args.tests,
                        args.suite,
                        args.out,
                        budgets=budgets,
                    )
                finally:
                    await executor.close()
            finally:
                await api.aclose()

    print(render(result), end="")
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

        summary = build_site(args.pilot_dirs, args.out, repo_root=Path.cwd(), title=args.title)
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
