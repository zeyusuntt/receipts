#!/usr/bin/env bash
# 6bb802cc35f0: is a healthy canary still admitted when the provider reports no cost, or zero?
# ArenaChatClient returns cost_usd=None when the provider's usage has no cost.
# Usage: 6bb802cc35f0.sh REPLAY_DIR PATCH   (REPLAY_DIR holds start/ and fixed/)
set -u
docker run --rm -v "$1/start:/src:ro" -v "$1/fixed:/fixed:ro" -v "$2:/patch.diff:ro" python:3.12-slim sh -c '
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1
cat > /probe.py <<PY
import asyncio, sys, tempfile
from pathlib import Path
from types import SimpleNamespace
from aeread.shared_runner.run.adapter_campaign import run_adapter_canary
class Client:
    def __init__(self, cost): self.cost = cost
    async def complete(self, request):
        # The same fields as the fake client in tests/test_adapter_campaign.py.
        return SimpleNamespace(output_text="{\"status\":\"ok\"}", cost_usd=self.cost, resolved_model="glm-5p2",
                               finish_reason="stop", input_tokens=20, cached_input_tokens=0, output_tokens=5)
for cost in (None, 0.0, 0.001):
    path = Path(tempfile.mkdtemp()) / "c.json"
    try:
        record = asyncio.run(run_adapter_canary(family_id="steer", checkpoint_path=path, client=Client(cost)))
        print(sys.argv[1], "cost", cost, "->", record.get("status"), record.get("failure_condition"))
    except Exception as e:
        print(sys.argv[1], "cost", cost, "-> error", type(e).__name__, str(e)[:80])
PY
cp -r /src /w && cd /w && git apply /patch.diff && pip install -q -e . >/dev/null 2>&1 && python /probe.py shipped
pip uninstall -q -y aeread >/dev/null 2>&1; cp -r /fixed /f && cd /f && pip install -q -e . >/dev/null 2>&1 && python /probe.py upstream' 2>&1 | grep -E "^(shipped|upstream)"
