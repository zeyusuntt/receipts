#!/usr/bin/env bash
# 43670c88be2c: does execute_campaign still reach the canary after run_canary's signature change?
# The probe stubs the bridge and the single provider probe, so no network call is made.
# Usage: 43670c88be2c.sh REPLAY_DIR PATCH   (REPLAY_DIR holds start/ and fixed/)
set -u
docker run --rm -v "$1/start:/src:ro" -v "$1/fixed:/fixed:ro" -v "$2:/patch.diff:ro" python:3.12-slim sh -c '
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1
cat > /probe.py <<PY
import asyncio, sys, tempfile
from pathlib import Path
import aeread_families.econevals.campaign as c
c.EconevalsBridge = lambda **kw: object()
c.discover_bridge_python = lambda: "python"
async def rejected(**kw):
    return {"status": "rejected", "failure_type": "probe", "failure_condition": "auth", "cost_usd": 0.0,
            "plan_sha256": kw.get("plan_sha256"), "request_sha256": "x"}
c._probe_canary = rejected
try:
    asyncio.run(c.execute_campaign(run_root=Path(tempfile.mkdtemp())))
except Exception as e:
    print(sys.argv[1], "->", type(e).__name__, str(e)[:100])
PY
cp -r /src /w && cd /w && git apply /patch.diff && pip install -q -e . >/dev/null 2>&1 && python /probe.py shipped
pip uninstall -q -y aeread >/dev/null 2>&1; cp -r /fixed /f && cd /f && pip install -q -e . >/dev/null 2>&1 && python /probe.py upstream' 2>&1 | grep -E "^(shipped|upstream)"
