"""A small web service that lets judges run Receipts live on preset tasks, under a spending cap.

Each preset replays the inputs of a task from the 100-task experiment (image, issue, failing
tests, suite) through `receipts.orchestrate.fix` on Token Factory Sandboxes. Spend is kept in a
ledger outside the container; when the ledger cannot be read, or the next run could pass the
cap, the page offers the recorded run of the same task instead.

It is deployed on Cloud Run with request-based billing, where an instance has CPU only while a
request is open. So a run lives inside the POST that started it: the response streams the run's
steps until the verdict, and closing the page stops the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import os
import signal
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

from receipts.orchestrate import ProgressEvent

SITE_URL = "https://zeyusuntt.github.io/receipts"
_AGENT = "Nemotron 3 Super on Token Factory"
_GATE = "the gate (Python)"


def describe_event(event: ProgressEvent) -> dict[str, Any]:
    """A progress event as the page shows it, with who did the step."""
    if event.kind in {"agent_tool", "agent_finish"}:
        who = _AGENT
    elif event.kind in {"baseline", "checkpoint"}:
        who = "Token Factory Sandbox"
    elif event.kind == "witness":
        who = "Token Factory Sandbox (witness)"
    elif event.kind == "check" and str(event.check_id or "").startswith("R8"):
        who = "Nemotron 3 Super review (advisory)"
    else:
        who = _GATE
    return {
        "kind": event.kind, "who": who, "message": event.message, "attempt": event.attempt,
        "passed": event.passed, "check": event.check_id, "exit_code": event.exit_code,
        "duration_s": event.duration_s,
    }


@dataclass(frozen=True)
class Preset:
    id: str
    title: str
    source: dict[str, Any]
    issue: str
    spec_tests: list[str]
    suite_scope: str
    spec_paths: list[str] | None
    recorded: dict[str, Any]


def load_presets(repo_root: Path, pilot_dir: Path, ids: Sequence[str]) -> list[Preset]:
    """Read each task's recorded inputs and outcome from the experiment's records."""
    presets = []
    for iid in ids:
        record = json.loads((pilot_dir / iid / "record.json").read_text(encoding="utf-8"))
        run_dir = Path(record["run_dir"])
        run_dir = run_dir if run_dir.is_absolute() else repo_root / run_dir
        inp = json.loads((run_dir / "input.json").read_text(encoding="utf-8"))
        attempts = record.get("attempts") or [{}]
        final = record.get("final") or {}
        issue_title = str(inp.get("issue", "")).split("\n", 1)[0].strip()
        repo = iid.rsplit("-", 1)[0].replace("__", "/")
        verified = final.get("verified_fix") is True
        presets.append(Preset(
            id=iid,
            title=f"{repo}: {issue_title}" if issue_title else repo,
            source=inp["source"],
            issue=inp["issue"],
            spec_tests=list(inp["spec_tests"]),
            suite_scope=inp["suite_scope"],
            spec_paths=inp.get("spec_paths"),
            recorded={
                "outcome": ("VERIFIED on appeal" if len(attempts) > 1 else "VERIFIED") if verified else "REJECTED",
                "receipts_dollars": (record.get("cost") or {}).get("model_dollars"),
                "wall_s": record.get("wall_time_s"),
                "unguarded_claimed_done": attempts[0].get("claimed_done"),
                "unguarded_official": attempts[0].get("official_resolved"),
                "run_url": f"{SITE_URL}/run/{iid}.html",
                "receipt_url": f"{SITE_URL}/receipt/{iid}.html",
            },
        ))
    return presets


class Ledger(Protocol):
    def entries(self) -> list[dict[str, Any]]: ...
    def append(self, entry: dict[str, Any]) -> None: ...


class FileLedger:
    """One JSON line per finished run."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def append(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")


def metadata_token() -> str:
    """An access token for the service account the Cloud Run service runs as."""
    request = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())["access_token"]


class BucketLedger:
    """The same JSON lines, kept in one Cloud Storage object so they survive restarts.

    The service runs as one instance, so it reads the object once and then writes it through.
    Each write names the generation it read, so a write made elsewhere is read again, not lost.
    """

    def __init__(self, bucket: str, name: str = "ledger.jsonl", *, api: str = "https://storage.googleapis.com",
                 token: Callable[[], str] = metadata_token):
        self.bucket, self.name, self.api, self.token = bucket, name, api.rstrip("/"), token
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] | None = None
        self._generation = 0  # 0 tells Cloud Storage the object must not exist yet

    def _open(self, url: str, data: bytes | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token()}"}
        if data is not None:
            headers["Content-Type"] = "application/x-ndjson"
        request = urllib.request.Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
        return urllib.request.urlopen(request, timeout=20)

    def _load(self) -> None:
        url = (f"{self.api}/storage/v1/b/{urllib.parse.quote(self.bucket)}/o/"
               f"{urllib.parse.quote(self.name, safe='')}?alt=media")
        try:
            with self._open(url) as response:
                body, generation = response.read().decode("utf-8"), int(response.headers["x-goog-generation"])
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise OSError(f"ledger read failed ({error.code})") from None
            body, generation = "", 0
        self._entries = [json.loads(line) for line in body.splitlines() if line.strip()]
        self._generation = generation

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._entries is None:
                self._load()
            return list(self._entries or [])

    def append(self, entry: dict[str, Any]) -> None:
        with self._lock:
            for _ in range(3):
                if self._entries is None:
                    self._load()
                entries = [*(self._entries or []), entry]
                data = "".join(json.dumps(item, sort_keys=True) + "\n" for item in entries).encode("utf-8")
                query = urllib.parse.urlencode({"uploadType": "media", "name": self.name,
                                                "ifGenerationMatch": self._generation})
                try:
                    with self._open(f"{self.api}/upload/storage/v1/b/{urllib.parse.quote(self.bucket)}/o?{query}",
                                    data) as response:
                        self._generation = int(json.loads(response.read())["generation"])
                except urllib.error.HTTPError as error:
                    if error.code != 412:
                        raise OSError(f"ledger write failed ({error.code})") from None
                    self._entries = None  # written elsewhere since it was read: read it again
                    continue
                self._entries = entries
                return
            raise OSError("ledger write failed (it kept changing)")


class UnavailableLedger:
    """Used when no durable ledger is configured: live runs stay off, so the cap cannot reset on a restart."""

    def entries(self) -> list[dict[str, Any]]:
        raise OSError("no durable ledger configured")

    def append(self, entry: dict[str, Any]) -> None:
        raise OSError("no durable ledger configured")


def configured_ledger() -> Ledger:
    bucket = os.environ.get("LEDGER_BUCKET")
    return BucketLedger(bucket) if bucket else UnavailableLedger()


@dataclass
class Limits:
    cap_dollars: float = 15.0
    # Charged for a run that is stopped or fails before it reports its cost, and held back for every
    # queued or running job, so the cap holds even if every run in flight costs this much.
    reserve_dollars: float = 1.0
    # Judges share one code, so the per-code limit is close to the daily one; the cap is the hard stop.
    per_code_per_day: int = 10
    global_per_day: int = 20
    max_queue: int = 4


class Refused(Exception):
    def __init__(self, reason: str, message: str, recorded_url: str | None = None):
        super().__init__(message)
        self.reason, self.message, self.recorded_url = reason, message, recorded_url


@dataclass
class Job:
    id: str
    preset: Preset
    code: str
    state: str = "queued"
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    created: float = 0.0
    started: float | None = None
    finished: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


Runner = Callable[[Preset, Callable[[dict[str, Any]], None], threading.Event], dict[str, Any]]


class LiveService:
    def __init__(self, presets: Sequence[Preset], ledger: Ledger, limits: Limits, runner: Runner, *,
                 codes: Sequence[str], clock: Callable[[], float] = time.time, secrets: Sequence[str] = ()):
        self.presets = {preset.id: preset for preset in presets}
        self.ledger, self.limits, self.runner, self.clock = ledger, limits, runner, clock
        self.codes = [code for code in codes if code]
        # Provider errors can end up in step messages and receipts; the page never shows these values.
        self.secrets = sorted({value for value in [*secrets, *self.codes] if len(value) >= 6}, key=len, reverse=True)
        self.jobs: dict[str, Job] = {}
        self.queue: deque[Job] = deque()
        self.running: Job | None = None
        self._lock = threading.Condition()
        self._closed = False
        self._charge_failed = False  # a run that could not be charged keeps live runs off until a restart
        self._worker: threading.Thread | None = None

    @staticmethod
    def code_hash(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()[:12]

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[redacted]")
            return value
        if isinstance(value, dict):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    def _valid(self, code: str) -> bool:
        return any(hmac.compare_digest(code.encode("utf-8"), known.encode("utf-8")) for known in self.codes)

    def _day(self, timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()

    def _spent(self, entries: list[dict[str, Any]]) -> float:
        return sum(float(entry.get("dollars") or 0) for entry in entries)

    def _entries(self) -> list[dict[str, Any]]:
        if self._charge_failed:
            raise OSError("a run could not be charged")
        return self.ledger.entries()

    def health(self) -> dict[str, Any]:
        try:
            entries = self._entries()
        except Exception:
            return {"ok": True, "live": False, "reason": "ledger unavailable", "queue": len(self.queue)}
        spent = self._spent(entries)
        with self._lock:
            in_flight = len(self.queue) + (self.running is not None)
        live = spent + self.limits.reserve_dollars * (in_flight + 1) <= self.limits.cap_dollars
        return {"ok": True, "live": live, "spent_dollars": round(spent, 4), "cap_dollars": self.limits.cap_dollars,
                "queue": in_flight}

    def submit(self, code: str, preset_id: str) -> Job:
        if not self._valid(code):
            raise Refused("code", "That judge code is not valid.")
        preset = self.presets.get(preset_id)
        if preset is None:
            raise Refused("preset", "Pick one of the listed tasks.")
        recorded = preset.recorded["run_url"]
        try:
            entries = self._entries()
        except Exception:
            raise Refused("ledger", "Live runs are paused; here is the recorded run of this task.", recorded) from None
        now = self.clock()
        today = self._day(now)
        with self._lock:
            pending = list(self.queue) + ([self.running] if self.running else [])
            if self._spent(entries) + self.limits.reserve_dollars * (len(pending) + 1) > self.limits.cap_dollars:
                raise Refused("cap", "The spending cap for live runs is reached; here is the recorded run.", recorded)
            mine = self.code_hash(code)
            todays = [entry for entry in entries if self._day(float(entry.get("started") or 0)) == today]
            if sum(entry.get("code") == mine for entry in todays) + sum(job.code == mine for job in pending) \
                    >= self.limits.per_code_per_day:
                raise Refused("code limit", "This judge code has used today's live runs.", recorded)
            if len(todays) + len(pending) >= self.limits.global_per_day:
                raise Refused("daily limit", "Today's live runs are used up.", recorded)
            if len(self.queue) >= self.limits.max_queue:
                raise Refused("queue full", "The queue is full; try again in a few minutes.", recorded)
            job = Job(id=uuid.uuid4().hex[:12], preset=preset, code=mine, created=now)
            self.jobs[job.id] = job
            self.queue.append(job)
            self._lock.notify_all()
        return job

    def stop(self, job_id: str, code: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None or not self._valid(code) or job.code != self.code_hash(code):
            return False
        return self.cancel(job_id)

    def cancel(self, job_id: str) -> bool:
        """Stop a run whoever asks: used when the page that started it has gone."""
        job = self.jobs.get(job_id)
        if job is None:
            return False
        with self._lock:
            if job in self.queue:
                self.queue.remove(job)
                job.state, job.finished = "stopped", self.clock()
                return True
        job.cancel.set()
        return job.state == "running"

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        with self._lock:
            queued = list(self.queue)
            position = 0 if job is self.running else queued.index(job) + 1 if job in queued else None
        return {"id": job.id, "preset": job.preset.id, "title": job.preset.title, "state": job.state,
                "position": position, "events": list(job.events), "result": job.result, "error": job.error,
                "recorded": job.preset.recorded}

    def start(self) -> None:
        self._worker = threading.Thread(target=self._work, name="receipts-live", daemon=True)
        self._worker.start()

    def close(self, wait_s: float = 0.0) -> None:
        """Stop taking runs and stop the one in progress, waiting up to wait_s for it to be charged."""
        with self._lock:
            self._closed = True
            self._lock.notify_all()
        if self.running is not None:
            self.running.cancel.set()
        if wait_s and self._worker is not None:
            self._worker.join(wait_s)

    def _work(self) -> None:
        while True:
            with self._lock:
                while not self.queue and not self._closed:
                    self._lock.wait()
                if self._closed:
                    return
                job = self.queue.popleft()
                self.running, job.state, job.started = job, "running", self.clock()
            dollars, result, error = self.limits.reserve_dollars, None, None
            try:
                result = self._redact(self.runner(job.preset, lambda event: job.events.append(self._redact(event)),
                                                  job.cancel))
                if result.get("dollars") is not None:
                    dollars = float(result["dollars"])
                state = "done"
            except InterruptedError:
                state = "stopped"
            except Exception as failure:  # the page shows the kind of failure, never its text
                state, error = "failed", f"The run failed ({type(failure).__name__})."
                # The text goes to the service log, which only the project's owners can read.
                print(self._redact(f"run {job.id} ({job.preset.id}) failed:\n{traceback.format_exc()}"),
                      file=sys.stderr, flush=True)
            finished = self.clock()
            # Charge the run before anyone can see it finished, so the cap never lags the page.
            try:
                self.ledger.append({"job": job.id, "preset": job.preset.id, "code": job.code,
                                    "dollars": round(dollars, 6), "state": state, "started": job.started,
                                    "finished": finished})
            except Exception:
                self._charge_failed = True
            finally:
                with self._lock:
                    job.result, job.error, job.finished, job.state = result, error, finished, state
                    self.running = None


def tokenfactory_runner(out_root: Path) -> Runner:
    """Run a preset through `receipts.orchestrate.fix` on Token Factory, with the advisory review."""

    def run(preset: Preset, emit: Callable[[dict[str, Any]], None], cancelled: threading.Event) -> dict[str, Any]:
        return asyncio.run(_run_preset(preset, emit, cancelled, out_root))

    return run


async def _run_preset(preset: Preset, emit: Callable[[dict[str, Any]], None], cancelled: threading.Event,
                      out_root: Path) -> dict[str, Any]:
    from receipts.agent.worker import WorkerBudget
    from receipts.cli import _BorrowedTokenFactorySandboxApi
    from receipts.cost import CostMeter
    from receipts.llm import TokenFactoryClient, load_config
    from receipts.orchestrate import RunBudgets, fix
    from receipts.receipt_text import render
    from receipts.sandbox.busybox import load_busybox
    from receipts.sandbox.protocol import ImageSource
    from receipts.sandbox.sink import RunSink
    from receipts.sandbox.tokenfactory import TokenFactoryExecutor
    from receipts.sandbox.tokenfactory_api import TokenFactorySandboxApi
    from receipts.verify.review import REVIEWER_SETTINGS

    run_id = f"live-{uuid.uuid4().hex[:12]}"
    out = out_root / run_id
    # The host's secrets arrive as environment variables; a .env file, if any, wins as in the CLI.
    config = load_config()
    model = TokenFactoryClient(config)
    reviewer = TokenFactoryClient(config.model_copy(update=REVIEWER_SETTINGS), meter=CostMeter())
    # Tighter than the CLI's defaults so one run cannot cost more than about a dollar.
    budgets = RunBudgets(baseline_limit_s=600, verification_timeout_s=600,
                         worker=WorkerBudget(max_turns=30, max_wall_seconds=600, max_completion_tokens=32_000,
                                             prompt_token_budget=100_000))
    api = TokenFactorySandboxApi.from_env()
    try:
        with tempfile.TemporaryDirectory(prefix="receipts-live-") as root:
            executor = TokenFactoryExecutor(Path(root), RunSink(out), run_id, api, busybox=load_busybox())
            if getattr(executor, "api", None) is api:
                executor.api = _BorrowedTokenFactorySandboxApi(api)
            task = asyncio.ensure_future(fix(
                executor, model, ImageSource.model_validate(preset.source), preset.issue, preset.spec_tests,
                preset.suite_scope, out, appeals=1, budgets=budgets, spec_paths=preset.spec_paths,
                progress=lambda event: emit(describe_event(event)), review="advisory", reviewer=reviewer,
            ))
            try:
                while not task.done():
                    if cancelled.is_set():
                        task.cancel()
                        raise InterruptedError("stopped by the judge")
                    await asyncio.sleep(0.5)
                result = task.result()
            finally:
                await executor.close()
    finally:
        await api.aclose()
    status = result.final_verdict.status
    return {"verdict": {"PASS": "VERIFIED", "REJECTED": "REJECTED"}.get(status, "ERROR"),
            "dollars": result.cost.get("estimated_dollars"), "wall_s": result.wall_time_s,
            "attempts": len(result.attempts), "receipt": render(result)}


_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Run Receipts live</title><meta name="referrer" content="no-referrer">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Red+Hat+Mono:wght@400;600&amp;family=Red+Hat+Text:wght@400;700&amp;display=swap">
<style>
:root{--ink:#1d2124;--muted:#565d63;--rule:#d5d8d4;--panel:#f3f4f2;--link:#1f4f7a;--ok:#0d6831;--bad:#b42318}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font:15px/1.5 'Red Hat Text',system-ui,sans-serif}
main{max-width:1000px;margin:auto;padding:20px 16px 48px;display:flex;flex-direction:column;gap:18px}
h1{font-size:22px;margin:0}h2{font-size:16px;margin:0}p{margin:0;max-width:75ch}a{color:var(--link)}
label{display:block;font-weight:700;margin-bottom:4px}input,select,button{font:inherit;padding:6px 10px;border:1px solid var(--rule);background:#fff}
button{border-color:var(--ink);cursor:pointer}button:disabled{opacity:.5;cursor:default}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
.muted{color:var(--muted)}table{width:100%;border-collapse:collapse;font:12.5px/1.5 'Red Hat Mono',monospace}td{padding:2px 8px;vertical-align:top;border-bottom:1px solid var(--panel)}
td:first-child{color:var(--muted);white-space:nowrap}.ok{color:var(--ok)}.bad{color:var(--bad)}pre{background:var(--panel);padding:10px;overflow:auto;font:12px/1.5 'Red Hat Mono',monospace}
.box{border:1px solid var(--rule);padding:12px}
/* On a phone the longest task title and the longest words in a step must not widen the page. */
.row>div{min-width:0;max-width:100%}select{max-width:100%}td:nth-child(2){overflow-wrap:anywhere}
@media (max-width:480px){td:first-child{white-space:normal}}
</style></head><body><main>
<h1>Run Receipts live on a preset task</h1>
<p>Nemotron 3 Super writes a fix on Nebius Token Factory; a Token Factory Sandbox forked from before the agent started runs the tests again; the gate, plain Python, decides. Each run takes one to five minutes. Live runs can come out differently from the recording. Keep this page open until the run finishes: closing it stops the run.</p>
<div class="box"><div class="row">
<div><label for="code">Judge code</label><input id="code" autocomplete="off" size="18" aria-describedby="code-hint"></div>
<div><label for="preset">Task</label><select id="preset">__OPTIONS__</select></div>
<button id="run">Run</button><button id="stop" disabled>Stop</button></div>
<p id="code-hint" class="muted" style="margin-top:8px">The code is in the testing notes attached to the Devpost submission. Without a code, the recorded runs are at <a href="__SITE__/">__SITE_NAME__</a>.</p>
<p id="status" class="muted" style="margin-top:8px">__STATUS__</p></div>
<div id="out" class="box" hidden><h2 id="title"></h2><table><tbody id="events"></tbody></table><div id="result"></div></div>
</main><script>
const $=id=>document.getElementById(id);let job=null,ended=false;
// A link with ?code= fills the box; the code stays in the address so a reload keeps it.
const given=new URLSearchParams(location.search).get('code');if(given)$('code').value=given;
function text(el,s){el.textContent=s;return el}
function row(cells,cls){const tr=document.createElement('tr');cells.forEach((c,i)=>{const td=text(document.createElement('td'),c);if(i==2&&cls)td.className=cls;tr.appendChild(td)});return tr}
function idle(){$('run').disabled=false;$('stop').disabled=true}
function show(j){if(j.id){job=j.id;text($('title'),j.title);$('events').replaceChildren();$('result').replaceChildren()}
 j.events.forEach(e=>$('events').appendChild(row([e.who,e.message,e.passed===true?'pass':e.passed===false?'fail':(e.exit_code==null?'':'exit '+e.exit_code)],e.passed===false?'bad':e.passed?'ok':'')));
 if(j.state=='queued')text($('status'),j.position>1?'Queued: '+(j.position-1)+' run(s) ahead of yours.':'Starting next.');
 else if(j.state=='running')text($('status'),'Running. Each step is listed with who did it.');
 else if(j.recorded){ended=true;idle();const res=$('result');const rec=j.recorded;const p=document.createElement('p');
  if(j.state=='done'){const r=j.result;text(p,'Verdict: '+r.verdict+' in '+Math.round(r.wall_s)+' s, $'+(r.dollars==null?'?':r.dollars.toFixed(3))+' of Nemotron tokens. Recorded on Oct 3: the unguarded agent '+(rec.unguarded_claimed_done?'said done':'did not say done')+' and SWE-rebench\'s grader marked that '+(rec.unguarded_official?'resolved':'not resolved')+'; Receipts ended '+rec.outcome+' for $'+(rec.receipts_dollars||0).toFixed(3)+'.');
   const pre=text(document.createElement('pre'),r.receipt);res.append(p,pre)}
  else{text(p,(j.state=='stopped'?'Stopped.':j.error||'The run did not finish.')+' ');res.append(p)}
  const a=text(document.createElement('a'),'The recorded run of this task');a.href=rec.run_url;res.append(a);text($('status'),'Finished: '+j.state+'.')}}
async function follow(r){const reader=r.body.getReader(),dec=new TextDecoder();let buf='';
 try{for(;;){const {value,done}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});let i;
  while((i=buf.indexOf('\n'))>=0){const line=buf.slice(0,i);buf=buf.slice(i+1);if(line.trim())show(JSON.parse(line))}}}catch(e){}
 if(!ended){idle();text($('status'),'The connection closed before the run finished, so the run was stopped.')}}
$('run').onclick=async()=>{$('run').disabled=true;ended=false;text($('status'),'Sending.');
 const r=await fetch('api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('code').value,preset:$('preset').value})});
 if(!r.ok){const j=await r.json();idle();text($('status'),j.message);if(j.recorded_url){const a=text(document.createElement('a'),' Recorded run');a.href=j.recorded_url;$('status').append(a)}return}
 $('out').hidden=false;$('stop').disabled=false;follow(r)};
$('stop').onclick=async()=>{if(job)await fetch('api/jobs/'+job+'/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('code').value})})};
</script></body></html>
"""


def render_page(service: LiveService) -> str:
    options = "".join(f'<option value="{html.escape(p.id, quote=True)}">{html.escape(p.title)}</option>'
                      for p in service.presets.values())
    health = service.health()
    status = ("Live runs are open." if health.get("live")
              else "Live runs are paused; every task links to its recorded run.")
    return (_PAGE.replace("__OPTIONS__", options).replace("__STATUS__", html.escape(status))
            .replace("__SITE_NAME__", html.escape(SITE_URL.removeprefix("https://")))
            .replace("__SITE__", html.escape(SITE_URL, quote=True)))


_FINISHED = {"done", "stopped", "failed"}


def make_server(service: LiveService, host: str, port: int, tick: float = 1.0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # no request logs: they would carry judge codes in bodies
            return

        def _send(self, status: int, body: Any, content_type: str = "application/json") -> None:
            data = (body if isinstance(body, str) else json.dumps(body)).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")  # a page address may carry ?code=
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _stream(self, job: Job) -> None:
            """One JSON line per tick with the steps since the last line, until the run finishes."""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            sent, first = 0, True
            try:
                while True:
                    view = service.snapshot(job.id) or {}
                    line = {"state": view["state"], "position": view["position"], "events": view["events"][sent:]}
                    sent = len(view["events"])
                    if first:
                        line.update(id=job.id, title=view["title"])
                    finished = view["state"] in _FINISHED
                    if finished:
                        line.update(result=view["result"], error=view["error"], recorded=view["recorded"])
                    self.wfile.write((json.dumps(line) + "\n").encode("utf-8"))
                    self.wfile.flush()
                    if finished:
                        return
                    first = False
                    time.sleep(tick)
            except OSError:  # the page that started the run has gone, and with it the run's CPU
                service.cancel(job.id)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 4096:
                return {}
            try:
                value = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return {}
            return value if isinstance(value, dict) else {}

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in {"/", "/index.html"}:
                self._send(200, render_page(service), "text/html")
            elif path == "/health":
                self._send(200, service.health())
            elif path.startswith("/api/jobs/"):
                view = service.snapshot(path.removeprefix("/api/jobs/"))
                self._send(200 if view else 404, view or {"reason": "job", "message": "No such run."})
            else:
                self._send(404, {"reason": "path", "message": "Not found."})

        def do_HEAD(self) -> None:  # link checkers ask with HEAD: the answer GET gives, without its body
            self.do_GET()

        def do_POST(self) -> None:
            path, body = self.path.split("?", 1)[0], self._body()
            if path == "/api/jobs":
                try:
                    job = service.submit(str(body.get("code", "")), str(body.get("preset", "")))
                except Refused as refused:
                    status = 403 if refused.reason == "code" else 429 if "limit" in refused.reason \
                        or refused.reason in {"cap", "queue full"} else 400 if refused.reason == "preset" else 503
                    self._send(status, {"reason": refused.reason, "message": refused.message,
                                        "recorded_url": refused.recorded_url})
                    return
                self._stream(job)
            elif path.startswith("/api/jobs/") and path.endswith("/stop"):
                job_id = path.removeprefix("/api/jobs/").removesuffix("/stop")
                stopped = service.stop(job_id, str(body.get("code", "")))
                self._send(200 if stopped else 403, {"stopped": stopped})
            else:
                self._send(404, {"reason": "path", "message": "Not found."})

    return ThreadingHTTPServer((host, port), Handler)


PRESET_IDS = (
    "pycqa__pyflakes-335",
    "3yourmind__django-migration-linter-258",
    "maas__python-libmaas-219",
    "planetlabs__planet-client-python-81",
    "rock-learning__pytransform3d-48",
)


def main() -> None:
    """Serve the live page. Configuration comes from the environment (the host's secrets)."""
    repo_root = Path(os.environ.get("RECEIPTS_REPO", ".")).resolve()
    presets = load_presets(repo_root, repo_root / "pilot" / "v2-P", PRESET_IDS)
    ledger = configured_ledger()
    limits = Limits(cap_dollars=float(os.environ.get("LIVE_CAP_DOLLARS", "15")))
    service = LiveService(presets, ledger, limits, tokenfactory_runner(Path(tempfile.mkdtemp(prefix="live-runs-"))),
                          codes=os.environ.get("JUDGE_CODES", "").split(","),
                          secrets=[os.environ.get(name, "") for name in ("OPENAI_API_KEY", "NEBIUS_AI_PROJECT")])
    service.start()
    server = make_server(service, "0.0.0.0", int(os.environ.get("PORT", "8080")))

    def shut_down(*_: Any) -> None:  # Cloud Run allows 10 seconds after SIGTERM
        service.close(wait_s=8)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shut_down)
    server.serve_forever()


if __name__ == "__main__":
    main()
