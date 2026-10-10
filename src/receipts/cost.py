"""Token and sandbox cost accounting for a Receipts run."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


SUPER_MODEL = "nvidia/nemotron-3-super-120b-a12b"
LIGHTNING_MODEL = "nvidia/Nemotron-3_5-Lightning"
NANO_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
ULTRA_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"

TOKEN_FACTORY_PRICING_READ_DATE = "2026-10-02"
TOKEN_FACTORY_PRICING_SOURCE = (
    "GET https://api.tokenfactory.nebius.com/v1/models?verbose=true"
)

# Daytona's published per-second rates as of 2026-10-01 (daytona.io pricing).
DAYTONA_PRICING_READ_DATE = "2026-10-01"
DAYTONA_VCPU_DOLLARS_PER_HOUR = 0.0504
DAYTONA_MEMORY_GIB_DOLLARS_PER_HOUR = 0.0162
DAYTONA_DISK_GIB_DOLLARS_PER_HOUR = 0.000108
DAYTONA_INCLUDED_DISK_GIB = 5

# USD per one million tokens, from the Token Factory model listing above.
price_table: dict[str, dict[str, float | bool]] = {
    SUPER_MODEL: {
        "prompt_per_million": 0.30,
        "completion_per_million": 0.90,
        "estimated": True,
    },
    LIGHTNING_MODEL: {
        "prompt_per_million": 0.06,
        "completion_per_million": 0.24,
        "estimated": True,
    },
    NANO_MODEL: {
        "prompt_per_million": 0.06,
        "completion_per_million": 0.24,
        "estimated": True,
    },
    ULTRA_MODEL: {
        "prompt_per_million": 1.00,
        "completion_per_million": 3.00,
        "estimated": True,
    },
}


class CostSummary(BaseModel):
    """The durable cost artifact, including defaults for pre-C2b runs."""

    models: dict[str, dict[str, int | float | None]] = Field(default_factory=dict)
    estimated_dollars: float | None = None
    sandbox_seconds: float = Field(default=0, ge=0)
    pricing_is_estimate: bool = True
    planner_tokens: int = Field(default=0, ge=0)
    planner_dollars: float | None = Field(default=0, ge=0)
    model_retries: dict[str, int] = Field(default_factory=dict)


def estimate_daytona_sandbox_dollars(
    usage: Sequence[Mapping[str, Any]],
) -> float:
    """Estimate Daytona compute cost from per-sandbox lifetime records."""

    total = Decimal("0")
    for item in usage:
        resources = item["resources"]
        seconds = Decimal(str(item["seconds"]))
        cpu = Decimal(str(resources["cpu"]))
        memory = Decimal(str(resources["memory"]))
        disk = Decimal(str(resources["disk"]))
        billable_disk = max(
            Decimal("0"),
            disk - Decimal(DAYTONA_INCLUDED_DISK_GIB),
        )
        hourly = (
            cpu * Decimal(str(DAYTONA_VCPU_DOLLARS_PER_HOUR))
            + memory * Decimal(str(DAYTONA_MEMORY_GIB_DOLLARS_PER_HOUR))
            + billable_disk * Decimal(str(DAYTONA_DISK_GIB_DOLLARS_PER_HOUR))
        )
        total += seconds * hourly / Decimal(3_600)
    return float(total)


def estimate_tokenfactory_sandbox_dollars(
    usage: Sequence[Mapping[str, Any]],
) -> float:
    """Sum the per-operation cost reported by Token Factory Sandboxes."""

    total = Decimal("0")
    for item in usage:
        total += Decimal(str(item["cost"]))
    return float(total)


class TokenUsage(BaseModel):
    """The token counters reported for one model response."""

    prompt: int = Field(default=0, ge=0)
    completion: int = Field(default=0, ge=0)
    reasoning: int = Field(default=0, ge=0)


def token_count(usage: TokenUsage) -> int:
    return usage.prompt + usage.completion + usage.reasoning


def estimate_model_dollars(
    model: str,
    usage: TokenUsage,
    prices: Mapping[str, Mapping[str, float | bool]] | None = None,
) -> float | None:
    selected_prices = price_table if prices is None else prices
    price = selected_prices.get(model)
    if price is None:
        return None
    prompt_price = Decimal(str(price["prompt_per_million"]))
    completion_price = Decimal(str(price["completion_per_million"]))
    total = (
        Decimal(usage.prompt) * prompt_price
        + Decimal(usage.completion) * completion_price
    ) / Decimal(1_000_000)
    return float(total)


class CostMeter:
    """Accumulate model usage and sandbox runtime without estimating either."""

    def __init__(
        self,
        prices: dict[str, dict[str, float | bool]] | None = None,
    ) -> None:
        self._prices = prices if prices is not None else price_table
        self._usage: dict[str, TokenUsage] = {}
        self._sandbox_seconds = 0.0

    def add_usage(self, model: str, usage: TokenUsage) -> None:
        current = self._usage.get(model, TokenUsage())
        self._usage[model] = TokenUsage(
            prompt=current.prompt + usage.prompt,
            completion=current.completion + usage.completion,
            reasoning=current.reasoning + usage.reasoning,
        )

    def add_sandbox_seconds(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sandbox seconds cannot be negative")
        self._sandbox_seconds += seconds

    def summary(self) -> dict[str, Any]:
        models: dict[str, dict[str, int | float | None]] = {}
        total = Decimal("0")
        all_models_priced = True

        for model in sorted(self._usage):
            usage = self._usage[model]
            price = self._prices.get(model)
            estimated_dollars: float | None
            if price is None:
                estimated_dollars = None
                all_models_priced = False
            else:
                model_cost = Decimal(
                    str(estimate_model_dollars(model, usage, self._prices)),
                )
                total += model_cost
                estimated_dollars = float(model_cost)

            models[model] = {
                "prompt_tokens": usage.prompt,
                "completion_tokens": usage.completion,
                "reasoning_tokens": usage.reasoning,
                "estimated_dollars": estimated_dollars,
            }

        return CostSummary(
            models=models,
            estimated_dollars=float(total) if all_models_priced else None,
            sandbox_seconds=self._sandbox_seconds,
        ).model_dump(mode="json")
