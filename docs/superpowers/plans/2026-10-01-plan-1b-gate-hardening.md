# Plan 1b: Gate hardening after the red-team. Implementation Plan

> **For agentic workers:** implement one task at a time, test first. Each task names the attack tests that must flip and the unit tests to add. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the six PASS holes and three wrong verdicts the Oct 1 red-team found in the Plan 1 code, keep every Plan 1 test green, and turn the attacks into a permanent regression suite.

**Source:** `docs/research/2026-10-01-gate-redteam.md` (the report) and the attack tests Codex wrote in `.build/attacks/` (ignored by git). Design: `docs/superpowers/specs/2026-09-30-branch-and-verify-design.md`, decisions 13 and 14.

**Branch:** `build/plan-1`. Baseline: 84 tests pass (`.venv/bin/python -m pytest -p no:cacheprovider -o addopts="" -q`).

## Global constraints

- Same as Plan 1: async executor protocol; receipts written once, complete; no network; no em-dashes; no AI attribution in files or commit messages; do not modify `pyproject.toml` or `uv.lock`.
- The local executor is a development and test executor. It cannot stop an agent shell from writing outside its worktree; it must detect tampering instead and turn it into ERROR. Prevention is the Token Factory executor's job (immutable images) and the Docker executor's (Plan 2).
- Every hole closes by producing REJECTED or ERROR, never by special-casing the attack test.
- Hole 6 (production code that detects pytest) is a documented limit, not a bug: its test stays and asserts PASS, with a docstring that says why.

## Task H1: Regression suite and patch classification hardening

**Files:**
- Create: `tests/attacks/__init__.py`, `tests/attacks/helpers.py` and every `tests/attacks/test_*.py`, copied from `.build/attacks/` (keep the `.build/attacks/` originals untouched).
- Modify: `src/receipts/models.py` (FileCategory), `src/receipts/patchscope.py`, `src/receipts/verify/gate.py` (R4 only), `tests/test_patchscope.py`.

Requirements:
1. Copy the attack suite into `tests/attacks/`. Rewrite each hole test's final assertions to the verdict the hardened gate must give: `test_pytest_shadow.py`, `test_binary_pytest_shadow.py`, `test_pytest_toml_plugin.py`, `test_external_diff_provenance.py`, `test_pytest_shadow_error.py`: status REJECTED; `test_checkpoint_escape.py`: status ERROR with an error mentioning the checkpoint; `test_pytest_toml_shrink.py` and `test_rename_wrong_r4.py`: R4_patch_scope among the failed predicates. Leave the correctly-caught tests as they are. `test_calc_detects_pytest.py` keeps asserting PASS and gains a docstring naming it a known limit of any test-based gate.
2. Tests that need H2, H3 or H4 to pass are marked `@pytest.mark.xfail(strict=True, reason="closed by Task H<n>")`; the task that closes them removes the marker.
3. `patchscope.categorize(path, protected_modules=frozenset())`: add `pytest.toml` and `.pytest.toml` to the pytest configuration names; add category `executable_artifact` for any path ending `.pyc`, `.pyo`, `.so`, `.pyd`, `.dylib` or `.pth`; add category `shadow` for a path with no directory part whose stem (for `name.py`, `name.pyc`, `name.so` and the like) or name (for a package directory's `__init__.py`, i.e. `name/__init__.py` at the top level) is in `protected_modules`. `summarize_patch` and `filter_patch` take the same optional `protected_modules` argument and pass it through. The filter drops `executable_artifact` and `shadow` files. R4 rejects both categories, with evidence naming the category.
4. Add `receipts.patchscope.default_protected_modules()` returning `frozenset(sys.stdlib_module_names) | {"pytest", "_pytest", "py", "pluggy", "conftest"}` plus the top-level names of every installed distribution visible to the executor's interpreter (`importlib.metadata.packages_distributions()` keys). Plan 1's callers (`LocalExecutor.patch`, `verify_attempt`) pass it.
5. Unit tests in `tests/test_patchscope.py` for each new category and for the filter dropping them; existing tests keep passing.

Done when: the Plan 1 suite passes, the new unit tests pass, `test_pytest_toml_plugin.py` and `test_pytest_toml_shrink.py` pass without xfail, and every other flipped attack is either passing or strictly xfailed with the task that will close it.

## Task H2: Trusted pytest runner

**Files:** Modify `src/receipts/sandbox/local.py` and `src/receipts/sandbox/protocol.py`; add tests to `tests/test_local_executor.py`; remove the H2 xfail markers in `tests/attacks/`.

Requirements:
1. `run_pytest` no longer runs `python -m pytest` with the worktree first on `sys.path`. It runs `python -I <executor_root>/tools/receipts_pytest.py <args>`, where the bootstrap file is written by the executor outside every worktree when the executor starts. `-I` keeps the current directory, `PYTHONPATH` and user site out of `sys.path`.
2. The bootstrap imports `pytest`, resolves `pytest.__file__` with `os.path.realpath`, and exits with code 4 and the message `receipts: untrusted pytest at <path>` on stderr if that path is inside the current working directory; otherwise it calls `sys.exit(pytest.main(sys.argv[1:]))`.
3. The command environment for `run_pytest` clears `PYTEST_ADDOPTS` and `PYTEST_PLUGINS`. Plugin autoload stays on: the witness environment is the pre-agent environment.
4. Tests: a worktree containing `pytest.py` still runs the real pytest (the fake file is never imported); the bootstrap's untrusted-origin exit is covered by a unit test that points it at a fake package path.

Done when: all Plan 1 tests and H1 tests pass, and `test_pytest_shadow.py`, `test_binary_pytest_shadow.py` and `test_pytest_shadow_error.py` pass without xfail.

## Task H3: Trusted patch extraction, no renames

**Files:** Modify `src/receipts/sandbox/local.py`; add tests to `tests/test_local_executor.py`; remove the H3 xfail markers.

Requirements:
1. `patch(branch, snapshot_sha)` never runs git inside the agent's worktree. It creates an executor-owned staging directory as a fresh copy of the branch's origin checkpoint (whose `.git` predates the agent), then mirrors the agent worktree onto it with Python (no shell): every path except `.git/` is copied with `lstat` semantics (symlinks stay symlinks, modes preserved), and every staging path absent from the agent worktree (except `.git/`) is deleted.
2. In staging, git runs with `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL` set to `os.devnull`, `HOME` set to the executor root, and `-c core.hooksPath=/dev/null -c core.attributesFile=/dev/null -c diff.external= -c core.quotePath=false`; the commands are `git add -A` then `git diff --cached --binary --no-ext-diff --no-textconv --no-renames <snapshot_sha>`.
3. The receipt's `cmd` says the patch was computed in staging; `branch.head` and sequence numbering behave as before.
4. Tests: a `.git/config` edit with `diff.external` or a `filter` in the agent worktree has no effect on the patch; a rename of a test file into a source path shows as a deletion plus an addition and fails R4; the existing patch tests still pass.

Done when: all earlier tests pass and `test_external_diff_provenance.py` and `test_rename_wrong_r4.py` pass without xfail.

## Task H4: Checkpoint integrity

**Files:** Modify `src/receipts/models.py` (Checkpoint), `src/receipts/sandbox/local.py`, `src/receipts/verify/run.py`, `src/receipts/verify/gate.py` (ERROR precedence and reason only, amended by the plan owner on Oct 1 after review); add tests, including `tests/test_gate.py`; remove the H4 xfail markers.

Requirements:
1. `Checkpoint` gains `digest: str | None = None`. `LocalExecutor.checkpoint` computes it as the sha256 over the sorted list of (relative path, file mode, sha256 of bytes or of the link target) for every entry under the checkpoint directory, `.git` included.
2. `fork` and the staging step of `patch` recompute the digest first and raise `CheckpointTampered(checkpoint_id)` on mismatch.
3. `verify_attempt` catches `CheckpointTampered` and returns an `Attempt` whose apply receipt is a failed apply (exit code 1, stderr `checkpoint <id> was modified after prepare`) on a branch named for the witness, and whose verification is None, so the gate returns ERROR with that reason in the claim-preserving way it already does.
4. Tests: writing into the checkpoint directory from the agent branch makes the next fork raise; `test_checkpoint_escape.py` ends in ERROR.
5. Gate (amendment): `evaluate` checks a failed apply receipt before a failed patch receipt, and the ERROR reason for a failed apply is the first line of `apply.stderr_tail`, truncated to 200 characters, falling back to the existing constant message when empty. A unit test in `tests/test_gate.py` covers this precedence and the truncation.

Done when: every test in the repository passes and no xfail marker is left in tests/attacks/; the attack suite shows all 18 attacks with the expected verdicts.

## Final state

`.venv/bin/python -m pytest -p no:cacheprovider -o addopts="" -q` passes everything; no `xfail` remains in `tests/attacks/`; the README fixture table (Plan 4) can be generated from `tests/attacks/` and `tests/fixtures/gate_cases.py`.
