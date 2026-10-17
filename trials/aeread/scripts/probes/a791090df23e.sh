#!/usr/bin/env bash
# a791090df23e: with the default budget, is an empty completion retried?
# The target test passes max_tokens=1200; the example client uses the default.
# Usage: a791090df23e.sh REPLAY_DIR PATCH   (REPLAY_DIR holds start/ and fixed/)
set -u
docker run --rm -v "$1/start:/src:ro" -v "$1/fixed:/fixed:ro" -v "$2:/patch.diff:ro" python:3.12-slim sh -c '
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1
cat > /probe.py <<PY
import sys
from aeread.integrations.everos_memory import build_openrouter_llm_fn
calls = []
class Msg: content = ""
class Choice:
    def __init__(self, text): self.message = Msg(); self.message.content = text
class Resp:
    usage = None
    def __init__(self, text): self.choices = [Choice(text)]
class Completions:
    def create(self, **kw):
        calls.append(kw["max_tokens"])
        return Resp("" if len(calls) == 1 else "spoken")
class Chat: completions = Completions()
class Client: chat = Chat()
fn = build_openrouter_llm_fn("some/model", client=Client())
print(sys.argv[1], "default budget: returned", repr(fn("prompt")), "budgets", calls)
PY
cp -r /src /w && cd /w && git apply /patch.diff && pip install -q -e . >/dev/null 2>&1 && python /probe.py shipped
pip uninstall -q -y aeread >/dev/null 2>&1; cp -r /fixed /f && cd /f && pip install -q -e . >/dev/null 2>&1 && python /probe.py upstream' 2>&1 | grep -E "^(shipped|upstream)"
