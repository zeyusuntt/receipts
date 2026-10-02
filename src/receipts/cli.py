"""Command-line entry points for running and inspecting Receipts."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from daytona import AsyncDaytona, DaytonaConfig

from receipts.agent.worker import WorkerBudget
from receipts.llm import (
    ModelClient,
    TokenFactoryClient,
    _parse_dotenv,
    load_config,
)
from receipts.orchestrate import RunBudgets, RunResult, fix
from receipts.pilot.runner import InstanceRecord, run_pilot
from receipts.pilot.screen import screen_candidates
from receipts.preflight import run_preflight
from receipts.receipt_text import render
from receipts.sandbox.daytona import AsyncDaytonaApi, DaytonaExecutor
from receipts.sandbox.docker import DockerExecutor
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import ImageSource, RepoAtCommit
from receipts.sandbox.sink import MemorySink, RunSink
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
    fix_parser.add_argument("--image", help="container image for the Daytona executor")
    fix_parser.add_argument("--workdir", help="repository path inside the Daytona image")
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
        choices=("local", "docker", "daytona"),
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

    show_parser = commands.add_parser("show", help="print a run's Markdown receipt")
    show_parser.add_argument("run_dir", type=Path)

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
    pilot_run.add_argument("--executor", choices=("daytona",), default="daytona")
    pilot_run.add_argument("--out", required=True, type=Path)
    pilot_run.add_argument("--concurrency", type=int, default=1)

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

    pilot_report = pilot_commands.add_parser(
        "report",
        help="build the report from pilot records",
    )
    pilot_report.add_argument("pilot_dir", type=Path)
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
    if args.executor == "daytona":
        if not args.image or not args.workdir:
            raise ValueError("--image and --workdir are required for the Daytona executor")
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
                )
            finally:
                await executor.close()
        else:
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
                )
            finally:
                await executor.close()

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


def _load_id_file(path: Path) -> list[str]:
    return [
        line.strip().split(maxsplit=1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _daytona_executor_factory(executor_root: Path, api_key: str):
    def make_executor(run_id: str) -> DaytonaExecutor:
        client = AsyncDaytona(DaytonaConfig(api_key=api_key))
        api = AsyncDaytonaApi(client)
        return DaytonaExecutor(
            executor_root / run_id,
            MemorySink(),
            run_id,
            api,
        )

    return make_executor


async def _run_pilot(args: argparse.Namespace, model: ModelClient | None) -> int:
    if args.n < 0:
        raise ValueError("--n must be non-negative")
    if args.concurrency < 1:
        raise ValueError("--concurrency must be at least 1")
    candidates = _load_pilot_candidates(args.candidates, args.rows)
    selected_model = model or TokenFactoryClient(
        load_config(env_path=Path(".env")),
        env_path=Path(".env"),
    )
    dotenv = _parse_dotenv(Path(".env"))
    api_key = os.environ.get("DAYTONA_API_KEY") or dotenv.get("DAYTONA_API_KEY")
    if not api_key:
        raise ValueError("DAYTONA_API_KEY is required for the Daytona executor")

    with tempfile.TemporaryDirectory(prefix="receipts-pilot-executor-") as root:
        executor_root = Path(root)
        records = await run_pilot(
            _daytona_executor_factory(executor_root, api_key),
            selected_model,
            candidates,
            args.out,
            n=args.n,
            concurrency=args.concurrency,
            budgets=RunBudgets(
                baseline_limit_s=600,
                verification_timeout_s=600,
                worker=WorkerBudget(
                    max_turns=40,
                    max_wall_seconds=1_200,
                    max_completion_tokens=64_000,
                ),
            ),
        )

    ran = sum(record.status == "ran" for record in records)
    excluded = sum(record.status == "excluded" for record in records)
    infra_errors = sum(record.status == "infra_error" for record in records)
    print(f"PILOT ran={ran} excluded={excluded} infra_error={infra_errors}")
    return 0


async def _run_pilot_screen(args: argparse.Namespace) -> int:
    candidates = _load_pilot_candidates(args.candidates, _PILOT_ROWS_PATH)
    exclusions = set(_load_id_file(args.exclude))
    dotenv = _parse_dotenv(Path(".env"))
    api_key = os.environ.get("DAYTONA_API_KEY") or dotenv.get("DAYTONA_API_KEY")
    if not api_key:
        raise ValueError("DAYTONA_API_KEY is required for the Daytona executor")

    with tempfile.TemporaryDirectory(prefix="receipts-screen-executor-") as root:
        included = await screen_candidates(
            _daytona_executor_factory(Path(root), api_key),
            candidates,
            args.out,
            start=args.start,
            exclude=exclusions,
            want=args.want,
            concurrency=args.concurrency,
        )

    print(f"SCREEN included={len(included)}")
    return 0


def _run_pilot_report(pilot_dir: Path) -> int:
    try:
        report_module = importlib.import_module("receipts.pilot.report")
    except ModuleNotFoundError as exc:
        if exc.name == "receipts.pilot.report":
            raise RuntimeError("pilot reporting is not available until Task P4") from exc
        raise

    records = [
        InstanceRecord.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(pilot_dir.glob("*/record.json"))
    ]
    report = report_module.build_report(records)
    markdown = report_module.render(report)
    (pilot_dir / "REPORT.md").write_text(markdown, encoding="utf-8")
    (pilot_dir / "report.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(pilot_dir / "REPORT.md")
    return 0


async def _dispatch(args: argparse.Namespace, model: ModelClient | None) -> int:
    if args.command == "doctor":
        return await _doctor(args.live, model)
    if args.command == "preflight":
        return await run_preflight(args.out)
    if args.command == "fix":
        return await _run_fix(args, model)
    if args.command == "show":
        return _show(args.run_dir)
    if args.command == "pilot" and args.pilot_command == "run":
        return await _run_pilot(args, model)
    if args.command == "pilot" and args.pilot_command == "screen":
        return await _run_pilot_screen(args)
    if args.command == "pilot" and args.pilot_command == "report":
        return _run_pilot_report(args.pilot_dir)
    raise AssertionError(f"unknown command: {args.command}")


def main(
    argv: Sequence[str] | None = None,
    *,
    model: ModelClient | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_dispatch(args, model))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
