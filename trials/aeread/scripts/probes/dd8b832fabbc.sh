#!/usr/bin/env bash
# dd8b832fabbc: which recalled snippets survive the outcome-aware filter?
# The issue: drop snippets from known-failed episodes when anything better survives; when nothing
# else survives, keep them rather than recall nothing. Uses the test file's own helpers.
# Usage: dd8b832fabbc.sh REPLAY_DIR PATCH   (REPLAY_DIR holds start/ and fixed/)
set -u
docker run --rm -v "$1/start:/src:ro" -v "$1/fixed:/fixed:ro" -v "$2:/patch.diff:ro" python:3.12-slim sh -c '
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1
cat > /probe.py <<PY
import sys
sys.path.insert(0, ".")
from tests.test_everos_memory import FakeMemory, make_candidate

def recall(outcomes, hit_sessions):
    hits = {"episodes": [{"summary": f"recap {s}", "session_id": f"aeread_mem-case03-{s}"} for s in hit_sessions]}
    cand, prompts = make_candidate(FakeMemory(hits=hits))
    for session, aer in outcomes:
        cand.begin_episode(f"case03-{session}")
        cand.end_episode(f"AER={aer}")
    cand.begin_episode("case03-s9")
    cand.act("obs", "proposal")
    return [f"recap {s}" for s in hit_sessions if f"recap {s}" in prompts[0]]

print(sys.argv[1], "two good sessions (0.1, 0.2), both recalled ->", recall([("s1", 0.1), ("s2", 0.2)], ["s1", "s2"]))
print(sys.argv[1], "failed s1 and good s2, only s1 recalled ->", recall([("s1", 0.0), ("s2", 0.2)], ["s1"]))
PY
cp -r /src /w && cd /w && git apply /patch.diff && pip install -q -e ".[dev]" >/dev/null 2>&1 && python /probe.py shipped
pip uninstall -q -y aeread >/dev/null 2>&1; cp -r /fixed /f && cd /f && pip install -q -e ".[dev]" >/dev/null 2>&1 && python /probe.py upstream' 2>&1 | grep -E "^(shipped|upstream)|Error"
