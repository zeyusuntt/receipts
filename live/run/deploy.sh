#!/usr/bin/env bash
# Deploys the live judge page to Cloud Run. Run it from the repository root after `gcloud auth login`:
#
#   JUDGE_CODES=code-1,code-2 bash live/run/deploy.sh PROJECT_ID [REGION]
#
# It enables the APIs it needs, lets source deploys build, and creates a runtime service account
# with no project roles and a private bucket for the spend ledger that only that account may write.
# Then it builds the page from this checkout and deploys it with request-based billing (CPU only while a request is open),
# at most one instance and none when idle. OPENAI_API_KEY and NEBIUS_AI_PROJECT come from .env
# through a temporary file and are never printed. Last, it adds a $5 budget alert on the project.
# Running it again redeploys from the checkout; anything that already exists is kept.
set -euo pipefail

PROJECT_ID=${1:?usage: JUDGE_CODES=code-1,code-2 bash live/run/deploy.sh PROJECT_ID [REGION]}
REGION=${2:-us-central1}
: "${JUDGE_CODES:?set JUDGE_CODES to the comma-separated judge codes}"
PYTHON=${PYTHON:-.venv/bin/python}
SERVICE=receipts-live
RUNTIME=receipts-live-runtime
RUNTIME_SA="$RUNTIME@$PROJECT_ID.iam.gserviceaccount.com"
NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
BUCKET="receipts-live-ledger-$NUMBER"
URL="https://$SERVICE-$NUMBER.$REGION.run.app"

# A new service account takes a few seconds to become visible to IAM; retry the binding instead of failing.
retry() {
  for attempt in 1 2 3 4 5 6; do
    "$@" >/dev/null && return 0
    echo "  retrying in 10s ($attempt/6)"
    sleep 10
  done
  "$@" >/dev/null
}

echo "Enabling APIs (a minute the first time)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  storage.googleapis.com --project "$PROJECT_ID"

# A source deploy builds as the Compute Engine default account, which needs Cloud Run Builder.
retry gcloud projects add-iam-policy-binding "$PROJECT_ID" --condition None --role roles/run.builder \
  --member "serviceAccount:$NUMBER-compute@developer.gserviceaccount.com"

gcloud iam service-accounts describe "$RUNTIME_SA" --project "$PROJECT_ID" >/dev/null 2>&1 ||
  gcloud iam service-accounts create "$RUNTIME" --project "$PROJECT_ID" --display-name "Receipts live page"

gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 ||
  gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT_ID" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member "serviceAccount:$RUNTIME_SA" --role roles/storage.objectUser

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
"$PYTHON" live/run/build.py "$WORK/context"
# The same .env parser the CLI uses; the file it writes is removed on exit.
JUDGE_CODES="$JUDGE_CODES" LEDGER_BUCKET="$BUCKET" "$PYTHON" - "$WORK/env.json" <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, "src")
from receipts.llm import _parse_dotenv

dotenv = _parse_dotenv(Path(".env"))
missing = [key for key in ("OPENAI_API_KEY", "NEBIUS_AI_PROJECT") if not dotenv.get(key)]
if missing:
    sys.exit(f".env has no {' or '.join(missing)}")
keys = ("OPENAI_API_KEY", "NEBIUS_AI_PROJECT", "OPENAI_BASE_URL", "NEMOTRON_MODEL")
values = {key: dotenv[key] for key in keys if dotenv.get(key)}
values.update(JUDGE_CODES=os.environ["JUDGE_CODES"], LEDGER_BUCKET=os.environ["LEDGER_BUCKET"])
Path(sys.argv[1]).write_text(json.dumps(values))
os.chmod(sys.argv[1], 0o600)
PY

echo "Building and deploying $SERVICE (a few minutes)"
gcloud run deploy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --source "$WORK/context" \
  --allow-unauthenticated --service-account "$RUNTIME_SA" --env-vars-file "$WORK/env.json" \
  --cpu-throttling --min-instances 0 --max-instances 1 --cpu 1 --memory 1Gi \
  --concurrency 20 --timeout 3600 --quiet

# Alerts only (a budget never stops spending); it covers the whole project.
BILLING=$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingAccountName)' 2>/dev/null || true)
BILLING=${BILLING#billingAccounts/}
if [ -n "$BILLING" ] && gcloud services enable billingbudgets.googleapis.com --project "$PROJECT_ID"; then
  gcloud billing budgets list --billing-account "$BILLING" --billing-project "$PROJECT_ID" \
    --format='value(displayName)' 2>/dev/null | grep -qx "$SERVICE" ||
    gcloud billing budgets create --billing-account "$BILLING" --billing-project "$PROJECT_ID" \
      --display-name "$SERVICE" --budget-amount 5USD --filter-projects "projects/$PROJECT_ID" \
      --threshold-rule percent=0.5 --threshold-rule percent=1.0 ||
    echo "No budget alert made; add one in the console under Billing > Budgets & alerts."
fi

echo "Checking $URL/health"
for attempt in 1 2 3 4 5 6; do
  curl -fsS --max-time 30 "$URL/health" && echo && exit 0
  sleep 10
done
echo "$URL/health did not answer yet; open $URL in a minute." >&2
