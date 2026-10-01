"""Bounded tool-calling worker and one-conversation appeal loop."""

from __future__ import annotations

import asyncio
import json
import os
import posixpath
import re
import shlex
import time
from typing import Any, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from receipts.llm import AssistantTurn, ModelClient, ToolCall
from receipts.models import Branch, Claims, Receipt
from receipts.sandbox.protocol import Executor


SYSTEM_PROMPT = """\
You are an autonomous coding agent operating on a git repository.
Act only by calling the supplied tools, exactly one tool per turn.
Do not ask the user questions. Tests and pytest configuration are read-only.
Use read_file to inspect files, write_file to make source changes, and run_command to test them.
When the task is done, call finish with a concise summary and accurate claims.
"""

APPEAL_INSTRUCTION = (
    "Fix the source so these checks pass. "
    "Tests and pytest configuration are read-only."
)

_READ_MAX_BYTES = 12_000
_COMMAND_OUTPUT_CHARS = 6_000
_COMMAND_TIMEOUT_S = 300
_TOOL_NAMES = ("read_file", "write_file", "run_command", "finish")
_ONE_CALL_REPLY = "one tool call per turn; only the first was run"
_FREE_TEXT_REPAIR = (
    "Respond with exactly one tool call. The available tools are "
    "read_file, write_file, run_command, finish."
)
_UNKNOWN_TOOL_REPLY = (
    "unknown tool, the tools are read_file, write_file, run_command, finish"
)


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a repository-relative file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write complete content to a repository-relative file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command in the repository.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish the attempt and state what was done and tested.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "claims": {
                        "type": "object",
                        "properties": {
                            "tests_run": {"type": "boolean"},
                            "target_tests_pass": {"type": "boolean"},
                            "full_suite_pass": {"type": "boolean"},
                            "files_changed": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "tests_run",
                            "target_tests_pass",
                            "full_suite_pass",
                            "files_changed",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": ["summary", "claims"],
                "additionalProperties": False,
            },
        },
    },
]


class WorkerBudget(BaseModel):
    max_turns: int = Field(default=25, gt=0)
    max_wall_seconds: float = Field(default=900, gt=0)
    max_completion_tokens: int = Field(gt=0)


class WorkerOutcome(BaseModel):
    end: Literal[
        "finished",
        "budget_exhausted",
        "protocol_error",
        "model_error",
    ]
    claims: Claims | None = None
    summary: str
    turns: int
    receipt_ids: list[str]


class _ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str


class _WriteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str


class _RunCommandArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str


class _FinishArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    claims: Claims


def _tool_arguments(
    call: ToolCall,
    arguments_type: type[BaseModel],
) -> tuple[Any, str]:
    supported_names = set(arguments_type.model_fields)
    unsupported_names = sorted(set(call.arguments) - supported_names)
    supported = {
        name: value
        for name, value in call.arguments.items()
        if name in supported_names
    }
    arguments = arguments_type.model_validate(supported)
    if not unsupported_names:
        return arguments, ""
    return arguments, (
        "note: ignored unsupported argument(s): "
        + ", ".join(unsupported_names)
    )


def _with_note(note: str, result: str) -> str:
    if not note:
        return result
    return f"{note}\n{result}"


def _assistant_message(turn: AssistantTurn) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": turn.content or None,
    }
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=True),
                },
            }
            for call in turn.tool_calls
        ]
    return message


def _tool_message(call_id: str, content: str) -> dict[str, str]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": content,
    }


def _cap_bytes(content: str, maximum: int) -> str:
    encoded = content.encode()
    if len(encoded) <= maximum:
        return content
    return encoded[:maximum].decode(errors="ignore")


def _shell_tokens(command: str) -> list[str] | None:
    if any(token in command for token in ("`", "$(", "\n", "\r")):
        return None
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars="|&;<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def pytest_args(command: str, repo_root: str | None = None) -> str | None:
    tokens = _shell_tokens(command)
    if tokens is None:
        return None
    if tokens[:1] == ["cd"]:
        if len(tokens) < 4 or tokens[2] != "&&":
            return None
        directory = posixpath.normpath(tokens[1])
        allowed_directories = {"."}
        if repo_root is not None:
            allowed_directories.add(posixpath.normpath(repo_root))
        if directory not in allowed_directories:
            return None
        tokens = tokens[3:]
    if any(token and set(token) <= set("|&;<>") for token in tokens):
        return None
    if tokens and tokens[0] in {"pytest", "py.test"}:
        return shlex.join(tokens[1:])
    if (
        len(tokens) >= 3
        and re.fullmatch(r"python(?:3(?:\.\d+)?)?", os.path.basename(tokens[0]))
        and tokens[1:3] == ["-m", "pytest"]
    ):
        return shlex.join(tokens[3:])
    return None


class Worker:
    def __init__(
        self,
        *,
        model: ModelClient,
        executor: Executor,
        branch: Branch,
        initial_message: str,
        writer: TextIO,
        repo_root: str | None = None,
    ) -> None:
        self.model = model
        self.executor = executor
        self.branch = branch
        self.writer = writer
        system_prompt = SYSTEM_PROMPT
        if repo_root is not None:
            system_prompt += f"Commands run in the repository root ({repo_root}).\n"
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_message},
        ]
        self.repo_root = repo_root
        self._receipt_ids: list[str] = []
        self._successful_write = False
        self._premature_finish_refused = False

    async def attempt(self, budget: WorkerBudget) -> WorkerOutcome:
        return await self._run(budget)

    async def appeal(self, evidence: str, budget: WorkerBudget) -> WorkerOutcome:
        self.messages.append(
            {
                "role": "user",
                "content": f"{evidence}\n\n{APPEAL_INSTRUCTION}",
            },
        )
        return await self._run(budget)

    def _outcome(
        self,
        end: Literal[
            "finished",
            "budget_exhausted",
            "protocol_error",
            "model_error",
        ],
        *,
        summary: str,
        turns: int,
        claims: Claims | None = None,
    ) -> WorkerOutcome:
        return WorkerOutcome(
            end=end,
            claims=claims,
            summary=summary,
            turns=turns,
            receipt_ids=list(self._receipt_ids),
        )

    def _log_turn(
        self,
        *,
        request_message_count: int,
        turn: AssistantTurn,
        end_reason: str,
    ) -> None:
        row = {
            "request_message_count": request_message_count,
            "tool_calls": [call.model_dump(mode="json") for call in turn.tool_calls],
            "usage": turn.usage.model_dump(mode="json"),
            "end_reason": end_reason,
        }
        self.writer.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
        self.writer.flush()

    def _record_receipt(self, receipt: Receipt) -> None:
        self._receipt_ids.append(receipt.receipt_id)

    @staticmethod
    def _budget_reason(
        budget: WorkerBudget,
        *,
        turns: int,
        completion_tokens: int,
        elapsed: float,
    ) -> str | None:
        if turns >= budget.max_turns:
            return f"turn budget exhausted after {turns} turn(s)"
        if completion_tokens >= budget.max_completion_tokens:
            return (
                "completion token budget exhausted after "
                f"{completion_tokens} token(s)"
            )
        if elapsed >= budget.max_wall_seconds:
            return f"wall budget exhausted after {elapsed:.3f} second(s)"
        return None

    async def _run(self, budget: WorkerBudget) -> WorkerOutcome:
        started = time.monotonic()
        turns = 0
        completion_tokens = 0
        consecutive_protocol_errors = 0

        while True:
            elapsed = time.monotonic() - started
            reason = self._budget_reason(
                budget,
                turns=turns,
                completion_tokens=completion_tokens,
                elapsed=elapsed,
            )
            if reason is not None:
                return self._outcome(
                    "budget_exhausted",
                    summary=reason,
                    turns=turns,
                )

            request_message_count = len(self.messages)
            remaining = budget.max_wall_seconds - elapsed
            try:
                turn = await asyncio.wait_for(
                    self.model.chat(self.messages, TOOLS),
                    timeout=remaining,
                )
            except TimeoutError:
                return self._outcome(
                    "budget_exhausted",
                    summary=(
                        "wall budget exhausted while waiting for model response"
                    ),
                    turns=turns,
                )
            except Exception as exc:
                return self._outcome(
                    "model_error",
                    summary=f"model call failed: {exc}",
                    turns=turns,
                )

            turns += 1
            completion_tokens += turn.usage.completion
            self.messages.append(_assistant_message(turn))

            if not turn.tool_calls:
                consecutive_protocol_errors += 1
                if consecutive_protocol_errors >= 3:
                    self._log_turn(
                        request_message_count=request_message_count,
                        turn=turn,
                        end_reason="protocol_error",
                    )
                    return self._outcome(
                        "protocol_error",
                        summary="model made three consecutive protocol errors",
                        turns=turns,
                    )
                self.messages.append({"role": "user", "content": _FREE_TEXT_REPAIR})
                outcome = self._budget_after_turn(
                    budget,
                    started=started,
                    turns=turns,
                    completion_tokens=completion_tokens,
                )
                self._log_turn(
                    request_message_count=request_message_count,
                    turn=turn,
                    end_reason=outcome.end if outcome is not None else "continue",
                )
                if outcome is not None:
                    return outcome
                continue

            primary, *extra = turn.tool_calls

            if primary.name not in _TOOL_NAMES:
                self.messages.append(_tool_message(primary.id, _UNKNOWN_TOOL_REPLY))
                for call in extra:
                    self.messages.append(_tool_message(call.id, _ONE_CALL_REPLY))
                consecutive_protocol_errors += 1
                if consecutive_protocol_errors >= 3:
                    self._log_turn(
                        request_message_count=request_message_count,
                        turn=turn,
                        end_reason="protocol_error",
                    )
                    return self._outcome(
                        "protocol_error",
                        summary="model made three consecutive protocol errors",
                        turns=turns,
                    )
                outcome = self._budget_after_turn(
                    budget,
                    started=started,
                    turns=turns,
                    completion_tokens=completion_tokens,
                )
                self._log_turn(
                    request_message_count=request_message_count,
                    turn=turn,
                    end_reason=outcome.end if outcome is not None else "continue",
                )
                if outcome is not None:
                    return outcome
                continue

            try:
                result, finished = await self._execute_tool(
                    primary,
                    remaining_s=max(
                        0.0,
                        budget.max_wall_seconds - (time.monotonic() - started),
                    ),
                )
            except ValidationError as exc:
                result = "invalid tool arguments: " + str(exc)
                self.messages.append(_tool_message(primary.id, result))
                for call in extra:
                    self.messages.append(_tool_message(call.id, _ONE_CALL_REPLY))
                consecutive_protocol_errors += 1
                if consecutive_protocol_errors >= 3:
                    self._log_turn(
                        request_message_count=request_message_count,
                        turn=turn,
                        end_reason="protocol_error",
                    )
                    return self._outcome(
                        "protocol_error",
                        summary="model made three consecutive protocol errors",
                        turns=turns,
                    )
                outcome = self._budget_after_turn(
                    budget,
                    started=started,
                    turns=turns,
                    completion_tokens=completion_tokens,
                )
                self._log_turn(
                    request_message_count=request_message_count,
                    turn=turn,
                    end_reason=outcome.end if outcome is not None else "continue",
                )
                if outcome is not None:
                    return outcome
                continue
            except TimeoutError:
                self._log_turn(
                    request_message_count=request_message_count,
                    turn=turn,
                    end_reason="budget_exhausted",
                )
                return self._outcome(
                    "budget_exhausted",
                    summary="wall budget exhausted while running a tool",
                    turns=turns,
                )
            except Exception as exc:
                consecutive_protocol_errors = 0
                result = f"tool error: {type(exc).__name__}: {exc}"
                finished = None
            else:
                consecutive_protocol_errors = 0

            if finished is not None:
                summary, claims = finished
                finish_result = f"{result}\nfinished" if result else "finished"
                self.messages.append(_tool_message(primary.id, finish_result))
                for call in extra:
                    self.messages.append(_tool_message(call.id, _ONE_CALL_REPLY))
                self._log_turn(
                    request_message_count=request_message_count,
                    turn=turn,
                    end_reason="finished",
                )
                return self._outcome(
                    "finished",
                    summary=summary,
                    turns=turns,
                    claims=claims,
                )

            self.messages.append(_tool_message(primary.id, result))
            for call in extra:
                self.messages.append(_tool_message(call.id, _ONE_CALL_REPLY))
            outcome = self._budget_after_turn(
                budget,
                started=started,
                turns=turns,
                completion_tokens=completion_tokens,
            )
            self._log_turn(
                request_message_count=request_message_count,
                turn=turn,
                end_reason=outcome.end if outcome is not None else "continue",
            )
            if outcome is not None:
                return outcome

    def _budget_after_turn(
        self,
        budget: WorkerBudget,
        *,
        started: float,
        turns: int,
        completion_tokens: int,
    ) -> WorkerOutcome | None:
        reason = self._budget_reason(
            budget,
            turns=turns,
            completion_tokens=completion_tokens,
            elapsed=time.monotonic() - started,
        )
        if reason is None:
            return None
        return self._outcome(
            "budget_exhausted",
            summary=reason,
            turns=turns,
        )

    async def _execute_tool(
        self,
        call: ToolCall,
        *,
        remaining_s: float,
    ) -> tuple[str, tuple[str, Claims] | None]:
        if remaining_s <= 0:
            raise TimeoutError

        if call.name == "read_file":
            arguments, note = _tool_arguments(call, _ReadFileArgs)
            content = await asyncio.wait_for(
                self.executor.read_file(
                    self.branch,
                    arguments.path,
                    max_bytes=_READ_MAX_BYTES,
                ),
                timeout=remaining_s,
            )
            return _with_note(note, _cap_bytes(content, _READ_MAX_BYTES)), None

        if call.name == "write_file":
            arguments, note = _tool_arguments(call, _WriteFileArgs)
            receipt = await asyncio.wait_for(
                self.executor.write_file(
                    self.branch,
                    arguments.path,
                    arguments.content,
                ),
                timeout=remaining_s,
            )
            self._record_receipt(receipt)
            if receipt.exit_code == 0:
                self._successful_write = True
                return _with_note(note, "ok"), None
            refusal = receipt.stderr_tail or receipt.stdout_tail
            result = refusal or f"refused (exit {receipt.exit_code})"
            return _with_note(note, result), None

        if call.name == "run_command":
            arguments, note = _tool_arguments(call, _RunCommandArgs)
            timeout_s = min(_COMMAND_TIMEOUT_S, int(remaining_s))
            if timeout_s < 1:
                raise TimeoutError
            args = pytest_args(arguments.command, repo_root=self.repo_root)
            if args is None:
                receipt = await self.executor.run(
                    self.branch,
                    arguments.command,
                    timeout_s=timeout_s,
                )
            else:
                receipt = await self.executor.run_pytest(
                    self.branch,
                    args,
                    timeout_s=timeout_s,
                )
            self._record_receipt(receipt)
            combined = (receipt.stdout_tail + receipt.stderr_tail)[
                -_COMMAND_OUTPUT_CHARS:
            ]
            status = "timed out" if receipt.timed_out else f"exit {receipt.exit_code}"
            result = status + (f"\n{combined}" if combined else "")
            return _with_note(note, result), None

        arguments, note = _tool_arguments(call, _FinishArgs)
        if not self._successful_write and not self._premature_finish_refused:
            self._premature_finish_refused = True
            return _with_note(note, "nothing has been changed yet"), None
        return note, (arguments.summary, arguments.claims)


__all__ = [
    "APPEAL_INSTRUCTION",
    "SYSTEM_PROMPT",
    "TOOLS",
    "Worker",
    "WorkerBudget",
    "WorkerOutcome",
    "pytest_args",
]
