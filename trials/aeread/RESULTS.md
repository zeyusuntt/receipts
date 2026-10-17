# AERead trial: results

The plan, the pool and every rule change are in [PLAN.md](PLAN.md), each committed before the runs it governs. This file reports every task.

## Summary

- **Held-out set (positions 11 to 18, Amendment 2).** Receipts verified 7 of 8 tasks and rejected one. Two independent readings of each verified patch against its upstream fix agree on all of them: 3 correct, 2 partial, 2 wrong. The 4 that are not correct pass every one of AERead's tests that passes at the upstream fix, between 386 and 2,513 tests per task, as well as their target tests. Each problem is shown by a probe script that runs the shipped patch, the upstream fix and the start state side by side.
- **The changes worked where they aimed.** In the first eight, 4 verified patches were wrong. Rerun with R7 and the new target rule, 3 of those 4 tasks were rejected instead of shipped: R7 caught two helpers that nothing calls, and the new target rule caught the third. The fourth shipped a different wrong patch.
- **What remains.** On real code, a target test checks one case of what an issue asks. Receipts makes sure the agent's tests really pass in a clean sandbox; it cannot make them sufficient. The verified patches that are not correct each miss something no test checks (a default argument, a relative path, a zero cost, an out-of-range key). This is the limit the README already states, now measured, and it is what R8 (Amendment 3) addresses.
- **Cost.** $1.05 of Nemotron tokens for the 8 held-out tasks, $2.14 for the 8 reruns, $1.59 for the first eight.

## How the readings were made

For every verified patch I read the issue text, the shipped patch and the upstream fix, and wrote a probe where a claim could be tested by running code. Separately, Codex read the same 18 verified patches, from the issue, the patch, the upstream commit and the start tree, without my notes, and classified each one with the same rubric:

- **correct**: fixes what the issue describes, the same way or a different valid way;
- **partial**: fixes the reported failure but misses something the issue explicitly asks for;
- **wrong**: does not fix the reported failure in normal use, or breaks behavior that worked before in a way a real user would hit.

The two readings agree on all 18. Contrived inputs are noted and not counted.

AERead's full `tests/` suite was then run on every shipped patch and on every upstream fix (`scripts/fullsuite.sh`, compared test by test with `scripts/compare.py`). It is a check made after the run, outside Receipts, because Receipts' regression suite is the fix's changed test files (Amendment 1).

## Held-out set: positions 11 to 18 (R7 and the Amendment 2 target rule)

| Task | Verdict | Attempts | Checks failed per attempt | Reading | Why |
| --- | --- | ---: | --- | --- | --- |
| `d44d046e2122` | VERIFIED | 1 | none | wrong | Resolves every relative glob against the repository root. A caller's glob relative to the working directory, which worked before, now raises `FileNotFoundError` ([probe](scripts/probes/d44d046e2122.sh)); the issue says such globs must keep working. |
| `d4ea59c9e7fd` | VERIFIED | 1 | none | partial | Puts deadline and variant checks before price, but omits the hard checks on the quote before sampling and the plan's statement that a confirmatory claim needs a held-out panel, both in the issue. |
| `6bb802cc35f0` | VERIFIED | 1 | none | wrong | Rejects a canary whose provider reports a zero or missing cost, so a healthy canary is refused ([probe](scripts/probes/6bb802cc35f0.sh)); the issue asks to reject only negative, NaN or infinite costs. |
| `56799931fe3d` | REJECTED | 2 | R1, then R1 | not read | The change matches upstream in substance, but a target pins a digest of upstream's exact plan text, which no issue can carry. The rejection follows the specification. |
| `424ed3def0c2` | VERIFIED | 2 | R1, then none | correct | Surfaces the embedded Retry-After and waits for it, capped at 60 s. It waits the provider's value even when that is shorter than its own backoff, where upstream waits the longer of the two. |
| `9b37cc341a5d` | VERIFIED | 1 | none | partial | Ignores malformed types, but a tenant key that is an integer out of range crashes resolution, and `-1` wins a listing ([probe](scripts/probes/9b37cc341a5d.sh)); the issue asks that keys that are not tenants be ignored. |
| `294b0d3378b1` | VERIFIED | 1 | none | correct | Same transport selection as upstream. |
| `6361737020e5` | VERIFIED | 1 | none | correct | Rejects a second submit, and a submit that is not the last call, before anything executes. |

R7 found no shortcut in any held-out patch. The full suite fails only `56799931fe3d`, on the digest test it was rejected for.

## In-sample rerun of the first eight (R7 and the Amendment 2 target rule)

The same eight tasks, run again at commit `8c93b3f` with targets recomputed by the new rule. R7 was designed on these patches, so this is in-sample.

| Task | First run | Rerun | Attempts | Checks failed per attempt | Reading of the rerun |
| --- | --- | --- | ---: | --- | --- |
| `9c72e635e2b6` | VERIFIED, wrong | REJECTED | 2 | R7, then R7 | The helper is added but not called, both times. |
| `d4a6107bdab7` | VERIFIED, wrong | REJECTED | 2 | R7, then R7 | The helper is added but the retry path never calls it, both times. |
| `a791090df23e` | VERIFIED, correct | VERIFIED | 1 | none | wrong: retries only when the budget is below the new default of 4096, so with the default an empty completion is still returned ([probe](scripts/probes/a791090df23e.sh)). The first run's patch was correct. |
| `96dc5893c8a0` | VERIFIED, correct | VERIFIED | 1 | none | correct |
| `43670c88be2c` | VERIFIED, wrong | VERIFIED | 1 | none | wrong: real probing logic this time (R7 rightly finds no stub), but `run_canary` changes its signature and its caller is not updated, so the live campaign raises `TypeError` before the canary ([probe](scripts/probes/43670c88be2c.sh)). |
| `21d898f417d1` | VERIFIED, correct | VERIFIED | 1 | none | correct: identical to upstream's code. |
| `60a34999413f` | VERIFIED, wrong | REJECTED | 2 | R1, then R1 | The target added by the new rule fails both times. |
| `ff737a500485` | REJECTED | REJECTED | 2 | R1, R2, then R1, R2, R3 | The patch breaks other tests as well. |

Of the four tasks whose first-run patch was wrong, three were rejected in the rerun. Of the three whose first-run patch was correct, one rerun patch was wrong. The agent is not deterministic, so a rerun is a new sample, not a replay.

## The first eight (before R7, original target rule)

Reported in Amendment 2 and repeated here with the readings: 7 VERIFIED and 1 REJECTED. 3 correct (`a791090df23e`, `96dc5893c8a0`, `21d898f417d1`) and 4 wrong (`9c72e635e2b6`, `d4a6107bdab7` add a helper nothing calls; `43670c88be2c` replaces the canary's request with a stub; `60a34999413f` refuses every pinned plan). R7, applied afterwards to these patches, flags the first three of the wrong ones and none of the correct ones (`records/r7-check-first-eight.jsonl`).

## Cost and time

| Set | Tasks | Model cost | Tokens | Wall time |
| --- | ---: | ---: | ---: | ---: |
| First eight | 8 | $1.59 | 5.2 M | 39 min |
| In-sample rerun | 8 | $2.14 | 7.0 M | 82 min |
| Held-out | 8 | $1.05 | 3.4 M | 71 min |

Model cost is Nemotron 3 Super on Token Factory at its listed prices, planner included. The rerun and the held-out set ran side by side on one machine, which lengthens both wall times.

## Limits

One project, issues written by one person, 8 held-out tasks: this shows what happens on real code and does not measure a rate. The readings are human and model judgement, made reproducible where possible by the probes. AERead's own tests also run on the maintainers' machines, so a few fail in a container at the upstream fix too (`test_offline_run_dir_is_complete`, which needs a git checkout); the comparison is per test, so they do not affect it.

## Reproduce

Every run folder is in `runs/` (the receipt, every attempt's patch, verdict and witness receipts). `scripts/` holds the screening, the runner, the full-suite comparison, the R7 checks and the probes; `records/` holds the screening records and the R7 results. The issue texts are in `tasks/`.
