from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from receipts.live import (
    SITE_URL,
    BucketLedger,
    FileLedger,
    Limits,
    LiveService,
    Refused,
    describe_event,
    load_presets,
    make_server,
    render_page,
)
from receipts.orchestrate import ProgressEvent

FIXTURE = Path(__file__).parent / "fixtures" / "site"
TASK = "pypa__twine-1066"
CODE = "judge-code-1"
NOW = datetime(2026, 12, 3, 17, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    return root


def presets(repo):
    return load_presets(repo, repo / "pilot", [TASK])


class FakeRunner:
    """Emits two events, waits until released or cancelled, then reports a cost."""

    def __init__(self, dollars=0.04, verdict="VERIFIED", fail=None):
        self.release = threading.Event()
        self.started = threading.Event()
        self.dollars, self.verdict, self.fail = dollars, verdict, fail

    def __call__(self, preset, emit, cancelled):
        emit(describe_event(ProgressEvent(kind="agent_tool", message="read setup.py", action="read")))
        self.started.set()
        while not self.release.is_set():
            if cancelled.is_set():
                raise InterruptedError("stopped")
            time.sleep(0.01)
        if self.fail:
            raise RuntimeError(self.fail)
        emit(describe_event(ProgressEvent(kind="verdict", message="all checks pass", passed=True)))
        return {"verdict": self.verdict, "dollars": self.dollars, "wall_s": 61.0, "receipt": "# Receipt\n"}


def service(repo, tmp_path, runner=None, limits=None, entries=(), clock=lambda: NOW):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    for entry in entries:
        ledger.append(entry)
    return LiveService(presets(repo), ledger, limits or Limits(), runner or FakeRunner(), codes=[CODE], clock=clock)


def wait_for(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def test_presets_come_from_the_recorded_run(repo):
    [preset] = presets(repo)
    record = json.loads((repo / "pilot" / TASK / "record.json").read_text())
    inp = json.loads((repo / "runs" / TASK / "input.json").read_text())
    assert preset.id == TASK
    assert preset.source == inp["source"] and preset.issue == inp["issue"]
    assert preset.spec_tests == inp["spec_tests"] and preset.suite_scope == inp["suite_scope"]
    assert preset.recorded["receipts_dollars"] == pytest.approx(record["cost"]["model_dollars"])
    assert preset.recorded["unguarded_claimed_done"] == record["attempts"][0]["claimed_done"]
    assert preset.recorded["unguarded_official"] == record["attempts"][0]["official_resolved"]
    assert preset.recorded["run_url"].endswith(f"/run/{TASK}.html")
    assert preset.title.startswith("pypa/twine")


@pytest.mark.parametrize("code,preset,reason", [("wrong", TASK, "code"), (CODE, "nobody__nothing-1", "preset")])
def test_submit_refuses_a_wrong_code_or_preset(repo, tmp_path, code, preset, reason):
    with pytest.raises(Refused) as refused:
        service(repo, tmp_path).submit(code, preset)
    assert refused.value.reason == reason


def test_spending_cap_refuses_and_points_to_the_recording(repo, tmp_path):
    spent = [{"job": "old", "preset": TASK, "code": "x", "dollars": 14.5, "state": "done", "started": NOW - 86400 * 9}]
    live = service(repo, tmp_path, limits=Limits(cap_dollars=15.0, reserve_dollars=1.0), entries=spent)
    with pytest.raises(Refused) as refused:
        live.submit(CODE, TASK)
    assert refused.value.reason == "cap"
    assert refused.value.recorded_url.endswith(f"/run/{TASK}.html")
    assert live.health()["live"] is False and live.health()["spent_dollars"] == pytest.approx(14.5)


def test_daily_limits_per_code_and_overall_use_the_utc_day(repo, tmp_path):
    live = service(repo, tmp_path, limits=Limits(per_code_per_day=2, global_per_day=3))
    code_hash = live.code_hash(CODE)
    yesterday = {"job": "y", "preset": TASK, "code": code_hash, "dollars": 0.01, "state": "done", "started": NOW - 86400}
    today = {"job": "t", "preset": TASK, "code": code_hash, "dollars": 0.01, "state": "done", "started": NOW - 60}
    live.ledger.append(yesterday)
    live.ledger.append(today)
    live.ledger.append(dict(today, job="t2"))
    with pytest.raises(Refused) as refused:
        live.submit(CODE, TASK)
    assert refused.value.reason == "code limit"
    live.codes.append("judge-code-2")
    live.ledger.append(dict(today, job="t3", code="someone-else"))
    with pytest.raises(Refused) as refused:
        live.submit("judge-code-2", TASK)
    assert refused.value.reason == "daily limit"


def test_queue_positions_and_a_finished_run_is_charged_its_cost(repo, tmp_path):
    runner = FakeRunner(dollars=0.04)
    live = service(repo, tmp_path, runner=runner, limits=Limits(max_queue=1))
    live.start()
    first = live.submit(CODE, TASK)
    runner.started.wait(5)
    second = live.submit(CODE, TASK)
    assert live.snapshot(first.id)["position"] == 0 and live.snapshot(second.id)["position"] == 1
    with pytest.raises(Refused) as refused:
        live.submit(CODE, TASK)
    assert refused.value.reason == "queue full"
    runner.release.set()
    wait_for(lambda: live.snapshot(second.id)["state"] == "done")
    view = live.snapshot(first.id)
    assert view["state"] == "done" and view["result"]["verdict"] == "VERIFIED"
    assert [event["who"] for event in view["events"]] == ["Nemotron 3 Super on Token Factory", "the gate (Python)"]
    charged = [entry for entry in live.ledger.entries() if entry["job"] in {first.id, second.id}]
    assert [entry["dollars"] for entry in charged] == [0.04, 0.04]
    assert all(entry["code"] == live.code_hash(CODE) and CODE not in json.dumps(entry) for entry in charged)
    live.close()


def test_stop_cancels_the_run_and_charges_the_reserve(repo, tmp_path):
    runner = FakeRunner()
    live = service(repo, tmp_path, runner=runner, limits=Limits(reserve_dollars=0.5))
    live.start()
    job = live.submit(CODE, TASK)
    runner.started.wait(5)
    assert live.stop(job.id, "wrong") is False
    assert live.stop(job.id, CODE) is True
    wait_for(lambda: live.snapshot(job.id)["state"] == "stopped")
    [entry] = [entry for entry in live.ledger.entries() if entry["job"] == job.id]
    assert entry["dollars"] == 0.5 and entry["state"] == "stopped"
    live.close()


def test_a_failed_run_shows_a_generic_error_and_charges_the_reserve(repo, tmp_path):
    runner = FakeRunner(fail="sandbox 503 for key sk-secret-value")
    live = service(repo, tmp_path, runner=runner, limits=Limits(reserve_dollars=0.5))
    live.start()
    job = live.submit(CODE, TASK)
    runner.release.set()
    wait_for(lambda: live.snapshot(job.id)["state"] == "failed")
    view = json.dumps(live.snapshot(job.id))
    assert "sk-secret-value" not in view and "RuntimeError" in view
    assert [entry["dollars"] for entry in live.ledger.entries() if entry["job"] == job.id] == [0.5]
    live.close()


def test_an_unreadable_ledger_turns_live_runs_off(repo, tmp_path):
    class Broken(FileLedger):
        def entries(self):
            raise OSError("hub unavailable")

    live = LiveService(presets(repo), Broken(tmp_path / "x.jsonl"), Limits(), FakeRunner(), codes=[CODE], clock=lambda: NOW)
    assert live.health()["live"] is False
    with pytest.raises(Refused) as refused:
        live.submit(CODE, TASK)
    assert refused.value.reason == "ledger"


def test_events_name_who_did_each_step():
    def who(**kwargs):
        return describe_event(ProgressEvent(message="m", **kwargs))["who"]

    assert who(kind="agent_tool", action="edit") == "Nemotron 3 Super on Token Factory"
    assert who(kind="agent_finish") == "Nemotron 3 Super on Token Factory"
    assert who(kind="baseline") == "Token Factory Sandbox"
    assert who(kind="witness", exit_code=0) == "Token Factory Sandbox (witness)"
    assert who(kind="check", check_id="R1_fail_to_pass", passed=True) == "the gate (Python)"
    assert who(kind="check", check_id="R8_review_advisory", passed=True) == "Nemotron 3 Super review (advisory)"
    assert who(kind="appeal") == "the gate (Python)"


def _request(url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def _serve(live):
    server = make_server(live, "127.0.0.1", 0, tick=0.01)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_a_run_streams_its_steps_in_the_request_that_started_it(repo, tmp_path, monkeypatch):
    # On Cloud Run the CPU is there only while a request is open, so the run lives inside its POST.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-for-pages")
    runner = FakeRunner()
    live = service(repo, tmp_path, runner=runner)
    server, port = _serve(live)
    base = f"http://127.0.0.1:{port}"
    try:
        live.start()
        status, page = _request(base + "/")
        assert status == 200 and "pypa/twine" in page and CODE not in page
        status, body = _request(base + "/health")
        assert status == 200 and json.loads(body)["live"] is True
        status, body = _request(base + "/api/jobs", {"code": "wrong", "preset": TASK})
        assert status == 403 and json.loads(body)["reason"] == "code"
        threading.Timer(0.2, runner.release.set).start()
        status, body = _request(base + "/api/jobs", {"code": CODE, "preset": TASK})
        assert status == 200
        lines = [json.loads(line) for line in body.splitlines()]
        assert lines[0]["id"] and lines[0]["title"].startswith("pypa/twine")
        assert [event["who"] for line in lines for event in line["events"]] == [
            "Nemotron 3 Super on Token Factory", "the gate (Python)"]
        assert lines[-1]["state"] == "done" and lines[-1]["result"]["verdict"] == "VERIFIED"
        assert lines[-1]["recorded"]["run_url"].endswith(f"/run/{TASK}.html")
        assert all("result" not in line for line in lines[:-1])
        assert _request(f"{base}/api/jobs/{lines[0]['id']}")[0] == 200
        assert _request(base + "/api/jobs/does-not-exist")[0] == 404
        for text in (page, body):
            assert "sk-test-not-for-pages" not in text
    finally:
        server.shutdown()
        live.close()


def test_closing_the_page_stops_the_run_and_charges_the_reserve(repo, tmp_path):
    runner = FakeRunner()
    live = service(repo, tmp_path, runner=runner, limits=Limits(reserve_dollars=0.5))
    server, port = _serve(live)
    try:
        live.start()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", "/api/jobs", json.dumps({"code": CODE, "preset": TASK}),
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        job = json.loads(response.readline())["id"]
        runner.started.wait(5)
        response.close()
        connection.close()
        wait_for(lambda: live.snapshot(job)["state"] == "stopped")
        wait_for(lambda: any(entry["job"] == job for entry in live.ledger.entries()))
        [entry] = [entry for entry in live.ledger.entries() if entry["job"] == job]
        assert entry["dollars"] == 0.5 and entry["state"] == "stopped"
    finally:
        server.shutdown()
        live.close()


def test_a_charge_that_cannot_be_written_turns_live_runs_off(repo, tmp_path):
    class Unwritable(FileLedger):
        def append(self, entry):
            raise OSError("bucket unavailable")

    runner = FakeRunner()
    live = LiveService(presets(repo), Unwritable(tmp_path / "x.jsonl"), Limits(), runner, codes=[CODE],
                       clock=lambda: NOW)
    live.start()
    job = live.submit(CODE, TASK)
    runner.release.set()
    wait_for(lambda: live.snapshot(job.id)["state"] == "done")
    assert live.health()["live"] is False
    with pytest.raises(Refused) as refused:
        live.submit(CODE, TASK)
    assert refused.value.reason == "ledger"
    live.close()


def test_without_a_durable_ledger_live_runs_stay_off(repo, tmp_path, monkeypatch):
    from receipts.live import configured_ledger

    monkeypatch.delenv("LEDGER_BUCKET", raising=False)
    live = LiveService(presets(repo), configured_ledger(), Limits(), FakeRunner(), codes=[CODE], clock=lambda: NOW)
    assert live.health()["live"] is False
    with pytest.raises(Refused) as refused:
        live.submit(CODE, TASK)
    assert refused.value.reason == "ledger"


def test_a_bucket_name_selects_the_cloud_storage_ledger(monkeypatch):
    from receipts.live import configured_ledger

    monkeypatch.setenv("LEDGER_BUCKET", "receipts-ledger")
    ledger = configured_ledger()
    assert isinstance(ledger, BucketLedger) and ledger.bucket == "receipts-ledger"


class FakeBucket:
    """The two Cloud Storage JSON API calls the ledger makes: a media download and a media upload."""

    def __init__(self):
        self.body, self.generation, self.gets, self.fail = None, 0, 0, None
        bucket = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _reply(self, status, body=b"", headers=()):
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                bucket.gets += 1
                assert self.headers["Authorization"] == "Bearer t0ken"
                assert self.path == "/storage/v1/b/ledger-bucket/o/ledger.jsonl?alt=media"
                if bucket.fail:
                    self._reply(bucket.fail)
                elif bucket.body is None:
                    self._reply(404)
                else:
                    self._reply(200, bucket.body, [("x-goog-generation", str(bucket.generation))])

            def do_POST(self):
                assert self.headers["Authorization"] == "Bearer t0ken"
                url = urlparse(self.path)
                query = parse_qs(url.query)
                assert url.path == "/upload/storage/v1/b/ledger-bucket/o"
                assert query["uploadType"] == ["media"] and query["name"] == ["ledger.jsonl"]
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if int(query["ifGenerationMatch"][0]) != bucket.generation:
                    self._reply(412)
                    return
                bucket.body, bucket.generation = body, bucket.generation + 1
                self._reply(200, json.dumps({"generation": str(bucket.generation)}).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.api = f"http://127.0.0.1:{self.server.server_address[1]}"

    def ledger(self):
        return BucketLedger("ledger-bucket", api=self.api, token=lambda: "t0ken")


@pytest.fixture
def bucket():
    fake = FakeBucket()
    yield fake
    fake.server.shutdown()


def test_the_bucket_ledger_keeps_runs_across_restarts_in_one_object(bucket):
    ledger = bucket.ledger()
    assert ledger.entries() == []
    ledger.append({"job": "a", "dollars": 0.04})
    ledger.append({"job": "b", "dollars": 1.0})
    assert [entry["job"] for entry in ledger.entries()] == ["a", "b"]
    assert bucket.gets == 1  # one instance is the only writer, so it reads the object once
    assert [entry["job"] for entry in bucket.ledger().entries()] == ["a", "b"]


def test_the_bucket_ledger_reads_again_when_the_object_changed_under_it(bucket):
    first, second = bucket.ledger(), bucket.ledger()
    assert first.entries() == []
    second.append({"job": "x", "dollars": 0.5})
    first.append({"job": "y", "dollars": 0.25})
    assert [entry["job"] for entry in bucket.ledger().entries()] == ["x", "y"]


def test_an_unreadable_bucket_turns_live_runs_off(repo, tmp_path, bucket):
    bucket.fail = 500
    with pytest.raises(OSError):
        bucket.ledger().entries()
    live = LiveService(presets(repo), bucket.ledger(), Limits(), FakeRunner(), codes=[CODE], clock=lambda: NOW)
    assert live.health()["live"] is False


def test_secret_values_never_reach_the_page_even_inside_an_error_message(repo, tmp_path):
    key = "nb-live-key-0123456789"

    def leaky(preset, emit, cancelled):
        emit(describe_event(ProgressEvent(kind="agent_tool", message=f"401 for key {key}", action="read")))
        return {"verdict": "REJECTED", "dollars": 0.01, "wall_s": 3.0, "receipt": f"reviewer error: bad key {key}"}

    live = LiveService(presets(repo), FileLedger(tmp_path / "l.jsonl"), Limits(), leaky, codes=[CODE],
                       clock=lambda: NOW, secrets=[key, "", CODE])
    live.start()
    job = live.submit(CODE, TASK)
    wait_for(lambda: live.snapshot(job.id)["state"] == "done")
    view = json.dumps(live.snapshot(job.id))
    assert key not in view and "[redacted]" in view
    live.close()


def test_the_image_installs_git_because_the_sandbox_executor_keeps_its_trees_with_it():
    # TokenFactoryExecutor refuses to start without git, and python:3.12-slim has none.
    dockerfile = (Path(__file__).parents[1] / "live" / "run" / "Dockerfile").read_text()
    installs = [line.split("apt-get install", 1)[1].split() for line in dockerfile.splitlines()
                if "apt-get install" in line]
    assert any("git" in packages for packages in installs)


def test_a_failed_run_leaves_its_traceback_in_the_service_log_without_secrets(repo, tmp_path, capsys):
    key = "nb-live-key-0123456789"
    runner = FakeRunner(fail=f"git executable not found near {key}")
    live = LiveService(presets(repo), FileLedger(tmp_path / "l.jsonl"), Limits(), runner, codes=[CODE],
                       clock=lambda: NOW, secrets=[key])
    live.start()
    job = live.submit(CODE, TASK)
    runner.release.set()
    wait_for(lambda: live.snapshot(job.id)["state"] == "failed")
    live.close()
    log = capsys.readouterr().err
    assert f"run {job.id} ({TASK}) failed" in log and "Traceback" in log and "git executable not found" in log
    assert key not in log and "[redacted]" in log


def test_the_page_says_where_the_judge_code_is_and_links_the_recordings_for_anyone_without_one(repo, tmp_path):
    page = render_page(service(repo, tmp_path))
    assert 'aria-describedby="code-hint"' in page
    hint = page.split('id="code-hint"', 1)[1].split("</p>", 1)[0]
    assert "The code is in the testing notes attached to the Devpost submission." in hint
    assert f'<a href="{SITE_URL}/">' in hint


PROBE = "receipts-probe-0777"


def _get_with_probe(port, path):
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{port}{path}?code={PROBE}", timeout=5)
    except urllib.error.HTTPError as error:
        return error


def test_a_code_in_the_address_is_never_printed_by_the_server(repo, tmp_path):
    live = service(repo, tmp_path)
    server, port = _serve(live)
    try:
        for path in ("/", "/index.html", "/health", "/api/jobs/nope", "/elsewhere"):
            with _get_with_probe(port, path) as response:
                assert PROBE not in response.read().decode() and PROBE not in str(response.headers)
                # The address holds the code, so no request the page makes may carry it as a Referer.
                assert response.headers["Referrer-Policy"] == "no-referrer"
    finally:
        server.shutdown()
        live.close()


_DOM = """
const made = {};
const element = id => made[id] || (made[id] = {id, value: '', textContent: '', disabled: false, hidden: false,
  replaceChildren() {}, appendChild() {}, append() {}});
let fresh = 0;
globalThis.document = {getElementById: element, createElement: () => element('new-' + fresh++)};
globalThis.location = {search: process.argv[2]};
"""


def _page_script(repo, tmp_path, tail=""):
    page = render_page(service(repo, tmp_path))
    program = tmp_path / "page.js"
    program.write_text(_DOM + page.split("<script>", 1)[1].split("</script>", 1)[0] + tail)
    return program


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to check the page's script")
def test_the_page_script_parses(repo, tmp_path):
    # Python reads escapes in the template; a lost backslash once broke the whole script.
    check = subprocess.run(["node", "--check", str(_page_script(repo, tmp_path))], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page's script")
@pytest.mark.parametrize("search, expected", [(f"?code={PROBE}", PROBE), ("", ""), ("?task=x", "")])
def test_the_page_fills_the_code_box_from_the_address_and_shows_it_nowhere_else(repo, tmp_path, search, expected):
    program = _page_script(repo, tmp_path, "\nconsole.log(JSON.stringify(made));\n")
    made = json.loads(subprocess.run(["node", str(program), search], capture_output=True, text=True,
                                     check=True, timeout=30).stdout)
    assert made.get("code", {}).get("value", "") == expected
    others = {key: value for key, value in made.items() if key != "code"}
    assert PROBE not in json.dumps(others)
