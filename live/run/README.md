# Receipts live

Runs [Receipts](https://github.com/zeyusuntt/receipts) live on five preset tasks from its 100-task experiment, behind a judge code. The page is `src/receipts/live.py`; `live/run/build.py` copies the package and the five tasks' recorded inputs into a build context, and `live/run/deploy.sh` deploys that to Cloud Run.

The service runs with request-based billing, at most one instance and none when idle. With request-based billing an instance has CPU only while a request is open, so each run lives inside the request that started it and streams its steps back; closing the page stops the run.

Environment: `OPENAI_API_KEY` and `NEBIUS_AI_PROJECT` (Nebius Token Factory), `JUDGE_CODES` (comma-separated), `LEDGER_BUCKET` (a private Cloud Storage bucket that keeps the spend ledger, writable only by the service's own account), optionally `LIVE_CAP_DOLLARS` (default 15).
