Receipts shipped 1 false done.

# What a verified fix costs: dollars, minutes and 1 shipped failure across 50 SWE-rebench tasks.

## Unguarded agent (A)

Claimed dones: 23.

False-done rate: 17.4% (4 of 23), Wilson 95% CI 7% to 37.1%.

False dones accepted by the naive green check: 3.

A false done can appear in more than one breakdown row.

| Kind | False dones |
| --- | ---: |
| Spec still failing (R1) | 4 |
| Regression (R2) | 0 |
| Tests removed or newly skipped (R3) | 0 |
| Test or config edited (R4) | 1 |
| Tests never run on the final state | 1 |

## Receipts (B)

| Result | Count |
| --- | ---: |
| Verified fixes | 24 |
| Verified on first verdict | 20 |
| Verified on appeal | 4 |
| Shipped false dones | 1 |

Verified-fix rate: 48% (24 of 50), Wilson 95% CI 34.8% to 61.5%.

### Cost per verified fix

Model dollars estimate Token Factory token usage. Sandbox dollars estimate Daytona vCPU, memory and billable disk over measured sandbox lifetimes. Total dollars combines both estimates.

Snapshot storage is not included because Daytona had not published its price when the rates were read on 2026-10-01.

| Model dollars (estimated) | Sandbox dollars (estimated) | Total dollars (estimated) | Tokens | Sandbox lifetime seconds | Wall seconds |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.095 | 0.035 | 0.13 | 1530939.375 | 953.496 | 925.458 |

### Rehearsal measurements

Peak live sandboxes: 0.

Records without sandbox intervals: 58.

Model retries: none.

## Harness

Total tool calls: 0.

Edit-failure rate (edit calls that did not apply, over all edit calls): 0 of 0.

Context guard: 0 turns; 0 messages replaced.

1875 turns not recorded (worker rows before result logging).

8 worker logs unreadable or missing; 0 unreadable rows skipped.

### Result classes

| Class | Calls |
| --- | ---: |
| bad_args | 0 |
| command_timeout | 0 |
| edit_invalid_utf8 | 0 |
| edit_multiple_matches | 0 |
| edit_no_match | 0 |
| edit_too_large | 0 |
| finish_refused | 0 |
| malformed_args | 0 |
| nonzero_exit | 0 |
| not_executed | 0 |
| noted | 0 |
| ok | 0 |
| tool_error | 0 |
| unknown_tool | 0 |
| write_refused | 0 |

### Alias calls

None.

## Shipped bytes

Shipped bytes: digests agree on 0 of 0 attempts.

79 attempts not recorded (records before this check).

Mismatches: none.

## Gate and official-grader agreement

| Gate status | Official resolved | Official not resolved | Official unavailable |
| --- | ---: | ---: | ---: |
| PASS | 24 | 1 | 0 |
| REJECTED | 6 | 47 | 0 |
| ERROR | 0 | 1 | 0 |

### Disagreements and gate errors

| Instance | Attempt | Classification | Failed predicates | Gate error |
| --- | ---: | --- | --- | --- |
| aio-libs__aiohttp-8823 | 1 | gate_stricter | R4_patch_scope | none |
| meltano__sdk-3020 | 2 | gate_stricter | R4_patch_scope | none |
| pandas-dev__pandas-56926 | 2 | gate_stricter | R4_patch_scope | none |
| py-pdf__pypdf2-1318 | 2 | gate_looser | none | none |
| qiskit__qiskit-ibm-runtime-452 | 1 | gate_stricter | R2_pass_to_pass | none |
| qiskit__qiskit-ibm-runtime-452 | 2 | gate_stricter | R2_pass_to_pass | none |
| sparckles__robyn-1002 | 1 | gate_stricter | R4_patch_scope | none |
| vyperlang__vyper-3261 | 1 | gate_error | none | verification exited 4 (pytest usage or internal error) |

## Exclusions

| Instance | Reason | Run directory |
| --- | --- | --- |
| benchopt__benchopt-414 | baseline suite took 362s, over the limit | `pilot/run-2026-10-01c/benchopt__benchopt-414/runs/pilot-benchopt__benchopt-414-28588e3367` |
| copier-org__copier-2007 | first baseline run is not a valid pytest run (exit 137, junit=missing) | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/copier-org__copier-2007/runs/pilot-copier-org__copier-2007-0eb84fe5c1` |
| jazzband__pip-tools-822 | baseline suite took 430s, over the limit | `pilot/run-2026-10-01c/jazzband__pip-tools-822/runs/pilot-jazzband__pip-tools-822-afe27e2fe2` |
| keras-team__keras-19775 | first baseline run is not a valid pytest run (exit 137, junit=missing) | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/keras-team__keras-19775/runs/pilot-keras-team__keras-19775-069c2e78ac` |
| martinthoma__flake8-simplify-173 | target tests did not fail in every baseline run: ['tests/test_900_rules.py::test_sim910[d.get(key,', "tests/test_900_rules.py::test_sim910[d.get('key',"] | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/martinthoma__flake8-simplify-173/runs/pilot-martinthoma__flake8-simplify-173-124723af31` |
| modin-project__modin-6673 | baseline suite took 601s, over the limit | `pilot/run-2026-10-01c/modin-project__modin-6673/runs/pilot-modin-project__modin-6673-c9e459e5d7` |
| pyccel__pyccel-2151 | target tests did not fail in every baseline run: ['tests/epyccel/test_builtins.py::test_min_if[c]', 'tests/epyccel/test_builtins.py::test_min_in_min[c]'] | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/pyccel__pyccel-2151/runs/pilot-pyccel__pyccel-2151-16d3308430` |
| redis__redis-py-1895 | first baseline run is not a valid pytest run (exit 3, junit=missing) | `pilot/run-2026-10-01c/redis__redis-py-1895/runs/pilot-redis__redis-py-1895-0cb63c5305` |

## Infrastructure errors

| Instance | Reason | Run directory |
| --- | --- | --- |
| qiskit__qiskit-ibm-runtime-452 | OSError: trusted git command failed: no output | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/qiskit__qiskit-ibm-runtime-452/runs/pilot-qiskit__qiskit-ibm-runtime-452-d3f0655b3d` |

## Cleanup errors

None.

## Per instance

| Instance | A claimed done | A official | B outcome | B official | Cost | Run directory |
| --- | --- | --- | --- | --- | --- | --- |
| aaugustin__websockets-467 | yes | resolved | verified on first verdict | resolved | 186010 tokens; $0.012 model estimated; $0.008 sandbox estimated; $0.02 total estimated; 207.419 sandbox lifetime s; 245.192 wall s | `pilot/run-2026-10-01c/aaugustin__websockets-467/runs/pilot-aaugustin__websockets-467-47ec2319d5` |
| agnostiqhq__covalent-1660 | yes | resolved | verified on first verdict | resolved | 136239 tokens; $0.008 model estimated; $0.014 sandbox estimated; $0.022 total estimated; 379.08 sandbox lifetime s; 372.026 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/agnostiqhq__covalent-1660/runs/pilot-agnostiqhq__covalent-1660-59e144e701` |
| aio-libs__aiohttp-8823 | no | resolved | verified on appeal | resolved | 1084645 tokens; $0.067 model estimated; $0.03 sandbox estimated; $0.097 total estimated; 802.917 sandbox lifetime s; 767.658 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/aio-libs__aiohttp-8823/runs/pilot-aio-libs__aiohttp-8823-3a7d9ab4f1` |
| aio-libs__multidict-1204 | yes | resolved | verified on first verdict | resolved | 216776 tokens; $0.013 model estimated; $0.005 sandbox estimated; $0.018 total estimated; 130.47 sandbox lifetime s; 131.493 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/aio-libs__multidict-1204/runs/pilot-aio-libs__multidict-1204-ebcf68b813` |
| altair-viz__altair-3068 | yes | not resolved | refused | not resolved | 189040 tokens; $0.012 model estimated; $0.02 sandbox estimated; $0.032 total estimated; 550.117 sandbox lifetime s; 472.903 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/altair-viz__altair-3068/runs/pilot-altair-viz__altair-3068-ce9d8223f2` |
| amaranth-lang__amaranth-842 | yes | not resolved | refused | not resolved | 528896 tokens; $0.033 model estimated; $0.009 sandbox estimated; $0.042 total estimated; 232.727 sandbox lifetime s; 262.869 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/amaranth-lang__amaranth-842/runs/pilot-amaranth-lang__amaranth-842-e2ab039e57` |
| audreyr__cookiecutter-729 | no | not resolved | refused | not resolved | 673157 tokens; $0.042 model estimated; $0.008 sandbox estimated; $0.05 total estimated; 212.349 sandbox lifetime s; 240.034 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/audreyr__cookiecutter-729/runs/pilot-audreyr__cookiecutter-729-e1af494579` |
| aws-cloudformation__cfn-lint-3659 | no | not resolved | refused | not resolved | 137021 tokens; $0.009 model estimated; $0.018 sandbox estimated; $0.027 total estimated; 499.218 sandbox lifetime s; 426.498 wall s | `pilot/run-2026-10-01c/aws-cloudformation__cfn-lint-3659/runs/pilot-aws-cloudformation__cfn-lint-3659-09c4937034` |
| backblaze__b2_command_line_tool-259 | no | not resolved | refused | not resolved | 1300916 tokens; $0.08 model estimated; $0.012 sandbox estimated; $0.092 total estimated; 319.839 sandbox lifetime s; 317.239 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/backblaze__b2_command_line_tool-259/runs/pilot-backblaze__b2_command_line_tool-259-18d206629b` |
| benchopt__benchopt-414 | no | unavailable | excluded | unavailable | 0 tokens; not available model estimated; $0.013 sandbox estimated; not available total estimated; 364.618 sandbox lifetime s; 405.197 wall s | `pilot/run-2026-10-01c/benchopt__benchopt-414/runs/pilot-benchopt__benchopt-414-28588e3367` |
| borgbackup__borg-8847 | yes | resolved | verified on first verdict | resolved | 66563 tokens; $0.004 model estimated; $0.009 sandbox estimated; $0.013 total estimated; 247.343 sandbox lifetime s; 272.923 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/borgbackup__borg-8847/runs/pilot-borgbackup__borg-8847-b92eb13f49` |
| census-instrumentation__opencensus-python-165 | yes | resolved | verified on first verdict | resolved | 79011 tokens; $0.005 model estimated; $0.004 sandbox estimated; $0.009 total estimated; 117.675 sandbox lifetime s; 121.068 wall s | `pilot/run-2026-10-01c/census-instrumentation__opencensus-python-165/runs/pilot-census-instrumentation__opencensus-python-165-59afa19279` |
| cloudreach__sceptre-381 | no | not resolved | refused | not resolved | 915836 tokens; $0.056 model estimated; $0.01 sandbox estimated; $0.066 total estimated; 259.948 sandbox lifetime s; 256.269 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/cloudreach__sceptre-381/runs/pilot-cloudreach__sceptre-381-8f7782e2b9` |
| copier-org__copier-2007 | no | unavailable | excluded | unavailable | 0 tokens; not available model estimated; $0.002 sandbox estimated; not available total estimated; 46.945 sandbox lifetime s; 85.037 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/copier-org__copier-2007/runs/pilot-copier-org__copier-2007-0eb84fe5c1` |
| datadog__guarddog-156 | no | not resolved | refused | not resolved | 32761 tokens; $0.002 model estimated; $0.008 sandbox estimated; $0.01 total estimated; 210.516 sandbox lifetime s; 238.879 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/datadog__guarddog-156/runs/pilot-datadog__guarddog-156-7181a759d4` |
| facelessuser__pymdown-extensions-2003 | no | not resolved | refused | not resolved | 3091510 tokens; $0.192 model estimated; $0.02 sandbox estimated; $0.212 total estimated; 537.085 sandbox lifetime s; 567.625 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/facelessuser__pymdown-extensions-2003/runs/pilot-facelessuser__pymdown-extensions-2003-bc9080943d` |
| fsspec__universal_pathlib-261 | yes | resolved | verified on first verdict | resolved | 536415 tokens; $0.033 model estimated; $0.006 sandbox estimated; $0.04 total estimated; 175.038 sandbox lifetime s; 177.524 wall s | `pilot/run-2026-10-01c/fsspec__universal_pathlib-261/runs/pilot-fsspec__universal_pathlib-261-ae46b407dd` |
| getmoto__moto-7795 | no | not resolved | refused | not resolved | 217460 tokens; $0.014 model estimated; $0.012 sandbox estimated; $0.026 total estimated; 332.977 sandbox lifetime s; 334.886 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/getmoto__moto-7795/runs/pilot-getmoto__moto-7795-8f3ad1c6e1` |
| giampaolo__psutil-2379 | no | not resolved | refused | not resolved | 76945 tokens; $0.005 model estimated; $0.009 sandbox estimated; $0.014 total estimated; 250.42 sandbox lifetime s; 261.629 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/giampaolo__psutil-2379/runs/pilot-giampaolo__psutil-2379-958602dffe` |
| hypothesisworks__hypothesis-3279 | no | not resolved | verified on appeal | resolved | 1761664 tokens; $0.108 model estimated; $0.013 sandbox estimated; $0.121 total estimated; 346.775 sandbox lifetime s; 358.469 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/hypothesisworks__hypothesis-3279/runs/pilot-hypothesisworks__hypothesis-3279-54ed651553` |
| ipython__traitlets-687 | yes | resolved | verified on first verdict | resolved | 143055 tokens; $0.009 model estimated; $0.005 sandbox estimated; $0.014 total estimated; 136.257 sandbox lifetime s; 173.402 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/ipython__traitlets-687/runs/pilot-ipython__traitlets-687-3608841c8b` |
| ishepard__pydriller-84 | no | not resolved | refused | not resolved | 895621 tokens; $0.056 model estimated; $0.016 sandbox estimated; $0.073 total estimated; 443.805 sandbox lifetime s; 453.683 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/ishepard__pydriller-84/runs/pilot-ishepard__pydriller-84-dedbef44ef` |
| jazzband__pip-tools-822 | no | unavailable | excluded | unavailable | 0 tokens; not available model estimated; $0.016 sandbox estimated; not available total estimated; 433.987 sandbox lifetime s; 435.53 wall s | `pilot/run-2026-10-01c/jazzband__pip-tools-822/runs/pilot-jazzband__pip-tools-822-afe27e2fe2` |
| jelmer__dulwich-1619 | no | not resolved | refused | not resolved | 3044792 tokens; $0.19 model estimated; $0.018 sandbox estimated; $0.208 total estimated; 496.052 sandbox lifetime s; 483.515 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/jelmer__dulwich-1619/runs/pilot-jelmer__dulwich-1619-89c8879b24` |
| jupyter-incubator__sparkmagic-572 | yes | resolved | verified on first verdict | resolved | 32056 tokens; $0.002 model estimated; $0.006 sandbox estimated; $0.008 total estimated; 161.26 sandbox lifetime s; 166.6 wall s | `pilot/run-2026-10-01c/jupyter-incubator__sparkmagic-572/runs/pilot-jupyter-incubator__sparkmagic-572-d46ec7493e` |
| keras-team__keras-19775 | no | unavailable | excluded | unavailable | 0 tokens; not available model estimated; $0.003 sandbox estimated; not available total estimated; 87.57 sandbox lifetime s; 152.479 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/keras-team__keras-19775/runs/pilot-keras-team__keras-19775-069c2e78ac` |
| kinto__kinto-2229 | no | not resolved | refused | not resolved | 703586 tokens; $0.044 model estimated; $0.021 sandbox estimated; $0.065 total estimated; 575.958 sandbox lifetime s; 540.089 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/kinto__kinto-2229/runs/pilot-kinto__kinto-2229-deb78c8b96` |
| leshchenko1979__fast_bitrix24-114 | yes | resolved | verified on first verdict | resolved | 116006 tokens; $0.008 model estimated; $0.006 sandbox estimated; $0.013 total estimated; 156.801 sandbox lifetime s; 196.509 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/leshchenko1979__fast_bitrix24-114/runs/pilot-leshchenko1979__fast_bitrix24-114-8d7fc935c7` |
| litestar-org__polyfactory-422 | no | not resolved | verified on appeal | resolved | 751782 tokens; $0.047 model estimated; $0.011 sandbox estimated; $0.058 total estimated; 298.102 sandbox lifetime s; 291.223 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/litestar-org__polyfactory-422/runs/pilot-litestar-org__polyfactory-422-418a5c67da` |
| marketsquare__robotframework-robocop-1329 | no | not resolved | refused | not resolved | 1357464 tokens; $0.083 model estimated; $0.012 sandbox estimated; $0.094 total estimated; 319.404 sandbox lifetime s; 336.821 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/marketsquare__robotframework-robocop-1329/runs/pilot-marketsquare__robotframework-robocop-1329-92568dbb16` |
| martinthoma__flake8-simplify-173 | no | unavailable | excluded | unavailable | 0 tokens; not available model estimated; $0 sandbox estimated; not available total estimated; 6.437 sandbox lifetime s; 40.244 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/martinthoma__flake8-simplify-173/runs/pilot-martinthoma__flake8-simplify-173-124723af31` |
| materials-consortia__optimade-python-tools-279 | no | not resolved | refused | not resolved | 3436045 tokens; $0.216 model estimated; $0.021 sandbox estimated; $0.237 total estimated; 572.561 sandbox lifetime s; 633.146 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/materials-consortia__optimade-python-tools-279/runs/pilot-materials-consortia__optimade-python-tools-279-bae37207e7` |
| meltano__sdk-3020 | no | not resolved | refused | resolved | 832283 tokens; $0.052 model estimated; $0.01 sandbox estimated; $0.062 total estimated; 279.327 sandbox lifetime s; 309.332 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/meltano__sdk-3020/runs/pilot-meltano__sdk-3020-7162dd748d` |
| modin-project__modin-6673 | no | unavailable | excluded | unavailable | 0 tokens; not available model estimated; $0.022 sandbox estimated; not available total estimated; 607.835 sandbox lifetime s; 609.201 wall s | `pilot/run-2026-10-01c/modin-project__modin-6673/runs/pilot-modin-project__modin-6673-c9e459e5d7` |
| mpmath__mpmath-903 | no | not resolved | refused | not resolved | 141705 tokens; $0.009 model estimated; $0.007 sandbox estimated; $0.016 total estimated; 196.028 sandbox lifetime s; 223.826 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/mpmath__mpmath-903/runs/pilot-mpmath__mpmath-903-fda99c26d8` |
| pallets__click-1964 | yes | resolved | verified on first verdict | resolved | 829328 tokens; $0.051 model estimated; $0.007 sandbox estimated; $0.058 total estimated; 189.993 sandbox lifetime s; 212.649 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/pallets__click-1964/runs/pilot-pallets__click-1964-ac7363ee73` |
| pallets__werkzeug-2709 | yes | resolved | verified on first verdict | resolved | 122301 tokens; $0.008 model estimated; $0.006 sandbox estimated; $0.013 total estimated; 156.157 sandbox lifetime s; 185.515 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/pallets__werkzeug-2709/runs/pilot-pallets__werkzeug-2709-478474470d` |
| pandas-dev__pandas-56926 | no | not resolved | refused | resolved | 2695821 tokens; $0.164 model estimated; $0.07 sandbox estimated; $0.234 total estimated; 1887.183 sandbox lifetime s; 1750.907 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/pandas-dev__pandas-56926/runs/pilot-pandas-dev__pandas-56926-9fac1af8c2` |
| pdm-project__pdm-2123 | yes | not resolved | refused | not resolved | 423301 tokens; $0.026 model estimated; $0.037 sandbox estimated; $0.063 total estimated; 1005.706 sandbox lifetime s; 846.372 wall s | `pilot/run-2026-10-01c/pdm-project__pdm-2123/runs/pilot-pdm-project__pdm-2123-7221bda164` |
| pennylaneai__pennylane-2834 | no | not resolved | refused | not resolved | 1808208 tokens; $0.111 model estimated; $0.014 sandbox estimated; $0.125 total estimated; 376.127 sandbox lifetime s; 349.82 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/pennylaneai__pennylane-2834/runs/pilot-pennylaneai__pennylane-2834-221ea15711` |
| py-pdf__pypdf2-1318 | no | not resolved | shipped false done | not resolved | 1388635 tokens; $0.085 model estimated; $0.015 sandbox estimated; $0.101 total estimated; 414.019 sandbox lifetime s; 434.922 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/py-pdf__pypdf2-1318/runs/pilot-py-pdf__pypdf2-1318-b7d07b97ca` |
| pyccel__pyccel-2151 | no | unavailable | excluded | unavailable | 0 tokens; not available model estimated; $0.002 sandbox estimated; not available total estimated; 57.204 sandbox lifetime s; 89.712 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/pyccel__pyccel-2151/runs/pilot-pyccel__pyccel-2151-16d3308430` |
| pytest-dev__pyfakefs-1075 | yes | resolved | verified on first verdict | resolved | 39793 tokens; $0.003 model estimated; $0.005 sandbox estimated; $0.008 total estimated; 138.285 sandbox lifetime s; 178.076 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/pytest-dev__pyfakefs-1075/runs/pilot-pytest-dev__pyfakefs-1075-b8124f683a` |
| python-babel__babel-505 | yes | resolved | verified on first verdict | resolved | 307650 tokens; $0.02 model estimated; $0.013 sandbox estimated; $0.033 total estimated; 344.163 sandbox lifetime s; 358.298 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/python-babel__babel-505/runs/pilot-python-babel__babel-505-bf5ee86e17` |
| python-markdown__markdown-1361 | yes | resolved | verified on first verdict | resolved | 106164 tokens; $0.007 model estimated; $0.004 sandbox estimated; $0.011 total estimated; 110.205 sandbox lifetime s; 139.411 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/python-markdown__markdown-1361/runs/pilot-python-markdown__markdown-1361-b0b86193cc` |
| qiskit__qiskit-12528 | no | not resolved | refused | not resolved | 641545 tokens; $0.041 model estimated; $0.097 sandbox estimated; $0.138 total estimated; 2609.229 sandbox lifetime s; 2205.617 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/qiskit__qiskit-12528/runs/pilot-qiskit__qiskit-12528-54b6ba5a95` |
| qiskit__qiskit-ibm-runtime-452 | no | resolved | refused | resolved | 885519 tokens; $0.056 model estimated; $0.012 sandbox estimated; $0.068 total estimated; 318.869 sandbox lifetime s; 308.228 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/qiskit__qiskit-ibm-runtime-452/runs/pilot-qiskit__qiskit-ibm-runtime-452-388a6c711e` |
| radioastronomysoftwaregroup__pyuvdata-724 | yes | resolved | verified on first verdict | resolved | 26205 tokens; $0.002 model estimated; $0.013 sandbox estimated; $0.015 total estimated; 358.114 sandbox lifetime s; 349.959 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/radioastronomysoftwaregroup__pyuvdata-724/runs/pilot-radioastronomysoftwaregroup__pyuvdata-724-860a10de44` |
| redis__redis-py-1895 | no | unavailable | excluded | unavailable | 0 tokens; not available model estimated; $0 sandbox estimated; not available total estimated; 3.836 sandbox lifetime s; 34.247 wall s | `pilot/run-2026-10-01c/redis__redis-py-1895/runs/pilot-redis__redis-py-1895-0cb63c5305` |
| sanic-org__sanic-ext-161 | no | resolved | verified on first verdict | resolved | 701484 tokens; $0.044 model estimated; $0.007 sandbox estimated; $0.051 total estimated; 199.425 sandbox lifetime s; 224.958 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/sanic-org__sanic-ext-161/runs/pilot-sanic-org__sanic-ext-161-28ef972c3b` |
| scikit-build__scikit-build-core-254 | yes | resolved | verified on first verdict | resolved | 132683 tokens; $0.009 model estimated; $0.002 sandbox estimated; $0.011 total estimated; 66.266 sandbox lifetime s; 68.134 wall s | `pilot/run-2026-10-01c/scikit-build__scikit-build-core-254/runs/pilot-scikit-build__scikit-build-core-254-6815e5e271` |
| scrapy__scrapy-3840 | yes | resolved | verified on first verdict | resolved | 214436 tokens; $0.014 model estimated; $0.007 sandbox estimated; $0.021 total estimated; 187.779 sandbox lifetime s; 219.821 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/scrapy__scrapy-3840/runs/pilot-scrapy__scrapy-3840-5fe781168b` |
| senth__minecraft-mod-manager-36 | yes | resolved | verified on first verdict | resolved | 33167 tokens; $0.002 model estimated; $0.005 sandbox estimated; $0.007 total estimated; 137.647 sandbox lifetime s; 139.586 wall s | `pilot/run-2026-10-01c/senth__minecraft-mod-manager-36/runs/pilot-senth__minecraft-mod-manager-36-64ad25dc12` |
| sparckles__robyn-1002 | no | resolved | verified on appeal | resolved | 1131404 tokens; $0.069 model estimated; $0.144 sandbox estimated; $0.213 total estimated; 3888.833 sandbox lifetime s; 3479.419 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/sparckles__robyn-1002/runs/pilot-sparckles__robyn-1002-f0626d0b22` |
| textualize__rich-2201 | yes | not resolved | refused | not resolved | 828462 tokens; $0.051 model estimated; $0.012 sandbox estimated; $0.063 total estimated; 333.668 sandbox lifetime s; 335.466 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/textualize__rich-2201/runs/pilot-textualize__rich-2201-d74bfda219` |
| tox-dev__sphinx-autodoc-typehints-294 | no | not resolved | refused | not resolved | 801647 tokens; $0.05 model estimated; $0.008 sandbox estimated; $0.059 total estimated; 228.56 sandbox lifetime s; 247.053 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/tox-dev__sphinx-autodoc-typehints-294/runs/pilot-tox-dev__sphinx-autodoc-typehints-294-fc6fd1b452` |
| vyperlang__vyper-3261 | no | not resolved | gate error | not resolved | 585407 tokens; $0.037 model estimated; $0.012 sandbox estimated; $0.049 total estimated; 311.983 sandbox lifetime s; 334.037 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/vyperlang__vyper-3261/runs/pilot-vyperlang__vyper-3261-f1b904e620` |
| zoofio__flexx-236 | yes | resolved | verified on first verdict | resolved | 354125 tokens; $0.022 model estimated; $0.006 sandbox estimated; $0.028 total estimated; 174.226 sandbox lifetime s; 209.411 wall s | `/Users/sunzeyu/Documents/nebius-hackathon/pilot/run-2026-10-01c/zoofio__flexx-236/runs/pilot-zoofio__flexx-236-1033c1b54b` |
