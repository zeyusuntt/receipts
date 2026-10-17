#!/usr/bin/env bash
# 9b37cc341a5d: is an integer tenant key that is not a tenant ignored?
# The issue: a key that is not a tenant should not stop an independent valid bid from winning.
# Usage: 9b37cc341a5d.sh REPLAY_DIR PATCH   (REPLAY_DIR holds start/ and fixed/)
set -u
docker run --rm -v "$1/start:/src:ro" -v "$1/fixed:/fixed:ro" -v "$2:/patch.diff:ro" python:3.12-slim sh -c '
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1
cat > /probe.py <<PY
import math, sys
from aeread import housing_env as hz
world = hz.make_bid_world(num_tenants=2, num_listings=2, seed=0)
valid = math.nextafter(world.ask[0], math.inf)
for bids in ({99: (0, valid)}, {99: (0, valid + 1000), 0: (0, valid)}, {-1: (0, valid + 1000), 0: (0, valid)}):
    try:
        print(sys.argv[1], bids.keys(), "->", hz.resolve_bids(world, bids).pairs)
    except Exception as e:
        print(sys.argv[1], bids.keys(), "-> error", type(e).__name__)
PY
cp -r /src /w && cd /w && git apply /patch.diff && pip install -q -e . >/dev/null 2>&1 && python /probe.py shipped
pip uninstall -q -y aeread >/dev/null 2>&1; cp -r /fixed /f && cd /f && pip install -q -e . >/dev/null 2>&1 && python /probe.py upstream' 2>&1 | grep -E "^(shipped|upstream)"
