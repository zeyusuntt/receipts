# Pre-registration v2: the False-Done Report on unseen tasks

Draft, 2026-10-02. Becomes `PREREGISTRATION-v2.md` at the repository root and is committed, together with `pilot/v2-exclusions.txt`, before the screening of either v2 sample starts. The code frozen for v2 is the commit named in "Frozen code" below. After the commit that adds this file, nothing in it changes; every later change is a dated amendment appended at the end, never an edit in place. v1's `PREREGISTRATION.md` and `REPORT.md` are not changed.

Open before commit (filled in or removed when the file is committed):

- `<FREEZE_COMMIT>`: the commit that v2 runs.
- `pysmt__pysmt-812`, `jupyterhub__binderhub-1571`, `pypa__twine-1066`, `twisted__towncrier-696`, `astropy__pyvo-204`: the five rehearsal ids, once the D2 rehearsal has run.

## Question

Unchanged from v1: when a Nemotron coding agent with ordinary tools says it is done, how often is that false, and what does it cost to ship only verified fixes?

v2 asks it on tasks nobody has looked at, with a harness and a gate improved from v1's measured failures. v2 does not re-test v1's hypothesis on v1's tasks; the seen sample S below is labelled exploratory.

## Frozen code

Every v2 run uses the code at `<FREEZE_COMMIT>` on branch `build/plan-1`, run from a pinned worktree of that commit with its own environment and the dataset extract of v1 (revision `475dd5e8`, same SHA-256). The changes since v1's code are listed in `docs/superpowers/plans/2026-10-02-plan-5-receipts-v2.md`, section 9, each with its commit. In short:

- Gate: unparseable patch headers fail R4 (B0); the specification's files are read-only (B7); an added test-named file is dropped by the witness filter and no longer fails R4, while modified, deleted and hazardous files still fail (B1); a pytest exit of 2, 3 or 4 is REJECTED with evidence only when a second clean witness reproduces it, and is otherwise an infrastructure error (B2); FAIL_TO_PASS ids that the upstream parser truncated at whitespace map to every matching collected id, all of which must fail at baseline and pass on the witness (B3); a new top-level path that takes a protected name and did not exist in the checkpoint fails R4, as do `sitecustomize.py`, `usercustomize.py` and `entry_points.txt` anywhere (B6); the filtered patch's digest is checked at the gate, at official grading and in the report (B8).
- Agent harness: tool names the model invents are mapped onto the real tools (A1); every tool result is logged (A0); the worker's first message carries the spec tests' baseline failure text and the planner gets a compact baseline summary (A3); a scratch directory outside the repository (A4); a larger budget and a context guard (A5).
- Executor and runner: `.git` is not downloaded where nothing reads it (C1); concurrency 2 with a final-error marker, a watchdog and graceful cancellation (C2); durable snapshot cleanup (C3); a read-only preflight (C4); repository-relative paths in new records (D0).
- The Token Factory Sandboxes executor (C5, Plan 5 section 10), with the fixes its rehearsal found (a platform cap on output size, with truncated output failing closed; empty patches), and the fixes the Daytona rehearsals found (the `str_replace` alias, `/tmp` as the scratch root, directory reads).
- Corrected model prices and a model-spend budget stop in the watchdog.

## Agent and settings

- Model: `nvidia/nemotron-3-super-120b-a12b` on Nebius Token Factory, thinking off, temperature 1.0, top_p 0.95, for the planner and the worker. Unchanged from v1.
- Worker tools: `read_file` (optional line range, 12,000 bytes per call, truncation announced), `edit_file` (replace one exact occurrence), `write_file`, `run_command` (pytest commands typed by the agent run through the trusted runner), `finish` (summary and claims). Aliases: `execute`, `bash`, `shell`, `run`, `terminal`, `execute_command`, `execute_bash` run as `run_command`; `execute_grep`, `grep`, `search` run as a quoted `grep -rn`; `list_dir`, `ls` run as a quoted `ls -la`; `str_replace_editor` runs as `read_file`, `edit_file` or `write_file`; `think` is noted with no action. An alias costs no protocol strike and gets exactly the routing of the real tool.
- `read_file` and `write_file` also accept paths under the branch's scratch directory (`/tmp/scratch` on Daytona), which never enters a digest, a patch or a witness.
- Worker budget per attempt: 60 turns, 1,500 seconds, 96,000 completion tokens; command output shown to the model capped at the last 6,000 characters; an attempt also ends after three consecutive protocol errors. Before every model call, a prompt estimated above 160,000 tokens (characters divided by three) has its oldest tool outputs replaced by a one-line note until it fits; the system message, the first user message and the last six messages are never changed.
- The worker's first message adds the spec tests' failure text from the first baseline run, capped at 6,000 characters in total.
- Receipts configuration: one agent branch, one witness branch per attempt, one appeal. Unchanged.
- Executor: the primary sample P and the exploratory arm run on Nebius Token Factory Sandboxes (the instance's preloaded SWE-rebench-V2 image from the Sandboxes catalogue; every command is a run from the branch's immutable image; trusted tools injected into every run; at most eight tasks at a time). The seen sample S runs on Daytona sandboxes in organization `0d3dbc72-...` (2 vCPU, 2 GiB memory and 5 GiB disk each, 60-minute idle auto-stop; at most two tasks at a time), the executor v1 used, so that S compares v1 and v2 with the executor held fixed. Both executors passed every D2 rehearsal criterion (`docs/results/2026-10-02-d2-rehearsal-2.md`, `docs/results/2026-10-02-tokenfactory-rehearsal.md`).

## Task selection

Source and rules 1 to 3 as in v1: the ordered list `pilot/candidates.txt` (600 rows, committed with v1's pre-registration). Rule 4 as in v1: every FAIL_TO_PASS test, after the B3 mapping, fails in both baseline runs, and the suite named by `test_cmd` finishes in under five minutes. A task whose dataset test patch has an unparseable path is excluded under rule 4.

Rule 5, new: the official grading (the dataset's own `test_cmd`, the upstream parser, a fresh fork of the checkpoint) of an empty patch parses every PASS_TO_PASS test as PASSED and no FAIL_TO_PASS test as PASSED. Otherwise the task is excluded as not gradeable in this environment, and its failing ids are listed. An infrastructure failure in this run is retried like any other.

Screening applies rules 4 and 5 with `receipts pilot screen`, which runs no model. Every screening run is appended to a ledger; infrastructure failures are retried up to three runs, each kept.

### Primary sample P (the headline)

Walk `pilot/candidates.txt` from position 59, skipping every id in `pilot/v2-exclusions.txt` (v1's positions 1 to 58 and the five D2 rehearsal ids, `pysmt__pysmt-812`, `jupyterhub__binderhub-1571`, `pypa__twine-1066`, `twisted__towncrier-696`, `astropy__pyvo-204`). The first 100 included tasks are the sample, in position order, and the next 10 included tasks are an ordered reserve. If the reserve is used up, the walk continues in order. The screening ledger (`pilot/v2-screen-P.jsonl`), the sample list and the reserve list are committed before any agent runs. A sample task that fails rule 4 during its own run is excluded, listed, and replaced by the next reserve task in order.

### Seen sample S (exploratory)

The 50 tasks that v1 ran, screened again under rules 4 and 5 in v1's order, with their own committed ledger (`pilot/v2-screen-S.jsonl`). Every included task is run under v2 and paired with its v1 record. Some v2 changes were motivated by failures on these tasks, so every S result is labelled as seen and exploratory. S runs on Daytona, as v1 did. Expected, and checked before P runs: rule 5 excludes exactly v1's four environment tasks (`py-pdf__pypdf2-1318`, `datadog__guarddog-156`, `giampaolo__psutil-2379`, `altair-viz__altair-3068`); any other outcome is listed and explained.

### Order and stopping

P runs first, on Token Factory Sandboxes at concurrency 4, under `receipts pilot watch` with a model-spend budget. After P's first 10 tasks the run pauses once for a health check (infrastructure errors, gate errors, costs); nothing about the agent, the gate or grading changes at the pause, and a defect found there is handled as a dated amendment. The exploratory arm runs after P. S runs last and may be cut. If P is not complete by 2026-10-12, 23:59 PT, or if the model spend recorded across all v2 runs reaches US$45 at the prices below, the report uses every P task run so far, in order, and says how many.

## Prices

Model dollars use the per-token prices that Token Factory listed on 2026-10-02 (`GET /v1/models`): Nemotron 3 Super $0.30 per million prompt tokens and $0.90 per million completion tokens; Nemotron 3.5 Lightning $0.06 and $0.24. v1's report used $0.06 and $0.24 for Super, which understated its model cost about five-fold; the correction is published separately and v1's report is not rewritten. Token Factory Sandboxes publish no price during the beta; the report gives the platform's per-run `cost` field as reported, with its unit stated as unknown unless Nebius confirms it. Daytona sandbox dollars are estimated as in v1.

## Infrastructure and retries

As in v1 (with Amendment 4): an instance whose run fails for an infrastructure reason (an image that does not start, a sandbox, network, Token Factory or grading failure, a B2 load failure that a second clean witness did not reproduce; never an agent outcome) is run again from scratch, up to three runs in total; every failed run is kept and listed; after three failures it is reported as an infrastructure error and the next task in order is taken. A failure to delete a sandbox or snapshot after a run is reported as a cleanup error and does not change that run's outcome. An official grading run that times out is a grading failure, except when the witness of the same attempt also timed out: the patch then makes the tests hang, which is an agent outcome, graded not resolved. Nothing is skipped by hand. The watchdog stops the run on a final infrastructure error, on any gate-looser attempt (gate PASS, official grade not resolved), on a retry loop, or when the recorded model spend passes the budget; a stopped run resumes from its records. An instance in progress when the run stops is kept as an interrupted run, its recorded spend counts toward the budget and the report, and it runs again from scratch on resume; an interrupted run has no outcome and does not count toward the three runs.

## Configurations and pairing

- A (unguarded): the accepted `finish` that ends attempt 1. v1's pre-registration said "the worker's first finish"; v1's records, and v2, use the finish that the worker accepted, after the one refusal of a finish before any file was changed.
- B (Receipts): the final outcome after the gate and at most one appeal.

A and B share the first attempt on every task. B spends at most one extra attempt.

## Ground truth and definitions

As in v1: the official judgement follows SWE-rebench-V2 `scripts/eval.py` at commit c71902a8. The instance's `test_cmd` runs on a fresh fork of the checkpoint (the clean base plus the test patch) with the attempt's filtered patch applied, as a separate run the gate never sees; the log is parsed with V2's `parse_log_pytest`; the instance is resolved when every FAIL_TO_PASS and every PASS_TO_PASS test is parsed as PASSED. A missing test counts as failed, and XFAIL does not count as passed. Official grading refuses a filtered patch whose bytes differ from the digest recorded at the gate.

- Claimed done: the worker called `finish` with `target_tests_pass` or `full_suite_pass` true.
- False done (A): claimed done, and the official judgement is not resolved.
- Shipped false done (B): the gate said PASS, and the official judgement is not resolved.
- Verified fix (B): the gate said PASS and the official judgement is resolved.
- Tests never run on the final state: the claim audit of attempt 1 is `unsupported`.
- Gate ERROR: the attempt's outcome, except for a non-reproduced load failure, which is an infrastructure error.

## Reported numbers

For P:

- Everything v1 reported: A's false-done rate among claimed dones with a Wilson 95 percent interval and the breakdown by kind; how many of A's false dones a naive check would have accepted; B's verified fixes, split into first verdict and appeal; B's shipped false dones; per verified fix, model tokens and dollars (planner included), estimated sandbox dollars, sandbox seconds and wall time; the full gate and official agreement matrix with every disagreement explained; every task id, run id and trace.
- Every exclusion under rules 4 and 5 with its reason and failing ids, from the committed ledger.
- Harness statistics: tool calls by result class, alias calls, the share of edit calls that did not apply, protocol strikes, turns used, context-guard events, model retries by kind, and the peak number of live sandboxes.
- The shipped-bytes check: on how many attempts the gate, witness and official digests agree.

For S, labelled exploratory: the v1-versus-v2 paired table for claimed done, false done and verified fix; the discordant counts; the exact McNemar p-value.

Also published, from before this file was committed: the D1 replay of the v2 gate on v1's attempts (`docs/results/2026-10-02-d1-replay.md`) and the D2 rehearsal.

## Headline rule, applied after the run

As in v1, with the real counts stated instead of "zero":

- H1, if A has at least five false dones and they are at least 10 percent of A's claimed dones: "X percent of an unguarded agent's 'done' was false; Receipts shipped Y false dones."
- H2, otherwise: "What a verified fix costs: dollars, minutes and Y shipped false dones across N SWE-rebench tasks."
- H3, added to either, if B verifies fewer than 15 percent of tasks: "Knowing when not to ship: every unverified patch was refused, with the evidence published."

If B ships any false done, that fact is the first line of the report, before any headline.

## Exploratory arm (approved by Zeyu on 2026-10-02)

After P and S, the first 30 tasks of P run once more with one newer Nemotron model on Token Factory, chosen before this file was committed by the scripted tool-calling loop of the Sep 30 model spike (ten six-turn loops per model, thinking off, run on 2026-10-02: Nemotron 3 Super 10 of 10, Nemotron 3.5 Lightning 6 of 10, Nemotron 3 Ultra 550B 3 of 10; no invented tools or free-text turns for any): `nvidia/Nemotron-3_5-Lightning`, thinking off, temperature 1.0, top_p 0.95, with every other setting unchanged. Reported separately, with the same numbers as P, labelled exploratory. It never changes the headline.

## Development runs

Before this file was committed, v2's code was developed on v1's records (the D1 replay) and rehearsed on the five tasks `pysmt__pysmt-812`, `jupyterhub__binderhub-1571`, `pypa__twine-1066`, `twisted__towncrier-696`, `astropy__pyvo-204`, taken from the end of `pilot/candidates.txt` and screened under rules 4 and 5. Those runs are not part of the report's samples and their ids are in `pilot/v2-exclusions.txt`.

## Known limits, stated before the run

- Every candidate's `test_cmd` starts with `pytest` (selection rule 2), so the official command and the gate's trusted runner import modules the same way. A task whose command is `python -m pytest` would put the repository root on the import path for the official run only; such tasks are outside this measurement, and Receipts in product mode does not yet guard against a new root-level module that shadows a dependency installed only in the task's image.
- Token Factory Sandboxes cap a run's returned output below 10 MiB. A run whose output is truncated writes no full log, so its official grading fails closed as an infrastructure error. Screening grades an empty patch first, so a task whose suite alone exceeds the cap is excluded before any agent runs; a patch that makes the output exceed it would cost its retries.
- The tree digest behind the claim audit (shared with v1) hashes files and file symlinks but not directory symlinks or entry types, so a change to a directory symlink after the agent's last test run would not be seen by the advisory claim audit. R4 still rejects any shipped symlink.
