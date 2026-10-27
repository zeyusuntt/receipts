# Plan 5: Receipts v2. Fix what the pilot measured, then measure again on unseen tasks

**Status:** approved by Zeyu on Oct 2, with every recommended decision: one commit per reviewed task; A6 dropped; B6 without the in-image scan; P (100 unseen) plus S (v1's 50, seen), P first; rule 5 judged by the official command; `docs/` committed; pilot data published as a sanitized release. v1's leftover snapshots in the old Daytona organization are out of scope, and Tier 2 is not pursued. Revision 3, Oct 2: an adversarial review (three read-only Codex passes against the code and the v1 records) was folded in. Every finding that touches the trust boundary was reproduced or read in the main session before it was accepted. The revision log and the rejected findings are at the end. Revision 2 is kept at `.build/plan-5-rev2-backup.md`.
**Inputs:** `REPORT.md` (launch 3, 50 tasks), the records in `pilot/run-2026-10-01c/`, `pilot/run-2026-10-01c/environment-artifacts.json`, `data/rebench-v2-python.jsonl`.
**Evidence:** `.build/v1_evidence.py` recomputes every number in section 1 from the record-selected runs (50 tasks, 79 attempts). Card D-a fixed its attempt segmentation and read-only rule on Oct 2. If a number here disagrees with the script, the script wins.

## 1. What v1 measured

| # | Finding | Number | What it means |
| --- | --- | --- | --- |
| F1 | Attempts that ended on budget | 29 of 79 (28 on the 40-turn cap, 1 on time); 2 more ended on three protocol errors (`mpmath-903`) | The worker is turn-bound. |
| F2 | Calls to tools that do not exist | 60 (`execute` 46, `execute_grep` 6, `bash` 3, `grep` 2, `think`, `list_dir`, `str_replace_editor`) | Each costs a turn and a protocol strike. These are Nemotron's tool-name priors from other harnesses. |
| F3 | Model responses with more than one tool call | 0 of 1,875 in the 79 analyzed attempts (0 of 2,084 across all retained logs, which include 5 superseded infrastructure runs) | The model obeys "one tool per turn". Batching would change nothing without changing that contract, so it is not planned. |
| F4 | Where the turns go | 42% of executed calls are read-only (796 of 1,874). Median first edit: turn 6 in attempt 1. In the 29 budget-exhausted attempts (1,157 calls): reads 33%, edits 25%, shell 15%, test runs 14%, Python probes 11%, invented tools 2%; median 11 edits and 4 test runs; 12.5% of calls exactly repeat an earlier call | No single sink: reads are a third, edits a quarter. The worker log records calls but not results, so we cannot yet say how many edits failed to match (A0). |
| F5 | What the agent starts with | The worker's first message has the issue, the spec test ids, the suite scope and the planner's plan. No failure output. The planner gets the raw baseline JSON (median 11 KB over the 50 record-selected runs, max 213 KB) and still no failure output | The single most useful fact, why the spec test fails, costs the agent turns to rediscover. |
| F6 | R4 (patch scope) failures | 22 attempts: 18 touched only new test-named files, 3 modified existing test files, 1 did both. In 4 attempts R4 was the only failed predicate, and all 4 were officially resolved | R4 punishes files that verification never sees, because the filter drops them. |
| F7 | Junk in shipped patches | 3 of 25 PASS attempts add files a maintainer would refuse: a cached PDF, `debug_tmp.py` at the root, and a root-level copy of the package next to the legitimate edit in `src/scikit_build_core/` | "Verified" is not yet "mergeable". |
| F8 | Shadow detection | `default_protected_modules()` reads the host's installed distributions, and `categorize` only recognises a root module file or a one-level `__init__.py` | The root-level `scikit_build_core/build/...` copy passed R4 in launch 3. |
| F9 | Gate ERROR on a patch that broke test loading | 1 (`vyper-3261`, pytest exit 4 from a syntax error) | No appeal was offered for a fixable mistake. |
| F10 | Tasks the official grader cannot resolve in our sandbox | 4 of 50 (network, npm download, host sysfs, chart rendering), observed by the trusted runner, not by the official command | One became a shipped false done. A rule 5 judged on our junit ids would exclude a fifth task by mistake (F19). |
| F11 | Test ids that upstream truncated at whitespace | 10 of 600 candidates in FAIL_TO_PASS, 69 in PASS_TO_PASS, 73 in either. 1 v1 task was lost to it | B3 must handle both lists and many-to-one mappings. |
| F12 | Wall time per task | median 300 s, p90 647 s (linear interpolation) | Every Daytona test run downloads the whole tree, including `.git`, for a digest that ignores `.git`. A rough timestamp estimate puts tree downloads near a third of task wall time. |
| F13 | Concurrency | v1 ran one task at a time. Per task, at most 2 sandboxes are live (base released before the agent; agent plus witness; official forks one at a time) | Concurrency 2 peaks at 4 sandboxes, 8 vCPU and 8 GiB. The new organization's caps are a live precondition (C4). |
| F14 | Record portability | 46 of 58 `record.json` files store absolute `~/Documents/...` run directories; across all v1 artifacts the old prefix appears 2,327 times in 398 files | A top-level rewrite would not sanitize the archive. |
| F15 | Daytona storage | v1 left 68 snapshots (reconstructed: 56 in launch 3, 1 in launch 2, 11 earlier) in the old organization `a3b20c34-...`. The new organization `0d3dbc72-...` holds 0 and its key can delete. The runner already deletes snapshots on close, but a 403 is logged and forgotten | Deletion must be durable and verified against the provider (C3). |
| F16 | Patch parser | `_DIFF_HEADER` matches only unquoted headers. A test file whose name git must quote (a newline, tab or quote in the path) rides inside the previous source block: R4 does not see it and `filter_patch` keeps it. Reproduced on Oct 2. No v1 patch has a quoted header | A path to a shipped test edit. Closed by B0. |
| F17 | Spec files outside test naming | In 27 of 601 candidates the dataset's `test_patch` touches a file the categoriser calls `source` or `other` (for example a root `test.py`, `exercise/tests.py`, fixture YAML). None of v1's 85 filtered diffs touched one | An agent could edit the spec itself, and both the witness and the official grader would run the edited spec. Closed by B7. |
| F18 | Shipped bytes | R5 compares the witness apply digest with the in-memory filtered digest. Official grading re-reads `filtered.diff` from disk and nothing checks it is the same text | Invariant 3 is true in practice but not checked. Closed by B8. |
| F19 | Inherited tests | `junit.py` builds a node id from the file that defines a test. For inherited tests (`fsspec__universal_pathlib-261`) that is `upath/tests/cases.py::...`, while pytest and the dataset use the collecting module `upath/tests/implementations/test_data.py::...` | Fail closed for the gate (an unmatched spec id excludes a task), but rule 5 must not be judged on these ids. |

## 2. Goals, in order

1. **No shipped false done that the environment or Receipts causes.** Close every known path (F16 to F18), and grade only tasks the official rule can resolve here, decided before the agent runs.
2. **Shipped patches a maintainer would accept.** Verified and clean.
3. **More verified fixes for the same model, by removing harness waste.** Every change is a general property of a good coding harness, decided before v2 and frozen at one commit.
4. **A headline from tasks nobody has looked at.** v2's primary sample is disjoint from v1, so v1's lessons cannot leak into the headline.

## 3. Changes

Every item is test-first: the failing test is written and seen to fail before the code changes. "Files" names the expected touch points; the task card confirms them. Items are tiered: **must** items protect the headline and block the freeze; **should** items improve the harness and are frozen only if done by the cut line (section 6).

### Workstream B: the gate (all must, except B3b)

The soundness invariant behind B1 is that the witness and the official grader apply only `filter_patch` output, and that exact text is what ships. B0 makes the filter's parse total, B7 widens what it protects, and B8 checks the "exact text" part on every attempt.

**B0. Patch parsing fails closed.** (F16)
- Change:
  - Every `diff --git` line must match the unquoted form with identical `a/` and `b/` paths, which is what the executor's `--no-renames` diff produces. Any other header (quoted, mismatched, rename or copy) makes R4 fail with "unparseable path", and `filter_patch` keeps nothing from that patch.
  - `ChangedFile` gains `status`: `added` when the block has `new file mode`, `deleted` when it has `deleted file mode`, otherwise `modified`. A delete and re-create of the same path is `modified`.
- Files: `patchscope.py`, `models.py`, `verify/gate.py`; `tests/test_patchscope.py`, `tests/attacks/`.
- Attack tests, written first: the Oct 2 reproduction (a source block followed by a quoted `tests/test_\nx.py` block); names with tab, quote, backslash and a literal ` b/`; a mode-only change to a test file; delete and re-create of a test path; an added versus a modified binary test file.

**B1. A new test-named file is dropped, not fatal.** (F6)
- Change: in R4, a `test` category file whose status is `added` no longer fails. It is already dropped by `filter_patch` and listed on the receipt. A modified or deleted test file still fails.
- Precedence: hazard categories are checked before the exemption: `outside`, `symlink`, `executable_artifact`, `pytest_config`, `spec` (B7), `reserved` and `shadow` (B6). An added file that is both test-named and a hazard stays fatal.
- Files: `patchscope.py` (category and hazard as separate fields), `verify/gate.py`; tests and `tests/attacks/`.
- Attack tests, written first. Each must hold:
  1. A new `conftest.py` fails R4.
  2. A new `tests/test_x.py` that monkeypatches the module under test at import is dropped, and R1 decides on the witness.
  3. An edit to an existing spec test fails R4.
  4. A `git mv` of an existing test (a delete plus an add under `--no-renames`) fails R4 on the delete.
  5. A source fix that imports a dropped helper fails R1 on the witness, with the import error as evidence.
  6. A new test file plus a correct source fix is a PASS, and the receipt lists the dropped file.
  7. A new test-named file under a protected top-level name fails R4.

**B2. A patch that breaks test loading is a rejection with evidence.** (F9)
- Change: after a valid baseline, a witness run that is not timed out and exits 2, 3 or 4 is run once more on a fresh fork from C0.
  - Both runs exit 2, 3 or 4: REJECTED. R1 fails with "the suite could not load with this patch (pytest exit N)" and the stored output tail, which holds pytest's error summary. R2 and R3 fail with "not evaluable: the suite did not load". R4 and R5 are evaluated normally. The appeal receives this evidence.
  - The second run does not reproduce it: ERROR, classified as infrastructure, so the pilot retries the task under the infrastructure rule.
  - Pytest also exits 2, 3 or 4 on SIGINT, plugin crashes under memory pressure and bad arguments, so a single run is not enough to blame the agent.
- These stay ERROR: timeouts, exit 137, a missing junit with exit 0, 1 or 5, and a failed apply. `PREREGISTRATION-v2.md` states how each ERROR kind is counted (v1 counted them as the attempt's outcome).
- Files: `verify/gate.py`, `verify/run.py`, `orchestrate.py`, `pilot/runner.py` (infrastructure classification); `tests/test_gate.py`, `tests/test_verify_run.py`, `tests/test_pilot_runner.py`.

**B3. Map ids that upstream truncated.** (F11)
- Change: when a dataset FAIL_TO_PASS or PASS_TO_PASS id is not collected, it maps to every collected id whose first whitespace-separated token equals it.
  - R1 requires all mapped targets to pass. Upstream keeps the last status line for a truncated key, so this is at least as strict for both lists.
  - The mapping (dataset id, full ids, count) is stored with the baseline and shown on the receipt. An empty mapping fails closed, as today.
  - R2 needs no change: it protects every collected id under its full name.
- Files: `swerebench.py`, `verify/run.py`, `models.py`, `orchestrate.py`, `pilot/report.py`; tests with `martinthoma__flake8-simplify-173`'s real ids, plus zero, one and many matches and mixed pass and fail order.

**B3b (should). Exact node ids for inherited tests.** (F19)
- Change: the trusted runner's bootstrap adds a property-only plugin that writes each item's real `nodeid` into its junit testcase, and `junit.py` prefers it (rebased to the invocation directory) over the id rebuilt from `file`. Python 3.7 compatible; no effect on outcomes.
- This touches the trusted runner (invariant 5), so it ships with its own amendment text in `PREREGISTRATION-v2.md` and a test on the stored fsspec junit.
- Without it, spec ids in inherited tests keep failing closed, and the report lists those exclusions.

**B4. Gradeability is a selection rule (rule 5), judged by the official command.** (F10)
- Rule: at screening, the official grading (the dataset's raw `test_cmd`, upstream parser, B3 mapping) runs on a fresh C0 fork with an empty patch. Every PASS_TO_PASS must parse as PASSED and every FAIL_TO_PASS must not. Otherwise the task is excluded as "not gradeable in this environment", with the failing ids listed.
- This asks the oracle that will grade the task, not our runner, so it also avoids F19. An infrastructure failure in this run follows the infrastructure-retry rule; it never silently excludes.
- Refactor: `grade_patch(checkpoint, patch_text)` serves both screening and attempts.
- Applied to v1, the rule should exclude exactly `pypdf2-1318`, `guarddog-156`, `psutil-2379` and `altair-3068`. Checking that is part of D1.
- Files: `pilot/grade.py`, `pilot/runner.py`, `swerebench.py`, `models.py`; screening and empty-patch grading tests.

**B5. Keep the subtest check.**
- The gate's junit-based R2 caught a `SUBFAILED` regression (`qiskit-ibm-runtime-452`) that the upstream parser misses.
- Add the stored junit as a fixture. Assert the junit failure, the R2 rejection and the official parser's disagreement. Document the behaviour in the gate's docstring.
- Files: `junit.py` (docstring), `verify/gate.py`; `tests/test_junit.py`, `tests/test_gate.py`.

**B6. Shadow and startup-hook detection.** (F8)
- Protected names, stored with the baseline so the gate stays pure:
  - the host's stdlib and installed names, as today;
  - the repository's own top-level packages and modules in the C0 tree, at the root and under `src/`, read from the trusted checkpoint tree.
- Reserved, fatal anywhere in a path: `sitecustomize.py`, `usercustomize.py`, any segment ending in `.dist-info` or `.egg-info`, and `entry_points.txt`. These run at interpreter start or register pytest plugins without touching configuration files.
- Rule: a new path is `shadow` when its first segment (or first segment under `src/`) is protected and that top-level path did not exist in C0. Editing the real package of a flat-layout repository is still `source`.
- Not in this plan: scanning the sandbox's installed distributions from inside the image. Since Amendment 2 the witness and the official command import modules the same way, so a root shadow cannot split them. The scan's value is defense in depth, at the cost of a Python 3.7 metadata scanner with many failure modes. Section 7 lists it.
- Files: `patchscope.py`, `models.py`, `verify/run.py`, `orchestrate.py`, the executors' checkpoint path; tests, including both scikit-build patches (launch 2 and launch 3).

**B7. The spec is read-only.** (F17)
- Change: every path in the instance's `test_patch` (in product mode, the human's test commit) gets the hazard `spec`. Any change to it fails R4 and `filter_patch` drops it.
- The path list is stored with the run input, so the gate stays pure.
- Files: `patchscope.py`, `models.py`, `swerebench.py`, `orchestrate.py`, `verify/run.py`; tests with `amoffat__sh-598`'s root `test.py` and a fixture YAML from a real `test_patch`.

**B8. Bind the shipped bytes.** (F18)
- Change: the attempt record stores the SHA-256 of `filtered.diff` when it is written. Official grading checks the file against it and against the witness apply digest before applying, and records its own apply digest. The report asserts that all four are equal for every attempt. E2's re-verify checks the same digest.
- Files: `orchestrate.py`, `models.py`, `pilot/grade.py`, `pilot/runner.py`, `pilot/report.py`; a test that mutates `filtered.diff` between the gate and grading.

### Workstream A: the agent harness (should, except A5)

**A0. Log tool results.** (F4)
- Change: each `worker.jsonl` call row also records `executed`, a result class and the byte size of the text returned to the model. Classes: `ok`, `unknown_tool`, `bad_args`, `malformed_args` (from `MalformedToolCall`, today a generic strike), `edit_no_match`, `edit_multiple_matches`, `edit_too_large`, `edit_invalid_utf8`, `write_refused`, `command_timeout` (wins over a nonzero exit), `nonzero_exit`, `finish_refused`, `not_executed`, `tool_error`.
- Files: `agent/worker.py`, `llm.py`, `pilot/report.py`; `tests/test_worker.py`, `tests/test_llm.py`, `tests/test_pilot_report.py`.
- Done when: the rehearsal's logs can answer "how many edits failed to match, and why".

**A1. Tool aliases.** (F2)
- Change: map the names the model reaches for onto our tools. They cost no protocol strike, and each reply names the real tool. An alias is rewritten before dispatch, so it gets exactly the routing the real tool would get; it does not make `bash -c 'pytest'` or `cd tests && pytest` trusted.

  | Model's call | Runs as |
  | --- | --- |
  | `execute`, `bash`, `shell`, `run`, `terminal`, `execute_command`, `execute_bash` with `command`, `cmd` or `script` | `run_command` |
  | `execute_grep`, `grep`, `search` with `pattern` and optional `path` | `run_command` with `grep -rn -- <pattern> <path>`, each argument `shlex.quote`d |
  | `list_dir`, `ls` with optional `path` | `ls -la -- <path>`, quoted |
  | `str_replace_editor` with `view`, `str_replace` or `create` (v1's shape: `command`, `path`, `old_text`, `new_text`) | `read_file`, `edit_file` or `write_file` |
  | `think` | no action, the reply is "noted", no strike |

  Anything else stays an unknown-tool strike.
- Files: `agent/worker.py`; `tests/test_worker.py`.
- Tests first: one per row; a pattern containing `'; rm -rf /` arrives as a literal; leading-dash, newline and NUL arguments; an aliased `execute` running `pytest` produces a junit-bearing receipt; aliased `bash -c 'pytest'` does not.

**A2. Dropped.** Batching read-only calls. See F3.

**A3. Start the agent where the failure is.** (F5)
- Change:
  - `JunitSummary` keeps failure text for failed and errored tests and for collection-error files (new-module tasks fail at collection), capped at 2,000 characters each, ANSI stripped.
  - `Baseline` keeps the targets' failure text from the first baseline run.
  - The worker's first message gains `<baseline_failures>`, capped at 6,000 characters in total.
  - The planner's raw baseline dump is replaced by a compact summary: targets with outcomes and failure text, plus counts of collected, protected, unstable and skipped tests.
  - Record per model call: request size, prompt tokens and finish reason (planner included).
- Product argument: this is exactly what a developer sees when they write the failing test and run it.
- Files: `junit.py`, `models.py`, `verify/run.py`, `agent/planner.py`, `orchestrate.py`, `llm.py`; their tests, and a compatibility test that loads every v1 `result.json`, `baseline.json` and receipt with the new models.

**A4. A scratch area outside the repository.** (F7)
- Change:
  - Executors expose a per-branch scratch path, `/tmp/scratch` in Docker and Daytona and a directory beside the worktree locally, created after the agent fork so it never enters C0.
  - `write_file` and `read_file` accept paths under it, lexically contained.
  - The system prompt says to put probe scripts there, and that new source files in the repository ship with the fix while test and configuration files are dropped.
- Scratch never enters a digest or a patch.
- Files: `sandbox/protocol.py`, `local.py`, `docker.py`, `daytona.py`, `agent/worker.py`, `orchestrate.py`; tests per executor: a scratch write works, traversal out of scratch is refused, the digest and the patch are unchanged by scratch writes, a witness fork does not contain scratch.

**A5 (must). Budget and context.** (F1)
- Change: 60 turns, 1,500 seconds and 96,000 completion tokens per attempt, still with one appeal.
- Context guard: v1 reached 88,646 prompt tokens at 40 turns, and the whole history is resent each turn. When a request would exceed a fixed prompt budget of 160,000 tokens, the oldest tool outputs are replaced by a one-line note. Token Factory reported a 262,144-token context for Super on Oct 2, and completions need headroom; C4 re-checks it before the launch. The rule is deterministic and frozen.
- Cost: prompt tokens grow with the square of turns. Budget-exhausted attempts were 83% of v1's model cost, so expect model cost per budget-exhausted attempt to roughly double.
- Files: `orchestrate.py` (`RunBudgets`), `cli.py` (it duplicates the defaults), `agent/worker.py`; `tests/test_orchestrate.py`, `tests/test_pilot_runner.py`, `tests/test_worker.py`.

**A6. Dropped.** A reminder that intercepts the first `finish` when new files exist. It would change configuration A's treatment relative to v1 (the agent gets a second look before its claim is recorded), and sandbox `git status` does not match the shipped patch. B1, B6 and A4 already remove most of F7, and the receipt lists every new file.

### Workstream C: executor speed, scale and preflight (must, except C1)

**C1 (should). Do not download `.git` where it is not needed.** (F12)
- Change: `_download_tree` takes an explicit mode. The checkpoint download keeps `.git`, because symlink reconstruction and host-side patch staging run trusted git on it. Digest and agent-tree downloads skip it.
- Record tree-listing and download durations on receipts.
- Files: `sandbox/daytona.py`; `tests/test_daytona_executor.py`. Tests: checkpoint symlinks, patch computation and digest equality still hold, and nested `.git` is skipped.

**C2. Two tasks at a time, safely.** (F13)
- Change: run with `concurrency=2` once these hold:
  - an integrated fake-Daytona test at concurrency 2 covering baselines, appeal, official grading, retries, resume and cancellation;
  - the runner writes an explicit terminal marker for a final infrastructure error, and the watchdog reads only that (today it can kill a pending retry and its healthy sibling);
  - SIGTERM cancels gracefully, with shielded executor cleanup;
  - each task's cost counts planner and worker usage;
  - 429 retries and live-sandbox intervals (creation and deletion timestamps) are recorded, so the rehearsal can show the peak.
- Files: `pilot/runner.py`, `cli.py`, `llm.py`, `orchestrate.py`, `cost.py`, `sandbox/daytona.py`, the watchdog (moved from `.build/` into the repository); their tests.

**C3. Durable snapshot cleanup.** (F15)
- Change: deletion already runs on close. Make it durable: persist each snapshot's provider id, name, deletion status and last error in a cleanup manifest before deleting; treat 403 as a failure; on resume, retry pending cleanup before starting new work, without re-running any agent.
- Files: `sandbox/daytona.py`, `pilot/runner.py`, `models.py`, `rundir.py`; `tests/test_daytona_executor.py`, `tests/test_pilot_runner.py`.

**C4. Preflight artifact.** (F13, F15)
- Before D2 and before D4, a read-only preflight writes a dated JSON with no secrets: the Daytona organization id, key permissions, snapshot count and size, the tier's vCPU, memory and disk caps, the Token Factory balance, and the model's context limit. D2 and D4 do not start unless it passes. Separately, Zeyu deletes v1's 68 snapshots in the old account, which does not block v2.

### Workstream D: the v2 measurement (must)

**D-a. Fix the evidence script. Done Oct 2.** Segment worker logs by `result.json` `attempts[*].worker.turns`, use only record-selected runs, count read-only only for executed calls. Re-check F3 to F5 against it.

**D0. Portable records, untouched evidence.** (F14)
- New runs write every path repository-relative.
- v1's records are never edited. D5 builds a sanitized publication copy that rewrites every path-bearing field, asserts zero old-prefix matches, and checks that `pilot report` gives the same numbers. Both the original and the sanitized SHA-256 manifests are published.

**D1. Counterfactual replay of the v2 gate on v1 attempts.**
- The gate is a pure function of stored receipts. Re-evaluate every v1 attempt under the v2 gate (B0, B1, B2, B3, B7, and B6 with the repository's packages inferred from stored trees and patch paths, labelled partial because v1 stored no package inventory), and publish the table.
- Expected:
  - the 4 R4-only attempts become PASS;
  - `vyper-3261` attempt 1 becomes REJECTED (B2's second run cannot be replayed; the stored exit and tail are taken as reproduced, and the table says so);
  - launch 3's scikit-build patch becomes REJECTED on R4 as shadow;
  - no attempt the official grader did not resolve **newly** becomes PASS. `pypdf2-1318` attempt 2 stays an unresolved PASS; it is the environment case that B4 excludes at screening.
- B4's rule cannot be replayed on v1 data (v1 never graded an empty patch); screening S checks it for real (gate 2).
- Any new gate-looser case blocks the freeze.

**D2. Rehearsal.**
- Five tasks taken from the end of `pilot/candidates.txt`: walk backwards and keep the first five that pass rules 1 to 5. Their ids are committed to `pilot/v2-exclusions.txt` before P is selected, together with v1's 58 ids.
- Pass criteria:
  - no invented-tool strikes;
  - no R4 failure caused by a new test file;
  - no new file in a shipped patch that a reviewer would remove;
  - no gate ERROR except infrastructure;
  - peak live sandboxes within the caps at concurrency 2, from recorded intervals;
  - zero snapshots in the organization afterwards, read from the provider;
  - peak prompt tokens under the context budget;
  - 429 count and median wall time per task reported next to v1's 300 s.
- After the last fix, the full suite, D1 and D2 all run again.

**D3. `PREREGISTRATION-v2.md`, committed before screening starts.**
- Fixed and unchanged: the question; the model, sampler and thinking setting (`nvidia/nemotron-3-super-120b-a12b`, temperature 1.0, top_p 0.95, thinking off, for the planner and the worker); one appeal; official ground truth as in v1.
- Changed: every item in section 3 that landed, frozen at one named commit.
- Definitions made explicit:
  - configuration A is the accepted `finish` that ends attempt 1 (v1's wording said "first finish" while its records used the accepted one; this is stated);
  - how each gate ERROR kind is counted (B2).
- Samples. Both use `pilot/candidates.txt` and its order:
  - **Primary, unseen (P):** walk from position 59, skip every id in `pilot/v2-exclusions.txt`, and apply rules 1 to 5 in a screening phase (prepare, two baseline runs and the empty-patch official run; no model). Take the first 100 included as the sample and the next 10 as an ordered reserve. Expect about 139 positions (149 for 95 percent confidence). If the reserve runs out, keep walking in order. Commit a selection ledger (position, id, exclusion reason, B3 mapping, membership) and both lists before any agent runs. **The headline comes from P only.**
  - **Seen (S):** v1's 50 tasks, screened under rule 5 and re-run under v2, paired with their v1 records, labelled as seen.
- Reported:
  - everything v1 reported, for P;
  - for S, the v1-versus-v2 paired table (claimed done, false done, verified), discordant counts and the exact McNemar p-value, labelled exploratory;
  - harness statistics for both (strikes, turns, edit failures from A0, context-guard events).
- Headline rules H1 to H3 as in v1, with the sentence stating the real counts. That fixes v1's deviation.
- Infrastructure retries as in v1 (Amendment 4), plus B2's non-reproduced load failures.
- Order and stop rule: P runs to completion before S starts. If P is not complete by Oct 12, 23:59 PT, report every task run so far, in order.
- Any code change after the freeze is a dated amendment.

**D4. Run and report.**
- Run C4's preflight, screen, commit the sample, then run P and then S at concurrency 2 under the watchdog.
- Estimates from v1's records: about 190 to 200 screens; 11 to 15 hours elapsed in total; model $10 to $15 (A5's longer attempts); sandbox $3.50 to $5.50. Check the Token Factory balance first.
- The report is generated by code. The narrative explains every disagreement. v1's `REPORT.md` stays unchanged.

**D5. Publish the data.**
- Archive v1 (including the aborted launches) and v2 records, traces and receipts as a GitHub release, as the sanitized copy from D0 plus the original manifest.
- Scan for secrets before upload.

### Workstream E: what the judges see

E runs alongside D. Judges score design, impact and idea as much as implementation, and in an online event with 14,000 registrants they judge from the write-up, the diagram and the video (playbook, EcoLafaek lesson).

- **E0. Script first (new, starts Oct 2, no code).** Write the video script and the README first screen before the run (playbook law 1), with placeholders for v2's numbers, so the run's receipts are chosen to serve the story rather than found afterwards.
- **E1. Receipt site (the demo URL).**
  - `receipts site` generates a static site from run directories: a Run page and a Receipt page per the D1 mockups (https://claude.ai/artifact/9rqEefF1fbjs8NoGMQuk8d).
  - Each Receipt page shows the predicates, the claim audit next to what the agent said, the dropped files and the new files.
  - Hosted on GitHub Pages.
- **E2. `receipts reverify <receipt>`.** Anyone with Docker can re-check a published receipt on the task's public image: apply the shipped patch on a clean fork, check its digest (B8), re-run the spec tests, and compare. No hosted button spends our sandbox credits. Checked Oct 2: the SWE-rebench-V2 images are public on Docker Hub (`docker.io/swerebenchv2/...`); an anonymous manifest request returns 200 for candidates at positions 1, 101, 301 and 600, including scikit-build-core-254. Anonymous pulls are rate-limited per IP (about 100 per six hours), which a judge will not reach.
- **E3. README first screen.** The false-done number, one real receipt, and "re-verify it yourself" in three commands.
- **E4. Video under three minutes.** The spine:
  1. The pilot's own false done (scikit-build: our gate shipped it, the pre-registered process caught it, here is the fix).
  2. The v2 headline.
  3. A live re-verify.
- **E5. Submission.**
  - The Devpost text, addressing all four criteria by name.
  - `FEEDBACK.md`, with upstream findings for SWE-rebench (ids truncated at spaces, `SUBFAILED` ignored, network-dependent PASS_TO_PASS tests, spec files outside test naming) and Nemotron tool-calling observations (F2, F3).
  - A public repository with the MIT license already in `LICENSE`.
- **E6 (option, Zeyu decides after v2 launches).** A GitHub Action that runs the gate on a pull request and posts the receipt as a check.

## 4. Acceptance gates

1. The full suite passes (337 today plus the new tests), including the attack suite with B0, B1 and B7's new attacks, and the v1 corpus loads under the new models.
2. D1's replay table shows no new gate-looser case, and screening the seen sample S excludes exactly v1's four environment tasks under rule 5 (or every difference is explained before P runs).
3. The D2 rehearsal meets every criterion it lists, after the last fix, with the full suite and D1 re-run.
4. C4's preflight artifact passes before D2 and before D4.
5. `PREREGISTRATION-v2.md` is committed before screening; the exclusion list, the selection ledger, the sample and the reserve are committed before any agent run.
6. The v2 report is generated by code, B8's four digests agree on every attempt, every disagreement is explained, and v1's `REPORT.md` and records are untouched.

## 5. Risks

- **Overfitting to v1.** Several changes answer failures seen on v1's tasks. Mitigation: the headline comes only from the unseen sample P, and S is labelled as seen.
- **B1 opens a gaming path.** Mitigation: B0 makes the filter's parse total, hazards are checked before the exemption, existing test edits and all configuration stay fatal, and seven attack tests pin it down.
- **Unknown paths to a shipped false done remain.** This review found three (F16 to F18). Mitigation: the B attacks, D1, and B8's digest check on every attempt; the watchdog still stops on any gate-looser case.
- **Context growth at 60 turns.** Mitigation: A5's guard, C4's context limit, and D2's peak-prompt criterion.
- **B2 misclassifies.** A flaky load failure that reproduces twice becomes an agent outcome. Mitigation: two fresh forks; the report lists every B2 rejection with its tail.
- **Scope.** Revision 3 adds B0, B7, B8, C4 and D-a and widens C2 and C3. Mitigation: the must and should tiers and the cut line in section 6.
- **The Daytona caps, snapshot quota or permissions block the run.** C4 and gate 4 cover this.
- **Token Factory rate limits at concurrency 2.** Unlikely: Token Factory listed Super's per-request limits as effectively unlimited on Oct 2. The rehearsal measures them anyway. Fall back to concurrency 1; that costs wall time, not validity.
- **v2 eats the product time.** Hard stop on Oct 12. If v2 slips, v1 stays the headline and v2 is reported as far as it ran.
- **Disk.** 65 GB free on Oct 2. Staging downloads of large repositories need several GB at a time. C4 checks it.

## 6. Order of work and dates (deadline Oct 30, 10:00 PT)

| When | What |
| --- | --- |
| Oct 2 | Zeyu approves. C4 preflight. Batch 1 (no executor dependency): B0, B7, B8, B1, B5, D-a. E0 starts. |
| Oct 3 | Batch 2: B2, B3, B4 (`grade_patch`), B6, A5, A0, A1. |
| Oct 4 | Batch 3: C2, C3, D0 (new paths), A3, A4, C1, B3b. |
| Oct 5 | **Cut line.** Any should item not merged is left out of v2. D1 replay. Full suite. |
| Oct 6 | D2 rehearsal, fixes, then the full suite, D1 and D2 again. |
| Oct 7 | Freeze, D3, screening (about 200 screens), commit the ledger and the sample, start P. |
| Oct 8 | P completes; S starts. |
| Oct 9 | S completes. The SF City Winner meetup (4 to 10 pm), if Zeyu goes. |
| Oct 10 | v2 report. Oct 12, 23:59 PT stays the hard stop for P. |
| Oct 7 to 10 | E1 and E2, while the runs go. |
| Oct 10 to 27 | E3 to E5, and E6 if chosen. |
| Oct 28 | Full submission dry run from a clean clone. |
| Oct 29 | Submit, one day early. |

## 7. Not doing, and why

- **Batching tool calls:** see F3.
- **The A6 finish reminder:** it changes configuration A; see A6.
- **Scanning installed distributions inside the image (full B6):** both runs import alike since Amendment 2, and a Python 3.7 metadata scanner has many failure modes. Revisit if D1 or D2 shows a shadow that the repository-package rule misses.
- **Thinking mode or a different model:** v2 measures the harness and the gate, so the model stays fixed.
- **A second appeal:** the design says one appeal. A second would change what B means.
- **Prompt tuning on v1 tasks:** it would contaminate S and could leak into P's design.
- **A public live re-verify button:** it costs money per click and invites abuse. E2 gives the same proof with the viewer's own Docker.
- **Switching to Token Factory Sandboxes mid-plan:** only if access arrives before the freeze, and then rehearse on it again.

## 8. Revision 3 log (Oct 2)

Three read-only Codex reviews (numbers and measurement; the gate's trust boundary; harness and executors) checked revision 2 against the code and the v1 records. The main session reproduced F16 in a scratch repository, counted F17 over the candidates and v1's 85 filtered diffs, confirmed F19 on the stored fsspec baseline, and read the code behind C1, C3 and the watchdog race.

Accepted: F16 to F19 and B0, B7, B8, B3b; corrected F3, F4, F5, F10 to F15; B1's status model (renames cannot occur under `--no-renames`) and precedence; B2's re-run rule; B3's stored mapping; B4 on the official command; B6's reserved names; A0's full taxonomy; A1's routing statement and tests; A3's collection-error text and context metadata; A5's context guard; C1's download mode; C2's watchdog, signal, cost and 429 fixes; C3 as durable cleanup; C4; D0 without editing v1; D1's partial B6 replay and the pypdf2 wording; D2's committed exclusions and full re-run; D3's ledger, P before S and A's definition; corrected D4 estimates; incomplete Files lists.

Rejected or changed:
- **Model cost of $7 to $11:** the reviewer scaled cost linearly with turns. Prompt tokens grow with the square of turns, and budget-exhausted attempts dominate cost, so $10 to $15 stays.
- **B2 with a C0 control run:** replaced by a second patched run on a fresh fork, which tests reproducibility directly at the same cost.
- **Header parsing via `git diff --name-status -z` in every executor:** replaced by fail-closed parsing in the pure `patchscope`, which closes F16 without executor changes.
- **The full in-image B6 scanner:** deferred, see section 7.
- **Daytona symlink containment for the scratch path:** not a trust issue. Scratch lives only in the agent's sandbox, where the agent already has an arbitrary shell, and nothing from it reaches C0, a witness or a patch.
- **`sitecustomize` as a direct route to a false done:** real but adversarial. It needs a patch that detects which runner loads it, the same class as "code that detects it is under test" in v1's limits. It is closed anyway, cheaply, by B6's reserved names.

## 9. Implementation status and deviations (Oct 2)

Each item landed test-first, was reviewed (trust-boundary items in the main session), and was committed on its own after the full suite passed with Docker. Commits are on `build/plan-1`.

| Item | Commit | Note |
| --- | --- | --- |
| B0 | `2f8fb60` | As planned. |
| B7 | `0ba0a2e` | Also: a test patch with an unparseable path (18 dataset rows, all renames, none in `candidates.txt`) excludes the task instead of counting as infrastructure. |
| B1 | `4cc5eb9` | As planned. |
| B8 | `9c65215` | Also records the digest of the bytes official grading read, so a patch changed after the gate counts as a mismatch. |
| B5 | `d1237f3` | Regression tests on the stored qiskit data; the behaviour already existed. |
| C4 | `035f6a2` | Token Factory settings follow the model client (`.env` overrides the shell). Daytona organization limits are not readable with our key (403), so D2 measures the peak instead. |
| A1 | `059c532` | As planned, plus review fixes (non-string editor command, view ranges). |
| B2 | `22f1995` | As planned. |
| B6 | `9dac934` | `reserved` is narrowed to `sitecustomize.py`, `usercustomize.py` and `entry_points.txt` by file name; other `.dist-info`/`.egg-info` files stay `other`, because reinstalling an editable package rewrites them when they are in C0. |
| A0 | `c511d9a` | Plus review fixes (malformed-call metadata can no longer raise; tolerant log parsing; edit-failure rate over all edit calls). |
| B4 | `d02002b` | With `receipts pilot screen`. |
| B3 | `e3c4991` | FAIL_TO_PASS only: rule 5 is judged by the upstream parser, which truncates PASS_TO_PASS ids exactly as the dataset does. |
| A5 | `e7ce066` | As planned. |
| C1 | `55b81d1` | One recursive listing per download is kept; only downloads are skipped. |
| C3 + D0 | `43eba91` | With `receipts pilot cleanup`. Existing records are never rewritten. |
| A3 | `2c69576` | As planned. |
| C2 | `3f04e1f`, `ec4bc5b` | Watchdog is `receipts pilot watch`. |
| D-a | (gitignored) | `.build/v1_evidence.py`. |
| B3b | cut | It changes the trusted runner a week before the freeze, for a benefit that is only fewer fail-closed exclusions. Inherited spec ids keep failing closed, and screening lists them. |
| A4 | in progress | Should tier. |
| D1 | in progress | B4's rule cannot be replayed on v1 data: v1 never ran an empty-patch official grading. Instead, screening the seen sample S runs rule 5 on v1's tasks for real, and the expectation is that it excludes exactly the four environment tasks. |

## 10. C5: the Token Factory Sandboxes executor (added Oct 2, Zeyu approved the switch)

Token Factory Sandboxes access became active on Oct 2 (all six permissions; 50 concurrent operations). The catalogue preloads 32,064 SWE-rebench-V2 images, including 598 of the 600 candidates' images (`docker.io/swerebenchv2/X:Y` is tag `swerebenchv2/X:Y`). A trivial run takes about 1.1 s; every non-disposable run returns a new immutable image, and two runs from one image are isolated. Plan 5 already allowed the switch if access arrived before the freeze, with a new rehearsal. Zeyu approved it on Oct 2 because the track asks for agents that "write, run, and test code in Token Factory".

Design, keeping every trust property of the Daytona executor:

- A branch is a chain of immutable images; each command on a branch is one non-disposable run from the branch's head and moves the head. Receipts record the platform's image uuids before and after, so lineage comes from the platform. A checkpoint is an image uuid; images are immutable, so C0 cannot be changed after the checkpoint.
- Trusted tooling is injected at spawn time through the API's `files`, never read from the image: a statically linked busybox (busybox.net 1.35.0 x86_64 musl, SHA-256 `6e123e7f3202a8c1e9b1f94d8941580a25135382b99e8d3e34fb858bba311348`, uploaded once and checked by digest) and the trusted pytest bootstrap. A static binary ignores the image's libraries, preload files and PATH.
- Full output: commands write stdout and stderr to files that are downloaded through the inspect API, because the run result truncates them at 64 KB. Official grading needs the full `-rA` log.
- Patch: the injected busybox archives the agent's worktree (without the top-level `.git`) into one tar; the host extracts it over a trusted copy of the checkpoint tree (archived once per task, with `.git`) and runs the existing hardened host-side git staging. The witness applies the filtered patch, uploaded and injected, with the upstream `git apply` flags, on a C0-derived image.
- Tree digests for the claim audit are computed in the sandbox by the injected busybox.
- No sandboxes or snapshots to delete: runs end on their own. Cost per run comes from the platform's reported cost.
- Concurrency: up to eight tasks at a time, well under the 50-operation limit.

Cards: TF-1 REST client and fake (in progress), TF-2 executor core, TF-3 pytest, digests, patch and apply, CLI and preflight, TF-4 live smoke test and rehearsal on the five D2 tasks.

Decision gate: if the Token Factory rehearsal meets every D2 criterion by Oct 6, 23:59 PT, v2 freezes on Token Factory Sandboxes. Otherwise v2 freezes on Daytona, which passed rehearsal 2 (`docs/results/`), and Token Factory Sandboxes is used for re-verify and the demo only. The Oct 12 stop rule for P is unchanged.

## 11. Pre-freeze review (Oct 2)

A final adversarial review of the freeze candidate returned NO-GO with 13 findings. One did not apply (every one of the 600 candidates' test commands starts with `pytest`, so the `python -m pytest` import difference cannot occur in this sample). Two are stated as known limits in the pre-registration instead of fixed: output over Token Factory's 10 MiB cap fails closed (screening removes tasks whose suite alone exceeds it), and the advisory tree digest ignores directory symlinks (R4 still rejects any shipped symlink). The other ten were fixed in three cards, each reviewed in the main thread, plus four gaps found in that review:

| Commit | What changed |
| --- | --- |
| `292ef59` | Token Factory executor: trusted busybox and pytest runner at a fresh random path per run; a client timeout above each run's own timeout, raised as infrastructure; archive caps on size (512 MiB), members (200,000, read one at a time) and member path length; a run that must return an image and does not fails. Found in review: the worktree download now stops streaming at the size cap instead of reading the whole archive into memory. |
| `f9896ff` | Runner and grading: interrupted runs are archived with their partial spend and rerun from scratch; cleanup failures no longer change outcomes; official grading refuses an apply-digest mismatch and a witness-apply mismatch; an official timeout is an agent outcome when the witness also timed out. Found in review: the watchdog's budget now counts interrupted runs. |
| `398bc18` | Report and CLI: spend over every run class, cost per verified fix over all spend, screening ledgers in the report, `pilot run --model`. Found in review: `--model` refuses a model with no listed price (its spend would be invisible to the budget), and Token Factory's per-run sandbox cost is shown as reported, not as dollars, because its unit is not published. |
| `500b9af` | Pre-registration draft: the hang, interruption and spend-stop rules, and the known limits. |

Checks on `500b9af`: the full suite passes with Docker (only the two live-network tests skip). The D1 replay gives the same verdict on all 80 v1 attempts as the committed D1 result, with no new gate-looser attempt.

### Smoke test on Token Factory (Oct 2)

Two seen rehearsal tasks ran at `500b9af` (`pilot/v2-smoke-tf/`): `pypa__twine-1066` with `--model nvidia/Nemotron-3_5-Lightning` and `pysmt__pysmt-812` with Super. Lightning verified on its third run, with the gate and the official grade agreeing; its first two runs were infrastructure errors, each a status poll that got no answer within 30 seconds. The Super run showed stalls of 13 and 9.5 minutes with no activity and was stopped by the session's one-hour limit after 47 turns; it left `record.interrupted-1.json` with its partial spend (1.04 million tokens, $0.32), which exercised the interrupted-run path live. The cause of the stalls and timeouts was this Mac, not Token Factory: the power log shows repeated sleep ("Dark Wake Thermal Emergency", "Maintenance Sleep") during the run, which was not started under `caffeinate`, and direct probes on a wake answered in about 2 seconds (model) and under 1 second (downloads). Sleep also stops `time.monotonic()` on macOS, so the worker's wall budget did not see it (951 seconds recorded against about an hour of clock time). Every v2 run is therefore launched under `caffeinate -i -s` on AC power with the lid open, as v1 was. Probing found two live-only defects that the fake did not model. Both are fixed test-first, with the fake changed to answer as the live API does:

- Transport errors were never retried, so one slow poll discarded a whole task. Reads (GET, HEAD, DELETE) are now retried with the same backoff as 429 and 5xx; other requests are retried only when the connection failed, so a run is never spawned twice.
- Reading a directory failed: the live API answers 422 to a directory download and names listed entries relative to the directory. `read_file` now lists the directory, as on Daytona, and still refuses an entry outside it. Checked on the live API.

The worker's wall budget includes time waiting for the model and the sandbox API, so a slow provider could end an attempt. Rather than change the budget a day before the freeze, records now keep the worker's end summary and the report counts attempts by the budget that ended them; the pre-registration states the limit. In v1, 1 of 79 attempts ended on the wall budget and 28 on turns.

### Final smoke and freeze (Oct 2)

The final smoke ran at `9bf8a9a` under `caffeinate` (`pilot/v2-smoke-tf-2/`): `pypa__twine-1066` on Super and `astropy__pyvo-204` on Lightning both verified on the first verdict, with the gate and the official grade agreeing, every patch digest agreeing, no infrastructure or cleanup error, and about 85 seconds each. v2 was pre-registered in `4a1d8c2` (`PREREGISTRATION-v2.md` and `pilot/v2-exclusions.txt`), frozen at `9bf8a9a`. Runs start from the repository checkout behind a guard (`.build/v2-guard.sh`) that refuses to launch unless `src/`, `pyproject.toml` and `uv.lock` match `9bf8a9a`; v1's separate worktree left absolute paths in its records, which broke when the repository moved. P screening started at 17:00 PT on Token Factory at concurrency 6 (`.build/v2-screen-P.sh`).
