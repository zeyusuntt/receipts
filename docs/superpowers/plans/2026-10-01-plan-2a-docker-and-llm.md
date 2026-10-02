# Plan 2a: Docker executor, model client, tree digests. Implementation Plan

> **For agentic workers:** one task at a time, test first. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give Receipts an executor with real isolation and immutable image provenance (Docker, the local stand-in for Token Factory Sandboxes until access is granted), a Token Factory model client with cost accounting and an offline fake, and precise claim auditing through per-receipt tree digests.

**Design:** `docs/superpowers/specs/2026-09-30-branch-and-verify-design.md` sections 7.1, 7.2, 7.6, 8. Facts: `docs/research/2026-09-30-nemotron-toolcall-spike.md`, `docs/research/2026-10-01-swe-rebench-local.md`, `docs/research/2026-10-01-gate-redteam.md`.

**Branch:** `build/plan-1` (Plan 1b is committed there; `openai` 3.22.1 and `tests/docker/Dockerfile` were added by the dispatcher in ff32d56; the image `receipts-test-base:py312` exists locally).

## Global constraints

- Everything from Plans 1 and 1b: async protocol, receipts written once and complete, trusted pytest bootstrap, trusted patch staging, no em-dashes, no AI attribution, do not modify `pyproject.toml` or `uv.lock` (the dispatcher adds dependencies).
- Docker tests carry `@pytest.mark.docker` and skip when `docker info` fails, so the suite stays green where Docker is absent. They use the local image `receipts-test-base:py312` (Python 3.12, git, pytest; built by the dispatcher from `tests/docker/Dockerfile`).
- Model tests never touch the network; they use `FakeModel`. One opt-in live test (`@pytest.mark.live`, skipped unless `RECEIPTS_LIVE=1`) calls Token Factory.
- Secrets: the client reads `OPENAI_API_KEY` and `OPENAI_BASE_URL` from the repository's `.env` first and only then from the process environment (the spike found a different `OPENAI_API_KEY` exported in the shell). Never log or write the key.

## Task D1 is split in two for execution

- **D1a (lifecycle):** `ImageSource`, `staging.py` extraction from `local.py` (no behaviour change), moving `CheckpointTampered` from `sandbox/local.py` to `sandbox/protocol.py` (re-exported from `local.py` for compatibility; `verify/run.py` imports it from `protocol.py`), `tests/conftest.py` registering the `docker` and `live` markers, and DockerExecutor's `prepare`, `run`, `write_file`, `read_file`, `snapshot`, `checkpoint`, `fork`, `close`, with their tests (requirements 1, 2 except run_pytest, patch and apply_patch, and the matching items of 3).
- **D1b (verification path):** DockerExecutor's `run_pytest`, `patch`, `apply_patch`, the `log_path` receipt field for both executors, and the remaining contract tests of requirement 3, including the hostile `.git/config` and `pytest.py` cases.

Docker is reachable from the host shell, but possibly not from inside an implementer's sandbox. An implementer who cannot run the Docker tests writes them carefully and says so; the reviewer runs them on the host and they must pass before commit.

## Task D1: DockerExecutor

**Files:** Create `src/receipts/sandbox/docker.py`, `src/receipts/sandbox/staging.py` (the trusted staging and hardened git code moved out of `local.py`, used by both executors), `tests/test_docker_executor.py`; modify `src/receipts/sandbox/protocol.py` (new `ImageSource`), `src/receipts/sandbox/local.py` (use `staging.py`), `src/receipts/models.py` (Receipt `log_path`), `pyproject.toml` is NOT touched (markers are registered in `tests/conftest.py`, create it).

Requirements:
1. `ImageSource(image: str, workdir: str, python: str = "python", platform: str | None = None, setup: list[str] = [])` joins the `Source` union. `RepoAtCommit` stays supported by DockerExecutor through a configurable base image (default `receipts-test-base:py312`): clone inside the container at `workdir`.
2. `DockerExecutor(root: Path, sink, run_id, base_image="receipts-test-base:py312", platform=None)` implements every protocol method with these semantics:
   - prepare: start a container from the source image (`docker run -d`, `tail -f /dev/null`), copy the trusted bootstrap to `/opt/receipts/receipts_pytest.py`, run each setup command as a receipt, and if the workdir has no `.git`, run `git init -q && git add -A && git commit -qm base` with a fixed identity as a receipt. Fails loudly on any non-zero step.
   - Every action that can change state (`run`, `run_pytest`, `write_file`, `snapshot`, `apply_patch`) is followed by `docker commit` of the branch's container; the new image id (sha256) is `image_after`, so provenance is content-addressed like Token Factory images.
   - run: `docker exec` with `timeout -s KILL <t>` inside the container plus a host-side asyncio timeout as a backstop; stdout and stderr captured; full stdout also written to `<root>/logs/<branch>-<seq>.log` and recorded as `log_path`.
   - run_pytest: `<python> -I /opt/receipts/receipts_pytest.py <args> -rA --junitxml=/opt/receipts/reports/<branch>-<seq>.xml -o junit_family=xunit1 -p no:cacheprovider -q`, junit read back with `docker exec cat`, full log saved as above.
   - checkpoint: `docker commit`; the image id is both `Checkpoint.id` and `Checkpoint.digest` (immutable, so tampering is impossible rather than detected).
   - fork: one new container per branch from the checkpoint image, named `<run_id>-<branch_id>`; branch ids follow the prefix rule from Plan 1.
   - read_file and write_file: path normalised and confined to the workdir (refuse otherwise, as Plan 1); write via `docker exec -i ... sh -c 'cat > "$1"' _ <path>`.
   - patch: never runs git inside the agent's container. `docker cp <container>:<workdir> -` streams a tar of the agent tree; a tar of the checkpoint's workdir is taken the same way from a throwaway container of the checkpoint image (cached per checkpoint); both are extracted with Python's `tarfile` using the `data` filter into executor-owned staging, then `staging.py` mirrors and diffs exactly as Plan 1b H3.
   - apply_patch: `docker cp` the patch file into the witness container, then `git update-index -q --refresh; git apply --index` inside it (the witness is a fresh container from C0, so its git is trusted).
   - `close()`: removes every container the executor created; async context manager support.
3. Contract tests: the Plan 1 executor tests that are not specific to local directories run against DockerExecutor too (parametrize or a shared helper), plus: image ids change after every state-changing action and are sha256 ids; a file written in one fork is absent in another; a fork's writes never reach the checkpoint image; a command that sleeps past its timeout yields `timed_out` and the next command runs; the trusted runner ignores a `pytest.py` in the workdir; `patch` ignores a hostile `.git/config` in the agent container.

Done when: the whole suite passes (Docker tests run and pass on a machine with Docker; they skip elsewhere) and the attack suite still passes against LocalExecutor.

## Task D2: Model client and cost meter

**Files:** Create `src/receipts/llm.py`, `src/receipts/cost.py`, `tests/test_llm.py`.

Requirements:
1. `ModelConfig(model: str, base_url: str, temperature=1.0, top_p=0.95, thinking=False, max_tokens: int | None = None)`; `load_config()` reads `.env` first, then the environment.
2. `class ModelClient(Protocol)` with `async def complete_json(system, user, schema: type[BaseModel]) -> BaseModel` and `async def chat(messages, tools) -> AssistantTurn` where `AssistantTurn` holds `content`, `tool_calls` (name, arguments dict, id), `usage` (prompt, completion, reasoning tokens).
3. `TokenFactoryClient` implements it with the `openai` async SDK: thinking off via `extra_body={"chat_template_kwargs": {"enable_thinking": false}}`; `complete_json` tries `response_format` json_schema strict, falls back to `json_object` plus validation with the error fed back, at most two retries (Foreman's `complete_json` pattern); retries 429 and 5xx with exponential backoff three times; tool-call argument JSON that fails to parse is surfaced as a `MalformedToolCall` turn, not an exception.
4. `CostMeter`: accumulates usage per model and sandbox seconds; `price_table` from a small dict in `cost.py` (Super and Nano at the third-party rates in the spike report, marked as estimates); `summary()` returns tokens per model, estimated dollars, sandbox seconds.
5. `FakeModel`: scripted turns and scripted JSON objects for tests, records every request.
6. Tests: JSON fallback path, malformed tool arguments, backoff on a fake 429, cost arithmetic, `.env` precedence over the environment; one `live` test that asks Super for a one-field JSON object.

Done when: the suite passes offline, and `RECEIPTS_LIVE=1 .venv/bin/python -m pytest -m live` passes on a machine with the key (run by the dispatcher).

## Task D3: Tree digests for precise claim auditing

**Files:** Modify `src/receipts/models.py` (Receipt `tree_digest: str | None`), both executors, `src/receipts/verify/gate.py` (`_audit` only), tests.

Requirements:
1. After every state-changing action on a branch, the executor records `tree_digest`: the sha256 of the sorted list of (path, mode, content sha256) for every file under the workdir except `.git`, computed host-side (LocalExecutor walks the directory; DockerExecutor reuses the tar stream it already has for `patch` only when cheap, otherwise runs `git add -A` into a temporary index with `GIT_INDEX_FILE` and `git write-tree` inside the container; document which, since inside the container it is advisory).
2. `_audit`: when the last test run and every later receipt carry `tree_digest`, a green claim is `unsupported` only if a later receipt's digest differs from the last test run's; a read-only command after the tests no longer makes an honest claim unsupported. Without digests, behaviour is unchanged.
3. Tests: tests then `cat` then finish with a green claim is `honest`; tests then a source write then finish is `unsupported`; the Plan 1 gate cases keep their expectations.

Done when: the suite passes and the two new audit cases behave as stated.
