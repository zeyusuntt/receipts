"""Command-line entry points for running and inspecting Receipts."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from receipts.llm import (
    ModelClient,
    TokenFactoryClient,
    _parse_dotenv,
    load_config,
)
from receipts.orchestrate import RunResult, fix
from receipts.receipt_text import render
from receipts.sandbox.docker import DockerExecutor
from receipts.sandbox.local import LocalExecutor
from receipts.sandbox.protocol import RepoAtCommit
from receipts.sandbox.sink import RunSink


_REQUIRED_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "NEMOTRON_MODEL")


class _DoctorResponse(BaseModel):
    ok: bool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="receipts")
    commands = parser.add_subparsers(dest="command", required=True)

    fix_parser = commands.add_parser("fix", help="run an agent and verify its patch")
    fix_parser.add_argument("--repo", required=True, help="repository path or URL")
    fix_parser.add_argument("--commit", required=True, help="commit to check out")
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
        choices=("local", "docker"),
        default="local",
    )
    fix_parser.add_argument("--out", required=True, type=Path)

    doctor_parser = commands.add_parser("doctor", help="check local configuration")
    doctor_parser.add_argument(
        "--live",
        action="store_true",
        help="also call the configured model and check Docker",
    )

    show_parser = commands.add_parser("show", help="print a run's Markdown receipt")
    show_parser.add_argument("run_dir", type=Path)
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
        else:
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

    print(render(result), end="")
    return 0 if result.verified_fix else 1


def _show(run_dir: Path) -> int:
    result_path = run_dir / "result.json"
    result = RunResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    print(render(result), end="")
    return 0


async def _dispatch(args: argparse.Namespace, model: ModelClient | None) -> int:
    if args.command == "doctor":
        return await _doctor(args.live, model)
    if args.command == "fix":
        return await _run_fix(args, model)
    if args.command == "show":
        return _show(args.run_dir)
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
