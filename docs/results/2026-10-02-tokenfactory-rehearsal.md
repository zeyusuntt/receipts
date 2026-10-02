# Token Factory Sandboxes rehearsal (2026-10-02)

Plan 5, section 10 (C5) and item D2, on the Token Factory executor. The five D2 rehearsal tasks were screened under rules 4 and 5 on Token Factory Sandboxes and then run at concurrency 4 under `receipts pilot watch`, at code commit `14cb223`, with Nemotron 3 Super. Records: `pilot/v2-rehearsal-tf/`. Report: `pilot/v2-rehearsal-tf/run/REPORT.md`.

## Getting there

Two live-only defects surfaced in screening and were fixed test-first before the run; each failed screening ledger is kept:

1. The live API refuses `truncate_output_at` of 10 MiB or more; the executor asked for 64 MiB. Fixed in `8a691ca`, which also makes truncated output fail closed: no full log is written, so official grading cannot parse a partial log, where missing tests count as failed (`pilot/v2-rehearsal-tf/screen-1-truncate-cap*`).
2. Screening grades an empty patch, and `git apply` rejects empty input. Fixed in `14cb223`: an empty patch is a successful apply that runs nothing, as on Daytona (`pilot/v2-rehearsal-tf/screen-2-empty-patch*`).

The third screening included all five tasks, as on Daytona, in 22 to 103 seconds each (Daytona: 112 to 160).

## Outcome

| Instance | B outcome | Official |
| --- | --- | --- |
| `astropy__pyvo-204` | verified on first verdict | resolved |
| `jupyterhub__binderhub-1571` | verified on first verdict | resolved |
| `pypa__twine-1066` | verified on first verdict | resolved |
| `pysmt__pysmt-812` | verified on first verdict | resolved |
| `twisted__towncrier-696` | rejected twice (R1 and R2, and R4 for an edit to `pyproject.toml`) | not resolved |

The gate and the official grader agreed on all six attempts, and the gate, witness and official digests of every filtered patch agreed.

## Pass criteria

| Criterion | Result |
| --- | --- |
| No invented-tool strikes | Met (0; also 0 bad arguments, 0 tool errors, 0 refused writes). |
| No R4 failure caused by a new test file | Met. towncrier's R4 failures are an edit to `pyproject.toml`, which stays fatal. |
| No new file in a shipped patch that a reviewer would remove | Met. No shipped patch added a file; towncrier's rejected attempts added files at the root and were not shipped. |
| No gate ERROR except infrastructure | Met. |
| Peak live sandboxes within the limits | Met: 4 concurrent runs against a limit of 50 operations. |
| Snapshots left behind | Not applicable: runs end on their own and images are immutable. |
| Peak prompt tokens under the budget | Met: 39,848. |
| 429 count and median wall time | 0 retries; median 216 s per task (v1: 300 s). |

## Cost: open question

Each run's result carries a `cost` that is exactly 0.0101 per second of the platform's measured elapsed time (281 runs; 89 platform seconds; 0.92 reported in total, against 672 seconds of wall time). The Sandboxes documentation publishes no pricing and does not name the unit. If the unit is US dollars, v2 on Token Factory would report roughly 35 to 45 in sandbox cost, more than the model cost. The billing page in the Token Factory console settles it; until then the report labels the figure "Token Factory reported cost".

## Decision gate

Every D2 criterion is met on Token Factory Sandboxes on Oct 2, before the Oct 6 deadline. By Plan 5, section 10, v2 freezes on Token Factory Sandboxes, subject only to the cost question above being compatible with the credits.
