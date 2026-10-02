"""Async model boundary for Token Factory and offline tests."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from receipts.cost import CostMeter, SUPER_MODEL, TokenUsage


DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
_JSON_RETRIES = 2
_API_RETRIES = 3
_T = TypeVar("_T", bound=BaseModel)


class ModelConfig(BaseModel):
    model: str
    base_url: str
    temperature: float = 1.0
    top_p: float = 0.95
    thinking: bool = False
    max_tokens: int | None = Field(default=None, gt=0)


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]
    id: str


class AssistantTurn(BaseModel):
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str | None = None
    retries: dict[str, int] = Field(default_factory=dict)


def _metadata_text(source: object, attribute: str) -> str:
    """Logging metadata must never raise, so a missing id or name becomes ''."""

    value = getattr(source, attribute, None)
    return value if isinstance(value, str) else ""


class ToolCallMetadata(BaseModel):
    id: str
    name: str
    malformed_args: bool


class MalformedToolCall(AssistantTurn):
    """A model turn whose tool arguments were not a JSON object."""

    tool_name: str
    tool_call_id: str
    raw_arguments: str
    error: str
    raw_tool_calls: list[ToolCallMetadata] = Field(default_factory=list)


class ModelClient(Protocol):
    async def complete_json(
        self,
        system: str,
        user: str,
        schema: type[_T],
    ) -> _T: ...

    async def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> AssistantTurn: ...


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _settings(
    env_path: Path,
    environ: Mapping[str, str] | None,
) -> dict[str, str]:
    values = dict(os.environ if environ is None else environ)
    values.update(_parse_dotenv(env_path))
    return values


def load_config(
    env_path: Path | str = Path(".env"),
    environ: Mapping[str, str] | None = None,
) -> ModelConfig:
    """Load public model settings, preferring repository .env values."""

    values = _settings(Path(env_path), environ)
    return ModelConfig(
        model=values.get("NEMOTRON_MODEL", SUPER_MODEL),
        base_url=values.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
    )


class TokenFactoryClient:
    def __init__(
        self,
        config: ModelConfig,
        *,
        client: Any | None = None,
        meter: CostMeter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        env_path: Path | str = Path(".env"),
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self._meter = meter
        self._sleep = sleep
        if client is None:
            values = _settings(Path(env_path), environ)
            api_key = values.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY is required")
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=config.base_url,
                timeout=180,
                max_retries=0,
            )
        self._client = client

    def _request_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "extra_body": {
                "chat_template_kwargs": {
                    "enable_thinking": self.config.thinking,
                },
            },
        }
        if self.config.max_tokens is not None:
            options["max_tokens"] = self.config.max_tokens
        return options

    @staticmethod
    def _retry_kind(exc: Exception) -> str | None:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return "429"
        if isinstance(status_code, int) and 500 <= status_code <= 599:
            return "5xx"
        if isinstance(exc, (APITimeoutError, TimeoutError)):
            return "timeout"
        if isinstance(exc, (APIConnectionError, ConnectionError)):
            return "connection"
        return None

    async def _create(self, **kwargs: Any) -> tuple[Any, dict[str, int]]:
        retries: dict[str, int] = {}
        for retry in range(_API_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                return response, retries
            except Exception as exc:
                kind = self._retry_kind(exc)
                if kind is None or retry == _API_RETRIES:
                    raise
                retries[kind] = retries.get(kind, 0) + 1
                await self._sleep(float(2**retry))
        raise AssertionError("unreachable")

    def _record_usage(self, response: Any) -> TokenUsage:
        raw_usage = getattr(response, "usage", None)
        details = getattr(raw_usage, "completion_tokens_details", None)
        usage = TokenUsage(
            prompt=getattr(raw_usage, "prompt_tokens", 0) or 0,
            completion=getattr(raw_usage, "completion_tokens", 0) or 0,
            reasoning=getattr(details, "reasoning_tokens", 0) or 0,
        )
        if self._meter is not None:
            self._meter.add_usage(self.config.model, usage)
        return usage

    async def complete_json(
        self,
        system: str,
        user: str,
        schema: type[_T],
    ) -> _T:
        schema_dict = schema.model_json_schema()
        use_strict = True
        last_error: str | None = None
        validation_attempt = 0
        call_retries: dict[str, int] = {}

        while True:
            current_system = system
            current_user = user
            if last_error is not None:
                current_user = (
                    f"{user}\n\nYour previous answer did not match the required format:\n"
                    f"{last_error}\n\nFix it and answer again. Respond with JSON only."
                )

            if use_strict:
                response_format: dict[str, Any] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": schema_dict,
                        "strict": True,
                    },
                }
            else:
                response_format = {"type": "json_object"}
                current_system = (
                    f"{system}\n\nRespond with a single JSON object matching this schema:\n"
                    f"{json.dumps(schema_dict, sort_keys=True)}"
                )

            try:
                response, retries = await self._create(
                    **self._request_options(),
                    messages=[
                        {"role": "system", "content": current_system},
                        {"role": "user", "content": current_user},
                    ],
                    response_format=response_format,
                )
                for kind, count in retries.items():
                    call_retries[kind] = call_retries.get(kind, 0) + count
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                if use_strict and status_code in {400, 422}:
                    use_strict = False
                    continue
                raise

            usage = self._record_usage(response)
            raw_finish_reason = getattr(response.choices[0], "finish_reason", None)
            finish_reason = (
                raw_finish_reason if isinstance(raw_finish_reason, str) else None
            )
            content = response.choices[0].message.content or "{}"
            try:
                result = schema.model_validate_json(content)
                metadata: dict[str, Any] = {}
                if "usage" in schema.model_fields:
                    metadata["usage"] = usage
                if "finish_reason" in schema.model_fields:
                    metadata["finish_reason"] = finish_reason
                if call_retries:
                    metadata["retries"] = dict(sorted(call_retries.items()))
                return result.model_copy(update=metadata) if metadata else result
            except ValidationError as exc:
                last_error = str(exc)
                validation_attempt += 1
                if validation_attempt > _JSON_RETRIES:
                    raise RuntimeError(
                        f"complete_json: {self.config.model} could not produce a valid "
                        f"{schema.__name__} after {_JSON_RETRIES + 1} attempt(s): "
                        f"{last_error}"
                    ) from exc

    async def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> AssistantTurn:
        response, retries = await self._create(
            **self._request_options(),
            messages=messages,
            tools=tools,
        )
        usage = self._record_usage(response)
        raw_finish_reason = getattr(response.choices[0], "finish_reason", None)
        finish_reason = raw_finish_reason if isinstance(raw_finish_reason, str) else None
        message = response.choices[0].message
        raw_calls = list(message.tool_calls or [])
        parsed_calls: list[ToolCall] = []
        raw_tool_calls: list[ToolCallMetadata] = []
        first_malformed: tuple[str, str, str, str] | None = None

        for raw_call in raw_calls:
            raw_arguments = raw_call.function.arguments
            try:
                arguments = (
                    raw_arguments
                    if isinstance(raw_arguments, dict)
                    else json.loads(raw_arguments)
                )
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be a JSON object")
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raw_tool_calls.append(
                    ToolCallMetadata(
                        id=_metadata_text(raw_call, "id"),
                        name=_metadata_text(raw_call.function, "name"),
                        malformed_args=True,
                    ),
                )
                if first_malformed is None:
                    first_malformed = (
                        raw_call.function.name,
                        raw_call.id,
                        str(raw_arguments),
                        str(exc),
                    )
                continue
            raw_tool_calls.append(
                ToolCallMetadata(
                    id=_metadata_text(raw_call, "id"),
                    name=_metadata_text(raw_call.function, "name"),
                    malformed_args=False,
                ),
            )
            if first_malformed is None:
                parsed_calls.append(
                    ToolCall(
                        name=raw_call.function.name,
                        arguments=arguments,
                        id=raw_call.id,
                    ),
                )

        if first_malformed is not None:
            tool_name, tool_call_id, raw_arguments, error = first_malformed
            return MalformedToolCall(
                content=message.content,
                tool_calls=parsed_calls,
                usage=usage,
                finish_reason=finish_reason,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                raw_arguments=raw_arguments,
                error=error,
                raw_tool_calls=raw_tool_calls,
                retries=retries,
            )

        return AssistantTurn(
            content=message.content,
            tool_calls=parsed_calls,
            usage=usage,
            finish_reason=finish_reason,
            retries=retries,
        )


class FakeModel:
    """An offline scripted ModelClient that records every request."""

    def __init__(
        self,
        *,
        turns: Iterable[AssistantTurn | Mapping[str, Any]] = (),
        json_objects: Iterable[BaseModel | Mapping[str, Any] | str] = (),
    ) -> None:
        self._turns = [
            turn if isinstance(turn, AssistantTurn) else AssistantTurn.model_validate(turn)
            for turn in turns
        ]
        self._json_objects = list(json_objects)
        self.requests: list[dict[str, Any]] = []

    async def complete_json(
        self,
        system: str,
        user: str,
        schema: type[_T],
    ) -> _T:
        self.requests.append(
            {
                "kind": "complete_json",
                "system": system,
                "user": user,
                "schema": schema,
            },
        )
        if not self._json_objects:
            raise AssertionError("FakeModel has no scripted JSON object left")
        scripted = self._json_objects.pop(0)
        if isinstance(scripted, str):
            return schema.model_validate_json(scripted)
        if isinstance(scripted, BaseModel):
            return schema.model_validate(scripted.model_dump())
        return schema.model_validate(scripted)

    async def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> AssistantTurn:
        self.requests.append(
            {
                "kind": "chat",
                "messages": copy.deepcopy(list(messages)),
                "tools": copy.deepcopy(list(tools)),
            },
        )
        if not self._turns:
            raise AssertionError("FakeModel has no scripted turn left")
        return self._turns.pop(0).model_copy(deep=True)
