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

## Amendment 1 (2026-10-16, before any task produced a verdict)

Screening. Position 3 (`d4a6107bdab7`) was first screened by a script that did not count a test file that cannot be imported at the start state (it imports a name the fix adds) as failing. Re-screened with the corrected script, it qualifies. The eight included tasks are therefore positions 2, 3, 5, 6, 7, 8, 9 and 10. Position 11 (`d44d046e2122`) also qualifies but is the ninth and is not run. Positions 1 and 4 are excluded: no changed test fails at the start state.

Regression suite. At these commits AERead's full `tests/` suite ran for more than 17 minutes in `python:3.12-slim` on this machine without finishing, and it includes tests tied to the maintainers' machines (a required directory name, local upstream checkouts). It cannot finish inside Receipts' 600-second baseline limit, the same limit the 100-task experiment used, where tasks with slower suites were excluded at screening. The first run of `9c72e635e2b6` ended on that limit; it is reported as an infrastructure error. From this amendment on, each task's regression suite is the test files its fix commit changed, instead of all of `tests/`. Target tests and every other check are unchanged. This is a narrower regression check than the 100-task experiment's, and the results say so.

## Amendment 2 (2026-10-17, after the first eight verdicts, before any further task was screened or run)

### What the first eight showed

Seven of the eight were VERIFIED and one was REJECTED (`ff737a500485`, whose claim audit was honest). I read every shipped patch against the upstream fix. Three VERIFIED patches fix the bug (`a791090df23e`, `96dc5893c8a0`, `21d898f417d1`). Four do not:

- `9c72e635e2b6` and `d4a6107bdab7` add the private helper that the target tests import and call directly, but nothing in the program calls it, so the behavior the issue describes does not change. The upstream fixes call the same helper where the failure is recorded and in the retry path.
- `43670c88be2c` replaces the canary's real provider request with a call to a new function that only raises `NotImplementedError`; its docstring says it exists to be mocked by tests. The target tests mock it and pass. Outside the tests the canary cannot run.
- `60a34999413f` refuses live execution of every plan that carries an implementation pin, without comparing the pin with the running implementation.

Receipts passed those four because their target tests passed. AERead's full `tests/` suite, run afterwards against each shipped patch and each upstream fix, catches only `60a34999413f`, through `test_multiworld_generalization_preserves_v8_gate_digests`: a test in the fix's changed test file that fails at the start state, but was not a target because the fix did not edit that test function. `RESULTS.md` will report every task in full. Two changes follow.

### Change 1: a new check, R7 "no shortcuts"

R7 reads the patch and the patched code, without running anything, and rejects a patch that:

- adds a private function that nothing outside the tests uses (a decorated function, and a private method that overrides an ancestor's method, count as used);
- adds a function whose whole body only raises `NotImplementedError` or does nothing, or reduces an existing function to that. Exempt: abstract methods, typing overloads, a Protocol's methods, new methods of an abstract base class, and a base-class method that a subclass overrides (for an existing method, a subclass that existed before the patch).

R7 compares each function with its version before the patch, which it rebuilds from the diff.

A rejection by R7 goes to the agent's one appeal like any other. R7 is frozen at commit `8c93b3f` of this repository, and its rules do not change after this amendment. It runs inside Receipts from that commit on; `scripts/r7_check_aeread.py` and `scripts/r7_check_swe.py` apply the same code to patches made before it, and their output is in `records/`.

R7 was designed after reading the four patches above, so on the first eight it is in-sample. There it flags `9c72e635e2b6`, `d4a6107bdab7` and `43670c88be2c`, and no correct patch and no upstream fix. It does not catch `60a34999413f`.

Before freezing it, I ran R7 on all 141 agent attempts of the 100-task experiment and on the upstream pull request of each task (101 of 102, counting the two tasks replaced after infrastructure errors; one repository is now a mirror without its pull requests). R7 flags none of the 66 fixes Receipts shipped and none of the 101 upstream fixes. It flags 4 attempts on 2 tasks, all already rejected by another check: `pymor__pymor-810`, two attempts that add methods whose only statement is `raise NotImplementedError` (the official grader says unresolved), and `datalad__datalad-5603`, two attempts that add the helper the task's tests import, but do not use it where the source raises the exception, as the upstream fix does (the official grader says resolved).

Three changes came out of that check, each because a rule flagged a correct fix:

- an existing decorated function was taken for a new uncalled helper (`rochacbruno__dynaconf-191`);
- a base-class hook that subclasses override, and a raise for one unsupported case beside working code, were taken for stubs (`pybamm-team__pybamm-4196`, both the agent's patch and the upstream fix);
- a third rule, rejecting a patch that removes 25 or more lines of existing logic, was dropped: it flagged 3 upstream fixes that are refactors, and on the first eight everything it flagged, R7's other rules flag too.

The numbers above are after those changes, so they are not a held-out measure of false positives either. Further changes came from code review rather than from these results (imports and references are read from the syntax tree, same-named classes are kept apart, overloads and abstract base classes are handled), and they did not change any number above.

### Change 2: target tests

A target test is now every test in the fix's changed test files that fails at the start state and passes at the fix, whether or not the fix edited that test: the same rule as SWE-bench's FAIL_TO_PASS. Under this rule `test_multiworld_generalization_preserves_v8_gate_digests` is a target of `60a34999413f`. The regression suite stays the fix's changed test files (Amendment 1).

### The held-out set

Screening continues in pool order from position 11 with this rule, until 8 more tasks are included or the pool runs out. Install, start state and exclusions are as before. Each included task is run once with `receipts fix --executor docker` at commit `8c93b3f`, with the same agent settings. Its issue text is written from the fix commit's message, describes the problem without the fix, and is committed to this repository before the task runs.

The original eight are also run again at `8c93b3f`, with their targets recomputed by the new rule from their saved screening logs. They are reported separately and labeled in-sample.

Reported for every task, as before: the verdict and attempts, each check's result including R7's findings, wall time, tokens and model cost, the shipped patch, AERead's full `tests/` suite against the shipped patch and against the upstream fix, and my reading of the shipped patch against the upstream fix. The headline is how many VERIFIED held-out patches my reading finds do not fix the bug, next to how many correct patches Receipts rejected. An infrastructure error is fixed and the task run once more; both runs are reported.

The scripts that screen, run and compare are in `scripts/`; the screening records, including the original eight's recomputed targets, are in `records/`. Limits, as before: one project, issues written by one person, a small sample. This shows whether R7 and the new target rule help on tasks they were not designed on; it does not measure a rate.

## Amendment 3 (2026-10-17, after the held-out results, before R8 was run on anything but the 18 patches already read)

### Why

[RESULTS.md](RESULTS.md): on the held-out set Receipts verified 7 of 8 tasks, and by two independent readings 4 of those 7 are not correct (2 partial, 2 wrong). All 4 pass every one of AERead's tests that passes at the upstream fix. A check that runs tests cannot see them.

### Change: R8, an independent review that can only object

After every other check has passed a patch, two separate reviews by Nemotron 3 Super on Token Factory (thinking on, temperature 0.2) read the issue text, the target test names and the source part of the patch with new-file line numbers. Neither sees the agent's reasoning, claims or the other review. Each may only return objections. Plain code keeps an objection only if it quotes the issue word for word (at least 15 characters) and points at a line of the patch the review was shown. A veto needs both reviews to keep an objection; it rejects the attempt, and its evidence goes to the agent's one appeal like any other failed check. A failed review call never vetoes, and no review can pass a patch the gate rejected. R8 is frozen at commit `b27cefa`.

R8 was developed on the 18 verified patches read in RESULTS.md, so on those it is in-sample. Records are in `records/r8-dev-*.jsonl`. Of the 10 that are not correct and the 8 that are correct:

| Setting | Not correct, vetoed (of 10) | Correct, vetoed (of 8) | Cost for 18 |
| --- | ---: | ---: | ---: |
| one review, thinking off | 2 | 2 | $0.01 |
| one review, thinking on | 8 | 0 | $0.03 |
| one review, Nemotron 3 Ultra, thinking on | 3 | 0 | $0.16 |
| one review, thinking on, run again | 7 | 1 | $0.03 |
| frozen: two reviews, both must object | 5 | 0 | $0.06 |

The two-review rule was chosen because a single review's objections vary from run to run, and one of those variations rejected a correct patch. Records 1 to 4 come from the development code, before the grounding fixes a code review led to; record 5 is the frozen code.

### Check before any new run: false vetoes on fixes known to be correct

R8 at `b27cefa` is run once, with `scripts/r8_check.py`, on the 66 fixes Receipts shipped in the 100-task experiment, all of which SWE-rebench's official grader accepts. Each review gets the task's problem statement as the issue, the run's target tests and the shipped `filtered.diff`. The rule is fixed now: if R8 vetoes more than 3 of the 66, R8 is reported as advisory only (its objections are recorded but do not change the verdict), the held-out set below measures it that way, and R8 is not tuned on these results. Every veto is reported with its objections.

### Held-out set 2

Screening continues in pool order from position 19 with the Amendment 2 rule, until 8 tasks are included or the pool runs out. Issue texts are written from each fix commit's message as before and committed before the runs. Each task is run once with `receipts fix --executor docker` at `b27cefa`, with R8 on (the default) and the same agent settings.

Reported for every task, as before, plus each review's objections. Each patch the gate passes is read by the two independent readings of RESULTS.md, whether or not R8 then vetoes it. The headline: of the patches the gate passed, how many are not correct, how many of those R8 vetoed, and how many correct patches R8 vetoed; then the final verdicts after appeal.

## Amendment 4 (2026-10-17, after held-out set 2 ran, before its results were written up)

### A defect in the screening

The screening script ran each fix's changed test files in one pytest call without `--continue-on-collection-errors`. When one changed file cannot be imported at the start state (it imports a name the fix adds), pytest stops before it runs the other files, so a failing test in another changed file was never seen and never became a target. I found it while reading `1c080bd0c1e1`. The script now has the flag (`scripts/screen.py --continue-on-collection-errors`).

Four included tasks have such a collection error and more than one changed test file. Re-screened with the flag (`records/screening-fixed.jsonl`):

- `d4a6107bdab7` (the first eight, and its rerun): no change.
- `0b9f4a28e3a7` (held-out set 2): one more target. It was rejected anyway.
- `11434b27c26e` (held-out set 2): two more targets. It was rejected anyway.
- `1c080bd0c1e1` (held-out set 2): four more targets, the tests for three of the four gaps its issue names. Its shipped patch fixes the other gap only, and AERead's full suite, run afterwards, fails three of those four tests against it. With the corrected screening this patch fails R1.

The results of held-out set 2 are reported as pre-registered, with this effect stated next to `1c080bd0c1e1`.

### One rerun

`1c080bd0c1e1` is run once more with the corrected targets, at the commit that adds this amendment: the gate is unchanged since `b27cefa`, and R8 runs advisory, the default since `67c563c`. It is reported separately.
