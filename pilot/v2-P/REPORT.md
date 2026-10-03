# 17.9 percent of an unguarded agent's 'done' was false; Receipts shipped zero.

## Screening

### `pilot/v2-screen-P.jsonl`

Included: 110; rule 4 exclusions: 6; rule 5 exclusions: 1; final infrastructure errors: 2; malformed rows: 0.

| Position | Instance | Result | Reason | Failing ids |
| ---: | --- | --- | --- | --- |
| 59 | rhayes777__pyautofit-888 | included |  |  |
| 60 | slackapi__python-slack-sdk-1703 | excluded under rule 4 | target tests did not fail in every baseline run: tests/slack_sdk_async/web/test_web_client_coverage.py::TestWebClientCoverage::test_coverage -> ['tests/slack_sdk_async/web/test_web_client_coverage.py::TestWebClientCoverage::test_coverage']; tests/slack_sdk_async/web/test_web_client_coverage.py::TestWebClientCoverage::test_legacy_coverage -> ['tests/slack_sdk_async/web/test_web_client_coverage.py::TestWebClientCoverage::test_legacy_coverage'] | tests/slack_sdk_async/web/test_web_client_coverage.py::TestWebClientCoverage::test_coverage, tests/slack_sdk_async/web/test_web_client_coverage.py::TestWebClientCoverage::test_legacy_coverage |
| 61 | deshaw__pyflyby-289 | included |  |  |
| 62 | azure__walinuxagent-638 | included |  |  |
| 63 | 3yourmind__django-migration-linter-258 | included |  |  |
| 64 | openmdao__openmdao-3029 | included |  |  |
| 65 | rq__rq-1947 | excluded under rule 5 | not gradeable in this environment: PASS_TO_PASS did not pass: tests/test_worker.py::TestWorker::test_clean_queue_registries, tests/test_worker.py::TestWorker::test_create_worker, tests/test_worker.py::TestWorker::test_custom_exc_handling, tests/test_worker.py::TestWorker::test_custom_job_class, tests/test_worker.py::TestWorker::test_custom_job_class_is_not_global, tests/test_worker.py::TestWorker::test_custom_queue_class, tests/test_worker.py::TestWorker::test_custom_queue_class_is_not_global, tests/test_worker.py::TestWorker::test_deleted_jobs_arent_executed, tests/test_worker.py::TestWorker::test_dequeue_job_and_maintain_ttl_non_blocking, tests/test_worker.py::TestWorker::test_dequeue_random_strategy, tests/test_worker.py::TestWorker::test_dequeue_round_robin, tests/test_worker.py::TestWorker::test_deserializing_failure_is_handled, tests/test_worker.py::TestWorker::test_disable_default_exception_handler, tests/test_worker.py::TestWorker::test_find_by_key, tests/test_worker.py::TestWorker::test_get_current_job, tests/test_worker.py::TestWorker::test_handle_retry, tests/test_worker.py::TestWorker::test_heartbeat, tests/test_worker.py::TestWorker::test_horse_fails, tests/test_worker.py::HerokuWorkerShutdownTestCase::test_handle_shutdown_request, tests/test_worker.py::HerokuWorkerShutdownTestCase::test_handle_shutdown_request_no_horse | tests/test_worker.py::TestWorker::test_clean_queue_registries, tests/test_worker.py::TestWorker::test_create_worker, tests/test_worker.py::TestWorker::test_custom_exc_handling, tests/test_worker.py::TestWorker::test_custom_job_class, tests/test_worker.py::TestWorker::test_custom_job_class_is_not_global, tests/test_worker.py::TestWorker::test_custom_queue_class, tests/test_worker.py::TestWorker::test_custom_queue_class_is_not_global, tests/test_worker.py::TestWorker::test_deleted_jobs_arent_executed, tests/test_worker.py::TestWorker::test_dequeue_job_and_maintain_ttl_non_blocking, tests/test_worker.py::TestWorker::test_dequeue_random_strategy, tests/test_worker.py::TestWorker::test_dequeue_round_robin, tests/test_worker.py::TestWorker::test_deserializing_failure_is_handled, tests/test_worker.py::TestWorker::test_disable_default_exception_handler, tests/test_worker.py::TestWorker::test_find_by_key, tests/test_worker.py::TestWorker::test_get_current_job, tests/test_worker.py::TestWorker::test_handle_retry, tests/test_worker.py::TestWorker::test_heartbeat, tests/test_worker.py::TestWorker::test_horse_fails, tests/test_worker.py::HerokuWorkerShutdownTestCase::test_handle_shutdown_request, tests/test_worker.py::HerokuWorkerShutdownTestCase::test_handle_shutdown_request_no_horse |
| 66 | pyfilesystem__pyfilesystem2-462 | included |  |  |
| 67 | pytask-dev__pytask-519 | included |  |  |
| 68 | niconoe__pyinaturalist-72 | included |  |  |
| 69 | robotframework__seleniumlibrary-1431 | included |  |  |
| 70 | palantir__python-language-server-829 | included |  |  |
| 71 | stac-utils__stac-fastapi-729 | included |  |  |
| 72 | gitpython-developers__gitpython-1832 | included |  |  |
| 73 | scitools__cartopy-2307 | included |  |  |
| 74 | kubernetes-client__python-1933 | included |  |  |
| 75 | datadog__datadogpy-555 | included |  |  |
| 76 | callowayproject__bump-my-version-180 | included |  |  |
| 77 | opensearch-project__opensearch-py-843 | included |  |  |
| 78 | stac-utils__pystac-client-782 | included |  |  |
| 79 | sdv-dev__rdt-704 | included |  |  |
| 80 | dpkp__kafka-python-2119 | excluded under rule 4 | target tests did not fail in every baseline run: test/test_producer.py::test_buffer_pool -> ['test/test_producer.py::test_buffer_pool']; test/test_producer.py::test_kafka_producer_gc_cleanup -> ['test/test_producer.py::test_kafka_producer_gc_cleanup'] | test/test_producer.py::test_buffer_pool, test/test_producer.py::test_kafka_producer_gc_cleanup |
| 81 | pybamm-team__pybamm-4196 | included |  |  |
| 82 | aspp__pelita-798 | included |  |  |
| 83 | zopefoundation__btrees-163 | included |  |  |
| 84 | skypyproject__skypy-573 | included |  |  |
| 85 | jnothman__upsetplot-253 | included |  |  |
| 86 | jupyter__jupyter_client-994 | excluded under rule 4 | target tests did not fail in every baseline run: tests/test_runapp.py::test_runapp -> ['tests/test_runapp.py::test_runapp'] | tests/test_runapp.py::test_runapp |
| 87 | dask__dask-5861 | included |  |  |
| 88 | qutech__qupulse-797 | included |  |  |
| 89 | bloomberg__memray-552 | included |  |  |
| 90 | mondeja__mkdocs-include-markdown-plugin-51 | included |  |  |
| 91 | more-itertools__more-itertools-892 | included |  |  |
| 92 | yukinarit__pyserde-430 | included |  |  |
| 93 | pycqa__pyflakes-335 | included |  |  |
| 94 | azuread__microsoft-authentication-library-for-python-186 | included |  |  |
| 95 | natcap__invest-787 | included |  |  |
| 96 | igorbenav__fastcrud-69 | included |  |  |
| 97 | researchobject__ro-crate-py-192 | included |  |  |
| 98 | neogeny__tatsu-320 | included |  |  |
| 99 | networkx__networkx-3101 | included |  |  |
| 100 | neurodatawithoutborders__pynwb-2052 | included |  |  |
| 101 | vacanza__holidays-2106 | included |  |  |
| 102 | qiskit-community__ecosystem-159 | included |  |  |
| 103 | theacodes__nox-466 | included |  |  |
| 104 | encode__django-rest-framework-8979 | included |  |  |
| 105 | samuelcolvin__pydantic-2806 | included |  |  |
| 106 | pgmpy__pgmpy-878 | included |  |  |
| 107 | rochacbruno__dynaconf-191 | included |  |  |
| 108 | mirumee__ariadne-codegen-159 | included |  |  |
| 109 | ntnu-ihb__pythonfmu-158 | included |  |  |
| 110 | openmdao__aviary-807 | included |  |  |
| 111 | kozea__weasyprint-2087 | included |  |  |
| 112 | pypa__pipx-1350 | included |  |  |
| 113 | educationaltestingservice__rsmtool-669 | included |  |  |
| 114 | yt-dlp__yt-dlp-13361 | included |  |  |
| 115 | twisted__pydoctor-191 | included |  |  |
| 116 | hhursev__recipe-scrapers-1230 | included |  |  |
| 117 | pymor__pymor-810 | included |  |  |
| 118 | dhi__mikeio-227 | final infrastructure error | RuntimeError: image not in the Token Factory Sandboxes catalogue: swerebenchv2/dhi-mikeio:227-50037f2 |  |
| 119 | pydap__pydap-502 | excluded under rule 4 | baseline suite took 0s, over the limit |  |
| 120 | pycqa__docformatter-104 | included |  |  |
| 121 | tdameritrade__stumpy-789 | excluded under rule 4 | baseline suite took 0s, over the limit |  |
| 122 | caikit__caikit-438 | included |  |  |
| 123 | crewaiinc__crewai-2552 | included |  |  |
| 124 | apluslms__a-plus-1199 | included |  |  |
| 125 | quora__pyanalyze-688 | included |  |  |
| 126 | sfdo-tooling__cumulusci-3624 | included |  |  |
| 127 | aws-cloudformation__cfn-python-lint-2006 | included |  |  |
| 128 | cs-si__eodag-380 | included |  |  |
| 129 | stac-utils__pystac-561 | included |  |  |
| 130 | gammapy__gammapy-5342 | included |  |  |
| 131 | wtforms__wtforms-596 | included |  |  |
| 132 | codezonediitj__pydatastructs-163 | included |  |  |
| 133 | python__typing_extensions-157 | included |  |  |
| 134 | ecmwf__earthkit-data-285 | included |  |  |
| 135 | s-knibbs__dataclasses-jsonschema-93 | included |  |  |
| 136 | enthought__traits-1534 | included |  |  |
| 137 | galileo-galilei__kedro-mlflow-585 | included |  |  |
| 138 | elastic__curator-750 | included |  |  |
| 139 | pyg-team__pytorch_geometric-7654 | included |  |  |
| 140 | pymodbus-dev__pymodbus-2502 | included |  |  |
| 141 | tqdm__tqdm-49 | included |  |  |
| 142 | msgpack__msgpack-python-331 | included |  |  |
| 143 | pythainlp__pythainlp-1056 | included |  |  |
| 144 | virtuslab__git-machete-179 | included |  |  |
| 145 | rock-learning__pytransform3d-48 | included |  |  |
| 146 | opendatacube__odc-geo-121 | included |  |  |
| 147 | ansys__pyansys-geometry-941 | excluded under rule 4 | first baseline run is not a valid pytest run (exit 4, junit=missing) |  |
| 148 | jsonpickle__jsonpickle-501 | included |  |  |
| 149 | ethereum__web3.py-2023 | included |  |  |
| 150 | pyfar__pyfar-58 | included |  |  |
| 151 | robotpy__cxxheaderparser-82 | included |  |  |
| 152 | pipxproject__pipx-680 | included |  |  |
| 153 | ericmjl__pyjanitor-728 | included |  |  |
| 154 | dai-lab__copulas-87 | included |  |  |
| 155 | mie-lab__trackintel-344 | included |  |  |
| 156 | cuthbertlab__music21-1775 | included |  |  |
| 157 | pints-team__pints-1444 | included |  |  |
| 158 | qiskit__qiskit-terra-8799 | included |  |  |
| 159 | datalad__datalad-5603 | included |  |  |
| 160 | systemd__mkosi-3346 | included |  |  |
| 161 | maas__python-libmaas-219 | included |  |  |
| 162 | crossgl__crosstl-202 | included |  |  |
| 163 | chezou__tabula-py-135 | included |  |  |
| 164 | astropy__ccdproc-867 | included |  |  |
| 165 | awslabs__cfn-python-lint-644 | final infrastructure error | RuntimeError: image not in the Token Factory Sandboxes catalogue: swerebenchv2/awslabs-cfn-python-lint:644-387836c |  |
| 166 | pennersr__django-allauth-3447 | included |  |  |
| 167 | ungarj__mapchete-685 | included |  |  |
| 168 | qutip__qutip-2561 | included |  |  |
| 169 | planetlabs__planet-client-python-81 | included |  |  |
| 170 | bluesky__bluesky-1702 | included |  |  |
| 171 | sdispater__tomlkit-68 | included |  |  |
| 172 | frictionlessdata__tabulator-py-129 | included |  |  |
| 173 | google__jax-22744 | included |  |  |
| 174 | labgrid-project__labgrid-1558 | included |  |  |
| 175 | oceanparcels__parcels-541 | included |  |  |
| 176 | fatiando__harmonica-491 | included |  |  |
| 177 | pvlib__pvlib-python-253 | included |  |  |

## Spend

| Run class | Runs | Model dollars | Token Factory reported sandbox cost (unit not published) |
| --- | ---: | ---: | ---: |
| Final | 100 | $26.772 | 62.436 |
| Infrastructure error | 6 | $0 | 1.072 |
| Interrupted | 7 | $0.24 | 0.233 |
| All runs | 113 | $27.012 | 63.741 |

Unreadable archives: 0.
All runs includes final agent runs and every readable infrastructure-error and interrupted archive.
The sandbox figure is the per-run `cost` that Token Factory Sandboxes report. Token Factory does not publish the unit or a price during the beta, so the figure is shown as reported, not as dollars, and no dollar total is given.

## Unguarded agent (A)

Claimed dones: 67.

False-done rate: 17.9% (12 of 67), Wilson 95% CI 10.6% to 28.7%.

False dones accepted by the naive green check: 6.

A false done can appear in more than one breakdown row.

| Kind | False dones |
| --- | ---: |
| Spec still failing (R1) | 8 |
| Regression (R2) | 4 |
| Tests removed or newly skipped (R3) | 0 |
| Test or config edited (R4) | 5 |
| Tests never run on the final state | 2 |

## Receipts (B)

| Result | Count |
| --- | ---: |
| Verified fixes | 66 |
| Verified on first verdict | 59 |
| Verified on appeal | 7 |
| Shipped false dones | 0 |

Verified-fix rate: 66% (66 of 100), Wilson 95% CI 56.3% to 74.5%.

### Cost per verified fix

Model dollars, sandbox cost, tokens and sandbox lifetime use all readable final, infrastructure-error and interrupted runs.

Model dollars estimate Token Factory token usage. The sandbox figure is the per-run `cost` that Token Factory Sandboxes report. Token Factory does not publish the unit or a price during the beta, so the figure is shown as reported, not as dollars, and no dollar total is given.

| Model dollars (estimated) | Token Factory reported sandbox cost (unit not published) | Tokens | Sandbox lifetime seconds | Wall seconds |
| ---: | ---: | ---: | ---: | ---: |
| 0.409 | 0.966 | 1335820.227 | 301.915 | 583.294 |

### Rehearsal measurements

Peak live sandboxes: 4 at 2026-10-03T01:20:44.058132+00:00.

Records without sandbox intervals: 2.

Model retries: none.

## Harness

Total tool calls: 4076.

Edit-failure rate (edit calls that did not apply, over all edit calls): 107 of 720 (14.9%).

Context guard: 0 turns; 0 messages replaced.

Attempts that ended on a budget: 30 on turns, 0 on wall time, 0 on completion tokens, 0 not recorded.

0 turns not recorded (worker rows before result logging).

1 worker log unreadable or missing; 0 unreadable rows skipped.

### Result classes

| Class | Calls |
| --- | ---: |
| bad_args | 30 |
| command_timeout | 0 |
| edit_invalid_utf8 | 0 |
| edit_multiple_matches | 23 |
| edit_no_match | 77 |
| edit_too_large | 0 |
| finish_refused | 0 |
| malformed_args | 0 |
| nonzero_exit | 599 |
| not_executed | 0 |
| noted | 10 |
| ok | 3319 |
| tool_error | 0 |
| unknown_tool | 14 |
| write_refused | 4 |

### Alias calls

| Alias | Calls |
| --- | ---: |
| execute | 377 |
| execute_command | 179 |
| execute_grep | 6 |
| str_replace | 55 |
| str_replace_editor | 31 |

## Shipped bytes

Shipped bytes: digests agree on 141 of 141 attempts.

0 attempts not recorded (records before this check).

Mismatches: none.

## Gate and official-grader agreement

| Gate status | Official resolved | Official not resolved | Official unavailable |
| --- | ---: | ---: | ---: |
| PASS | 66 | 0 | 0 |
| REJECTED | 3 | 72 | 0 |
| ERROR | 0 | 0 | 0 |

### Disagreements and gate errors

| Instance | Attempt | Classification | Failed predicates | Gate error |
| --- | ---: | --- | --- | --- |
| codezonediitj__pydatastructs-163 | 2 | gate_stricter | R4_patch_scope | none |
| datalad__datalad-5603 | 1 | gate_stricter | R3_no_shrink | none |
| datalad__datalad-5603 | 2 | gate_stricter | R3_no_shrink | none |

## Exclusions

None.

## Infrastructure errors

| Instance | Reason | Run directory |
| --- | --- | --- |
| cuthbertlab__music21-1775 | RuntimeError: Token Factory download of /tmp/receipts-b8ec76b8344e417fa09a2e145bef4953.tar exceeds size cap of 536870912 bytes: at least 536874348 bytes | `pilot/v2-P/cuthbertlab__music21-1775/runs/pilot-cuthbertlab__music21-1775-79ea50d41f` |
| cuthbertlab__music21-1775 | RuntimeError: Token Factory download of /tmp/receipts-434553a710ac4e4886c9da2e8a1d5e3f.tar exceeds size cap of 536870912 bytes: at least 536871549 bytes | `pilot/v2-P/cuthbertlab__music21-1775/runs/pilot-cuthbertlab__music21-1775-b3ade337ba` |
| cuthbertlab__music21-1775 | RuntimeError: Token Factory download of /tmp/receipts-af4d93a07b9349bbb294b58a3869f75a.tar exceeds size cap of 536870912 bytes: at least 536872291 bytes | `pilot/v2-P/cuthbertlab__music21-1775/runs/pilot-cuthbertlab__music21-1775-226bec556e` |
| natcap__invest-787 | RuntimeError: test digest command returned invalid JSON | `pilot/v2-P/natcap__invest-787/runs/pilot-natcap__invest-787-15b2165209` |
| natcap__invest-787 | RuntimeError: test digest command returned invalid JSON | `pilot/v2-P/natcap__invest-787/runs/pilot-natcap__invest-787-668f3f2c44` |
| natcap__invest-787 | RuntimeError: test digest command returned invalid JSON | `pilot/v2-P/natcap__invest-787/runs/pilot-natcap__invest-787-c12b32de7f` |

## Cleanup errors

None.

## Per instance

| Instance | A claimed done | A official | B outcome | B official | Cost | Run directory |
| --- | --- | --- | --- | --- | --- | --- |
| 3yourmind__django-migration-linter-258 | yes | resolved | verified on first verdict | resolved | 29419 tokens; $0.009 model estimated; 0.044 Token Factory reported cost, unit not published; 50.153 sandbox lifetime s; 68.63 wall s | `pilot/v2-P/3yourmind__django-migration-linter-258/runs/pilot-3yourmind__django-migration-linter-258-ad18c930bb` |
| apluslms__a-plus-1199 | no | not resolved | refused | not resolved | 1237602 tokens; $0.391 model estimated; 2.697 Token Factory reported cost, unit not published; 539.393 sandbox lifetime s; 900.486 wall s | `pilot/v2-P/apluslms__a-plus-1199/runs/pilot-apluslms__a-plus-1199-4caba45e35` |
| aspp__pelita-798 | yes | resolved | verified on first verdict | resolved | 512988 tokens; $0.157 model estimated; 0.094 Token Factory reported cost, unit not published; 75.634 sandbox lifetime s; 176.283 wall s | `pilot/v2-P/aspp__pelita-798/runs/pilot-aspp__pelita-798-01d637e964` |
| astropy__ccdproc-867 | yes | resolved | verified on first verdict | resolved | 29823 tokens; $0.009 model estimated; 0.238 Token Factory reported cost, unit not published; 80.19 sandbox lifetime s; 126.933 wall s | `pilot/v2-P/astropy__ccdproc-867/runs/pilot-astropy__ccdproc-867-b8a6e1503c` |
| aws-cloudformation__cfn-python-lint-2006 | no | not resolved | refused | not resolved | 1402213 tokens; $0.43 model estimated; 0.492 Token Factory reported cost, unit not published; 245.023 sandbox lifetime s; 842.324 wall s | `pilot/v2-P/aws-cloudformation__cfn-python-lint-2006/runs/pilot-aws-cloudformation__cfn-python-lint-2006-9d79ca1c37` |
| azure__walinuxagent-638 | yes | not resolved | refused | not resolved | 1161077 tokens; $0.355 model estimated; 0.118 Token Factory reported cost, unit not published; 159.313 sandbox lifetime s; 341.36 wall s | `pilot/v2-P/azure__walinuxagent-638/runs/pilot-azure__walinuxagent-638-32193fb72a` |
| azuread__microsoft-authentication-library-for-python-186 | no | resolved | verified on first verdict | resolved | 1374492 tokens; $0.424 model estimated; 0.128 Token Factory reported cost, unit not published; 157.457 sandbox lifetime s; 364.838 wall s | `pilot/v2-P/azuread__microsoft-authentication-library-for-python-186/runs/pilot-azuread__microsoft-authentication-library-for-py-6e4e84f263` |
| bloomberg__memray-552 | no | not resolved | refused | not resolved | 229268 tokens; $0.073 model estimated; 1.88 Token Factory reported cost, unit not published; 464.168 sandbox lifetime s; 1128.422 wall s | `pilot/v2-P/bloomberg__memray-552/runs/pilot-bloomberg__memray-552-e7dba23977` |
| caikit__caikit-438 | yes | resolved | verified on first verdict | resolved | 432034 tokens; $0.133 model estimated; 0.391 Token Factory reported cost, unit not published; 147.212 sandbox lifetime s; 246.715 wall s | `pilot/v2-P/caikit__caikit-438/runs/pilot-caikit__caikit-438-c78e6c9839` |
| callowayproject__bump-my-version-180 | yes | resolved | verified on first verdict | resolved | 309931 tokens; $0.097 model estimated; 0.145 Token Factory reported cost, unit not published; 87.207 sandbox lifetime s; 165.709 wall s | `pilot/v2-P/callowayproject__bump-my-version-180/runs/pilot-callowayproject__bump-my-version-180-d9d7632c82` |
| chezou__tabula-py-135 | yes | resolved | verified on first verdict | resolved | 52174 tokens; $0.016 model estimated; 2.924 Token Factory reported cost, unit not published; 164.197 sandbox lifetime s; 233.419 wall s | `pilot/v2-P/chezou__tabula-py-135/runs/pilot-chezou__tabula-py-135-7f3e33193b` |
| codezonediitj__pydatastructs-163 | yes | not resolved | refused | resolved | 241022 tokens; $0.076 model estimated; 0.085 Token Factory reported cost, unit not published; 110.656 sandbox lifetime s; 189.11 wall s | `pilot/v2-P/codezonediitj__pydatastructs-163/runs/pilot-codezonediitj__pydatastructs-163-079dbe7239` |
| crewaiinc__crewai-2552 | yes | resolved | verified on first verdict | resolved | 106585 tokens; $0.033 model estimated; 0.445 Token Factory reported cost, unit not published; 122.008 sandbox lifetime s; 285.821 wall s | `pilot/v2-P/crewaiinc__crewai-2552/runs/pilot-crewaiinc__crewai-2552-97d137fc0f` |
| crossgl__crosstl-202 | yes | resolved | verified on first verdict | resolved | 182157 tokens; $0.057 model estimated; 0.048 Token Factory reported cost, unit not published; 70.318 sandbox lifetime s; 126.571 wall s | `pilot/v2-P/crossgl__crosstl-202/runs/pilot-crossgl__crosstl-202-cecd7c5aee` |
| cs-si__eodag-380 | no | not resolved | verified on appeal | resolved | 3947691 tokens; $1.201 model estimated; 1.949 Token Factory reported cost, unit not published; 438.65 sandbox lifetime s; 922.997 wall s | `pilot/v2-P/cs-si__eodag-380/runs/pilot-cs-si__eodag-380-5181759cfe` |
| cuthbertlab__music21-1775 | no | unavailable | infrastructure error | unavailable | 0 tokens; not available model estimated; 0.314 Token Factory reported cost, unit not published; 157.52 sandbox lifetime s; 429.759 wall s | `pilot/v2-P/cuthbertlab__music21-1775/runs/pilot-cuthbertlab__music21-1775-226bec556e` |
| dai-lab__copulas-87 | yes | resolved | verified on first verdict | resolved | 120467 tokens; $0.038 model estimated; 0.085 Token Factory reported cost, unit not published; 67.035 sandbox lifetime s; 114.109 wall s | `pilot/v2-P/dai-lab__copulas-87/runs/pilot-dai-lab__copulas-87-1b3f3b0728` |
| dask__dask-5861 | yes | resolved | verified on first verdict | resolved | 34580 tokens; $0.011 model estimated; 0.055 Token Factory reported cost, unit not published; 51.017 sandbox lifetime s; 110.689 wall s | `pilot/v2-P/dask__dask-5861/runs/pilot-dask__dask-5861-afdf49683a` |
| datadog__datadogpy-555 | yes | resolved | verified on first verdict | resolved | 50540 tokens; $0.016 model estimated; 0.053 Token Factory reported cost, unit not published; 55.482 sandbox lifetime s; 95.902 wall s | `pilot/v2-P/datadog__datadogpy-555/runs/pilot-datadog__datadogpy-555-8e5399c81a` |
| datalad__datalad-5603 | yes | resolved | refused | resolved | 86405 tokens; $0.027 model estimated; 0.153 Token Factory reported cost, unit not published; 87.222 sandbox lifetime s; 149.941 wall s | `pilot/v2-P/datalad__datalad-5603/runs/pilot-datalad__datalad-5603-ad232ce16e` |
| deshaw__pyflyby-289 | yes | resolved | verified on first verdict | resolved | 136861 tokens; $0.042 model estimated; 0.121 Token Factory reported cost, unit not published; 86.574 sandbox lifetime s; 129.482 wall s | `pilot/v2-P/deshaw__pyflyby-289/runs/pilot-deshaw__pyflyby-289-69ddfeb637` |
| ecmwf__earthkit-data-285 | yes | resolved | verified on first verdict | resolved | 531314 tokens; $0.164 model estimated; 0.461 Token Factory reported cost, unit not published; 173.597 sandbox lifetime s; 298.179 wall s | `pilot/v2-P/ecmwf__earthkit-data-285/runs/pilot-ecmwf__earthkit-data-285-d31b6dc3c8` |
| educationaltestingservice__rsmtool-669 | yes | resolved | verified on first verdict | resolved | 1241861 tokens; $0.381 model estimated; 1.306 Token Factory reported cost, unit not published; 348.783 sandbox lifetime s; 1056.944 wall s | `pilot/v2-P/educationaltestingservice__rsmtool-669/runs/pilot-educationaltestingservice__rsmtool-669-6adb29f8a0` |
| elastic__curator-750 | no | not resolved | refused | not resolved | 1083623 tokens; $0.331 model estimated; 0.092 Token Factory reported cost, unit not published; 221.998 sandbox lifetime s; 406.463 wall s | `pilot/v2-P/elastic__curator-750/runs/pilot-elastic__curator-750-7088759c68` |
| encode__django-rest-framework-8979 | yes | not resolved | verified on appeal | resolved | 750248 tokens; $0.23 model estimated; 0.233 Token Factory reported cost, unit not published; 138.925 sandbox lifetime s; 338.705 wall s | `pilot/v2-P/encode__django-rest-framework-8979/runs/pilot-encode__django-rest-framework-8979-fcdf40c1c2` |
| enthought__traits-1534 | no | not resolved | verified on appeal | resolved | 2252182 tokens; $0.687 model estimated; 0.197 Token Factory reported cost, unit not published; 173.883 sandbox lifetime s; 459.894 wall s | `pilot/v2-P/enthought__traits-1534/runs/pilot-enthought__traits-1534-57d7df053e` |
| ericmjl__pyjanitor-728 | yes | resolved | verified on first verdict | resolved | 365677 tokens; $0.115 model estimated; 0.509 Token Factory reported cost, unit not published; 142.753 sandbox lifetime s; 279.5 wall s | `pilot/v2-P/ericmjl__pyjanitor-728/runs/pilot-ericmjl__pyjanitor-728-65b2a91a53` |
| ethereum__web3.py-2023 | yes | resolved | verified on first verdict | resolved | 351006 tokens; $0.109 model estimated; 0.129 Token Factory reported cost, unit not published; 87.625 sandbox lifetime s; 196.288 wall s | `pilot/v2-P/ethereum__web3.py-2023/runs/pilot-ethereum__web3.py-2023-09fbbfb992` |
| galileo-galilei__kedro-mlflow-585 | yes | resolved | verified on first verdict | resolved | 411997 tokens; $0.128 model estimated; 5.963 Token Factory reported cost, unit not published; 910.501 sandbox lifetime s; 995.71 wall s | `pilot/v2-P/galileo-galilei__kedro-mlflow-585/runs/pilot-galileo-galilei__kedro-mlflow-585-47880c35de` |
| gammapy__gammapy-5342 | no | not resolved | refused | not resolved | 507062 tokens; $0.157 model estimated; 1.104 Token Factory reported cost, unit not published; 255.755 sandbox lifetime s; 401.96 wall s | `pilot/v2-P/gammapy__gammapy-5342/runs/pilot-gammapy__gammapy-5342-56a1561ee1` |
| gitpython-developers__gitpython-1832 | no | not resolved | refused | not resolved | 1748144 tokens; $0.532 model estimated; 0.238 Token Factory reported cost, unit not published; 168.957 sandbox lifetime s; 490.047 wall s | `pilot/v2-P/gitpython-developers__gitpython-1832/runs/pilot-gitpython-developers__gitpython-1832-9be4fcf360` |
| hhursev__recipe-scrapers-1230 | yes | resolved | verified on first verdict | resolved | 135712 tokens; $0.042 model estimated; 0.111 Token Factory reported cost, unit not published; 92.987 sandbox lifetime s; 435.04 wall s | `pilot/v2-P/hhursev__recipe-scrapers-1230/runs/pilot-hhursev__recipe-scrapers-1230-faeaaa2d11` |
| igorbenav__fastcrud-69 | no | not resolved | refused | not resolved | 3705461 tokens; $1.123 model estimated; 0.497 Token Factory reported cost, unit not published; 194.077 sandbox lifetime s; 543.05 wall s | `pilot/v2-P/igorbenav__fastcrud-69/runs/pilot-igorbenav__fastcrud-69-e8d0d0ccb6` |
| jnothman__upsetplot-253 | no | not resolved | refused | not resolved | 772187 tokens; $0.238 model estimated; 1.244 Token Factory reported cost, unit not published; 250.078 sandbox lifetime s; 415.66 wall s | `pilot/v2-P/jnothman__upsetplot-253/runs/pilot-jnothman__upsetplot-253-e2569d546a` |
| jsonpickle__jsonpickle-501 | yes | resolved | verified on first verdict | resolved | 1009437 tokens; $0.313 model estimated; 0.125 Token Factory reported cost, unit not published; 106.824 sandbox lifetime s; 299.442 wall s | `pilot/v2-P/jsonpickle__jsonpickle-501/runs/pilot-jsonpickle__jsonpickle-501-5eb548efc8` |
| kozea__weasyprint-2087 | no | not resolved | refused | not resolved | 4642847 tokens; $1.412 model estimated; 0.676 Token Factory reported cost, unit not published; 338.041 sandbox lifetime s; 899.767 wall s | `pilot/v2-P/kozea__weasyprint-2087/runs/pilot-kozea__weasyprint-2087-a5888efabe` |
| kubernetes-client__python-1933 | no | not resolved | refused | not resolved | 1597989 tokens; $0.488 model estimated; 0.318 Token Factory reported cost, unit not published; 210.615 sandbox lifetime s; 515.51 wall s | `pilot/v2-P/kubernetes-client__python-1933/runs/pilot-kubernetes-client__python-1933-2d1f8b9408` |
| maas__python-libmaas-219 | yes | resolved | verified on first verdict | resolved | 27356 tokens; $0.009 model estimated; 0.033 Token Factory reported cost, unit not published; 50.229 sandbox lifetime s; 88.919 wall s | `pilot/v2-P/maas__python-libmaas-219/runs/pilot-maas__python-libmaas-219-4a3111fdbd` |
| mie-lab__trackintel-344 | no | not resolved | refused | not resolved | 159195 tokens; $0.05 model estimated; 0.585 Token Factory reported cost, unit not published; 245.885 sandbox lifetime s; 333.652 wall s | `pilot/v2-P/mie-lab__trackintel-344/runs/pilot-mie-lab__trackintel-344-87a18c5630` |
| mirumee__ariadne-codegen-159 | yes | resolved | verified on first verdict | resolved | 139543 tokens; $0.043 model estimated; 0.099 Token Factory reported cost, unit not published; 59.795 sandbox lifetime s; 107.254 wall s | `pilot/v2-P/mirumee__ariadne-codegen-159/runs/pilot-mirumee__ariadne-codegen-159-93bb7154d4` |
| mondeja__mkdocs-include-markdown-plugin-51 | no | not resolved | refused | not resolved | 1166428 tokens; $0.365 model estimated; 0.821 Token Factory reported cost, unit not published; 224.192 sandbox lifetime s; 433.734 wall s | `pilot/v2-P/mondeja__mkdocs-include-markdown-plugin-51/runs/pilot-mondeja__mkdocs-include-markdown-plugin-51-ce84d5d6e2` |
| more-itertools__more-itertools-892 | yes | resolved | verified on first verdict | resolved | 704143 tokens; $0.214 model estimated; 0.139 Token Factory reported cost, unit not published; 79.92 sandbox lifetime s; 178.646 wall s | `pilot/v2-P/more-itertools__more-itertools-892/runs/pilot-more-itertools__more-itertools-892-e6dc6076f5` |
| msgpack__msgpack-python-331 | yes | resolved | verified on first verdict | resolved | 299050 tokens; $0.093 model estimated; 0.022 Token Factory reported cost, unit not published; 78.221 sandbox lifetime s; 170.889 wall s | `pilot/v2-P/msgpack__msgpack-python-331/runs/pilot-msgpack__msgpack-python-331-45d53df8fe` |
| natcap__invest-787 | no | unavailable | infrastructure error | unavailable | 0 tokens; not available model estimated; 0.074 Token Factory reported cost, unit not published; 25.108 sandbox lifetime s; 32.835 wall s | `pilot/v2-P/natcap__invest-787/runs/pilot-natcap__invest-787-c12b32de7f` |
| neogeny__tatsu-320 | no | not resolved | refused | not resolved | 3155182 tokens; $0.959 model estimated; 0.089 Token Factory reported cost, unit not published; 188.914 sandbox lifetime s; 521.757 wall s | `pilot/v2-P/neogeny__tatsu-320/runs/pilot-neogeny__tatsu-320-7ec7104015` |
| networkx__networkx-3101 | yes | resolved | verified on first verdict | resolved | 145641 tokens; $0.046 model estimated; 0.078 Token Factory reported cost, unit not published; 72.116 sandbox lifetime s; 205.84 wall s | `pilot/v2-P/networkx__networkx-3101/runs/pilot-networkx__networkx-3101-6b3707109a` |
| neurodatawithoutborders__pynwb-2052 | yes | resolved | verified on first verdict | resolved | 33252 tokens; $0.01 model estimated; 0.291 Token Factory reported cost, unit not published; 91.204 sandbox lifetime s; 224.659 wall s | `pilot/v2-P/neurodatawithoutborders__pynwb-2052/runs/pilot-neurodatawithoutborders__pynwb-2052-2bde293e84` |
| niconoe__pyinaturalist-72 | yes | resolved | verified on first verdict | resolved | 35084 tokens; $0.011 model estimated; 0.06 Token Factory reported cost, unit not published; 63.934 sandbox lifetime s; 89.574 wall s | `pilot/v2-P/niconoe__pyinaturalist-72/runs/pilot-niconoe__pyinaturalist-72-702ef28b7d` |
| ntnu-ihb__pythonfmu-158 | yes | not resolved | refused | not resolved | 555264 tokens; $0.17 model estimated; 0.183 Token Factory reported cost, unit not published; 118.792 sandbox lifetime s; 238.959 wall s | `pilot/v2-P/ntnu-ihb__pythonfmu-158/runs/pilot-ntnu-ihb__pythonfmu-158-34942c73d2` |
| opendatacube__odc-geo-121 | yes | resolved | verified on first verdict | resolved | 156370 tokens; $0.048 model estimated; 0.457 Token Factory reported cost, unit not published; 114.255 sandbox lifetime s; 153.739 wall s | `pilot/v2-P/opendatacube__odc-geo-121/runs/pilot-opendatacube__odc-geo-121-153f4bb468` |
| openmdao__aviary-807 | no | not resolved | refused | not resolved | 3304975 tokens; $1.002 model estimated; 1.436 Token Factory reported cost, unit not published; 375.71 sandbox lifetime s; 775.956 wall s | `pilot/v2-P/openmdao__aviary-807/runs/pilot-openmdao__aviary-807-2467a5dac6` |
| openmdao__openmdao-3029 | no | not resolved | refused | not resolved | 1984055 tokens; $0.612 model estimated; 2.002 Token Factory reported cost, unit not published; 342.814 sandbox lifetime s; 674.146 wall s | `pilot/v2-P/openmdao__openmdao-3029/runs/pilot-openmdao__openmdao-3029-609b57f62b` |
| opensearch-project__opensearch-py-843 | yes | resolved | verified on first verdict | resolved | 239390 tokens; $0.075 model estimated; 0.073 Token Factory reported cost, unit not published; 65.668 sandbox lifetime s; 192.184 wall s | `pilot/v2-P/opensearch-project__opensearch-py-843/runs/pilot-opensearch-project__opensearch-py-843-8f22966050` |
| palantir__python-language-server-829 | no | not resolved | refused | not resolved | 2450431 tokens; $0.749 model estimated; 0.582 Token Factory reported cost, unit not published; 225.378 sandbox lifetime s; 515.069 wall s | `pilot/v2-P/palantir__python-language-server-829/runs/pilot-palantir__python-language-server-829-2a6b954e00` |
| pennersr__django-allauth-3447 | yes | not resolved | refused | not resolved | 432299 tokens; $0.132 model estimated; 0.317 Token Factory reported cost, unit not published; 162.885 sandbox lifetime s; 273.918 wall s | `pilot/v2-P/pennersr__django-allauth-3447/runs/pilot-pennersr__django-allauth-3447-f2542e9e53` |
| pgmpy__pgmpy-878 | yes | not resolved | refused | not resolved | 253337 tokens; $0.079 model estimated; 0.159 Token Factory reported cost, unit not published; 105.16 sandbox lifetime s; 208.289 wall s | `pilot/v2-P/pgmpy__pgmpy-878/runs/pilot-pgmpy__pgmpy-878-9f872e2eb4` |
| pints-team__pints-1444 | yes | resolved | verified on first verdict | resolved | 747294 tokens; $0.231 model estimated; 0.885 Token Factory reported cost, unit not published; 322.999 sandbox lifetime s; 737.925 wall s | `pilot/v2-P/pints-team__pints-1444/runs/pilot-pints-team__pints-1444-190773ed22` |
| pipxproject__pipx-680 | no | resolved | verified on first verdict | resolved | 2121809 tokens; $0.646 model estimated; 1.18 Token Factory reported cost, unit not published; 394.685 sandbox lifetime s; 606.508 wall s | `pilot/v2-P/pipxproject__pipx-680/runs/pilot-pipxproject__pipx-680-183a4a2cf5` |
| planetlabs__planet-client-python-81 | yes | not resolved | verified on appeal | resolved | 198967 tokens; $0.061 model estimated; 0.04 Token Factory reported cost, unit not published; 66.906 sandbox lifetime s; 137.154 wall s | `pilot/v2-P/planetlabs__planet-client-python-81/runs/pilot-planetlabs__planet-client-python-81-356d85f603` |
| pybamm-team__pybamm-4196 | yes | resolved | verified on first verdict | resolved | 1611647 tokens; $0.494 model estimated; 2.922 Token Factory reported cost, unit not published; 324.233 sandbox lifetime s; 635.804 wall s | `pilot/v2-P/pybamm-team__pybamm-4196/runs/pilot-pybamm-team__pybamm-4196-032ff41199` |
| pycqa__docformatter-104 | yes | resolved | verified on first verdict | resolved | 574049 tokens; $0.179 model estimated; 0.098 Token Factory reported cost, unit not published; 102.151 sandbox lifetime s; 245.683 wall s | `pilot/v2-P/pycqa__docformatter-104/runs/pilot-pycqa__docformatter-104-81a216bf2b` |
| pycqa__pyflakes-335 | yes | resolved | verified on first verdict | resolved | 32796 tokens; $0.01 model estimated; 0.032 Token Factory reported cost, unit not published; 44.791 sandbox lifetime s; 70.919 wall s | `pilot/v2-P/pycqa__pyflakes-335/runs/pilot-pycqa__pyflakes-335-c3389ca290` |
| pyfar__pyfar-58 | no | not resolved | refused | not resolved | 3377878 tokens; $1.021 model estimated; 0.457 Token Factory reported cost, unit not published; 247.157 sandbox lifetime s; 528.194 wall s | `pilot/v2-P/pyfar__pyfar-58/runs/pilot-pyfar__pyfar-58-088545f170` |
| pyfilesystem__pyfilesystem2-462 | yes | not resolved | verified on appeal | resolved | 904972 tokens; $0.276 model estimated; 0.518 Token Factory reported cost, unit not published; 208.952 sandbox lifetime s; 354.89 wall s | `pilot/v2-P/pyfilesystem__pyfilesystem2-462/runs/pilot-pyfilesystem__pyfilesystem2-462-a7a07ad9fa` |
| pyg-team__pytorch_geometric-7654 | no | not resolved | refused | not resolved | 1288434 tokens; $0.403 model estimated; 0.905 Token Factory reported cost, unit not published; 224.73 sandbox lifetime s; 452.53 wall s | `pilot/v2-P/pyg-team__pytorch_geometric-7654/runs/pilot-pyg-team__pytorch_geometric-7654-310f2aed7b` |
| pymodbus-dev__pymodbus-2502 | yes | resolved | verified on first verdict | resolved | 28723 tokens; $0.009 model estimated; 0.153 Token Factory reported cost, unit not published; 76 sandbox lifetime s; 104.566 wall s | `pilot/v2-P/pymodbus-dev__pymodbus-2502/runs/pilot-pymodbus-dev__pymodbus-2502-a2e46abb38` |
| pymor__pymor-810 | yes | not resolved | refused | not resolved | 606090 tokens; $0.186 model estimated; 2.646 Token Factory reported cost, unit not published; 318.674 sandbox lifetime s; 663.841 wall s | `pilot/v2-P/pymor__pymor-810/runs/pilot-pymor__pymor-810-aba6bce223` |
| pypa__pipx-1350 | yes | resolved | verified on first verdict | resolved | 40996 tokens; $0.013 model estimated; 5.194 Token Factory reported cost, unit not published; 1116.77 sandbox lifetime s; 1305.377 wall s | `pilot/v2-P/pypa__pipx-1350/runs/pilot-pypa__pipx-1350-54fbd8f247` |
| pytask-dev__pytask-519 | yes | resolved | verified on first verdict | resolved | 154603 tokens; $0.047 model estimated; 0.176 Token Factory reported cost, unit not published; 86.195 sandbox lifetime s; 126.191 wall s | `pilot/v2-P/pytask-dev__pytask-519/runs/pilot-pytask-dev__pytask-519-a04b416eed` |
| pythainlp__pythainlp-1056 | yes | resolved | verified on first verdict | resolved | 138886 tokens; $0.049 model estimated; 0.288 Token Factory reported cost, unit not published; 92.178 sandbox lifetime s; 247.724 wall s | `pilot/v2-P/pythainlp__pythainlp-1056/runs/pilot-pythainlp__pythainlp-1056-98ebf86118` |
| python__typing_extensions-157 | no | not resolved | refused | not resolved | 380318 tokens; $0.118 model estimated; 0.106 Token Factory reported cost, unit not published; 104.066 sandbox lifetime s; 200.466 wall s | `pilot/v2-P/python__typing_extensions-157/runs/pilot-python__typing_extensions-157-34a7e66fb9` |
| qiskit-community__ecosystem-159 | yes | resolved | verified on first verdict | resolved | 51814 tokens; $0.017 model estimated; 0.061 Token Factory reported cost, unit not published; 55.318 sandbox lifetime s; 97.194 wall s | `pilot/v2-P/qiskit-community__ecosystem-159/runs/pilot-qiskit-community__ecosystem-159-7b8e059aa3` |
| qiskit__qiskit-terra-8799 | yes | resolved | verified on first verdict | resolved | 93692 tokens; $0.029 model estimated; 0.295 Token Factory reported cost, unit not published; 131.629 sandbox lifetime s; 987.978 wall s | `pilot/v2-P/qiskit__qiskit-terra-8799/runs/pilot-qiskit__qiskit-terra-8799-74ca3a19a8` |
| quora__pyanalyze-688 | no | not resolved | refused | not resolved | 1304803 tokens; $0.396 model estimated; 0.749 Token Factory reported cost, unit not published; 274.769 sandbox lifetime s; 485.288 wall s | `pilot/v2-P/quora__pyanalyze-688/runs/pilot-quora__pyanalyze-688-5c0f83454c` |
| qutech__qupulse-797 | yes | resolved | verified on first verdict | resolved | 213930 tokens; $0.066 model estimated; 0.228 Token Factory reported cost, unit not published; 72.056 sandbox lifetime s; 148.217 wall s | `pilot/v2-P/qutech__qupulse-797/runs/pilot-qutech__qupulse-797-b67d817a55` |
| qutip__qutip-2561 | no | not resolved | refused | not resolved | 1904138 tokens; $0.583 model estimated; 1.048 Token Factory reported cost, unit not published; 376.32 sandbox lifetime s; 1165.897 wall s | `pilot/v2-P/qutip__qutip-2561/runs/pilot-qutip__qutip-2561-9d51b50c48` |
| researchobject__ro-crate-py-192 | yes | resolved | verified on first verdict | resolved | 139929 tokens; $0.043 model estimated; 0.069 Token Factory reported cost, unit not published; 60.205 sandbox lifetime s; 102.521 wall s | `pilot/v2-P/researchobject__ro-crate-py-192/runs/pilot-researchobject__ro-crate-py-192-ed0e4ed903` |
| rhayes777__pyautofit-888 | yes | resolved | verified on first verdict | resolved | 297604 tokens; $0.092 model estimated; 0.35 Token Factory reported cost, unit not published; 107.883 sandbox lifetime s; 193.022 wall s | `pilot/v2-P/rhayes777__pyautofit-888/runs/pilot-rhayes777__pyautofit-888-508cd1675e` |
| robotframework__seleniumlibrary-1431 | yes | resolved | verified on first verdict | resolved | 544331 tokens; $0.167 model estimated; 0.055 Token Factory reported cost, unit not published; 67.433 sandbox lifetime s; 169.751 wall s | `pilot/v2-P/robotframework__seleniumlibrary-1431/runs/pilot-robotframework__seleniumlibrary-1431-6180934973` |
| robotpy__cxxheaderparser-82 | yes | resolved | verified on first verdict | resolved | 1561664 tokens; $0.479 model estimated; 0.051 Token Factory reported cost, unit not published; 68.194 sandbox lifetime s; 270.715 wall s | `pilot/v2-P/robotpy__cxxheaderparser-82/runs/pilot-robotpy__cxxheaderparser-82-f932a1fb8b` |
| rochacbruno__dynaconf-191 | no | resolved | verified on first verdict | resolved | 1361472 tokens; $0.418 model estimated; 0.209 Token Factory reported cost, unit not published; 136.241 sandbox lifetime s; 370.491 wall s | `pilot/v2-P/rochacbruno__dynaconf-191/runs/pilot-rochacbruno__dynaconf-191-5d3d191876` |
| rock-learning__pytransform3d-48 | yes | not resolved | refused | not resolved | 61543 tokens; $0.019 model estimated; 0.143 Token Factory reported cost, unit not published; 80.17 sandbox lifetime s; 125.515 wall s | `pilot/v2-P/rock-learning__pytransform3d-48/runs/pilot-rock-learning__pytransform3d-48-33599d5630` |
| s-knibbs__dataclasses-jsonschema-93 | yes | resolved | verified on first verdict | resolved | 151118 tokens; $0.047 model estimated; 0.025 Token Factory reported cost, unit not published; 51.003 sandbox lifetime s; 92.429 wall s | `pilot/v2-P/s-knibbs__dataclasses-jsonschema-93/runs/pilot-s-knibbs__dataclasses-jsonschema-93-dfd35c894a` |
| samuelcolvin__pydantic-2806 | no | not resolved | verified on appeal | resolved | 1576700 tokens; $0.48 model estimated; 0.157 Token Factory reported cost, unit not published; 175.606 sandbox lifetime s; 385.869 wall s | `pilot/v2-P/samuelcolvin__pydantic-2806/runs/pilot-samuelcolvin__pydantic-2806-4294f3e043` |
| scitools__cartopy-2307 | no | not resolved | refused | not resolved | 1442453 tokens; $0.44 model estimated; 0.37 Token Factory reported cost, unit not published; 190.864 sandbox lifetime s; 491.489 wall s | `pilot/v2-P/scitools__cartopy-2307/runs/pilot-scitools__cartopy-2307-732738351d` |
| sdv-dev__rdt-704 | yes | resolved | verified on first verdict | resolved | 1165878 tokens; $0.359 model estimated; 0.628 Token Factory reported cost, unit not published; 203.81 sandbox lifetime s; 419.282 wall s | `pilot/v2-P/sdv-dev__rdt-704/runs/pilot-sdv-dev__rdt-704-4f5a9115a2` |
| sfdo-tooling__cumulusci-3624 | yes | resolved | verified on first verdict | resolved | 280229 tokens; $0.086 model estimated; 0.301 Token Factory reported cost, unit not published; 695.306 sandbox lifetime s; 850.608 wall s | `pilot/v2-P/sfdo-tooling__cumulusci-3624/runs/pilot-sfdo-tooling__cumulusci-3624-ed46a8ec8d` |
| skypyproject__skypy-573 | yes | resolved | verified on first verdict | resolved | 20280 tokens; $0.007 model estimated; 0.225 Token Factory reported cost, unit not published; 71.589 sandbox lifetime s; 117.67 wall s | `pilot/v2-P/skypyproject__skypy-573/runs/pilot-skypyproject__skypy-573-f0fbe60475` |
| stac-utils__pystac-561 | yes | resolved | verified on first verdict | resolved | 397914 tokens; $0.123 model estimated; 0.098 Token Factory reported cost, unit not published; 103.132 sandbox lifetime s; 245.091 wall s | `pilot/v2-P/stac-utils__pystac-561/runs/pilot-stac-utils__pystac-561-fda655ae3d` |
| stac-utils__pystac-client-782 | yes | resolved | verified on first verdict | resolved | 70174 tokens; $0.022 model estimated; 0.12 Token Factory reported cost, unit not published; 79.205 sandbox lifetime s; 241.296 wall s | `pilot/v2-P/stac-utils__pystac-client-782/runs/pilot-stac-utils__pystac-client-782-d858f24dfa` |
| stac-utils__stac-fastapi-729 | no | not resolved | refused | not resolved | 3883293 tokens; $1.187 model estimated; 0.39 Token Factory reported cost, unit not published; 245.443 sandbox lifetime s; 657.207 wall s | `pilot/v2-P/stac-utils__stac-fastapi-729/runs/pilot-stac-utils__stac-fastapi-729-07063ad25c` |
| systemd__mkosi-3346 | yes | resolved | verified on first verdict | resolved | 539352 tokens; $0.165 model estimated; 0.069 Token Factory reported cost, unit not published; 92.917 sandbox lifetime s; 226.616 wall s | `pilot/v2-P/systemd__mkosi-3346/runs/pilot-systemd__mkosi-3346-61a8f478d9` |
| theacodes__nox-466 | yes | resolved | verified on first verdict | resolved | 656627 tokens; $0.201 model estimated; 1.473 Token Factory reported cost, unit not published; 466.139 sandbox lifetime s; 624.116 wall s | `pilot/v2-P/theacodes__nox-466/runs/pilot-theacodes__nox-466-7cd2d00d26` |
| tqdm__tqdm-49 | no | resolved | verified on first verdict | resolved | 1255472 tokens; $0.383 model estimated; 0.034 Token Factory reported cost, unit not published; 82.502 sandbox lifetime s; 248.57 wall s | `pilot/v2-P/tqdm__tqdm-49/runs/pilot-tqdm__tqdm-49-071aa51f92` |
| twisted__pydoctor-191 | no | not resolved | refused | not resolved | 2804777 tokens; $0.858 model estimated; 0.281 Token Factory reported cost, unit not published; 217.02 sandbox lifetime s; 586.043 wall s | `pilot/v2-P/twisted__pydoctor-191/runs/pilot-twisted__pydoctor-191-05d2ce9296` |
| ungarj__mapchete-685 | yes | not resolved | refused | not resolved | 185192 tokens; $0.057 model estimated; 0.391 Token Factory reported cost, unit not published; 135.635 sandbox lifetime s; 216.271 wall s | `pilot/v2-P/ungarj__mapchete-685/runs/pilot-ungarj__mapchete-685-07a94cd33c` |
| vacanza__holidays-2106 | yes | resolved | verified on first verdict | resolved | 109027 tokens; $0.034 model estimated; 0.126 Token Factory reported cost, unit not published; 69.206 sandbox lifetime s; 205.728 wall s | `pilot/v2-P/vacanza__holidays-2106/runs/pilot-vacanza__holidays-2106-880dd1728d` |
| virtuslab__git-machete-179 | yes | resolved | verified on first verdict | resolved | 241825 tokens; $0.075 model estimated; 0.43 Token Factory reported cost, unit not published; 229.378 sandbox lifetime s; 303.561 wall s | `pilot/v2-P/virtuslab__git-machete-179/runs/pilot-virtuslab__git-machete-179-6df3ff22b8` |
| wtforms__wtforms-596 | no | not resolved | refused | not resolved | 2460361 tokens; $0.755 model estimated; 0.094 Token Factory reported cost, unit not published; 197.286 sandbox lifetime s; 485.865 wall s | `pilot/v2-P/wtforms__wtforms-596/runs/pilot-wtforms__wtforms-596-af0bf020ed` |
| yt-dlp__yt-dlp-13361 | yes | not resolved | verified on appeal | resolved | 726242 tokens; $0.221 model estimated; 0.276 Token Factory reported cost, unit not published; 194.586 sandbox lifetime s; 412.278 wall s | `pilot/v2-P/yt-dlp__yt-dlp-13361/runs/pilot-yt-dlp__yt-dlp-13361-2cef14a834` |
| yukinarit__pyserde-430 | yes | resolved | verified on first verdict | resolved | 470795 tokens; $0.144 model estimated; 5.128 Token Factory reported cost, unit not published; 595.711 sandbox lifetime s; 666.342 wall s | `pilot/v2-P/yukinarit__pyserde-430/runs/pilot-yukinarit__pyserde-430-acd6f7ef47` |
| zopefoundation__btrees-163 | no | resolved | verified on first verdict | resolved | 1174497 tokens; $0.361 model estimated; 0.191 Token Factory reported cost, unit not published; 150.296 sandbox lifetime s; 347.641 wall s | `pilot/v2-P/zopefoundation__btrees-163/runs/pilot-zopefoundation__btrees-163-7726cac202` |
