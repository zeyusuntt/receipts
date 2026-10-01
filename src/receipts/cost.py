"""Token and sandbox cost accounting for a Receipts run."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


SUPER_MODEL = "nvidia/nemotron-3-super-120b-a12b"
NANO_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"

# USD per one million tokens. These third-party rates are estimates from the
# Token Factory spike, not prices verified against a Nebius pricing page.
price_table: dict[str, dict[str, float | bool]] = {
    SUPER_MODEL: {
        "prompt_per_million": 0.06,
        "completion_per_million": 0.24,
        "estimated": True,
    },
    NANO_MODEL: {
        "prompt_per_million": 0.06,
        "completion_per_million": 0.24,
        "estimated": True,
    },
}


class TokenUsage(BaseModel):
    """The token counters reported for one model response."""

    prompt: int = Field(default=0, ge=0)
    completion: int = Field(default=0, ge=0)
    reasoning: int = Field(default=0, ge=0)


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
                prompt_price = Decimal(str(price["prompt_per_million"]))
                completion_price = Decimal(str(price["completion_per_million"]))
                model_cost = (
                    Decimal(usage.prompt) * prompt_price
                    + Decimal(usage.completion) * completion_price
                ) / Decimal(1_000_000)
                total += model_cost
                estimated_dollars = float(model_cost)

            models[model] = {
                "prompt_tokens": usage.prompt,
                "completion_tokens": usage.completion,
                "reasoning_tokens": usage.reasoning,
                "estimated_dollars": estimated_dollars,
            }

        return {
            "models": models,
            "estimated_dollars": float(total) if all_models_priced else None,
            "sandbox_seconds": self._sandbox_seconds,
            "pricing_is_estimate": True,
        }
