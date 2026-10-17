#!/usr/bin/env bash
# d44d046e2122: does an explicit glob relative to the working directory still work?
# The issue says a glob the caller passes explicitly should keep working as it does now.
# Usage: d44d046e2122.sh REPLAY_DIR PATCH   (REPLAY_DIR holds start/ and fixed/)
set -u
docker run --rm -v "$1/start:/src:ro" -v "$1/fixed:/fixed:ro" -v "$2:/patch.diff:ro" python:3.12-slim sh -c '
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1
mkdir -p /elsewhere/mycases && echo "{}" > /elsewhere/mycases/case07_x.json
probe() { cd /elsewhere && python -c "
from aeread.integrations import rllm_dataset as r
try:
    print(\"$1 relative explicit glob:\", [x[\"uid\"] for x in r.build_rows(\"mycases/case0*.json\", seeds=(1,))])
except Exception as e:
    print(\"$1 relative explicit glob: error\", type(e).__name__)
try:
    print(\"$1 default from elsewhere:\", len(r.build_rows()))
except Exception as e:
    print(\"$1 default from elsewhere: error\", type(e).__name__)
"; }
cp -r /src /w && cd /w && pip install -q -e . >/dev/null 2>&1 && probe start
cd /w && git apply /patch.diff && probe shipped
pip uninstall -q -y aeread >/dev/null 2>&1; cp -r /fixed /f && cd /f && pip install -q -e . >/dev/null 2>&1 && probe upstream' 2>&1 | grep -E "^(start|shipped|upstream)"
