#!/usr/bin/env bash
# Run `receipts fix --executor docker` on every included task of a screening file, one after another.
# Usage: run_tasks.sh WORK RECEIPTS_REPO SCREENING_FILE REPO_URL_PREFIX [RUN_SUFFIX]
#   WORK             the directory that holds the screening file
#   REPO_URL_PREFIX  where a git daemon serves the start states, for example
#                    git://host.docker.internal:9419 (each task is <prefix>/aeread-<id>/start)
#   RUN_SUFFIX       appended to each run folder name, for example -rerun
# The regression suite is the fix's changed test files (Amendment 1). The issue text is
# trials/aeread/tasks/<id>/issue.md and must exist before the task runs.
set -uo pipefail
set -f
WORK="$1"
REPO="$2"
SCREENING="$3"
PREFIX="$4"
SUFFIX="${5:-}"
cd "$REPO"
LIST="$WORK/run-list-$(basename "$SCREENING" .jsonl).txt"
python3 -I - "$WORK/$SCREENING" > "$LIST" <<'EOF'
import json, sys
from pathlib import Path
for line in Path(sys.argv[1]).read_text().splitlines():
    r = json.loads(line)
    if r.get("included"):
        print(r["commit"][:12], r["start_commit"], ",".join(r["test_files"]), " ".join(r["targets"]))
EOF
while read -r short start suite targets; do
  out="trials/aeread/runs/$short$SUFFIX"
  issue="trials/aeread/tasks/$short/issue.md"
  if [ -f "$out/receipt.md" ]; then echo "== $short$SUFFIX already has a receipt, skipped"; continue; fi
  if [ ! -f "$issue" ]; then echo "== $short has no issue file, skipped"; continue; fi
  test_args=()
  for t in $targets; do test_args+=(--test "$t"); done
  echo "== $short$SUFFIX start $(date '+%F %T')"
  begin=$(date +%s)
  env -u VIRTUAL_ENV uv run receipts fix \
    --repo "$PREFIX/aeread-$short/start" \
    --commit "$start" \
    --install "pip install -e '.[dev]'" \
    --suite "${suite//,/ }" \
    "${test_args[@]}" \
    --issue-file "$issue" \
    --executor docker \
    --out "$out" > "$WORK/run-$short$SUFFIX.log" 2>&1
  code=$?
  echo "== $short$SUFFIX exit $code after $(( $(date +%s) - begin ))s"
  tail -12 "$WORK/run-$short$SUFFIX.log"
done < "$LIST"
echo "== all done $(date '+%F %T')"
