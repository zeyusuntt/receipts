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
| Verified fixes | 5 |
| Verified on first verdict | 4 |
| Verified on appeal | 1 |
| Shipped false dones | 0 |

Verified-fix rate: 100% (5 of 5), Wilson 95% CI 56.6% to 100%.

### Cost per verified fix

Model dollars estimate Token Factory token usage. Sandbox dollars estimate Daytona vCPU, memory and billable disk over measured sandbox lifetimes. Total dollars combines both estimates.

Snapshot storage is not included because Daytona had not published its price when the rates were read on 2026-10-01.

| Model dollars (estimated) | Sandbox dollars (estimated) | Total dollars (estimated) | Tokens | Sandbox lifetime seconds | Wall seconds |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.032 | 0.01 | 0.041 | 501427.8 | 260.825 | 259.419 |

### Rehearsal measurements

Peak live sandboxes: 3 at 2026-10-02T10:46:04.656503+00:00.

Records without sandbox intervals: 0.

Model retries: none.

## Harness

Total tool calls: 143.

Edit-failure rate (edit calls that did not apply, over all edit calls): 1 of 12 (8.3%).

Context guard: 0 turns; 0 messages replaced.

0 turns not recorded (worker rows before result logging).

0 worker logs unreadable or missing; 0 unreadable rows skipped.

### Result classes

| Class | Calls |
| --- | ---: |
| bad_args | 1 |
| command_timeout | 2 |
| edit_invalid_utf8 | 0 |
| edit_multiple_matches | 0 |
| edit_no_match | 0 |
| edit_too_large | 0 |
| finish_refused | 1 |
| malformed_args | 0 |
| nonzero_exit | 13 |
| not_executed | 0 |
| noted | 0 |
| ok | 121 |
| tool_error | 1 |
| unknown_tool | 1 |
| write_refused | 3 |

### Alias calls

| Alias | Calls |
| --- | ---: |
| execute | 40 |

## Shipped bytes

Shipped bytes: digests agree on 6 of 6 attempts.

0 attempts not recorded (records before this check).

Mismatches: none.

## Gate and official-grader agreement

| Gate status | Official resolved | Official not resolved | Official unavailable |
| --- | ---: | ---: | ---: |
| PASS | 5 | 0 | 0 |
| REJECTED | 0 | 1 | 0 |
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
| astropy__pyvo-204 | yes | resolved | verified on first verdict | resolved | 128898 tokens; $0.008 model estimated; $0.002 sandbox estimated; $0.01 total estimated; 50.634 sandbox lifetime s; 52.76 wall s | `pilot/v2-rehearsal/run/astropy__pyvo-204/runs/pilot-astropy__pyvo-204-e4e15b8628` |
| jupyterhub__binderhub-1571 | yes | resolved | verified on first verdict | resolved | 291664 tokens; $0.018 model estimated; $0.007 sandbox estimated; $0.025 total estimated; 189.761 sandbox lifetime s; 176.107 wall s | `pilot/v2-rehearsal/run/jupyterhub__binderhub-1571/runs/pilot-jupyterhub__binderhub-1571-48572ede55` |
| pypa__twine-1066 | yes | resolved | verified on first verdict | resolved | 39161 tokens; $0.002 model estimated; $0.002 sandbox estimated; $0.004 total estimated; 53.556 sandbox lifetime s; 56.164 wall s | `pilot/v2-rehearsal/run/pypa__twine-1066/runs/pilot-pypa__twine-1066-0638a44b53` |
| pysmt__pysmt-812 | yes | resolved | verified on first verdict | resolved | 362360 tokens; $0.024 model estimated; $0.028 sandbox estimated; $0.052 total estimated; 767.663 sandbox lifetime s; 769.652 wall s | `pilot/v2-rehearsal/run/pysmt__pysmt-812/runs/pilot-pysmt__pysmt-812-a7e19b9255` |
| twisted__towncrier-696 | no | not resolved | verified on appeal | resolved | 1685056 tokens; $0.105 model estimated; $0.009 sandbox estimated; $0.114 total estimated; 242.508 sandbox lifetime s; 242.411 wall s | `pilot/v2-rehearsal/run/twisted__towncrier-696/runs/pilot-twisted__towncrier-696-ce351831c4` |
