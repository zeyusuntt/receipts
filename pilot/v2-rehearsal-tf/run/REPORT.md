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

Sandbox dollars are Token Factory reported cost. Total dollars combines that reported cost with the model estimate.

| Model dollars (estimated) | Sandbox dollars (estimated) | Total dollars (estimated) | Tokens | Sandbox lifetime seconds | Wall seconds |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.058 | 0.23 | 0.288 | 941723.25 | 167.952 | 304.886 |

### Rehearsal measurements

Peak live sandboxes: 4 at 2026-10-02T19:59:30.333561+00:00.

Records without sandbox intervals: 0.

Model retries: none.

## Harness

Total tool calls: 199.

Edit-failure rate (edit calls that did not apply, over all edit calls): 1 of 24 (4.2%).

Context guard: 0 turns; 0 messages replaced.

0 turns not recorded (worker rows before result logging).

0 worker logs unreadable or missing; 0 unreadable rows skipped.

### Result classes

| Class | Calls |
| --- | ---: |
| bad_args | 0 |
| command_timeout | 0 |
| edit_invalid_utf8 | 0 |
| edit_multiple_matches | 0 |
| edit_no_match | 1 |
| edit_too_large | 0 |
| finish_refused | 0 |
| malformed_args | 0 |
| nonzero_exit | 32 |
| not_executed | 0 |
| noted | 2 |
| ok | 164 |
| tool_error | 0 |
| unknown_tool | 0 |
| write_refused | 0 |

### Alias calls

| Alias | Calls |
| --- | ---: |
| execute | 78 |
| str_replace_editor | 4 |

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
| astropy__pyvo-204 | yes | resolved | verified on first verdict | resolved | 573846 tokens; $0.035 model estimated; $0.178 Token Factory reported cost; $0.214 total estimated; 110.465 sandbox lifetime s; 216.208 wall s | `pilot/v2-rehearsal-tf/run/astropy__pyvo-204/runs/pilot-astropy__pyvo-204-8fab0cca2a` |
| jupyterhub__binderhub-1571 | yes | resolved | verified on first verdict | resolved | 88226 tokens; $0.006 model estimated; $0.444 Token Factory reported cost; $0.449 total estimated; 198.182 sandbox lifetime s; 239.4 wall s | `pilot/v2-rehearsal-tf/run/jupyterhub__binderhub-1571/runs/pilot-jupyterhub__binderhub-1571-f4f5adf270` |
| pypa__twine-1066 | yes | resolved | verified on first verdict | resolved | 38896 tokens; $0.002 model estimated; $0.065 Token Factory reported cost; $0.068 total estimated; 57.631 sandbox lifetime s; 83.487 wall s | `pilot/v2-rehearsal-tf/run/pypa__twine-1066/runs/pilot-pypa__twine-1066-9a7e12ed85` |
| pysmt__pysmt-812 | yes | resolved | verified on first verdict | resolved | 239359 tokens; $0.015 model estimated; $0.085 Token Factory reported cost; $0.1 total estimated; 83.8 sandbox lifetime s; 181.168 wall s | `pilot/v2-rehearsal-tf/run/pysmt__pysmt-812/runs/pilot-pysmt__pysmt-812-5ba753dfea` |
| twisted__towncrier-696 | no | not resolved | refused | not resolved | 2826566 tokens; $0.173 model estimated; $0.149 Token Factory reported cost; $0.322 total estimated; 221.732 sandbox lifetime s; 499.28 wall s | `pilot/v2-rehearsal-tf/run/twisted__towncrier-696/runs/pilot-twisted__towncrier-696-74320b5d51` |
