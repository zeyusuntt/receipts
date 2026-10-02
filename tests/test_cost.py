import json

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
