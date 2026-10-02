# Handoff: execute Plan 5 (Receipts v2)

> 一句话：v1 pilot 已完成并写成 REPORT.md；下一步是 Plan 5：修 v1 测出来的问题，再在没见过的 100 个任务上做一次预注册的 v2 测量，同时做评委看得到的产品面。
> 需要本人决定：批准 Plan 5；Daytona 快照删除与 key 权限；见文末「Decisions for Zeyu」。
> 过期：2026-10-30 10:00 PT（提交截止）。

Written Oct 2, 2026 for an agent starting cold in `~/dev/nebius-hackathon`. Read this file, then `REPORT.md`, then `docs/superpowers/plans/2026-10-02-plan-5-receipts-v2.md`. Do not write code until Zeyu has approved Plan 5.

## 1. What this project is

**The entry.** It is for the Nebius x NVIDIA Global AI Hackathon on Devpost, in the Coding and Agentic Engineering track.
- Submissions are due **Oct 30, 2026, 10:00 PT**.
- Judging runs Dec 1 to 15, from the submitted materials only (text, images, video).
- Four criteria are weighted equally: Technological Implementation (Token Factory and Nemotron), Design, Potential Impact, and Quality of Idea.
- Event facts are in `HANDOVER.md` under "The event".

**The product, "Receipts".**
1. The human writes the failing test.
2. A Nemotron agent (`nvidia/nemotron-3-super-120b-a12b` on Token Factory) fixes the code in a sandbox branch.
3. A model-free gate verifies the patch on a clean witness branch forked from checkpoint C0. The agent gets one appeal with the gate's evidence.
4. Only a PASS ships, and every run produces a receipt that anyone can re-verify.

**The measurement, "the False-Done Report".**
- Question: how often is an unguarded agent's "done" false, and what does it cost to ship only verified fixes?
- Data: tasks from SWE-rebench-V2, graded by the official upstream rule in a separate run that the gate never sees.
- Discipline: pre-registered in `PREREGISTRATION.md`, with dated amendments.

## 2. State on Oct 2

**Code.** Local branch `build/plan-1` at `a03f2c9` (62 commits, no remote, never pushed). `main` holds only the first handover commit. Keep working on `build/plan-1`, or a branch from it, unless Zeyu says otherwise.
- Plans 1, 1b, 2a, 2b, 2c and 3 are implemented.
- 337 tests pass and 2 live tests are skipped.

**v1 pilot.** Launch 3 is done: 50 tasks and 79 attempts. Results are in `REPORT.md`.
- A: 4 of 23 claimed dones were false.
- B: 24 of 50 verified.
- Shipped false dones: 1 in launch 3 (network-only PASS_TO_PASS test), plus launch 2's gate defect, which is fixed.

**Uncommitted.**
- `HANDOVER.md` is modified.
- Untracked: `docs/` (all specs, plans and research, which have never been committed), `pilot/run-2026-10-01c/` and the two aborted launches (57 MB), `.env.example`, `.python-version` and `spikes/`.
- Do not commit any of these without Zeyu's word (see the decisions at the end).

**Gitignored and useful.** Everything below lives in `.build/`.

| Path | What it is |
| --- | --- |
| `.build/v1_evidence.py` | Recomputes every Plan 5 number |
| `.build/failure_modes.py` | Turn use and failure modes |
| `.build/env_artifacts.py` | Environment-ungradeable analysis |
| `.build/daytona_check.py` | Key, organization, permissions and snapshot storage. Read-only, never prints the key |
| `.build/pilot-launch.sh`, `.build/pilot_watch.py` | v1's launcher and watchdog |
| `.build/task-*-review.md` | Past review notes |
| `.build/evidence/`, `.build/rehearsal-*` | Earlier runs |

## 3. Paths and environment

**Repository.** `~/dev/nebius-hackathon`. Never put code projects back under `~/Documents`: iCloud evicts files there and hides `.pth` files.
- **Old copy:** `~/Documents/nebius-hackathon` holds only a stale `.venv`. Zeyu deletes it.
- **Python:** 3.12 (`.python-version`), project venv `.venv` (no `PYTHONPATH` needed here).
- **Tests:** `.venv/bin/python -m pytest -q`.
- **Python 3.7 scripts:** `tests/test_sandbox_scripts_py37.py` needs Docker with image `python:3.7-slim`.
- **v1 report:** `.venv/bin/python -m receipts.cli pilot report pilot/run-2026-10-01c`.

**Pinned v1 worktree.** `~/.local/share/nebius-hackathon/pilot-worktree`, at `78ff2b0`, with its own venv and dataset under `~/.local/share/nebius-hackathon/`.
- v1 ran from there. Leave it alone.
- v2 gets its own pinned worktree at the freeze commit.

**Dataset.** The extract (7,243 Python rows, revision `475dd5e8`, no gold patches) is in `data/` and in `~/.local/share/nebius-hackathon/data/` (same sha256). It is never committed.

**Secrets.** They live in `.env` (gitignored): Token Factory, Daytona and Tavily keys.
- `.env.example` lists the names.
- The CLI reads `DAYTONA_API_KEY` from the environment first, then `.env`. Nothing in Zeyu's shell profile exports it.
- The pinned v1 worktree has its own copy of `.env` with the old key. That copy only matters for v1.

**Disk.** 74 GB free on Oct 2. Large repositories need several GB of staging at a time.

## 4. Working rules (verbatim from CLAUDE.md files)

- "no commits or pushes unless asked; no AI attribution in git metadata; never commit an API key; plain writing without em-dashes."
- "never add Claude as a co-author/contributor, and never mention Claude, Claude Code, or AI generation in commit messages, PR bodies, or other git metadata."
- "For non-trivial changes, wait for my approval before writing code."
- "When fixing a reproducible bug, write or update a test that fails first, then fix the code until the test passes."

Commit policy for Plan 5: during Plans 1 to 3, Zeyu allowed one commit per reviewed task. Ask Zeyu to confirm that standing permission for Plan 5 in the approval message. Until then, do not commit.

## 5. How work gets done here

Zeyu wants implementation routed to Codex and design and review kept in Claude. The memory note is `feedback-prefer-codex-for-execution`. Per task, follow these steps:

1. **Write the task card.** The main session writes behavior, files, the failing tests to write first, constraints and done criteria. Plan 5's items are written to be card-sized.
2. **Implement through Codex.** Use the `codex:codex-rescue` agent with `--model gpt-5.6-sol` (gpt-6.1-sol is rejected for this account), in write mode.
   - Give it one bounded task of under about eight minutes. It has no network inside its sandbox.
   - Do any network setup (`uv sync`, downloads) in the main session first.
   - Codex writes the failing test, shows it failing, implements the change, and runs the targeted tests.
3. **Run the full suite** (the `test-runner` agent, or directly).
4. **Review.** The `code-reviewer` agent (Sonnet) reviews the diff. The main session also reviews anything touching the trust boundary: `verify/gate.py`, `patchscope.py`, `verify/run.py`, `sandbox/*`, `junit.py`, the pytest bootstrap in `sandbox/protocol.py`, and grading in `pilot/grade.py` and `swerebench.py`.
5. **Commit**, only under the confirmed policy. Plain message, no attribution.

Zeyu has opted into Workflow orchestration for batches of Codex tasks. Watch long runs with a monitor that detects retry loops.

## 6. Invariants that must never break

These are what make the report credible. A change that weakens one needs Zeyu's explicit approval and a pre-registration amendment.

1. **The gate is model-free and pure.** Verdicts come from receipts only (`verify/gate.py` has no I/O).
2. **Trusted verification state.** The witness is forked from C0, and C0 is the trusted checkpoint. The agent's branch never contributes anything but its patch.
3. **One patch, verified and shipped.** The witness and the official grader both apply `filter_patch` output, and that exact text is what ships (`filtered.diff`). The digest is checked by R5.
4. **Separate official grading.** It runs in its own fresh fork with the upstream command, parser and apply flags. The gate never sees it.
5. **Trusted pytest runner.** It runs `python -I`, checks pytest's origin, keeps the repository root off `sys.path`, and annotates junit with rootdir and invocation dir. Amendment 2 exists because this once broke.
6. **Pre-registration discipline.** Nothing about the agent, prompts, tools, budgets, gate or grading changes after a freeze without a dated amendment appended, never edited in place. v1's `PREREGISTRATION.md` and `REPORT.md` are never rewritten.
7. **Retries and selection.** Infrastructure errors are retried, up to three runs per task, and every run is kept. Agent outcomes are never retried. Nothing is skipped by hand.

## 7. Code map

| Area | Files |
| --- | --- |
| Gate and predicates R1 to R6 | `src/receipts/verify/gate.py` |
| Baseline, witness verification, re-runs | `src/receipts/verify/run.py` |
| Patch categories and the witness filter | `src/receipts/patchscope.py` |
| Agent: planner and worker (tools, budgets, appeal) | `src/receipts/agent/planner.py`, `src/receipts/agent/worker.py` |
| Run orchestration, worker first message, receipts on disk | `src/receipts/orchestrate.py`, `rundir.py`, `receipt_text.py` |
| Executors | `src/receipts/sandbox/{protocol,local,docker,daytona,staging,sink}.py` |
| SWE-rebench adapter and the upstream grading rule | `src/receipts/swerebench.py` |
| Pilot selection, runner, official grading, report | `src/receipts/pilot/{select,runner,grade,report}.py` |
| Model client, cost | `src/receipts/llm.py`, `cost.py` |
| CLI | `src/receipts/cli.py` |
| Gate attack regression tests | `tests/attacks/` |

Design spec: `docs/superpowers/specs/2026-09-30-branch-and-verify-design.md` (v3). Earlier plans are in `docs/superpowers/plans/`, and research is in `docs/research/`.

## 8. External services

**Token Factory.** Base URL `https://api.tokenfactory.nebius.com/v1/`. Model `nvidia/nemotron-3-super-120b-a12b`, thinking off, temperature 1.0, top_p 0.95.
- v1 cost about $0.095 of model per verified fix.
- Credits: $50 claimed on Sep 29. Check the balance before the v2 launch.
- Token Factory Sandboxes access was requested on Sep 30 and was not granted as of Oct 2.

**Daytona** is the executor.
- **Limits:** Tier 1 caps are 10 vCPU and 10 GiB. Outbound network is restricted.
- **Sandboxes:** 2 vCPU, 2 GiB and 5 GiB disk each, with a 60-minute idle auto-stop.
- **Checkpoints:** each checkpoint is a Daytona snapshot of about 2.3 GB.
- **Current key:** `.env` now holds a key that was switched on Oct 2, because v1 had run on the wrong account. It is named "harbor", belongs to organization `0d3dbc72-...` (an email-login account), and carries every permission Plan 5 needs, including `delete:snapshots`. That organization holds no snapshots of ours yet.
- **Before v2:** re-run the live Daytona test, because tier caps may differ from the old organization's.
- **v1's account:** v1 ran entirely in a different account, the Google-login one, in organization `a3b20c34-...`. The old key (still in the pinned v1 worktree's `.env`) has no snapshot permissions.
- **v1's snapshots:** that organization still holds v1's 68 snapshots (67 `receipts-pilot-*`, 1 `spike-*`), 165 GB in total. To delete them, either:
  - sign in to Daytona with Google, switch to that organization and open Snapshots; or
  - have Zeyu create a key there with `delete:snapshots`, put it in `.env` as `DAYTONA_OLD_API_KEY`, and run `.venv/bin/python .build/daytona_delete_old_snapshots.py`. That script does a dry run first, refuses a key from any other organization, and deletes only on `--yes`. Afterwards Zeyu revokes that key.
- **Re-verification:** v1's snapshots are not needed for re-verifying receipts, because E2 uses Docker.
- **Pre-registration:** the account change does not change the method. v2's pre-registration names the organization used and the sandbox resources, which stay at 2 vCPU, 2 GiB and 5 GiB.

**Codex.** Called through the `codex:codex-rescue` agent with `--model gpt-5.6-sol`.

## 9. Known gotchas

- **Old absolute paths in records.** 46 of 58 v1 `record.json` files store absolute `/Users/sunzeyu/Documents/...` run directories, a leftover of the move. Tools that open those paths must map them to the repository root. `.build/v1_evidence.py` shows how. Plan 5 D0 fixes this properly.
- **Old images.** About one task in six uses a Python 3.7 image. In-sandbox scripts must stay 3.7-compatible (Amendment 3).
- **Patch apply.** Patches apply with the upstream flags `git apply -v --3way --recount --ignore-space-change --whitespace=nowarn`, after `git update-index -q --refresh` (Amendment 5).
- **Daytona cleanup** treats 404 as already deleted. One ghost sandbox from an old rehearsal may still be listed.
- **Long runs** need the Mac on AC power with the lid open, under `caffeinate` (the launcher does this), and a watchdog (`.build/pilot_watch.py`). The watchdog stops on a final infrastructure error or a gate-looser case.
- **SWE-rebench parser quirks** (scripts/eval.py at c71902a8):
  - ids are truncated at the first whitespace;
  - `SUBFAILED` lines are ignored;
  - only PASSED counts, and a missing test counts as failed.
  - These are deliberate parts of the official rule, and they are `FEEDBACK.md` material.

## 10. First actions for the new session

1. **Read, in this order:** this file, `REPORT.md`, Plan 5, and `PREREGISTRATION.md`. Skim the design spec's gate section.
2. **Health checks:**
   - `git status`;
   - `.venv/bin/python -m pytest -q` (expect 337 passed, 2 skipped);
   - `.venv/bin/python .build/v1_evidence.py` (numbers must match Plan 5, section 1);
   - `.venv/bin/python .build/daytona_check.py`.
3. **Get an adversarial review of Plan 5 before presenting it.** Run a read-only Codex review (`codex:codex-rescue`, `--model gpt-5.6-sol`) of Plan 5 against the code. Ask it to refute:
   - each section-1 number;
   - the B1 soundness invariant (that the witness, the official grader and the shipped patch all use `filter_patch` output);
   - the claim that Tier 1 fits concurrency 2;
   - any item whose touch points are wrong.

   Fold in confirmed findings, and say which ones were rejected and why.
4. **Present Plan 5 to Zeyu** with the approach, assumptions, acceptance checklist and risks (Plan 5 sections 3 to 5). Ask for the decisions below. Wait for approval.
5. **After approval:** write the detailed task cards for the first batch (B1, B2, B3, B5 and A0, which have no executor dependency), and run them through the section 5 loop.
6. **At the end of the session:** update `HANDOVER.md`'s "Next agent actions", then follow the second-brain handoff from the global instructions. Run `cd "$HOME/Documents/second brain" && uv run python -m brain_tools radar`, and append one line to the "Agent 交接" section of `~/Documents/Obsidian Vault/Projects/beta fund.md`.

## 11. Decisions for Zeyu (recommendation first)

1. **Approve Plan 5 as revised.** Recommended. Ask also for the standing commit permission (one commit per reviewed task).
2. **Daytona.**
   - (a) The key change is done, and the new key has `delete:snapshots`.
   - (b) Delete v1's 68 snapshots in the old Google-login account, using either route in section 8.
   - (c) Tier 2 only if cheap. Concurrency 2 fits Tier 1.
3. **v2 design:** an unseen primary sample of 100 tasks (headline) plus re-running v1's 50 as a labelled "seen" ablation. Recommended over a single mixed sample, which would let v1's lessons leak into the headline.
4. **Ungradeable tasks:** exclude them by rule 5. Recommended, because it keeps the official rule intact. The alternative is grading on the subset of tests the environment can run.
5. **Commit `docs/`.** Recommended, after a read for private notes, because the specs and plans have no history today.
6. **Publish the pilot data** as a GitHub release archive. Recommended.
7. **GitHub repository name**, and when to make it public (before submission, with the MIT license already in `LICENSE`).
8. **Optional:**
   - the E6 GitHub Action, decided after v2 launches;
   - the SF City Winner meetup on Oct 9 (4 to 10 pm, Motoring Coffee, 1525 Union St).

## 12. Paste this to start the new session

```
Read docs/HANDOFF-2026-10-02-plan-5.md and follow its section 10. Do not write code until I approve Plan 5.
```
