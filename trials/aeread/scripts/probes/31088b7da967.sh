#!/usr/bin/env bash
# 31088b7da967: does each of the three named scorers accept the finalizer's scoring input?
# The finalizer calls scorer(scoring_input, evidence_refs=...), with a FamilyScoringInput.
# Usage: 31088b7da967.sh REPLAY_DIR PATCH   (REPLAY_DIR holds start/ and fixed/)
set -u
docker run --rm -v "$1/start:/src:ro" -v "$1/fixed:/fixed:ro" -v "$2:/patch.diff:ro" python:3.12-slim sh -c '
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1
cat > /probe.py <<PY
import inspect, sys
import aeread_families.datacenter_development_terms.environment as terms
import aeread_families.datacenter_development.objective_measurement as objective
import aeread_families.datacenter_development.adoption_measurement as adoption
for name, module in (("terms", terms), ("objective", objective), ("adoption", adoption)):
    scorers = [c for _, c in inspect.getmembers(module, inspect.isclass)
               if c.__module__ == module.__name__ and "__call__" in c.__dict__ and "Scorer" in c.__name__]
    for cls in scorers:
        source = inspect.getsource(cls.__call__)
        print(sys.argv[1], name, cls.__name__, "takes the scoring input:", "scoring_input" in source)
PY
cp -r /src /w && cd /w && git apply /patch.diff && pip install -q -e . >/dev/null 2>&1 && python /probe.py shipped
pip uninstall -q -y aeread >/dev/null 2>&1; cp -r /fixed /f && cd /f && pip install -q -e . >/dev/null 2>&1 && python /probe.py upstream' 2>&1 | grep -E "^(shipped|upstream)|Error"
