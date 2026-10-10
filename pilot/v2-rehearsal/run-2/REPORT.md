# What a verified fix costs: dollars, minutes and zero shipped failures across 5 SWE-rebench tasks.

## Unguarded agent (A)

Claimed dones: 4.

False-done rate: 0% (0 of 4), Wilson 95% CI 0% to 49%.

False dones accepted by the naive green check: 0.

A false done can appear in more than one breakdown row.

| Kind | False dones |
| --- | ---: |
| Spec still failing (R1) | 0 |
| Regression (R2) | 0 |
| Tests removed or newly skipped (R3) | 0 |
| Test or config edited (R4) | 0 |
| Tests never run on the final state | 0 |

## Receipts (B)

| Result | Count |
| --- | ---: |
| Verified fixes | 4 |
| Verified on first verdict | 4 |
| Verified on appeal | 0 |
| Shipped false dones | 0 |

Verified-fix rate: 80% (4 of 5), Wilson 95% CI 37.6% to 96.4%.

### Cost per verified fix

Model dollars estimate Token Factory token usage. Sandbox dollars estimate Daytona vCPU, memory and billable disk over measured sandbox lifetimes. Total dollars combines both estimates.

Snapshot storage is not included because Daytona had not published its price when the rates were read on 2026-10-01.

| Model dollars (estimated) | Sandbox dollars (estimated) | Total dollars (estimated) | Tokens | Sandbox lifetime seconds | Wall seconds |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.089 | 0.021 | 0.11 | 1439338 | 578.373 | 578.25 |

### Rehearsal measurements

Peak live sandboxes: 4 at 2026-10-02T17:36:20.400787+00:00.

Records without sandbox intervals: 0.

Model retries: none.

## Harness

Total tool calls: 262.

Edit-failure rate (edit calls that did not apply, over all edit calls): 19 of 40 (47.5%).

Context guard: 0 turns; 0 messages replaced.

0 turns not recorded (worker rows before result logging).

0 worker logs unreadable or missing; 0 unreadable rows skipped.

### Result classes

| Class | Calls |
| --- | ---: |
| bad_args | 0 |
| command_timeout | 4 |
| edit_invalid_utf8 | 0 |
| edit_multiple_matches | 0 |
| edit_no_match | 19 |
| edit_too_large | 0 |
| finish_refused | 0 |
| malformed_args | 0 |
| nonzero_exit | 35 |
| not_executed | 0 |
| noted | 0 |
| ok | 202 |
| tool_error | 2 |
| unknown_tool | 0 |
| write_refused | 0 |

### Alias calls

| Alias | Calls |
| --- | ---: |
| execute | 96 |
| execute_command | 16 |

## Shipped bytes

Shipped bytes: digests agree on 6 of 6 attempts.

0 attempts not recorded (records before this check).

Mismatches: none.

## Gate and official-grader agreement

| Gate status | Official resolved | Official not resolved | Official unavailable |
| --- | ---: | ---: | ---: |
| PASS | 4 | 0 | 0 |
| REJECTED | 0 | 2 | 0 |
| ERROR | 0 | 0 | 0 |

### Disagreements and gate errors

None.

## Exclusions

None.

## Infrastructure errors

None.

## Cleanup errors

None.

## Per instance

| Instance | A claimed done | A official | B outcome | B official | Cost | Run directory |
| --- | --- | --- | --- | --- | --- | --- |
| astropy__pyvo-204 | yes | resolved | verified on first verdict | resolved | 234574 tokens; $0.015 model estimated; $0.003 sandbox estimated; $0.018 total estimated; 93.293 sandbox lifetime s; 98.042 wall s | `pilot/v2-rehearsal/run-2/astropy__pyvo-204/runs/pilot-astropy__pyvo-204-6ade75c129` |
| jupyterhub__binderhub-1571 | no | not resolved | refused | not resolved | 2902539 tokens; $0.177 model estimated; $0.016 sandbox estimated; $0.193 total estimated; 426.174 sandbox lifetime s; 393.265 wall s | `pilot/v2-rehearsal/run-2/jupyterhub__binderhub-1571/runs/pilot-jupyterhub__binderhub-1571-d748df7d64` |
| pypa__twine-1066 | yes | resolved | verified on first verdict | resolved | 38847 tokens; $0.002 model estimated; $0.004 sandbox estimated; $0.006 total estimated; 108.578 sandbox lifetime s; 112.456 wall s | `pilot/v2-rehearsal/run-2/pypa__twine-1066/runs/pilot-pypa__twine-1066-c132ce39b3` |
| pysmt__pysmt-812 | yes | resolved | verified on first verdict | resolved | 1506828 tokens; $0.095 model estimated; $0.054 sandbox estimated; $0.149 total estimated; 1452.007 sandbox lifetime s; 1454.982 wall s | `pilot/v2-rehearsal/run-2/pysmt__pysmt-812/runs/pilot-pysmt__pysmt-812-3f36cacc99` |
| twisted__towncrier-696 | yes | resolved | verified on first verdict | resolved | 1074564 tokens; $0.067 model estimated; $0.009 sandbox estimated; $0.075 total estimated; 233.442 sandbox lifetime s; 254.256 wall s | `pilot/v2-rehearsal/run-2/twisted__towncrier-696/runs/pilot-twisted__towncrier-696-7b46f20a87` |
