import json

import pytest

import receipts.cost as cost_module


def test_old_cost_json_loads_with_zero_planner_cost_and_no_retries():
    old_json = json.dumps(
        {
            "models": {},
            "estimated_dollars": 0.0,
            "sandbox_seconds": 12.5,
            "pricing_is_estimate": True,
        },
    )

    assert hasattr(cost_module, "CostSummary"), "cost JSON needs a compatibility model"
    loaded = cost_module.CostSummary.model_validate_json(old_json)

    assert loaded.planner_tokens == 0
    assert loaded.planner_dollars == 0
    assert loaded.model_retries == {}


def test_token_factory_usage_sums_platform_reported_costs():
    usage = [
        {
            "seconds": 120,
            "cost": 0.0125,
            "resources": {"cpu": 0, "memory": 0, "disk": 0},
        },
        {
            "seconds": 30,
            "cost": 0.00375,
            "resources": {"cpu": 0, "memory": 0, "disk": 0},
        },
    ]

    assert cost_module.estimate_tokenfactory_sandbox_dollars(usage) == pytest.approx(
        0.01625,
    )


def test_daytona_usage_keeps_the_published_resource_estimate():
    usage = [
        {
            "seconds": 3_600,
            "resources": {"cpu": 2, "memory": 2, "disk": 5},
        },
        {
            "seconds": 1_800,
            "resources": {"cpu": 4, "memory": 8, "disk": 10},
        },
    ]

    assert cost_module.estimate_daytona_sandbox_dollars(usage) == pytest.approx(
        0.29907,
    )
