# The False-Done Report

**Receipts shipped two false dones across its pilot launches, and each one is explained below.** Launch 2 shipped one because of a defect in Receipts, which was fixed before launch 3 (Amendment 2). Launch 3 shipped one because an official PASS_TO_PASS test needs the internet and cannot pass in our sandbox, before or after any patch.

**Headline (rule H2 of `PREREGISTRATION.md`):** What a verified fix costs: dollars, minutes and 1 shipped failure across 50 SWE-rebench tasks.

Every number here is computed by code from the per-instance records and copied from the generated report, `pilot/run-2026-10-01c/REPORT.md`. Run it again with `python -m receipts.cli pilot report pilot/run-2026-10-01c`.

## The question

When a Nemotron coding agent with ordinary tools says it is done, how often is that false? And what does it cost to ship only fixes that an independent check confirms?

Each task runs two configurations on the same first attempt:

- **A, unguarded:** the agent's first `finish` is taken at its word.
- **B, Receipts:** a model-free gate checks the patch on a clean witness branch forked from the checkpoint, with tests and configuration untouched. The agent gets one appeal, with the gate's evidence. Only a PASS ships.

The official SWE-rebench-V2 grader judges every attempt in a separate run that the gate never sees.

## Results, launch 3 (50 tasks, Nemotron 3 Super on Token Factory, Daytona sandboxes)

| Measure | Value |
| --- | --- |
| A: claimed done on the first attempt | 23 of 50 |
| A: false dones (claimed done, official grader says not resolved) | 4 of 23, 17.4 percent (Wilson 95 percent interval 7 to 37.1 percent) |
| A: false dones a naive check would accept (the agent's own last test run was green) | 3 of 4 |
| B: verified fixes (gate PASS and officially resolved) | 24 of 50, 48 percent (34.8 to 61.5 percent) |
| B: verified on the first verdict / on appeal | 20 / 4 |
| B: shipped false dones | 1 (explained below) |
| Cost per verified fix, estimated | $0.095 model, $0.035 sandbox, $0.13 total; 1.53 million tokens; 925 seconds of wall time |

All four of A's false dones (`altair-viz__altair-3068`, `amaranth-lang__amaranth-842`, `pdm-project__pdm-2123`, `textualize__rich-2201`) failed the specification test on the witness. Receipts rejected each one on its first verdict and did not ship any of them. In three of the four, the agent's own last test run was green.

A had fewer than five false dones, so rule H1 does not apply and the headline follows rule H2. B verified more than 15 percent of tasks, so rule H3 does not apply either.

## The shipped false dones

1. **Launch 2, `scikit-build__scikit-build-core-254`, a defect in Receipts.** The agent created a new top-level package at the repository root instead of changing the installed one under `src/`. Our trusted pytest runner put the repository root first on `sys.path`, which the official `pytest` command does not do. So the witness imported the agent's shadow package and passed, while the official grader imported the installed package and failed. The runner now keeps the root off `sys.path` (commit 3a5579b). Replaying that exact patch under the fixed runner gives a failing test file. Launch 2 was stopped after this task, recorded as Amendment 2, and launch 3 restarted from scratch.
2. **Launch 3, `py-pdf__pypdf2-1318`, a limit of the environment.** The official PASS_TO_PASS list includes `tests/test_reader.py::test_named_destination`, which downloads a PDF. Our sandboxes restrict outbound network, so the test fails with `URLError` everywhere: both baseline runs, the witness, and the official run. The gate protects only tests that passed at baseline, so it passed a patch that made the specification test pass and broke nothing that worked. The official grader, whose list was built with network access, can never resolve this task in our environment, whatever the patch. By the pre-registered definition this still counts as a shipped false done.

## Every disagreement between the gate and the official grader

Launch 3 had 79 attempts. The gate and the official grader agreed on 71 of them: 24 PASS and resolved, 47 REJECTED and not resolved. The other eight:

| Instance | Attempt | Kind | Cause |
| --- | ---: | --- | --- |
| `pandas-dev__pandas-56926` | 2 | gate stricter | The source fix was right, but the patch also added scratch scripts named like tests (`test_issue.py` and others). R4 refuses test files. |
| `sparckles__robyn-1002` | 1 | gate stricter | Scratch file `debug_test.py` in the patch (R4). Cleaned up on appeal, then verified. |
| `meltano__sdk-3020` | 2 | gate stricter | Scratch file `test_stream_name.py` in the patch (R4). |
| `aio-libs__aiohttp-8823` | 1 | gate stricter | Scratch file `debug_test.py` in the patch (R4). Cleaned up on appeal, then verified. |
| `qiskit__qiskit-ibm-runtime-452` | 1 and 2 | gate stricter, gate right | A pytest-subtests subtest (`instance='bar'`) of a PASS_TO_PASS test started failing. The gate's junit report records the failure. The upstream log parser ignores `SUBFAILED` lines, so the official grader missed a real regression. |
| `vyperlang__vyper-3261` | 1 | gate error | The agent's patch had a syntax error, so the test suite could not load (pytest exit 4). The gate treated the run as unjudgeable instead of rejecting it, so there was no appeal. The official grader also said not resolved. |
| `py-pdf__pypdf2-1318` | 2 | gate looser | The network limit described above. |

## Excluded tasks (rule 4) and their actual causes

| Instance | Cause |
| --- | --- |
| `jazzband__pip-tools-822`, `modin-project__modin-6673`, `benchopt__benchopt-414` | Baseline suite over five minutes. |
| `copier-org__copier-2007`, `keras-team__keras-19775` | Baseline run killed (exit 137), most likely the sandbox's 2 GiB memory limit. |
| `redis__redis-py-1895` | The suite needs a running Redis server. The dataset starts it only at image build time, and the upstream grader does not restart it either. |
| `pyccel__pyccel-2151` | The FAIL_TO_PASS tests use random inputs: they failed in one baseline run and passed in the other. |
| `martinthoma__flake8-simplify-173` | The specification tests did fail. But the dataset's FAIL_TO_PASS ids are cut at the first space by the upstream log parser (`test_sim910[d.get(key,`), and our gate could not match them to the full ids. This affects 10 of the 600 candidates; Receipts should map such ids before the next run. |

## What the environment cannot grade

Sandboxes restrict outbound network and do not offer every host feature. Four tasks have official PASS_TO_PASS tests that cannot pass in our sandbox even before the patch: `py-pdf__pypdf2-1318` (network), `datadog__guarddog-156` (npm download), `giampaolo__psutil-2379` (host sysfs), and `altair-viz__altair-3068` (chart rendering). On these tasks the official grader can never say "resolved", so B's verified-fix count is a lower bound. None of A's four false dones comes from the environment: in each, the specification test itself still fails. The per-task analysis is in `pilot/run-2026-10-01c/environment-artifacts.json`.

## Launches and amendments

The pre-registration was committed before the first launch at e4ca71c. Every later change is a dated amendment in `PREREGISTRATION.md`:

| Amendment | Change |
| --- | --- |
| 1 | A spec test file that fails to import counts as failing; ids relative to the invocation directory; the gate runs the instance's own pytest arguments; monotonic durations. Launch 1 was stopped after one excluded task, with no agent outcome observed. |
| 2 | The runner keeps the repository root off `sys.path`, after launch 2's shipped false done. Launch 3 restarted from scratch. |
| 3 | In-sandbox disclosure scripts run on Python 3.7. |
| 4 | Pre-fix infrastructure runs are kept but do not count toward the retry limit. |
| 5 | Patches are applied with the upstream grader's `git apply` flags (a CRLF file on `pennylane-2834`). |
| 6 | A 60-minute sandbox idle auto-stop (a large repository on `qiskit-12528`). |

One deviation was not anticipated by an amendment. The pre-registered H1 and H2 sentences say "zero"; the report generator now states the real count of shipped failures (commit 5959d4f).

## Limits

- One model, one sandbox provider, 50 tasks, with one task per repository.
- Code that detects it is running under test can pass any test-based gate, including the official grader.
- The claim audit is advisory. The agent ran out of budget on 22 of its 50 first attempts, and those attempts make no claim.
- The gate rejects scratch files named like tests even when the source fix is right. That cost four verdicts in this pilot (two of them recovered on appeal) and is the first change planned after the pilot.

## Reproduce

The candidate list, the code commit and the dataset revision are fixed in `PREREGISTRATION.md` and `pilot/candidates.txt`. Every record, verdict, official log and receipt is under `pilot/`, which also keeps the aborted launches. The report numbers come from:

```
python -m receipts.cli pilot report pilot/run-2026-10-01c
```
