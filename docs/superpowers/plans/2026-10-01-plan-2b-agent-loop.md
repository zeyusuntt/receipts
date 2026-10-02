# Plan 2b: The agent loop, the orchestrator and the CLI. Implementation Plan

> **For agentic workers:** one task at a time, test first. Everything here must be testable offline with `FakeModel` and `LocalExecutor`.

**Goal:** Turn the gate and executors into the product: a planner and a bounded worker on Nemotron, one appeal driven by the gate's evidence, an orchestrator that writes the run directory and the receipt, and a CLI.

**Design:** `docs/superpowers/specs/2026-09-30-branch-and-verify-design.md` sections 3, 7.3 to 7.7, 9, 10. Facts: `docs/research/2026-09-30-nemotron-toolcall-spike.md` (tool calling and JSON settings that worked; Nano is not used in the loop).

**Depends on:** Plan 2a (ModelClient, FakeModel, CostMeter, tree digests, DockerExecutor), committed on `build/plan-1` up to b5bbc29. Read `src/receipts/llm.py` for the exact ModelClient, AssistantTurn and FakeModel interfaces before writing code.

## Global constraints

- Same as Plans 1, 1b, 2a. No network in tests. The model is always reached through the `ModelClient` protocol from Plan 2a.
- The worker never sees a Receipt object, only text the worker module builds from it (command, exit code, last 6,000 characters of output). The gate never sees model output.
- Every prompt is a module-level constant or a function of explicit inputs, so tests can assert on it.

## Task A1: Planner

**Files:** Create `src/receipts/agent/__init__.py`, `src/receipts/agent/planner.py`, `tests/test_planner.py`.

1. `Plan(BaseModel)`: `hypothesis: str`, `files_to_edit: list[str]`, `approach: str`.
2. `async def make_plan(model: ModelClient, ex: Executor, branch: Branch, issue: str, baseline: Baseline, spec_tests: list[str]) -> tuple[Plan, list[Receipt]]`: lists tracked files with one read-only command on the given branch (`git ls-files`, output capped at 400 paths, deepest paths dropped first), reads the files the spec tests live in and up to five source files they import (simple `import`/`from` parsing, repo-local modules only, each read capped at 12,000 bytes), then makes one `complete_json` call. Returns the plan and the receipts it caused.
3. The system prompt says: the tests named are the specification and are read-only; propose the smallest change; name only files that exist.
4. Tests with FakeModel and LocalExecutor on the fixture repo: the prompt contains the issue, the failing spec test id and the spec test file's text; files the plan names that do not exist are dropped and recorded; the function returns the receipts of its reads.

## Task A2: Worker and appeal

**Files:** Create `src/receipts/agent/worker.py`, `tests/test_worker.py`.

1. Tools exposed to the model (OpenAI function schemas): `read_file(path)`, `write_file(path, content)`, `run_command(command)`, `finish(summary, claims)` where `claims` has `tests_run`, `target_tests_pass`, `full_suite_pass`, `files_changed`.
2. `class Worker` holds the conversation. `async def attempt(budget) -> WorkerOutcome` runs the loop; `async def appeal(evidence: str, budget) -> WorkerOutcome` appends one user message (the evidence verbatim plus "Fix the source so these checks pass. Tests and pytest configuration are read-only.") and continues the same conversation. `WorkerOutcome`: `end` (`finished`, `budget_exhausted`, `protocol_error`, `model_error`), `claims: Claims | None`, `summary`, `turns`, `receipt_ids`.
3. One tool call per turn: extra calls in one turn are answered with "one tool call per turn; only the first was run". Free text with no tool call gets one repair message, the second time the attempt ends `protocol_error`. An unknown tool name gets one "unknown tool, the tools are ..." reply. A `finish` before any successful `write_file` receipt on the branch is answered once with "nothing has been changed yet"; a second `finish` is accepted.
4. Budget: max turns (default 25), max wall seconds (default 900), max completion tokens; hitting one ends `budget_exhausted`.
5. Tool results shown to the model: for commands, `exit <code>` (or `timed out`) plus the last 6,000 characters of combined output; for writes, `ok` or the refusal; for reads, the content capped at 12,000 bytes.
6. Every model turn is appended to a `worker.jsonl` writer passed in (request message count, tool calls, usage, end reason), never the API key.
7. Tests with FakeModel and LocalExecutor: a scripted honest fix ends `finished` with claims; two calls in one turn; free text twice; unknown tool; premature finish; turn budget; `appeal` continues the same message list and the evidence text appears verbatim.

## Task A3 is split in two for execution

- **A3a:** `src/receipts/orchestrate.py`, `src/receipts/rundir.py`, `tests/test_orchestrate.py`: requirements 1 and 2 and the first three test scenarios of requirement 5 (asserting on `result.json` and the run directory, not on Markdown).
- **A3b:** `src/receipts/receipt_text.py`, `src/receipts/cli.py`, the `[project.scripts]` entry in `pyproject.toml`, `tests/test_cli.py`, and Markdown assertions added to `tests/test_orchestrate.py`: requirements 3 and 4 and the remaining test scenarios.

## Task A3: Orchestrator, run directory, receipt, CLI

**Files:** Create `src/receipts/orchestrate.py`, `src/receipts/rundir.py`, `src/receipts/receipt_text.py`, `src/receipts/cli.py`, `tests/test_orchestrate.py`, `tests/test_cli.py`; modify `pyproject.toml` ONLY to add `[project.scripts] receipts = "receipts.cli:main"` (the one allowed pyproject edit in this plan).

1. `async def fix(ex, model, source, issue: str, spec_tests: list[str], suite_scope: str, run_dir: Path, appeals: int = 1, budgets=...) -> RunResult` performs, in order: prepare; baseline (twice, Plan 1); record disclosure (model config, thinking flag, sampling, receipts version, executor kind) and the digests of every file under the test tree and every pytest configuration file, plus `pip freeze` output saved to `lock.txt` with its digest; snapshot; checkpoint C0; fork the agent branch; plan; worker attempt; `verify_attempt`; gate; on REJECTED with an appeal left, `appeal` with the failed predicates' evidence lines and the claim audit sentence, then `verify_attempt` with the next witness and the gate again; write everything.
2. The run directory layout is exactly the spec's section 7.7; `result.json` holds the final verdict, the verdict history, the selected patch path (the last attempt's filtered patch when it PASSED), cost summary and wall time.
3. `receipt_text.render(result) -> str` renders the receipt as Markdown for a PR description: verdict, the six checks with evidence, what the agent said beside the record, base and patched runs, files changed and dropped, test digests, lock digest, model and settings, lineage line, cost. No em-dashes.
4. CLI: `receipts fix --repo PATH_OR_URL --commit SHA --test NODE_ID [--test ...] --issue-file FILE [--install CMD] [--suite ARGS] [--executor local|docker] --out DIR`; `receipts doctor` (checks `.env` values present, one tiny model call when `--live`, Docker reachable, prints READY or the first failing check); `receipts show RUN_DIR` (prints the receipt Markdown).
5. Tests (offline, FakeModel plus LocalExecutor on the fixture repo):
   - an honest scripted fix ends PASS on the first verdict, the run directory has every file of the layout, and the Markdown receipt contains the spec test id and "VERIFIED";
   - a scripted agent that edits the test file and claims green ends REJECTED with R4 on the first verdict, appeals, then makes an honest source fix and ends PASS, and the history holds both verdicts;
   - a scripted agent that never fixes ends with no verified fix after one appeal;
   - `receipts show` prints the receipt; `receipts doctor` without `--live` passes when `.env` has the keys and reports the missing one otherwise.

Done when: the suite passes offline, including every earlier test and the attack suite.
