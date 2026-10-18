# AERead trial: results

The plan, the pool and every rule change are in [PLAN.md](PLAN.md), each committed before the runs it governs. This file reports every task.

## Summary

- **Two held-out sets, 16 real bug fixes.** Receipts verified 13 and rejected 3. Two independent readings of each verified patch against its upstream fix, which agree on all 24 patches read in this trial, find 5 of the 13 correct, 3 partial and 5 wrong. Every one that is not correct passes its target tests, and most pass every test AERead has. Each problem is shown in the table, most by a probe script that runs the shipped patch and the upstream fix side by side.
- **What fixes it.** The false "done" on real code are patches that satisfy narrow tests. Three things caught some of them, each on its own evidence: R7 (a helper nothing calls, a stub) and a stricter target rule turned 3 of the 4 false "done" of the first eight into rejections when rerun; AERead's full test suite, which Receipts' 600-second limit keeps out of the regression check, catches 2 of the 4 in held-out set 2; and R8, two independent Nemotron reviews, flags 2 of those 4 and no correct patch.
- **R8 ships advisory, by a rule fixed in advance.** On the 66 fixes from the 100-task experiment that the official grader accepts, both reviews objected to 10, above the limit of 3. Most objections hold a patch to the wording of a SWE-rebench issue that the fix did not follow and the tests do not require. So R8 is recorded on every receipt and does not change the verdict.
- **What remains.** Receipts makes sure the agent's tests really pass in a clean sandbox; it cannot make them sufficient. That is the limit the README states, now measured on real code.
- **Cost.** $8.12 of Nemotron tokens for all 33 runs, and $0.48 for every R8 review.

## How the readings were made

For every verified patch I read the issue text, the shipped patch and the upstream fix, and wrote a probe where a claim could be tested by running code. Separately, Codex read the same 18 verified patches, from the issue, the patch, the upstream commit and the start tree, without my notes, and classified each one with the same rubric:

- **correct**: fixes what the issue describes, the same way or a different valid way;
- **partial**: fixes the reported failure but misses something the issue explicitly asks for;
- **wrong**: does not fix the reported failure in normal use, or breaks behavior that worked before in a way a real user would hit.

The two readings agree on all 18 patches of the first eight, held-out set 1 and the rerun, and on all 6 of held-out set 2. Contrived inputs are noted and not counted. Codex's readings are in `records/reading-codex-18.md` and `records/reading-codex-heldout2.md`.

AERead's full `tests/` suite was then run on every shipped patch and on every upstream fix (`scripts/fullsuite.sh`, compared test by test with `scripts/compare.py`). It is a check made after the run, outside Receipts, because Receipts' regression suite is the fix's changed test files (Amendment 1).

## Held-out set 1: positions 11 to 18 (R7 and the Amendment 2 target rule)

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

## Held-out set 2: positions 19 to 27 (Amendments 3 and 4)

R7 and the Amendment 2 target rule as before. R8 ran advisory, as the false-veto check below decided: each task ran with `--no-review` at the frozen code, and R8 (`scripts/r8_check.py`) reviewed every patch the gate passed, without changing any verdict. Position 20 was excluded at screening (no test fails at the start state).

| Task | Verdict | Attempts | Checks failed per attempt | R8, advisory | Reading | Why |
| --- | --- | ---: | --- | --- | --- | --- |
| `0b9f4a28e3a7` | REJECTED | 2 | R1, R4, then R1, R4 | | not read | A target pins a digest of upstream's exact plan text, and the agent edited a protected test file. |
| `1c080bd0c1e1` | VERIFIED | 1 | none | both object | wrong | Fixes one of the four gaps its issue names (only a 404 is promoted, proof keyed by route); multi-round proof, the durable condition and the Arena length path are untouched. The screening defect of Amendment 4 hid the tests for those gaps; AERead's full suite fails three of them against this patch, and the rerun with corrected targets was rejected (below). |
| `6e267dd04d15` | VERIFIED | 1 | none | no objection | correct | Identical to upstream. |
| `83f5619e4c69` | VERIFIED | 1 | none | both object | partial | Caps growth at eight times the declared budget, but omits the issue's second cap at half the provider's context window (upstream's version of that cap reads a field nothing sets, so in practice it does not apply either). |
| `9dac975e6ed0` | VERIFIED | 1 | none | no objection | correct | Same behavior as upstream. |
| `dd8b832fabbc` | VERIFIED | 1 | none | no objection | wrong | Drops recalled memories from every session below the best one, not only failed ones, and recalls nothing where the issue asks it to keep failed snippets as a fallback ([probe](scripts/probes/dd8b832fabbc.sh)). |
| `31088b7da967` | VERIFIED | 1 | none | no objection | wrong | Migrates two of the three scorers the issue names; the terms scorer, whose error the issue quotes, still rejects the finalizer's input ([probe](scripts/probes/31088b7da967.sh)). AERead's full suite fails 8 terms live-cell tests against it, in test files the fix did not change, which Receipts' regression suite (the changed test files, Amendment 1) does not run. |
| `11434b27c26e` | REJECTED | 2 | R1, then R1 | | not read | A target pins a digest of upstream's exact plan text. |

6 VERIFIED: 2 correct, 1 partial, 3 wrong, by the same two independent readings, which again agree on all six. Of the 4 that are not correct, R8 objected to 2 (`1c080bd0c1e1`, `83f5619e4c69`) and AERead's full suite fails 2 (`1c080bd0c1e1`, `31088b7da967`); together they find 3, and nothing finds `dd8b832fabbc`. R8 objected to neither correct patch.

**Rerun with corrected targets (Amendment 4).** `1c080bd0c1e1` run again with the four targets the screening defect had hidden: REJECTED at R1 and R2 on both attempts. With the targets screened correctly, Receipts rejects this task instead of shipping an incomplete fix.

## R8: the false-veto check (Amendment 3)

R8 was built to veto. Before it ran on any new data, a rule was fixed: run it once on the 66 fixes Receipts shipped in the 100-task experiment, all accepted by SWE-rebench's official grader, and ship it advisory if it vetoes more than 3. It vetoed 10 (15%); in 9 more, one of the two reviews objected. So R8 ships advisory (`records/r8-check-swe-66.jsonl`; 132 reviews cost $0.17).

Most of the ten objections point at a difference between the patch and the wording of the SWE-rebench issue that the official tests do not require: an attribute named differently from the one the issue proposed, a test refactor the issue suggested and the fix did not do, a special case the issue mentioned. R8 holds a patch to its issue's words, so it is only as precise as the issue. On AERead, where each issue was written from its fix commit, it objected to 5 of the 10 patches that are not correct and none of the 8 correct ones in development, and to 2 of 4 and none of 2 on held-out set 2.

## Screening defects

The trial found two defects in my own screening script, both about test files that cannot be imported at the start state: Amendment 1 (such a file was not counted as failing) and Amendment 4 (such a file stopped pytest before the other changed files ran). Both are fixed in `scripts/screen.py` and their effect on every task is reported.

## Cost and time

| Set | Tasks | Model cost | Tokens | Wall time |
| --- | ---: | ---: | ---: | ---: |
| First eight | 8 | $1.59 | 5.2 M | 39 min |
| In-sample rerun | 8 | $2.14 | 7.0 M | 82 min |
| Held-out set 1 | 8 | $1.05 | 3.4 M | 71 min |
| Held-out set 2 | 8 | $2.14 | 7.0 M | 53 min |
| Corrected-target rerun | 1 | $1.20 | 3.9 M | 13 min |
| R8 reviews (development, false-veto check, set 2) | 252 reviews | $0.48 | 0.7 M | |

Model cost is Nemotron 3 Super on Token Factory at its listed prices (Nemotron 3 Ultra for one development setting), planner included. The rerun and held-out set 1 ran side by side on one machine, which lengthens both wall times.

## Limits

One project, issues written by one person, 8 held-out tasks: this shows what happens on real code and does not measure a rate. The readings are human and model judgement, made reproducible where possible by the probes. AERead's own tests also run on the maintainers' machines, so a few fail in a container at the upstream fix too (`test_offline_run_dir_is_complete`, which needs a git checkout); the comparison is per test, so they do not affect it.

## Reproduce

Every run folder is in `runs/` (the receipt, every attempt's patch, verdict and witness receipts). `scripts/` holds the screening, the runner, the full-suite comparison, the R7 checks and the probes; `records/` holds the screening records and the R7 results. The issue texts are in `tasks/`.
