# What a verified fix costs: dollars, minutes and zero shipped failures across 30 SWE-rebench tasks.

## Spend

| Run class | Runs | Model dollars | Token Factory reported sandbox cost (unit not published) |
| --- | ---: | ---: | ---: |
| Final | 30 | $2.136 | 22.506 |
| Infrastructure error | 0 | $0 | 0 |
| Interrupted | 0 | $0 | 0 |
| All runs | 30 | $2.136 | 22.506 |

Unreadable archives: 0.
All runs includes final agent runs and every readable infrastructure-error and interrupted archive.
The sandbox figure is the per-run `cost` that Token Factory Sandboxes report. Token Factory does not publish the unit or a price during the beta, so the figure is shown as reported, not as dollars, and no dollar total is given.

## Unguarded agent (A)

Claimed dones: 22.

False-done rate: 13.6% (3 of 22), Wilson 95% CI 4.7% to 33.3%.

False dones accepted by the naive green check: 0.

A false done can appear in more than one breakdown row.

| Kind | False dones |
| --- | ---: |
| Spec still failing (R1) | 3 |
| Regression (R2) | 0 |
| Tests removed or newly skipped (R3) | 0 |
| Test or config edited (R4) | 1 |
| Tests never run on the final state | 3 |

## Receipts (B)

| Result | Count |
| --- | ---: |
| Verified fixes | 23 |
| Verified on first verdict | 20 |
| Verified on appeal | 3 |
| Shipped false dones | 0 |

Verified-fix rate: 76.7% (23 of 30), Wilson 95% CI 59.1% to 88.2%.

### Cost per verified fix

Model dollars, sandbox cost, tokens and sandbox lifetime use all readable final, infrastructure-error and interrupted runs.

Model dollars estimate Token Factory token usage. The sandbox figure is the per-run `cost` that Token Factory Sandboxes report. Token Factory does not publish the unit or a price during the beta, so the figure is shown as reported, not as dollars, and no dollar total is given.

| Model dollars (estimated) | Token Factory reported sandbox cost (unit not published) | Tokens | Sandbox lifetime seconds | Wall seconds |
| ---: | ---: | ---: | ---: | ---: |
| 0.093 | 0.979 | 1495735.522 | 256.605 | 498.168 |

### Rehearsal measurements

Peak live sandboxes: 4 at 2026-10-03T21:42:46.510936+00:00.

Records without sandbox intervals: 0.

Model retries: timeout: 4.

## Harness

Total tool calls: 1439.

Edit-failure rate (edit calls that did not apply, over all edit calls): 22 of 88 (25%).

Context guard: 0 turns; 0 messages replaced.

Attempts that ended on a budget: 11 on turns, 0 on wall time, 0 on completion tokens, 0 not recorded.

0 turns not recorded (worker rows before result logging).

0 worker logs unreadable or missing; 0 unreadable rows skipped.

### Result classes

| Class | Calls |
| --- | ---: |
| bad_args | 0 |
| command_timeout | 0 |
| edit_invalid_utf8 | 0 |
| edit_multiple_matches | 0 |
| edit_no_match | 22 |
| edit_too_large | 0 |
| finish_refused | 4 |
| malformed_args | 0 |
| nonzero_exit | 199 |
| not_executed | 0 |
| noted | 0 |
| ok | 1211 |
| tool_error | 0 |
| unknown_tool | 1 |
| write_refused | 2 |

### Alias calls

None.

## Shipped bytes

Shipped bytes: digests agree on 40 of 40 attempts.

0 attempts not recorded (records before this check).

Mismatches: none.

## Gate and official-grader agreement

| Gate status | Official resolved | Official not resolved | Official unavailable |
| --- | ---: | ---: | ---: |
| PASS | 23 | 0 | 0 |
| REJECTED | 0 | 17 | 0 |
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
| 3yourmind__django-migration-linter-258 | yes | resolved | verified on first verdict | resolved | 132514 tokens; $0.009 model estimated; 0.076 Token Factory reported cost, unit not published; 72.953 sandbox lifetime s; 116.019 wall s | `pilot/v2-arm-lightning/3yourmind__django-migration-linter-258/runs/pilot-3yourmind__django-migration-linter-258-d6cf0553fa` |
| aspp__pelita-798 | no | not resolved | refused | not resolved | 3550087 tokens; $0.224 model estimated; 0.178 Token Factory reported cost, unit not published; 196.391 sandbox lifetime s; 560.763 wall s | `pilot/v2-arm-lightning/aspp__pelita-798/runs/pilot-aspp__pelita-798-7cf01be3ed` |
| azure__walinuxagent-638 | yes | not resolved | refused | not resolved | 1458759 tokens; $0.092 model estimated; 0.082 Token Factory reported cost, unit not published; 128.527 sandbox lifetime s; 305.871 wall s | `pilot/v2-arm-lightning/azure__walinuxagent-638/runs/pilot-azure__walinuxagent-638-0dd5cd9dd5` |
| bloomberg__memray-552 | yes | resolved | verified on first verdict | resolved | 361207 tokens; $0.023 model estimated; 1.557 Token Factory reported cost, unit not published; 346.143 sandbox lifetime s; 636.559 wall s | `pilot/v2-arm-lightning/bloomberg__memray-552/runs/pilot-bloomberg__memray-552-b3b1a54c14` |
| callowayproject__bump-my-version-180 | yes | resolved | verified on first verdict | resolved | 101316 tokens; $0.007 model estimated; 0.1 Token Factory reported cost, unit not published; 63.582 sandbox lifetime s; 119.026 wall s | `pilot/v2-arm-lightning/callowayproject__bump-my-version-180/runs/pilot-callowayproject__bump-my-version-180-b7a48320b8` |
| dask__dask-5861 | yes | resolved | verified on first verdict | resolved | 28967 tokens; $0.002 model estimated; 0.047 Token Factory reported cost, unit not published; 49.097 sandbox lifetime s; 107.875 wall s | `pilot/v2-arm-lightning/dask__dask-5861/runs/pilot-dask__dask-5861-e09fa4d675` |
| datadog__datadogpy-555 | yes | resolved | verified on first verdict | resolved | 47238 tokens; $0.003 model estimated; 0.042 Token Factory reported cost, unit not published; 55.068 sandbox lifetime s; 103.621 wall s | `pilot/v2-arm-lightning/datadog__datadogpy-555/runs/pilot-datadog__datadogpy-555-5e9a23aa00` |
| deshaw__pyflyby-289 | yes | resolved | verified on first verdict | resolved | 202644 tokens; $0.013 model estimated; 0.079 Token Factory reported cost, unit not published; 74.481 sandbox lifetime s; 120.259 wall s | `pilot/v2-arm-lightning/deshaw__pyflyby-289/runs/pilot-deshaw__pyflyby-289-a854e83b1c` |
| gitpython-developers__gitpython-1832 | no | resolved | verified on first verdict | resolved | 1039321 tokens; $0.064 model estimated; 0.184 Token Factory reported cost, unit not published; 172.113 sandbox lifetime s; 276.879 wall s | `pilot/v2-arm-lightning/gitpython-developers__gitpython-1832/runs/pilot-gitpython-developers__gitpython-1832-d9a700ebe6` |
| jnothman__upsetplot-253 | yes | not resolved | refused | not resolved | 1235832 tokens; $0.078 model estimated; 1.442 Token Factory reported cost, unit not published; 297.182 sandbox lifetime s; 458.478 wall s | `pilot/v2-arm-lightning/jnothman__upsetplot-253/runs/pilot-jnothman__upsetplot-253-2fbbcaf1cc` |
| kubernetes-client__python-1933 | yes | resolved | verified on first verdict | resolved | 1236188 tokens; $0.077 model estimated; 0.191 Token Factory reported cost, unit not published; 141.476 sandbox lifetime s; 303.445 wall s | `pilot/v2-arm-lightning/kubernetes-client__python-1933/runs/pilot-kubernetes-client__python-1933-d1de781d33` |
| mondeja__mkdocs-include-markdown-plugin-51 | yes | resolved | verified on first verdict | resolved | 1029783 tokens; $0.064 model estimated; 0.046 Token Factory reported cost, unit not published; 96.593 sandbox lifetime s; 195.165 wall s | `pilot/v2-arm-lightning/mondeja__mkdocs-include-markdown-plugin-51/runs/pilot-mondeja__mkdocs-include-markdown-plugin-51-d48e6eed31` |
| more-itertools__more-itertools-892 | yes | resolved | verified on first verdict | resolved | 283445 tokens; $0.018 model estimated; 0.106 Token Factory reported cost, unit not published; 76.841 sandbox lifetime s; 130.879 wall s | `pilot/v2-arm-lightning/more-itertools__more-itertools-892/runs/pilot-more-itertools__more-itertools-892-3706a4f5ba` |
| niconoe__pyinaturalist-72 | yes | resolved | verified on first verdict | resolved | 99346 tokens; $0.006 model estimated; 0.055 Token Factory reported cost, unit not published; 60.391 sandbox lifetime s; 91.677 wall s | `pilot/v2-arm-lightning/niconoe__pyinaturalist-72/runs/pilot-niconoe__pyinaturalist-72-760c33eda0` |
| openmdao__openmdao-3029 | no | not resolved | refused | not resolved | 3621962 tokens; $0.222 model estimated; 1.202 Token Factory reported cost, unit not published; 374.466 sandbox lifetime s; 1372.235 wall s | `pilot/v2-arm-lightning/openmdao__openmdao-3029/runs/pilot-openmdao__openmdao-3029-8d77f91878` |
| opensearch-project__opensearch-py-843 | yes | resolved | verified on first verdict | resolved | 581430 tokens; $0.036 model estimated; 0.08 Token Factory reported cost, unit not published; 119.456 sandbox lifetime s; 188.472 wall s | `pilot/v2-arm-lightning/opensearch-project__opensearch-py-843/runs/pilot-opensearch-project__opensearch-py-843-4d62a2dd94` |
| palantir__python-language-server-829 | no | not resolved | refused | not resolved | 3247300 tokens; $0.202 model estimated; 0.284 Token Factory reported cost, unit not published; 267.969 sandbox lifetime s; 538.251 wall s | `pilot/v2-arm-lightning/palantir__python-language-server-829/runs/pilot-palantir__python-language-server-829-51b475d037` |
| pybamm-team__pybamm-4196 | no | not resolved | verified on appeal | resolved | 2293125 tokens; $0.14 model estimated; 4.216 Token Factory reported cost, unit not published; 439.731 sandbox lifetime s; 705.155 wall s | `pilot/v2-arm-lightning/pybamm-team__pybamm-4196/runs/pilot-pybamm-team__pybamm-4196-e8b53a4452` |
| pyfilesystem__pyfilesystem2-462 | no | not resolved | verified on appeal | resolved | 1948110 tokens; $0.119 model estimated; 0.456 Token Factory reported cost, unit not published; 291.559 sandbox lifetime s; 1111.121 wall s | `pilot/v2-arm-lightning/pyfilesystem__pyfilesystem2-462/runs/pilot-pyfilesystem__pyfilesystem2-462-0ec2979bbd` |
| pytask-dev__pytask-519 | yes | resolved | verified on first verdict | resolved | 236720 tokens; $0.015 model estimated; 0.171 Token Factory reported cost, unit not published; 110.455 sandbox lifetime s; 173.439 wall s | `pilot/v2-arm-lightning/pytask-dev__pytask-519/runs/pilot-pytask-dev__pytask-519-4ca0de8453` |
| qutech__qupulse-797 | yes | resolved | verified on first verdict | resolved | 2295123 tokens; $0.142 model estimated; 0.313 Token Factory reported cost, unit not published; 147.908 sandbox lifetime s; 319.456 wall s | `pilot/v2-arm-lightning/qutech__qupulse-797/runs/pilot-qutech__qupulse-797-39cb8d3e9d` |
| rhayes777__pyautofit-888 | yes | resolved | verified on first verdict | resolved | 565974 tokens; $0.035 model estimated; 0.28 Token Factory reported cost, unit not published; 155.661 sandbox lifetime s; 240.319 wall s | `pilot/v2-arm-lightning/rhayes777__pyautofit-888/runs/pilot-rhayes777__pyautofit-888-1f7f86d866` |
| robotframework__seleniumlibrary-1431 | yes | resolved | verified on first verdict | resolved | 111629 tokens; $0.007 model estimated; 0.036 Token Factory reported cost, unit not published; 50.496 sandbox lifetime s; 96.132 wall s | `pilot/v2-arm-lightning/robotframework__seleniumlibrary-1431/runs/pilot-robotframework__seleniumlibrary-1431-86cdd86202` |
| scitools__cartopy-2307 | yes | not resolved | refused | not resolved | 717996 tokens; $0.045 model estimated; 0.259 Token Factory reported cost, unit not published; 145.109 sandbox lifetime s; 306.69 wall s | `pilot/v2-arm-lightning/scitools__cartopy-2307/runs/pilot-scitools__cartopy-2307-5b4783f661` |
| sdv-dev__rdt-704 | yes | resolved | verified on first verdict | resolved | 1833916 tokens; $0.114 model estimated; 0.604 Token Factory reported cost, unit not published; 171.75 sandbox lifetime s; 349.998 wall s | `pilot/v2-arm-lightning/sdv-dev__rdt-704/runs/pilot-sdv-dev__rdt-704-f446a75699` |
| skypyproject__skypy-573 | yes | resolved | verified on first verdict | resolved | 31482 tokens; $0.002 model estimated; 0.194 Token Factory reported cost, unit not published; 66.55 sandbox lifetime s; 95.192 wall s | `pilot/v2-arm-lightning/skypyproject__skypy-573/runs/pilot-skypyproject__skypy-573-c53b75b1f4` |
| stac-utils__pystac-client-782 | yes | resolved | verified on first verdict | resolved | 49602 tokens; $0.003 model estimated; 0.115 Token Factory reported cost, unit not published; 71.557 sandbox lifetime s; 252.276 wall s | `pilot/v2-arm-lightning/stac-utils__pystac-client-782/runs/pilot-stac-utils__pystac-client-782-7d79796c79` |
| stac-utils__stac-fastapi-729 | no | not resolved | verified on appeal | resolved | 1474789 tokens; $0.093 model estimated; 0.307 Token Factory reported cost, unit not published; 223.158 sandbox lifetime s; 400.503 wall s | `pilot/v2-arm-lightning/stac-utils__stac-fastapi-729/runs/pilot-stac-utils__stac-fastapi-729-c761b1856e` |
| yukinarit__pyserde-430 | yes | resolved | verified on first verdict | resolved | 988406 tokens; $0.061 model estimated; 7.22 Token Factory reported cost, unit not published; 871.999 sandbox lifetime s; 968.99 wall s | `pilot/v2-arm-lightning/yukinarit__pyserde-430/runs/pilot-yukinarit__pyserde-430-2cc47a9b29` |
| zopefoundation__btrees-163 | no | not resolved | refused | not resolved | 3597706 tokens; $0.221 model estimated; 2.586 Token Factory reported cost, unit not published; 563.241 sandbox lifetime s; 813.128 wall s | `pilot/v2-arm-lightning/zopefoundation__btrees-163/runs/pilot-zopefoundation__btrees-163-d7ae3288d9` |
