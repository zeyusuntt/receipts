# nebius-hackathon

Built for: nebius-nvidia-global-ai-2026. Event research, strategy and status live in the hackathon HQ repo:
`/Users/sunzeyu/Documents/beta fund/activities/nebius-nvidia-global-ai-2026` (https://github.com/zeyusuntt/precision-medicine-pitch.git).

## Run it

    uv sync --extra dev
    uv run pytest

## Layout

    src/receipts/models.py     data models: Receipt, JunitSummary, DiffSummary, Baseline, Claims, Verdict
    src/receipts/junit.py      junit xml to JunitSummary
    src/receipts/patchscope.py unified diff to DiffSummary with file categories
    src/receipts/sandbox/      async Executor protocol, receipt sinks, the local implementation
    src/receipts/verify/       baseline runner, canonical verification, the gate
    tests/                     offline tests; tests/fixtures builds throwaway git repos
