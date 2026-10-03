# Feedback for Nebius Token Factory, NVIDIA Nemotron and SWE-rebench

Receipts ran a Nemotron coding agent on real SWE-rebench-V2 tasks, re-checked every claimed fix in a clean sandbox, and graded every patch again with SWE-rebench's own grader. Running that pipeline at scale surfaced the findings below. Each one names the record or file that shows it, so it can be checked. Counts are from our own runs (v1 pilot, Oct 1; v2 runs and screening, Oct 2 to 3). "Plan 5" is `docs/superpowers/plans/2026-10-02-plan-5-receipts-v2.md`, whose section 1 lists the findings from v1's records.

## Nebius Token Factory Sandboxes

What worked well: the catalogue preloads 32,064 SWE-rebench-V2 images (598 of our 600 candidates), a trivial run takes about 1.1 seconds, and immutable images make "fork the original checkpoint" exact, which is the core of our witness design. Screening 123 tasks at concurrency 6 and running agents at concurrency 4 hit no rate limit.

| # | Finding | Evidence | Suggestion |
| --- | --- | --- | --- |
| S1 | Some catalogue calls return 403 through `contree-sdk` 0.3.6 while the same call over REST succeeds. We use REST. | Plan 5, section 10 | Align the SDK's catalogue calls with the REST permissions. |
| S2 | `GET /v1/inspect/?tag=` answers 302 with a relative `Location` (`<uuid>/`). Clients that resolve it against the wrong base miss the image. | `src/receipts/sandbox/tokenfactory_api.py`, `image_by_tag` | Document the relative redirect, or return the uuid in the body. |
| S3 | `truncate_output_at` of 10 MiB or more is refused, and the default truncates a run's output at 64 KB. Neither limit is in the documentation. A full pytest `-rA` log can exceed 10 MiB. | `docs/results/2026-10-02-tokenfactory-rehearsal.md` | Document the cap, and offer a way to fetch a run's full stdout. |
| S4 | Downloading a directory through `/v1/inspect/{image}/download` answers 422 ("Path is not a regular file"), and the listing endpoint names entries relative to the listed directory. Both are undocumented; our fake API assumed otherwise, and directory reads failed live until we fixed them. | Commit `1d5ce80` | Document both, or accept an absolute-path option on the listing. |
| S5 | A run's `cost` is exactly 0.0101 per second of its `duration`, in an unpublished unit, and our billing did not change with it (32.2 units reported for screening and a 10-task canary; the account moved only by model spend). A run that times out after 600 seconds reports a `duration` near 0. | `docs/results/2026-10-02-v2-screen-P.md` | Publish the unit and the beta pricing, and say what `duration` measures. |
| S6 | Two of the 600 candidates' images are not in the catalogue: `swerebenchv2/dhi-mikeio:227-50037f2` and `swerebenchv2/awslabs-cfn-python-lint:644-387836c`. | `pilot/v2-screen-P.jsonl` | Add them, or list the dataset rows the catalogue does not cover. |

## NVIDIA Nemotron on Token Factory

| # | Finding | Evidence | Suggestion |
| --- | --- | --- | --- |
| N1 | Nemotron 3 Super calls tools that do not exist when its harness offers other names: 60 such calls in v1's 79 analysed attempts (`execute` 46, `execute_grep` 6, `bash` 3, `grep` 2, and `think`, `list_dir`, `str_replace_editor` once each). These look like tool names from other agent harnesses. Mapping them onto the real tools fixed it. | Plan 5, F2; commit `059c532` | Publish the tool names and schemas the model was tuned on, so harnesses can match them. |
| N2 | It obeys "one tool call per turn" exactly: 0 of 1,875 responses had more than one call. | Plan 5, F3 | Worth stating in the model card; harness builders can rely on it. |
| N3 | In a scripted six-turn tool-calling loop (ten runs per model, thinking off, Oct 2), Nemotron 3 Super completed 10 of 10, Nemotron 3.5 Lightning 6 of 10, and Nemotron 3 Ultra 550B 3 of 10. None invented a tool or answered in free text. | `PREREGISTRATION-v2.md`, "Exploratory arm" | The newer models completed this loop less often than Super; a multi-turn tool-calling check in their evaluation may be worth adding. |

## SWE-rebench-V2

| # | Finding | Evidence | Suggestion |
| --- | --- | --- | --- |
| R1 | Test ids are truncated at whitespace (parametrized ids with spaces): 10 of our 600 candidates in FAIL_TO_PASS, 69 in PASS_TO_PASS, 73 in either. | Plan 5, F11 | Store full node ids, or document the truncation rule. |
| R2 | The upstream pytest log parser ignores `SUBFAILED` lines, so a failing pytest-subtests subtest of a PASS_TO_PASS test goes unseen. In `qiskit__qiskit-ibm-runtime-452` our junit-based gate caught a regression that the official grade missed. | `REPORT.md`, disagreements table | Treat `SUBFAILED` as a failure of the parent test. |
| R3 | Some PASS_TO_PASS tests cannot pass in a sandbox without outbound network or host features, before or after any patch: `py-pdf__pypdf2-1318` (downloads a PDF), `datadog__guarddog-156` (npm download), `giampaolo__psutil-2379` (host sysfs), `altair-viz__altair-3068` (chart rendering), and in v2 screening `rq__rq-1947`. In such a sandbox these tasks can never be graded resolved, whatever the patch, and a harness that ignores the failure can ship a patch the grader then fails (our v1 pilot did once). | `REPORT.md`; `docs/results/2026-10-02-v2-screen-P.md` | Mark tests that need network or host features, or ship a per-row "empty patch passes" check. |
| R4 | In 27 of 601 candidate rows the `test_patch` touches files that do not follow test naming (a root `test.py`, `exercise/tests.py`, fixture YAML). A harness that protects only test-named files lets an agent edit the specification itself, and the official grade then runs the edited spec. | Plan 5, F17; commit `0ba0a2e` | List the specification's files in each row, so harnesses can make them read-only. |
