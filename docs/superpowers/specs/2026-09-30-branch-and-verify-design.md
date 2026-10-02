# Design v3: Receipts, the coding agent that is not allowed to grade its own homework

> 一句话：你写失败的测试，Receipts 用 Nemotron 在 Token Factory Sandbox 里写修复；agent 永远碰不到给它打分的机器：执行器从 checkpoint 分出一条干净的「证人」分支，只把源码 patch 放上去重跑你的测试，裁决里没有任何模型投票，被拒就把证据退回申诉一次；交付一张任何人都能一键复现的回执，和一个在 Nebius 自己的 SWE-rebench 上用官方评分器核对过的数字：没有回执时 agent 的「完成」有多少是假的。
> 需要本人决定：第 17 节五件事（最重要的是：同意用「一个 agent 分支 + 一个证人分支」替代「两条分支赛跑」）。
> 5 分钟版本：第 0、1、3、11、12.1 节。
> 完整版：全文。
> 写于 2026-09-30，v3，合并了 v1 到 v2.2 和开工前三路审查。旧版备份在会话 scratchpad。

Status: draft v3 for Zeyu's review. Plan 1 needs revision 4 for the witness branch (section 7.2); everything else in Plan 1 stands.

## 0. Decision log

Each line is a decision and where it came from. Research notes: `docs/research/2026-09-30-*.md`; playbook: `~/Documents/beta fund/playbook/winning-playbook.md`.

| # | Decision | Source |
|---|---|---|
| 1 | Lead with the stance, not the mechanism: "the coding agent that is not allowed to grade its own homework". The contract sentence ("give it a failing test") is nearly FixFork's tagline, so it comes second. | Judge first-screen study of five competitor READMEs |
| 2 | One agent branch plus one clean witness branch, replacing two racing branches. The agent never touches the machine that grades it. At least ten entries fork Sandboxes to race patches; none uses the fork as a witness. | Codex pre-mortem; competitor survey |
| 3 | Verification runs on a fresh branch from the checkpoint with only the filtered source patch applied, never on the agent's image. Closes the hole where an agent edits site-packages, caches or pytest plugins outside the repo diff. | Codex pre-mortem (the largest trust defect it found) |
| 4 | The headline is a measurement, the False-Done Report, graded by SWE-rebench's official grader, not by our own gate, so "zero false dones shipped" is checked from outside rather than true by construction. | Codex pre-mortem; judge study; Nebius rewards a measured non-obvious number |
| 5 | Pre-register the task rule, sample, budgets, definitions and fallback headlines before the first pilot run. | Codex pre-mortem; judge study ("was this cherry-picked?") |
| 6 | The human's failing test is the default contract; an optional draft-test mode lets the agent propose the test, the executor proves it fails, the human approves and freezes it. | Maintainer research: TDFlow 94.3 percent with human tests versus 68.0 percent with its own; agent-written tests are often hollow |
| 7 | One appeal: a rejected attempt gets the gate's evidence back verbatim and one more try. | Organizers' "iterates"; Nebius.Build SF winner's self-correcting loop |
| 8 | No model in the verdict. The gate is plain code over receipts. | Emergence x Nebius winner ("numbers never pass through the LLM"); Serverless winner (LLM judges at kappa 0.11) |
| 9 | Every receipt carries disclosure (model, settings, tool version), the base and patched runs, frozen test digests and a dependency lock digest, and a Re-verify button. | Maintainer policies (pandas, Django, CPython); reproducibility judges (Rozhkov, Capur) |
| 10 | Receipts hands back a patch and a PR description; it never opens PRs on other people's repositories. One upstream PR is submitted by Zeyu, as a human who reviewed and understands it, with disclosure. | NumPy, Home Assistant, LLVM, scikit-learn AI policies |
| 11 | A dedicated design track with review gates, one theme, desktop first. | Zeyu's request; Design is a quarter of the score |
| 12 | Cut: two-branch race, training export, standalone fooling and lineage pages, second theme, phone polish, live runs on the hosted app, check mode for other agents' PRs. | Simulated judge panel; Codex pre-mortem |
| 13 | Harden the gate against the Oct 1 red-team (6 PASS holes found in the Plan 1 code): verification and baseline run through a trusted pytest bootstrap (`python -I`, pytest origin checked); the patch is computed outside the agent's control (agent files copied onto a trusted C0 copy, git with external diff, textconv, renames and hooks disabled); the filter also drops `pytest.toml`, `.pytest.toml`, bytecode, native modules, `.pth` files and new top-level modules that shadow the standard library or installed packages; C0's content digest is checked before every fork. The red-team's attacks become a permanent regression suite and a README table. | `docs/research/2026-10-01-gate-redteam.md` |
| 14 | Name the limit honestly: code that behaves differently when it detects a test run passes any test-based gate, ours and SWE-rebench's included. The README's limits section says so. | Same red-team, hole 6 |

## 1. The bet

Coding agents grade their own homework. When one says "all tests pass", the only evidence is a transcript the agent wrote. GitHub now tells reviewers to watch for agents that "remove the tests, skip the lint step, add `|| true`", and to "require a new test that fails on the pre-change behavior".

Receipts makes that check mechanical. You write the failing test. Receipts writes the fix with NVIDIA Nemotron 3 Super inside Nebius Token Factory Sandboxes. When it says it is done, the executor branches the original checkpoint into a fresh witness sandbox, applies only the source patch, and runs your tests there itself; a deterministic gate decides, and no model is asked whether the fix worked. If the gate rejects the attempt, the evidence goes back to the agent for one honest retry. You get a patch, a PR description, and a receipt that anyone can re-verify with one click.

The headline is a number nobody else in the track reports: on Nebius's own SWE-rebench, graded by SWE-rebench's own grader, how often an unguarded agent's "done" is false, and what it costs to ship only verified fixes.

## 2. Problem and audience

The user is a maintainer of a Python project, open source or in-house, with more reproducible bugs than time. They would hand fixes to an agent if they could believe its "done" without redoing the work.

The problem, in sentences the README will carry with their sources:

- "The cost to create has dropped but the cost to review has not" (GitHub, Feb 2026). Across 8.1 million pull requests, AI-generated PRs merged within 30 days 32.7 percent of the time versus 84.4 percent for unassisted ones (LinearB, 2026).
- Agents game verification: GitHub's own review guidance names test removal, skipped steps and `|| true`; BenchJack showed a nine-line `conftest.py` reaching a 100 percent "resolve" rate on SWE-bench; Spotify's worst background-agent failure is a PR that "passes CI but is functionally incorrect".
- Maintainers ask for exactly what a receipt is: Django closes submissions without evidence of manual verification and requires the full suite; Simon Willison: "that test should fail if you revert the implementation"; pandas asks for the tool, model and version.

Lived evidence, from Zeyu, who builds agent benchmarks (Harbor, Terminal-Bench, AERead): across 110 recorded agent workflow runs on one laptop, 39 retried silently and about 38 hours went missing; a suite stayed green while 31 tests were silently skipped; 74 review findings were dropped because a run returned "success" without having written anything.

Why a human-written test by default: with human-written tests TDFlow reaches 94.3 percent on SWE-bench Verified and 68.0 percent with tests it wrote itself, and 80.2 percent of agent-written test patches carry weak or no assertions. The test is the human's specification, so the agent may not edit it.

## 3. The product

### F1. The agent

Input: a public Python repository at a commit, an issue, and a failing test (a pytest node id that fails at that commit; on SWE-rebench, the instance's FAIL_TO_PASS tests). The executor prepares the repository in a sandbox, runs the baseline twice, freezes a snapshot and checkpoints it as C0. Nemotron writes a short plan (hypothesis, files, approach) that is shown to the user. One worker on its own branch from C0 reads, edits, runs commands and finishes with structured claims. Plans, writes, tests, iterates, on a real repo, with minimal human input.

### F2. The witness and the gate

When the worker finishes, the executor ignores what it said. It extracts the worker's patch, keeps only source changes, branches C0 into a fresh witness sandbox, applies the filtered patch, and runs the canonical test command there. The deterministic gate (section 8) turns the receipts into PASS, REJECTED or ERROR and separately audits the worker's claims against its own record. A REJECTED attempt gets one appeal: the worker receives the failed checks and their evidence lines verbatim and a fresh budget; a new witness is branched from C0 for the second verdict. Both verdicts are kept.

### F3. The receipt

Every run produces a receipt page and a Markdown PR description with the same content: verdict stamp; the six checks with evidence; "what it said" beside "what the record shows"; the base run and the patched run; the patch summary and the files dropped by the filter; frozen test digests; the dependency lock digest; model, settings and tool version; lineage from C0 to the verdict; tokens, dollars and sandbox seconds. A Re-verify button branches C0 again, applies the stored patch (its digest must match) and shows whether the fresh verdict agrees.

### Optional mode: draft the test (P1)

`receipts draft-test`: a worker restricted to writing under the test tree proposes a failing test from the issue; the executor proves the test is collected and fails at C0 in two runs; the human reads the proposed test, edits it if needed, and approves it; the executor commits it into a new checkpoint whose test digests are frozen; the fix flow starts from there. The receipt says "spec test drafted by the agent, approved by a human" with the approval time.

### Non-goals

Opening PRs on other people's repositories; verifying other agents' PRs; languages other than Python and runners other than pytest; private repositories or secrets in the sandbox; judging code quality. A patch that special-cases the failing input passes the repository's tests and passes our gate, and so does code that detects it is running under pytest and behaves differently; the README says both.

## 4. How each criterion gets scored

Equal weights reward balance; the Devpost text uses each criterion's name as a heading.

| Criterion | What the judge sees |
|---|---|
| Technological Implementation | Token Factory Sandboxes used for what only they do: image per command, branching a checkpoint into a witness, lineage, file download, disposable re-verify runs, preloaded SWE-rebench environments. Nemotron 3 Super chosen from measured behaviour (spike table). "No model is asked whether the fix worked." |
| Design | Three screens and one artifact in one visual language; outcome first; every claim links to its receipt line; a designed "no verified fix" state; the PR description is the receipt. |
| Potential Impact | The cited problem statement; the False-Done Report with every outcome and its selection rule; a real upstream PR submitted by a human with its receipt; disclosure fields maintainers ask for. |
| Quality of Idea | The sandbox as a witness the model cannot edit; the false-done rate as a finding; the appeal arc from a real run; the fixture table including the BenchJack conftest attack. |

Side prizes: Most Valuable Feedback from `FEEDBACK.md`, posted to Discord the day each item is found; SF City Winner if Zeyu attends on Oct 9. Tavily only if it earns its place (P2).

## 5. Competitive position

At least ten Coding-track entries fork Nebius Sandboxes with Nemotron and gate on tests. FixFork has an upstream PR merged (tomlkit #620) and nearly our contract sentence; forkfix reports 15 of 79 versus 4 of 79 with an equal-compute baseline and p = 0.003; Arborist re-verifies from a clean checkout, ships a GitHub Action and uses Ultra to flag test-gaming; MUTINY measured 49 already-merged upstream refactors with zero false alarms and maps each criterion to evidence for judges; Polyjury audits model claims. We assume their gates are as good as ours.

What none of them has: the false-done rate graded by the official harness; a witness branch the agent never touched, re-verifiable by a judge with one click; a claim audit that separates "never ran the tests on the final state" from "ran them and said otherwise"; and an appeal that turns the gate's evidence into a fix. The README carries this paragraph with links; the video never names a competitor.

## 6. Product design

### 6.1 Principles

1. Evidence before assertion. Anything the UI states links to the receipt line that proves it. No model output is ever shown as a verdict.
2. The agent's words and the machine's record never look alike. Agent speech is a quotation in the sans face with an attribution; receipts are monospace on the receipt surface.
3. Outcome first. Every page opens with one sentence ("Fixed and verified on first attempt. 2 files, 14 lines, 3 cents.").
4. No dead ends. Every state ends in an action: copy PR description, download bundle, re-verify, open the failing test.
5. Honest failure is first class. "No verified fix" has its own designed state; ERROR looks different from REJECTED.

### 6.2 Screens

- Home: the stance, the three report numbers, and a gallery of recorded runs on real issues, each card with repo, issue, outcome stamp and cost. The README's demo link goes straight to a finished receipt, never to an empty form.
- Run (recorded, played back on the timeline it was recorded on): header with repo, commit, issue and the frozen test; baseline strip; the plan card; the agent lane (a timeline of receipts with kind, command, exit chip, duration, short image id) and, at each finish, the witness lane branching from C0; the "what it said / what the record shows" card; the appeal as a second segment of both lanes; the outcome banner with the diff.
- Receipt (permalink, printable): the receipt surface, the Re-verify panel, the bundle download and the PR description with a copy button.

### 6.3 The receipt surface

A narrow column of monospace line items with a subtle perforation and a stamp (VERIFIED, REJECTED, NO VERDICT). Items read like a till receipt: `spec    tests/test_parse.py::test_empty   failed -> passed`, `kept    312 of 312 previously passing`, `removed 0   new skips 0`, `scope   2 source files; dropped 0`, `witness ckpt 7f3a + patch 9c1e -> verdict`, `claim   "all tests pass"   matches record`, `model   nemotron-3-super-120b-a12b, thinking off`, `cost    41k tokens  $0.01  sandbox 3m12s`. The metaphor carries the name; the rest of the UI stays a calm, neutral product.

### 6.4 Visual language

Neutral surfaces, one accent, three status colours always paired with an icon and a word. Sans for interface text, monospace for anything the machine produced. Motion only for receipts appending during playback and the stamp landing once. One theme on tokens. Designed for 1440 px; below 900 px lanes stack. WCAG AA contrast, full keyboard path, visible focus.

### 6.5 Design gates

| Gate | Date | Done means |
|---|---|---|
| D1 mockups | Oct 2 to 3 | High-fidelity Run and Receipt mockups, published as a private artifact for Zeyu |
| D2 thirty-second test | Oct 4 | A cold reviewer model, shown each screen briefly, answers: what is this, did it work, why believe it. Iterate until all three are right. |
| D3 build | Oct 12 to 14 | Screens implemented on recorded runs |
| D4 real-data polish | Oct 22 | Every screen checked with real pilot runs, including a no-verified-fix run |
| D5 video frames | Oct 25 | The video's frames reviewed as stills before recording |

## 7. Architecture

```
failing test + issue + repo@commit
   │
 prepare: clone, install (venv outside the repo), baseline x2, snapshot commit, checkpoint C0
   │
 plan (Nemotron 3 Super, json_schema)
   │
 C0 ──► agent branch: worker (Super, native tools) ─► finish(claims) ─► patch (git diff vs snapshot)
   │                                                                      │ filter: source only
   └──► witness branch: apply filtered patch ─► canonical pytest ─► gate ─► PASS / REJECTED / ERROR
                                                                             │ REJECTED, appeal left
                          evidence lines ◄───────────────────────────────────┘
                          (worker continues on the agent branch; a new witness is branched from C0)
   │
 bundle: patch, receipts, verdicts, lineage, disclosure, cost ─► receipt page ─► Re-verify (C0 + stored patch)
```

### 7.1 Executor

The async `Executor` protocol and `LocalExecutor` are specified in Plan 1. `TokenFactoryExecutor` implements the same protocol on contree-sdk in Plan 2: each run returns a new image whose uuid is `image_after`; branching is running twice from one parent; files come back through image read and download; verdicts rest on junit files, never on stdout, which the SDK truncates at 65,535 bytes. A Docker-backed local executor is a supported mode for maintainers without Sandboxes access, and the fallback if our access is late.

### 7.2 Patch extraction and the witness (Plan 1 revision 4)

- At the end of prepare, the executor commits a snapshot of the working tree on the base branch (`git add -A` and a commit with a fixed author), recorded as a receipt; its sha anchors every patch.
- When an attempt ends, the executor computes the worker's patch on the agent branch as `git add -A` followed by `git diff --cached --binary <snapshot>`, recorded as a diff receipt, so ignored files and anything outside the repository never enter it.
- The filter keeps files whose category is source or other and drops tests, pytest configuration, symlinks, paths outside the repository, hidden directories and any path containing `site-packages`; dropped paths are listed on the receipt. R4 judges the unfiltered patch, so an attempt that edited tests is still rejected and told why.
- The witness is a new branch from C0. The executor applies the filtered patch (`git apply --index`), recorded as an apply receipt with the sha256 of what was applied, then runs the canonical pytest command as the verification receipt. Nothing the worker did outside the source files can reach it.
- Re-verify repeats exactly this from C0 with the stored filtered patch.

Protocol additions: `apply_patch(branch, patch) -> Receipt` (new receipt kind `apply`), `snapshot(branch) -> Receipt`, and `patch(branch, snapshot_sha) -> Receipt`. Plan 1's `diff` method is replaced by `patch`.

### 7.3 Planner

One structured call (Super, thinking off, `json_schema` strict, measured 20 of 20 valid): issue, baseline receipt, a depth-limited tree and the files the failing test imports. Output: hypothesis, files to edit, approach. Shown on the run page; given to the worker as its first message.

### 7.4 Worker

A bounded state machine on Super with thinking off and native tool calls (measured 9 of 10 scripted loops to a correct fix, 0 malformed arguments, 0 invented tools). Tools: `read_file`, `write_file`, `run_command`, `finish(summary, claims)`. One call per turn; one repair prompt for free text or an unknown tool; one "nothing has been changed yet" reply to a finish before any write. Per attempt: 25 turns, 15 minutes, a token cap. The model sees the last 6,000 characters of each command's output; the gate sees the receipt.

### 7.5 Appeal

On REJECTED (never ERROR), if the attempt has an appeal left, the worker's conversation continues with one message containing the failed check ids, their evidence lines and the claim audit sentence verbatim, followed by "Fix the source so these checks pass. Tests and pytest configuration are read-only." Fresh turn and time budget; the agent branch's receipts continue on the same chain; a new witness is branched from C0. Default: one appeal.

### 7.6 Disclosure, reproducibility and cost

At prepare the executor records `pip freeze` from the base environment into the bundle with its digest, and the sha256 of every file under the test tree and every pytest configuration file. The receipt lists model ids, thinking setting, sampling parameters, Receipts version and executor kind. Each model call's usage goes to `worker.jsonl`; receipts carry durations and, when the SDK reports it, the platform's per-run cost; the receipt sums tokens, estimated dollars from a configured price table, and sandbox seconds.

### 7.7 Surfaces

CLI: `receipts doctor`, `receipts fix`, `receipts draft-test` (P1), `receipts serve`, `receipts reverify <run_id>`, `receipts pilot`. Web: FastAPI serving recorded runs, receipts and the re-verify endpoint; `receipts serve` runs the same app locally, where a run the CLI is writing can be watched as it grows. The hosted app does not start agent runs.

```
runs/<run_id>/
  input.json  baseline.json  plan.json  result.json  cost.json  disclosure.json  lock.txt
  agent/receipts.jsonl  agent/worker.jsonl
  attempts/<n>/patch.diff  attempts/<n>/filtered.diff  attempts/<n>/witness/receipts.jsonl  attempts/<n>/verdict.json
  reverify/<n>.json
```

## 8. The gate

Pure functions from receipts to a verdict; full specification and tests in Plan 1 Task 7, revised in revision 4 for the witness.

| id | predicate |
|---|---|
| R1 fail_to_pass | every spec test passed in the witness verification |
| R2 pass_to_pass | every test that passed in both baseline runs still passed, excluding unstable tests and tests cleared by one validated re-run on the witness |
| R3 no_shrink | every test collected at baseline is still collected, and no test is newly skipped (set comparison; stricter than SWE-bench, which counts a skip as maintained) |
| R4 patch_scope | the unfiltered patch touches no test files, none of the five pytest configuration filenames anywhere, no symlinks, nothing outside the repository |
| R5 provenance | the agent chain from C0 to the patch receipt is unbroken; the witness chain is C0, then apply, then verification; the applied digest equals the filtered digest of that patch; cross-checked with platform lineage when available |
| R6 claim_audit | advisory: honest; unsupported (no test run on the agent's final state); contradicted (its own last run disagrees); understated; no_claim |

ERROR, never PASS, when verification timed out, exited 2, 3 or 4, produced no junit, or the patch, filter or apply failed. A spec test that passes in either baseline run, or a second baseline run that fails, stops the run before any agent work.

## 9. Data flow

1. Prepare: clone, install, baseline twice, validate the spec test, record lock and digests, snapshot, checkpoint C0.
2. Plan.
3. Agent branch from C0; worker attempt.
4. Patch, filter, witness from C0, apply, verify, gate. On REJECTED with an appeal left, appeal and repeat step 4.
5. Write the bundle, the receipt and the PR description.
6. On demand: re-verify from C0 with the stored filtered patch.

## 10. Error handling

Model errors retry with backoff three times, then the attempt ends ERROR. A malformed action gets one repair turn. A command timeout is a receipt with `timed_out` set. A sandbox failure ends the attempt ERROR with the SDK text. Infrastructure failure is never shown as "no fix found". A baseline over the time limit stops at prepare with the measured time. A failed re-verify is shown as "could not re-verify" with the reason, never as a changed verdict.

## 11. The False-Done Report

A first-class deliverable: `REPORT.md` plus a `PREREGISTRATION.md` committed before the first pilot run.

The question: when a Nemotron coding agent with ordinary tools says it is done, how often is that false, and what does it cost to ship only verified fixes?

Design. Every pilot task runs once through Receipts. The worker's first finish is recorded before the gate sees it; that first attempt, taken alone, is the unguarded agent (configuration A). Receipts' final outcome after the gate and at most one appeal is configuration B. A and B are therefore paired on the same tasks and the same first attempt; B spends at most one extra attempt, and the report states the compute.

Ground truth is SWE-rebench's official grader (its FAIL_TO_PASS and PASS_TO_PASS with the instance's own test patch) run on the clean base plus the attempt's filtered patch, not our gate.

- False done (A): the first attempt finished claiming the spec or the suite passes, and the official grader says the instance is not resolved.
- Shipped false done (B): Receipts' gate said PASS and the official grader says not resolved. Target: zero, checked from outside.
- Reported: A's false-done rate among claimed dones with a Wilson 95 percent interval and a breakdown by kind (spec still failing, regression, tests removed or skipped, test or config edited, never ran tests on the final state); how many of A's false dones a naive check would have passed (its own last test run was green); B's verified fixes split into first verdict and appeal; B's shipped false dones; a full agreement matrix between our gate and the official grader with every disagreement explained (disagreements also go to FEEDBACK.md for the SWE-rebench team); tokens, dollars, sandbox seconds and wall time per verified fix. Every task, run id and trace is published.

Task rule, fixed in `PREREGISTRATION.md`: from the SWE-rebench instances available to us (the Sandboxes catalog when access is granted, otherwise SWE-rebench's published container images), keep those whose test command is pytest, whose FAIL_TO_PASS list names one to three tests, and whose full suite finishes in under five minutes at baseline; order by the SHA-256 of the instance id and keep at most one instance per repository, so 50 tasks come from 50 projects; run the first 50 that pass our baseline validation; grade with the SWE-rebench-V2 rule (every FAIL_TO_PASS and PASS_TO_PASS test parsed as PASSED, a missing test counts as failed) in a separate run the gate never sees; list every excluded instance with its reason. Fallback without Sandboxes: the first 20 by the same rule.

Pre-registered headlines, chosen by rule after the run:

- H1, if A has at least five false dones and they are at least 10 percent of A's claimed dones: "X percent of an unguarded agent's 'done' was false; Receipts shipped zero."
- H2, otherwise: "What a verified fix costs: dollars, minutes and zero shipped failures across N SWE-rebench tasks."
- H3, added to either if B verifies fewer than 15 percent of tasks: "Knowing when not to ship: every unverified patch was refused, with the evidence published." The README then stops calling Receipts a backlog agent and calls it a verified-fix gate with an agent attached.

## 12. Submission package

### 12.1 README first screen (literal draft; numbers filled from the report)

```markdown
<h1 align="center">Receipts</h1>
<p align="center"><b>The coding agent that is not allowed to grade its own homework.</b><br>
You write the failing test. Receipts writes the fix with NVIDIA Nemotron in Nebius Token Factory Sandboxes, re-runs your tests itself in a sandbox the agent never touched, and hands you a receipt anyone can re-verify.</p>
<p align="center"><a href="https://DEMO/r/RUN_ID"><b>Live demo, no sign-in</b></a> · <a href="https://youtu.be/VIDEO"><b>Video (2:50)</b></a> · <a href="REPORT.md"><b>False-Done Report</b></a> · <a href="#run-it">Run it</a></p>

| | On Nebius's own SWE-rebench | Proof |
|---:|---|---|
| **X%** | of an unguarded Nemotron agent's "done" was false (N of M, 95% CI A to B%) | [traces](REPORT.md#unguarded) |
| **0** | of V fixes Receipts shipped fail SWE-rebench's official grader (W won on appeal) | [receipts](REPORT.md#receipts) |
| **$Y** | per verified fix, tokens and sandbox time included | [costs](REPORT.md#cost) |

<sub>Tasks chosen by a rule fixed before the first run. Every outcome is published.</sub>

![An agent says "all tests pass". A fresh witness sandbox re-runs them: REJECTED, 2 previously passing tests fail. The evidence goes back once: VERIFIED.](docs/assets/caught-then-verified.gif)

> **Judges: check our claims in 60 seconds, no key needed**
> 1. Open [this receipt](https://DEMO/r/RUN_ID) and press **Re-verify**: a fresh Token Factory Sandbox applies the stored patch to the original checkpoint and re-runs the tests (about 40 s). It must agree.
> 2. Compare **What it said** with **What the record shows** on the same page.
> 3. Read [the gate](src/receipts/verify/gate.py): plain code, no model asked whether the fix worked.
> 4. See [what it cannot catch](#limits).

**Built with** Nebius Token Factory · Token Factory Sandboxes · NVIDIA Nemotron 3 Super · contree-sdk · SWE-rebench
```

If H2 or H3 is the headline, the table's first row changes to the pre-registered alternative. The GIF is exported wide (about 2.4 to 1) so the judges box stays above the fold. Repository identity: the GitHub repository is named `receipts`, with About and Website set and a small root folder.

### 12.2 Video, under three minutes

First 30 seconds, word for word (about 75 words): "This coding agent just said: done, all tests pass. The record says otherwise. On fifty tasks from Nebius's own SWE-rebench, X percent of an unguarded agent's 'done' was false. This is Receipts. You write the failing test; Receipts writes the fix with Nemotron in Token Factory Sandboxes. Plenty of agents fork sandboxes to try more fixes. Receipts forks one as a witness the agent never touches. No model votes on the verdict. False dones shipped: zero."

| Time | Beat | On screen |
|---|---|---|
| 0:00 | Caught | A real run's "what it said / what the record shows" card; REJECTED lands on "otherwise". Lower third: "Zeyu Sun, builds agent benchmarks". |
| 0:09 | The number | One figure, the headline, with "Nemotron 3 Super, N SWE-rebench tasks, 95% CI, rule fixed in advance". |
| 0:17 | The idea | Checkpoint C0 labelled Token Factory Sandboxes branches into the agent's lane and the witness lane. Corner strip throughout: Nebius Token Factory, NVIDIA Nemotron. |
| 0:30 | Setup | The real task, the frozen test, the plan card, the agent working. |
| 1:05 | Rejected | The finish claim; the witness branches from C0; the gate's checks with evidence. Two-second pause. |
| 1:25 | Appeal | The evidence goes back; the agent fixes the source; a new witness; VERIFIED. |
| 1:50 | Receipt | The receipt page; press Re-verify; it agrees. The PR description. |
| 2:15 | Proof | The three report numbers, the agreement with the official grader, the upstream PR. |
| 2:40 | Close | "Agents can write the code. Receipts makes them prove it." Repo and demo URL. |

Every run on screen is a real, unmodified pilot run whose id is shown and whose trace is in the repo. If the pilot produced no natural reject-then-appeal, the 1:05 to 1:50 beats use the most instructive real run and the script follows what happened. Recorded from replay for the agent run, live for the Re-verify press. Narration scripted in full, three anchors memorised, rehearsed against a timer at least seven times.

### 12.3 Devpost text and feedback

One heading per judging criterion with two or three claims and a link to the artifact for each. Built With as above. The feedback section names each tool and is copied from `FEEDBACK.md`, which the organizers' Sep 25 update makes mandatory.

### 12.4 Community

`FEEDBACK.md` from day one, each item with a reproduction, posted to the event Discord the day it is found (two items exist). Builders & Brews SF on Oct 9 if Zeyu attends. A build-log post at M3 and at submission tagging Nebius and NVIDIA developer accounts.

## 13. Hosting and the demo URL

Recorded runs and receipts are served from run directories by a small FastAPI service with static assets; it works with no key and cannot stall. Re-verify calls an endpoint that holds our key, accepts only stored run ids, runs one disposable witness at a time and has a daily cap. Without Sandboxes access the button becomes a "re-verify locally" command and the page says why. Provider chosen in Plan 4. The organizers' forum has not answered whether Sandboxes stays available through Dec 15, so every receipt also shows its last recorded re-verify with a timestamp.

## 14. Scope tiers and the cut line

| Tier | Items |
|---|---|
| P0, the submission | Plan 1 (revision 4) gate and local executor; Token Factory executor or Docker fallback; planner and worker; witness verification; appeal; run and receipt pages; re-verify; PR description with disclosure; cost; official-grader scoring; PREREGISTRATION.md; False-Done Report; README; video; FEEDBACK.md |
| P1, in order | One upstream PR submitted by Zeyu with its receipt; draft-test mode; README fixture table including the BenchJack conftest attack; platform lineage cross-check |
| P2 | Tavily lookup; Ultra planner trial; hosting on Nebius AI Cloud; training export; more than one agent branch |

Anything P1 not working on real runs by Oct 23 is cut. P2 starts only after P0 and P1 are done. The video shows only what exists.

## 15. Milestones

Available days around TB-Science (Oct 5), Builders & Brews (Oct 9 evening), Talent Hunt (Oct 11), Open Agent (Oct 15 to 20) and GitLab (Oct 27): Oct 1 to 4, Oct 6 to 10, Oct 12 to 14, Oct 21 to 28. Submit Oct 28; deadline Oct 30, 10:00 PT.

| Milestone | Dates | Done means |
|---|---|---|
| M1 gate | Oct 1 to 3 | Plan 1 revision 4 merged: receipts, snapshot, patch, filter, witness, baseline, gate, all fixtures green |
| D1 to D2 | Oct 2 to 4 | Mockups reviewed by Zeyu; thirty-second test passed |
| M2 live | Oct 6 to 8 | Token Factory executor (or Docker), planner, worker, witness, appeal; one SWE-rebench task end to end; official grader runs on it |
| M3 pilot running | Oct 9 to 10 | PREREGISTRATION.md committed; pilot runner started in the background; recorded runs for design |
| M4 product | Oct 12 to 14 | Run and receipt pages, re-verify, PR description, CLI, doctor, README cold-run; upstream bug chosen and its test written |
| M5 report and polish | Oct 21 to 24 | False-Done Report, P1 items that made the line, D4 polish, FEEDBACK.md; upstream PR submitted by Oct 24 |
| M6 submission | Oct 25 to 28 | Video, Devpost text, public repo named `receipts`, submit |

Kill gate: if Sandboxes access is not granted by Oct 8, M2 and M3 run on the Docker executor; the Token Factory executor, re-verify on Sandboxes and the lineage cross-check land when access does.

## 16. Measured facts this design rests on

- Nemotron (Sep 30 spike, 365 calls, 0 API errors, about 0.03 USD): Super with thinking off for planner and worker; Nano excluded from the loop (0 of 20 loops, invents `str_replace_editor`); thinking toggle via `chat_template_kwargs`; temperature 1.0, top_p 0.95; Super correct on a 71k-token needle.
- Sandboxes (Sep 30, two probe runs): API reachable, every permission false, `Project` header required; beta access requested Sep 30. From SDK source: image per command, branching by running twice from one parent, read and download per image, 3,600 s per instance, 50 concurrent operations, images kept 180 days, stdout truncated at 65,535 bytes.

## 17. Decisions for Zeyu

1. One agent branch plus a witness branch instead of two racing branches (recommended; decision 2 in section 0).
2. Name and repository: Receipts, repository `receipts`.
3. Attend Builders & Brews SF on Oct 9.
4. The upstream PR: choose a Python project you use whose policy allows disclosed AI-assisted contributions, and agree to submit it under your name after reviewing it.
5. Approve Plan 1 revision 4 when it is ready, then implementation starts.

## 18. Risks, ranked

1. Sandboxes access late or denied. Mitigation: Docker executor from Oct 8; the witness, gate and receipts are ours; ask in person on Oct 9.
2. Read as another sandbox-forking agent in a field of ten. Mitigation: stance and number first; the witness, not the race, in the first 30 seconds; the gate never sold as the novelty.
3. The headline number is weak. Mitigation: pre-registered H2 and H3; the paired design makes even a modest result informative.
4. The official SWE-rebench grader is hard to run in our environment. Mitigation: try it at M2 on one task; if it fails, grade with our gate plus the instance's own FAIL_TO_PASS and PASS_TO_PASS lists, and say so in the report.
5. The demo looks rigged. Mitigation: only real, published runs on screen; attacks only in the fixture table; selection rule pre-registered.
6. Design does not land. Mitigation: D1 to D5, the thirty-second test, real-data polish before recording.
7. Schedule, and starting weeks behind the strongest entries. Mitigation: Codex implements, Claude reviews; the pilot runs in the background from M3; P1 and P2 are cut before P0 slips.
8. Re-verify unavailable during December judging. Mitigation: last recorded re-verify with timestamp on every receipt; local command documented.
9. The upstream PR adds to maintainer burden. Mitigation: one carefully chosen bug, Zeyu reviews it as they would their own, the project's AI policy is followed, disclosure is included, and it is withdrawn if the maintainer prefers.
