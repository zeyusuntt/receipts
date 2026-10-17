#!/usr/bin/env bash
# Run AERead's full tests/ suite on one variant of one task and write JUnit XML. This is a check
# made after the run, outside Receipts, to see what the narrower regression suite missed.
# Usage: fullsuite.sh WORK RECEIPTS_REPO REPLAYS TASK_ID shipped|upstream [RUN_SUFFIX]
#   shipped   the start state with the shipped patch of trials/aeread/runs/<id><suffix> applied
#   upstream  the tree at the upstream fix
set -uo pipefail
WORK="$1"; REPO="$2"; REPLAYS="$3"; T="$4"; V="$5"; SUFFIX="${6:-}"
OUT="$WORK/fullsuite"; mkdir -p "$OUT"
NAME="$T$SUFFIX-$V"
W="$WORK/$REPLAYS/aeread-$T"
if [ "$V" = "shipped" ]; then
  last=$(ls "$REPO/trials/aeread/runs/$T$SUFFIX/attempts" | sort -n | tail -1)
  patch="$REPO/trials/aeread/runs/$T$SUFFIX/attempts/$last/filtered.diff"
  src="$W/start"; mount_patch=(-v "$patch:/patch.diff:ro")
  prep="cp -r /src /w && cd /w && git apply --whitespace=nowarn /patch.diff"
else
  src="$W/fixed"; mount_patch=()
  prep="cp -r /src /w && cd /w"
fi
docker run --rm -v "$src:/src:ro" ${mount_patch[@]+"${mount_patch[@]}"} -v "$OUT:/out" python:3.12-slim sh -c "
  apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1;
  $prep || { echo APPLY_FAILED > /out/$NAME.status; exit 0; };
  pip install -q -e '.[dev]' > /tmp/pip.log 2>&1 || { echo INSTALL_FAILED > /out/$NAME.status; exit 0; };
  timeout 3600 python -m pytest -q -p no:cacheprovider --continue-on-collection-errors tests --junitxml=/out/$NAME.xml > /out/$NAME.log 2>&1;
  echo exit \$? > /out/$NAME.status"
echo "$NAME $(cat "$OUT/$NAME.status" 2>/dev/null)"
