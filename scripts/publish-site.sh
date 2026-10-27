#!/bin/bash
# Build the receipt site from the committed v2 records and stage it as the gh-pages branch
# for GitHub Pages. It never pushes: it prints the push command for the owner to run.
#
# Usage, from anywhere in the repository: scripts/publish-site.sh
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
OUT=$(mktemp -d)
PYTHONPATH=src .venv/bin/python -m receipts.cli site pilot/v2-P pilot/v2-arm-lightning \
  --out "$OUT/site" --title "Receipts" --featured pyfilesystem__pyfilesystem2-462 \
  --live-url https://receipts-live-683278413320.us-central1.run.app/
if grep -rlq "$HOME" "$OUT/site"; then
  echo "refusing to publish: the built site contains $HOME" >&2
  exit 1
fi
touch "$OUT/site/.nojekyll"

STAGE=$(mktemp -d)
git worktree add --detach "$STAGE" >/dev/null
cd "$STAGE"
git checkout -q --orphan gh-pages
git rm -rfq . >/dev/null 2>&1 || true
cp -R "$OUT/site/." .
git add -A
git -c user.name="$(git -C "$ROOT" config user.name)" -c user.email="$(git -C "$ROOT" config user.email)" \
  commit -q -m "Publish the receipt site from $(git -C "$ROOT" rev-parse --short HEAD)"
echo "gh-pages staged in $STAGE ($(find . -type f | wc -l | tr -d ' ') files)."
echo "To publish: git -C $STAGE push -f origin gh-pages"
