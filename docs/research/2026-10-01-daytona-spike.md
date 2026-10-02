# Daytona as an interim executor: spike results (2026-10-01)

## Verdict

1. GO as an interim executor for development and a small pilot, with three conditions: Tier 1 concurrency is tiny (10 GiB RAM total), the API key cannot delete snapshots, and there is no native fork for container sandboxes, so a fork is a snapshot plus N creates.
2. Strongest evidence: on SWE-rebench V2 `pycqa__docformatter-254` the real V2 image booted in 42 s, the FAIL_TO_PASS test failed as expected, a snapshot of the running sandbox took 62 s, branches from it came up in 1.3 to 1.7 s each with proven two-way isolation, and a fresh branch from the snapshot (after its source sandbox was deleted) took the gold patch and ran `10 passed`.
3. Cost is not a constraint: about $3 to $8 for 50 tasks (3 sandboxes each) against $200 of free credit; the blockers are quota and permissions, not price.

## Setup and test task

- SDK: PyPI `daytona` 0.220.0 (Python 3.14 venv in the scratchpad, not the repo). The only config needed is `DaytonaConfig(api_key=...)`; API URL defaults to `https://app.daytona.io/api` and the target region resolved to `us`. The SDK reads the API URL only from the process environment, never from `.env`, so we pass the key explicitly.
- Instance: `pycqa__docformatter-254` (usable, no fallback needed). Image `docker.io/swerebenchv2/pycqa-docformatter:254-5c9744e` (linux/amd64, 757 MB compressed on Docker Hub). Row JSON saved at `/private/tmp/claude-501/-Users-sunzeyu-Documents-nebius-hackathon/2d122625-9fb9-48b6-8d67-da6bf5e59de9/scratchpad/row.json`. FAIL_TO_PASS is one test (`...test_format_docstring_sphinx_style_recognize_yield[args0]`), PASS_TO_PASS has 9. The instance `test_cmd` already contains `-rA`.
- Probe: `/Users/sunzeyu/Documents/nebius-hackathon/spikes/daytona_probe.py` (throwaway, staged: `1 2 3 4 5 6 7 vm 8`, state kept in the scratchpad). Several extra checks (5b, 6g, 6h, 7b, 9, 10) were run as inline snippets against the same helpers; their evidence is in the ledger below.

## Ledger

| Step | Status | Time | Evidence |
|---|---|---|---|
| 1 Create from image | CHECKED | 41.9 s cold | `daytona.create(CreateSandboxFromImageParams(image=...))` took the public Docker Hub image directly, no snapshot step by us. `uname -m` = `x86_64`, Python 3.10.19, user `root` (the image's user, not Daytona's `daytona`), repo at `/docformatter`, `git status` = "Not currently on any branch. nothing to commit, working tree clean", HEAD `5c9744e98098dd9a092b591b196df7e133d51117`. Same image again with different resources: 7.2 s; identical request a third time: 0.9 s. |
| 2 Test patch and failing tests | CHECKED | apply 0.11 s, pytest 0.44 s | `fs.upload_file` of test_patch then `git apply` exit 0 (two test files modified). Instance test_cmd on the whole file: `1 failed, 9 passed in 0.05s`, exit 1. F2P node id alone: `1 failed in 0.02s`, exit 1. Needed no venv activation: `pytest` is on PATH. |
| 3 Snapshot from sandbox | CHECKED | 62.3 s | `sandbox.create_snapshot(name, timeout=900)` works on a running container sandbox (no stop needed). Snapshot id `2a6b6039-50e1-451d-9f66-fee5c5ed1b97`, state ACTIVE, 1.99 GB, ref `cr.app.daytona.io/sbox/daytona-212711d5...fc152ac:daytona` (content-addressed registry ref), `source_sandbox_id` recorded. Immutable in practice: there is no update call on `daytona.snapshot` (only activate, create, delete, get, list), the ref and id were unchanged after use, and a branch created after another branch was edited came up clean. Only `updated_at` moves, because `last_used_at` is touched on first use. The snapshot survives deletion of its source sandbox. Uncommitted working tree state (applied test patch, an untracked marker file) was captured. |
| 4 Fork into two branches | CHECKED (via snapshot), native fork FAILED | branch create 1.3 s (B), 1.7 s (witness) | `sandbox.fork()` on a container sandbox: `DaytonaUnprocessableEntityError: Failed to fork sandbox: Forking is not supported for this sandbox`. Fork is VM-class only (see step 7 and the VM line below). Snapshot route: A and B both from the snapshot. A got `a.txt` and an appended line in `src/docformatter/syntax.py`; B got `b.txt`. A had no `b.txt`; B had no `a.txt` and an unmodified `syntax.py`; the origin sandbox had neither file and an unmodified source file. Both branches kept the checkpoint marker and the applied test patch. Branch A's own create time was not measured (it came from a parallel attempt, see failures). |
| 5 Tree download | CHECKED | 1.06 s (0.18 s list, 0.88 s download) | No archive endpoint exists. `sandbox.fs.list_files(repo, depth=64)` returns the whole tree in one call (132 entries), then `sandbox.fs.download_files([FileDownloadRequest(source, destination)])` in batches of 500; 106 files, 1.6 MB, 0 errors, nothing executed in the sandbox. Modes: downloaded files are written locally as 0644 regardless; the real mode is only in the `list_files` metadata (`mode` string and `permissions` octal, e.g. `-rwxr-xr-x`/`0755`, `-rw-------`/`0600`), so exec bits must be re-applied from metadata. Symlinks do NOT survive: a file symlink is downloaded as a regular file with the target's content (even `abs_link -> /etc/hostname`), its metadata shows the target's mode, a dangling link is omitted, and a directory symlink (`loop -> .`, `usrlink -> /usr`) is listed as a directory with mode 0777 but not recursed into (no loop explosion, 0.19 s). |
| 6 Timeouts | CHECKED | 5.28 s for `sleep 30` with `timeout=5` | `process.exec("sleep 30; echo finished", timeout=5)` raises `DaytonaProcessExecutionTimeoutError: Failed to execute command: command execution timeout`; no exit code and no partial output come back. The process does not keep running: `ps` right after, 2 s later and 30 s later showed only the container's own `sleep infinity` (pid 108). A command that spawns children (`bash -c 'sleep 60 & sleep 60; wait'`, timeout 3) also left nothing behind. Omitting `timeout` entirely did not impose a 10 s cap (a `sleep 12` finished, exit 0), so always pass it. A 500 kB stdout plus stderr came back whole (500,010 chars, no 65,535 truncation) with stderr merged into `result`. Separate stdout and stderr, and partial output of a running command, are available only through the session API: `create_session`, `execute_session_command(..., run_async=True)`, `get_session_command_logs` returned `stdout` and `stderr` separately after 3 s while the command was still running. |
| 7 Limits and cost | CHECKED (docs and error text), tier itself UNVERIFIED | n/a | See the section below. Org usage overview call returned 403 `Access denied`, so the tier could not be read from the API. |
| 8 Clean up | CHECKED for sandboxes, BLOCKED for the snapshot | n/a | All 8 sandboxes created are gone (`daytona.list()` returned `[]`, confirmed twice). Snapshot `spike-ckpt-docformatter-254` is still there: `daytona.snapshot.delete(...)` and the deactivate call both returned 403 `Access denied` (the key lacks the `delete:snapshots` scope, per the API key docs). Someone with dashboard access must delete it at https://app.daytona.io/dashboard/snapshots; Daytona also deactivates unused snapshots after 2 weeks. |
| Extra: 9 witness from checkpoint | CHECKED | 2.6 s | New sandbox from the snapshot after the origin sandbox was deleted; uploaded the instance gold `patch`, `git apply --index` exit 0, test_cmd `10 passed in 0.05s`, exit 0. This is the witness and re-verify flow. |
| Extra: Linux VM class (native fork) | UNVERIFIED, blocked | n/a | `daytona.snapshot.create(CreateSnapshotParams(name=..., image=IMAGE, sandbox_class=SandboxClass.LINUX_VM))` returned `DaytonaForbiddenError: Failed to create snapshot: Access denied`. Creating from the shared `daytona-vm-small` snapshot returned `DaytonaBadRequestError: Failed to create sandbox: Snapshot daytona-vm-small is not available in region us`. Native `fork()` (memory plus filesystem) therefore could not be tried. Docs say it is VM-only and VM snapshots cannot come from declarative builds. |
| Not tested | UNVERIFIED | n/a | The `AsyncDaytona` client (the probe used the sync client; the async class exists with the same surface). Outbound network from inside a sandbox (git clone, pip) under Tier 1 network restrictions; V2 images did not need it. Commands longer than 10 minutes. Snapshot storage price (not on the pricing page). |

## Failures with exact error text

- Third parallel sandbox from the snapshot (4 GiB each, two already running): `DaytonaBadRequestError: Failed to create sandbox: Total memory limit exceeded. Maximum allowed: 10GiB.` followed by `To increase concurrency limits, upgrade your organization's Tier by visiting https://app.daytona.io/dashboard/limits.` The sibling creates in that parallel batch did succeed, which leaked one sandbox until the label sweep found it; always label sandboxes and register each id as it is created.
- `sandbox.fork()` on a container: `DaytonaUnprocessableEntityError: Failed to fork sandbox: Forking is not supported for this sandbox`.
- Org usage overview: `ForbiddenException: (403) ... {"statusCode":403,"error":"Forbidden","message":"Access denied"}`.
- LINUX_VM snapshot: `DaytonaForbiddenError: Failed to create snapshot: Access denied`.
- Snapshot delete and deactivate: `DaytonaForbiddenError: Failed to delete snapshot: Access denied` and a 403 `Access denied` on `/api/snapshots/{id}/deactivate`.
- Two assertions in my probe (4c, 4f) printed FAILED because of a wrong string match (`'a.txt': No such file` versus `a.txt: No such`); the printed outputs show isolation held, the probe was fixed and the re-evaluation is recorded.

## SDK calls that worked

```python
from daytona import (Daytona, DaytonaConfig, CreateSandboxFromImageParams,
                     CreateSandboxFromSnapshotParams, Resources, FileDownloadRequest)
d = Daytona(DaytonaConfig(api_key=KEY))

sb = d.create(CreateSandboxFromImageParams(image="swerebenchv2/pycqa-docformatter:254-5c9744e",
        resources=Resources(cpu=2, memory=4, disk=10), labels={"run": rid},
        auto_stop_interval=60, ttl_minutes=150), timeout=900)          # 42 s cold
r = sb.process.exec("pytest ...", cwd="/docformatter", timeout=600)    # r.exit_code, r.result (stdout+stderr merged)
sb.fs.upload_file(patch_bytes, "/tmp/p.diff")                          # also str path
data = sb.fs.download_file("/docformatter/report.xml")                 # bytes
sb.create_snapshot("ckpt-name", timeout=900)                           # on a running container, 62 s
snap = d.snapshot.get("ckpt-name")                                     # .id, .ref, .state, .size
b = d.create(CreateSandboxFromSnapshotParams(snapshot="ckpt-name", labels={...}), timeout=300)  # ~1.5 s
ents = sb.fs.list_files("/docformatter", depth=64)                     # .path .is_dir .mode .permissions .size
sb.fs.download_files([FileDownloadRequest(source=e.path, destination=local)], timeout=1800)
sb.delete(timeout=120)
```

## Limits and cost

- Per-sandbox defaults (observed on a default `create()`): 1 vCPU, 1 GiB RAM, 3 GiB disk, `auto_stop_interval=15` min, `auto_archive_interval=10080` min (7 days), `auto_delete_interval=-1` (off). Per-sandbox maximum per docs: 4 vCPU, 8 GiB, 10 GiB disk. `create_snapshot` inherits the source sandbox's resources, and snapshot-based creates cannot override them, so size the origin sandbox for what every branch needs. I used 2/4/10 for the spike; 2 vCPU, 2 GiB, 5 GiB would be enough for this image (1.99 GB snapshot).
- Concurrency for our key: the create error says total memory is capped at 10 GiB, which matches Tier 1 in the limits docs (10 vCPU, 10 GiB, 30 GiB disk; the docs' own two tables disagree on RAM, 10 versus 20). The response headers, oddly, reported `X-RateLimit-Limit-sandbox-create: 600` and `X-RateLimit-Limit-authenticated: 50000`, which are the Tier 4 values, so rate limits are not the constraint. At Tier 1 that is 2 sandboxes at 2 vCPU/4 GiB, or 5 at 2 vCPU/2 GiB (10 vCPU, 10 GiB, 25 GiB disk), so about 2 tasks at once with an agent and a witness each. Stopped container sandboxes still hold disk quota until deleted or archived. Tier 2 (100 vCPU, 200 GiB RAM, 300 GiB disk) needs a linked card and a $25 top-up; that is a decision for Zeyu.
- Auto-stop: containers stop after 15 min of inactivity by default and keep their filesystem; archive after 7 stopped days. For an executor, pass an explicit `auto_stop_interval` longer than any single operation, set `ttl_minutes` as a wall-clock safety net, and delete explicitly.
- Price (daytona.io/pricing, verified in the page source): vCPU $0.0504/h, RAM $0.0162 per GiB-h, disk $0.000108 per GiB-h after the first 5 GiB; billed per second; $200 free compute for new accounts. Snapshot storage price is not published there (UNVERIFIED).

| Config | $ per sandbox-hour | 50 tasks x 3 sandboxes x 20 min = 50 h | Realistic: agent 20 min + witness 3 + re-verify 3 = 26 min, 21.7 h |
|---|---|---|---|
| 2 vCPU, 2 GiB, 5 GiB | $0.1332 | $6.66 | $2.89 |
| 2 vCPU, 4 GiB, 10 GiB | $0.1661 | $8.31 | $3.60 |

## How DaytonaExecutor should map our protocol

Use `AsyncDaytona` (same surface; async path not exercised here). Label every sandbox and snapshot with the run id.
1. prepare(ImageSource): `create(CreateSandboxFromImageParams(image, resources=Resources(2,2,5), ttl_minutes=...))`, run `setup`, make the snapshot commit receipt as today. RepoAtCommit needs outbound git and pip, unverified on Tier 1.
2. run: `process.exec(cmd, cwd, timeout=timeout_s)`, always explicit. Catch `DaytonaProcessExecutionTimeoutError` and build a timed-out receipt; it carries no output, so for long commands redirect to a file (or use the session API) to keep a tail. Output is stdout and stderr merged.
3. run_pytest: upload the bootstrap and run it as today; take the verdict from the junit file via `fs.download_file`, never from the merged stdout. Inside an agent branch everything is root-controlled, so verdicts come only from the witness branch.
4. checkpoint: `create_snapshot(name)` on the running prepared branch (about 62 s once per task); `Checkpoint.id` = snapshot `ref`. Re-read `snapshot.get(name).ref` before each fork as the tamper check (no update API exists).
5. fork(checkpoint, n): n times `create(CreateSandboxFromSnapshotParams(snapshot=name))`, about 1.5 s each; `sandbox.fork()` is rejected on containers.
6. read_file, write_file: `fs.download_file` (truncate to max_bytes locally) and `fs.upload_file(bytes, path)`; the executor synthesizes the receipt.
7. patch: no exec. `list_files(depth=64)` plus batched `download_files` into a local staging dir (about 1 s), re-apply exec bits from `permissions`, then reuse `staging.py` for `git add -A` and `git diff --cached --binary`. Symlinks arrive as regular files or empty dirs, so the symlink drop rule cannot be seen from the download; a regular file cannot create a symlink on the witness, so this is safe but the dropped-path list loses that entry.
8. apply_patch: `fs.upload_file(patch, "/tmp/x.diff")` then `exec("git apply --index ...")` on the witness branch.
9. close: delete the sandboxes (and snapshots, once the key has `delete:snapshots`); sweep by label.
10. image_before and image_after: no image per command, so follow the local executor and use provenance ids, `f"{root}#{seq}"` where root is the snapshot `ref` for forked branches or the sandbox id before the first checkpoint; content hashes exist only at the checkpoint (snapshot ref) and at patch time (hash of the downloaded tree).
