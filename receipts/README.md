# Published receipts

One bundle per task of v2's primary sample P (`REPORT-v2.md`), written by `receipts export pilot/v2-P`. Each bundle is self-contained: the SWE-rebench-V2 task row, the run's model and budgets, the agent's full patch and the shipped (filtered) patch with their SHA-256 digests, and the recorded gate verdict and official grade of the final attempt.

Re-check any of them on a fresh sandbox:

```
uv sync
uv run receipts reverify receipts/pyfilesystem__pyfilesystem2-462.json
```

It verifies the digests before anything runs, rebuilds the task's original checkpoint from its public image, replays the agent's patch through the same filter and gate on a fresh witness, grades the shipped patch with SWE-rebench's official grader, and exits 0 only if every check agrees with the bundle. Docker is the default; `--executor tokenfactory` runs it on Nebius Token Factory Sandboxes (credentials in `.env`).

## Attribution

The task rows come from [nebius/SWE-rebench-V2](https://huggingface.co/datasets/nebius/SWE-rebench-V2), revision `475dd5e8703bb5fb22dd3c60b5d038b019eba1e0`, licensed CC-BY-4.0. Code in each row's test patch and in the patches comes from, or modifies, the task's own repository and is under that repository's license.
