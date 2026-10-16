# Beyond the benchmark: real bug fixes from AERead

Pre-registered: this file was committed and pushed before any agent ran on these tasks.

The 100-task experiment (`REPORT-v2.md`) used SWE-rebench. This trial asks how Receipts does on real bugs from a project that is not part of any benchmark.

## Source

AERead, https://github.com/aeread-org/AERead (public, Apache-2.0), branch `main` at `dec1a40f8de6`. Disclosure: I contribute to AERead. Every fix in the pool below was written by another contributor.

## Pool, fixed now

Every non-merge commit on `main` at `dec1a40f8de6` whose subject starts with "fix", that changes both Python source files and test files, with at most 3 source files and at most 150 changed source lines, and whose author is not me: 32 commits. They are listed below in the order used: ascending SHA-256 of the full commit hash, the same ordering rule as the 100-task experiment.

## Screening, in that order, until 8 tasks are included or the pool runs out

1. Start state: the fix's parent commit, plus one commit that applies only the fix commit's changes to test files.
2. Install with `pip install -e '.[dev]'` in `python:3.12-slim`.
3. Target tests: the tests the fix added or changed that fail in the start state. The rest of `tests/` is the regression suite.
4. A commit is excluded, with the reason recorded, if the install fails, if no target test fails in the start state, or if the start state cannot be built.

## Run

For each included task: `receipts fix --executor docker` from this repository at the commit that adds this file, with NVIDIA Nemotron 3 Super on Nebius Token Factory and the same agent settings as the 100-task experiment (one appeal). The issue text is written by me from the fix commit's message, describes the problem without the fix, and is saved with the task before its run.

## Reported for every included task, whatever happens

The verdict and attempts, wall time, tokens and model cost, the shipped patch, and my reading of the shipped patch against the upstream fix (the same cause fixed, a different but valid fix, or wrong). An infrastructure error is fixed and the task is run once more; both runs are reported.

## Limits

One project, issues written by one person, eight tasks. This shows Receipts on real code outside a benchmark; it does not measure a rate.

## The pool, in order

| # | Commit | Date | Author | Subject |
| --- | --- | --- | --- | --- |
| 1 | `a9ca7de16f11` | 2026-09-07 | Chenyu | fix: a sealed plan keeps the outcome list it sealed with (#62) |
| 2 | `9c72e635e2b6` | 2026-09-06 | Chenyu | fix: count what a failed case already paid for, and restate the ledger |
| 3 | `d4a6107bdab7` | 2026-09-06 | Chenyu | fix: two kernel contracts adapters were failing by coincidence, plus the failure-register standard |
| 4 | `de6a1ed5b859` | 2026-09-05 | Y.C. Fang | Fix shared-runner CI integration regressions |
| 5 | `a791090df23e` | 2026-07-31 | Lee | fix(everos): mute-proof example client — 4096 default budget + retry-on-empty |
| 6 | `96dc5893c8a0` | 2026-08-31 | Chenyu | fix: close housing bid and test import edge cases |
| 7 | `43670c88be2c` | 2026-09-05 | Chenyu | fix: let a zero-cost admission probe be re-probed instead of sealing the root |
| 8 | `21d898f417d1` | 2026-09-07 | Chenyu | fix: a spokesperson who says nothing must not crash the episode |
| 9 | `60a34999413f` | 2026-09-03 | Chenyu | fix: preserve frozen housing implementation pins |
| 10 | `ff737a500485` | 2026-09-10 | Chenyu | fix(receipts): reject coerced preimages and noncanonical rewrites |
| 11 | `d44d046e2122` | 2026-08-05 | Lee | fix(rllm): make the advertised install path actually work [TDD] |
| 12 | `d4ea59c9e7fd` | 2026-09-03 | Chenyu | fix: make procurement scaffold feasibility first |
| 13 | `6bb802cc35f0` | 2026-09-09 | Y.C. Fang | fix(shared-runner): harden adapter canary checkpointing |
| 14 | `56799931fe3d` | 2026-09-03 | Chenyu | fix: extend procurement rate limit window |
| 15 | `424ed3def0c2` | 2026-09-03 | Chenyu | fix: honor provider retry-after in procurement runs |
| 16 | `9b37cc341a5d` | 2026-08-31 | Lee | fix: harden Housing bid contract with red-green TDD |
| 17 | `294b0d3378b1` | 2026-09-01 | Chenyu | fix: select capture transport by OpenAI SDK major |
| 18 | `6361737020e5` | 2026-09-06 | Chenyu | fix: reject a step that calls the submit tool twice |
| 19 | `0b9f4a28e3a7` | 2026-09-03 | Chenyu | fix: score malformed procurement model output |
| 20 | `93af7d2fc747` | 2026-09-03 | Chenyu | fix: preserve Housing V11 implementation pins |
| 21 | `1c080bd0c1e1` | 2026-09-07 | Chenyu | fix: repair the four production-path gaps in the post-admission retry (#125 review) |
| 22 | `6e267dd04d15` | 2026-09-04 | Chenyu | fix: register the family through the trusted in-tree path |
| 23 | `83f5619e4c69` | 2026-09-06 | Chenyu | fix: bound the length-retry growth (#131) |
| 24 | `9dac975e6ed0` | 2026-09-06 | Chenyu | fix: make the termsbench primary unconditional, per ruling R13 |
| 25 | `dd8b832fabbc` | 2026-07-31 | Lee | fix(everos): inject agent cases (field-shape bug) + outcome-aware recall filter |
| 26 | `31088b7da967` | 2026-09-07 | Chenyu | fix: migrate the three remaining datacenter scorers to the kernel scoring contract (#144) |
| 27 | `11434b27c26e` | 2026-09-03 | Chenyu | fix: omit absent OpenRouter reasoning controls |
| 28 | `5a18ca33125f` | 2026-08-05 | Lee | fix(rllm): a broken run is an error, not a score of zero [TDD] |
| 29 | `553b582c2fda` | 2026-08-26 | Lee | fix: enforce portable shared-runner IDs with TDD |
| 30 | `28bfa5e8fcec` | 2026-09-05 | Y.C. Fang | Fix Arena GLM canary truncation |
| 31 | `4024666a788c` | 2026-09-07 | Chenyu | fix: label port-driven provider_call events with their attempt and action |
| 32 | `6dcaf4db05e7` | 2026-09-09 | Y.C. Fang | fix(shared-runner): preserve unknown canary costs |
