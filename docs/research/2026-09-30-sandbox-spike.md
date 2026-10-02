# Sandbox spike: can Token Factory Sandboxes fork a checkpoint into two branches?

Date: 2026-09-30. Wall time spent: about 30 minutes. Throwaway probe: `spikes/sandbox_probe.py`. SDK: `contree-sdk 0.3.6` installed in a scratchpad venv (not in the repo).

## Verdict

**BLOCKED, not yet GO or NO-GO on forking.** The Token Factory key authenticates to the Sandboxes API (`GET /sandboxes/v1/whoami` returns 200 with limits) but every permission comes back `False` (`import, spawn, spawn_disposable, list, cancel, set_image_tag`), and any real call fails with `403 Insufficient permissions: list and spawn`.
Strongest evidence: the API requires a `Project` header carrying a Nebius project ID (400 `Missing "Project" header` without it); that ID is only shown in the Token Factory console, there is no discovery API (`/v1/projects` is 404 on both APIs), and it is not in `.env`. No sandbox was spawned, so steps 2 to 7 were not executed.
One action unblocks everything: Zeyu copies the Sandboxes project ID from the console into `.env` as `NEBIUS_AI_PROJECT=...` and re-runs `spikes/sandbox_probe.py` (about 5 minutes; the script already covers steps 1 to 7 and prints a ledger).

## Ledger

| Step | Status | Evidence |
|---|---|---|
| 1 Auth | CHECKED (partial) | `Contree(token=<TF key>)` hits `https://api.tokenfactory.nebius.com/sandboxes/v1/whoami` in 0.59 s -> 200. `permissions` all False. `limits={instance_max_timeout: 3600, instance_max_concurrency: 50, instance_max_layer_bytes: 12884901888, images_import_max_concurrency: 8, images_import_max_timeout: 3600}`. Same key works on inference (`GET /v1/models` 200). |
| 1 Hello world run | UNVERIFIED | `images.oci("python:3.12-slim")` -> `ForbiddenError ... status=403, error='Insufficient permissions: list and spawn'` in 0.19 s. No spawn possible without a project. Cold-start latency unmeasured. |
| 2 Clone, pip, pytest | UNVERIFIED | Not executed. Network egress for git/pip is unverified; the REST spawn body has a `networking` field (API reference), default unknown. |
| 3 Checkpoint semantics | UNVERIFIED (design read from SDK source) | `image.run(..., disposable=False)` returns a new image object whose `.uuid` is the resulting filesystem state; `.result` carries `exit_code, stdout, stderr, elapsed_time, cost`. `sdk.images.use(uuid, strict=True)` re-resolves it. Not observed live. |
| 4 Fork into two branches | UNVERIFIED (design) | Forking is just calling `.run()` twice on the same parent image object; docs "Branching Workflows" show three children from one parent. Concurrency via `asyncio.gather` is natural (each run is an async operation polled by uuid). Isolation not observed live. |
| 5 Evidence retrieval | UNVERIFIED (design) | Per resulting image: `await img.read("/work/report.xml") -> bytes`, `await img.download(path, local)`, `await img.ls("/work")`. REST: `GET /v1/inspect/{uuid}/download?path=...`. Not observed live. |
| 6 Limits and quirks | CHECKED (from whoami + docs) / UNVERIFIED (behavior) | Limits above. Docs: max 50 simultaneous operations, checkpoint images kept 180 days, untagged unreferenced images may be deleted. SDK default `truncate_output_at=65535` bytes on stdout/stderr (pytest output will be cut; use junitxml). Cancel = `DELETE /v1/operations/{id}`; SDK auto-cancels on client-side timeout. Cost is reported per run in `result.cost` (unit unverified). Timeout behavior and cost values not observed live. |
| 7 SWE-rebench catalog | UNVERIFIED | Docs say 7,000+ preloaded environments (SWE-bench Verified, SWE-rebench, SWE-rebench-V2) but give no listing call; `sdk.images(tagged=True)` and `GET /v1/images` need `list` permission (400/403 here). |

## Measured latencies

- `whoami`: 0.59 s (first call), sub-second on repeats.
- `GET /v1/inspect/?tag=...` 403: 0.19 s.
- Inference `GET /v1/models`: 200, sub-second.
- Everything else: not measured.

## SDK calls that worked

```python
from contree_sdk import Contree
sdk = Contree(token=key)                    # default base_url https://api.tokenfactory.nebius.com/sandboxes/
who = await sdk.get_token_info()            # WhoAmI(permissions={...}, limits={...}, operations_stat={...})
```

Auth model (from `contree_sdk/auth.py`): `IAMAuth` sends `Authorization: Bearer <token>` plus `Project: <project id>`. The project id is read from env var `NEBIUS_AI_PROJECT` (SDK), `CONTREE_PROJECT` / `NEBIUS_AI_PROJECT` (CLI/MCP), or `~/.config/contree/auth.ini` `[profile:default] project = ...`. Without it the SDK sends the literal string `NEBIUS_AI_PROJECT`, which the API accepts but grants nothing.

## SDK calls that failed (exact text)

- `await sdk.images.oci("ubuntu:latest")` -> `ForbiddenError(request=RequestInfo(url='https://api.tokenfactory.nebius.com/sandboxes/v1/inspect/?tag=ubuntu%3Alatest', method='GET'), status=403, error='Insufficient permissions: list and spawn')`
- Same for `python:3.12-slim`.
- Raw `GET /sandboxes/v1/whoami` without `Project` header -> `400 {"error": "Missing \"Project\" header"}`; with empty `Project` -> same 400.
- Raw `GET /sandboxes/v1/images` without project -> `400 Missing "Project" header`.
- `GET /v1/projects` on inference and sandboxes hosts -> 404 (no discovery API).
- Legacy host `https://eu-north.nebius.computer/v1/whoami` with the TF key -> `401 Unauthorized` (different auth realm, not a fallback).
- A run of the probe returned `ForbiddenError: You do not have permission to perform this action` (403) on `whoami`. Root cause was local, not the API: the shell profile exports a different `OPENAI_API_KEY` (164 chars) than `.env` (236 chars) and the script preferred the environment. Fixed by reading `.env` first. Runner rule: never let the shell `OPENAI_API_KEY` shadow the Token Factory key.
- SDK logs `Token expires in 0 hours` on every client construction: `whoami.token_expiration` is about 5 minutes ahead (short-lived exchanged token). Cosmetic.

## Doc discrepancies worth knowing

- The Getting Started page shows `ContreeAsyncClient(...)` from `contree_client.httpx`; that class does not exist in 0.3.6. The README and source use `Contree(token=...)` / `ContreeSync(token=...)`.
- Docs never say where the project ID lives beyond "from your ConTree project" in the Token Factory console. Third-party notes (kimi-relay SANDBOXES.md) confirm: shown in console only; `403 Insufficient permissions: spawn` means Sandboxes permissions must be granted for that project in the console, not a beta-access problem.

## What the product runner should do

1. Read `OPENAI_API_KEY` and `NEBIUS_AI_PROJECT` from env; construct `Contree(token=key)`; call `get_token_info()` at startup and refuse to start if `permissions["spawn"]` is False (fail fast with the exact permission list).
2. Base image via `sdk.images.oci("python:3.12-slim")` (imports once, reused by tag).
3. One setup run: clone + install + baseline pytest, `disposable=False, tag="<repo>:installed"`, timeout <= 3600 s; keep its `.uuid` as the checkpoint.
4. Fork = `asyncio.gather(ckpt.run(A, disposable=False), ckpt.run(B, disposable=False))`; each returns its own image uuid.
5. Always run pytest with `--junitxml=/work/report.xml` and `; echo EXIT=$?` so the pytest exit code survives trailing commands.
6. Receipts come from the executor: `img.exit_code`, `img.stdout`, `await img.read("/work/report.xml")`, `img.result.cost`, `img.elapsed`; store with the image uuid so any branch can be re-inspected or re-run later.
7. Expect stdout/stderr truncation at 64 KB; put anything the verifier parses in files, not stdout.
8. Cap concurrency well under 50 running operations; catch `TooManyRequestsError` (SDK already retries with backoff).
9. Set explicit per-run `timeout`; the SDK cancels the operation server-side if the client gives up.
10. Re-run `spikes/sandbox_probe.py` first thing after the project ID lands; do not build on unverified fork behavior. Load credentials from `.env` explicitly; the shell already exports a different `OPENAI_API_KEY`.

## Run 2 (2026-09-30, later): project id present, still no permissions

`NEBIUS_AI_PROJECT` (an `aiproject-...` id from the console) was added to `.env` and the probe rerun with the `Project` header set. `whoami` returned 200 in 1.02 s with the same limits, and every permission was still `False` (`import, spawn, spawn_disposable, list, cancel, set_image_tag`). So the project id was necessary but not sufficient.

Third-party integrations that hit the same wall say the same thing: Sandboxes is in beta behind an access request, and "sandbox spawn capability is blocked on Nebius beta-access approval, not a console toggle" (https://github.com/rennf93/roboco/pull/1103); "every sandbox command maps a 401/403 to a message pointing at the request form" (https://github.com/opencolin/kimi-relay/blob/main/docs/SANDBOXES.md). The console has a Sandboxes page at https://tokenfactory.nebius.com/sandboxes (login required; not inspected here).

Next action: request Sandboxes access for this project from the console's Sandboxes page, and ask in the hackathon Discord (https://discord.gg/eXYTGhgnhK) for participant access, since the event's Coding track explicitly points at Sandboxes. Until it is granted, Plan 1 (offline) proceeds and Plan 2's Token Factory executor is blocked; the spec's fallback (Docker-backed local executor, Token Factory for inference only) stays the last resort.
