from __future__ import annotations

import html
import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote

# Fixed report and repository links, plus the IBM Plex stylesheet and its host.
ALLOWED_EXTERNAL = {"fonts.googleapis.com", "github.com"}

import pytest

from receipts.cli import main
from receipts.site import build_site
from receipts.pilot.report import build_report_from_directory


FIXTURE = Path(__file__).parent / "fixtures" / "site"
VERIFIED = "pypa__twine-1066"
REJECTED = "twisted__towncrier-696"
APPEAL = "synthetic__appeal-1"
FOOTER = "Generated from the run records by receipts site. No model was asked whether a fix worked."


class Page(HTMLParser):
    def __init__(self, path: Path):
        super().__init__()
        self.links = []
        self.text = []
        self.tags = []
        self.rows = []
        self.row = None
        self.feed(path.read_text())

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for key, value in attrs:
            if key in {"href", "src"}:
                self.links.append(value)
            assert not key.lower().startswith("on")
        if tag == "tr":
            self.row = []

    def handle_endtag(self, tag):
        if tag == "tr" and self.row is not None:
            self.rows.append(" ".join(self.row))
            self.row = None

    def handle_data(self, data):
        self.text.append(data)
        if self.row is not None:
            self.row.append(data)

    @property
    def plain(self):
        return " ".join(self.text)


@pytest.fixture
def bundle(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    # Absolute paths confined to this fixture root also let the existing report
    # inspect the fixture artifacts without changing its root or implementation.
    for path in (repo / "pilot").glob("*/record.json"):
        record = json.loads(path.read_text())
        record["run_dir"] = str(repo / record["run_dir"])
        path.write_text(json.dumps(record))
    return repo, repo / "pilot", tmp_path / "site"


def build(bundle, **kwargs):
    repo, pilot, out = bundle
    return build_site([pilot], out, repo_root=repo, **kwargs)


def test_pages_raw_files_and_excluded_large_artifacts(bundle):
    repo, pilot, out = bundle
    summary = build(bundle)
    assert summary.instances == 3
    assert (out / "index.html").is_file()
    assert (out / "assets/site.css").is_file()
    for iid in (VERIFIED, REJECTED, APPEAL):
        assert (out / f"run/{iid}.html").is_file()
        assert (out / f"receipt/{iid}.html").is_file()
        source = repo / "runs" / iid
        expected = ["record.json", "input.json", "plan.json", "disclosure.json", "result.json"]
        expected += [str(p.relative_to(source)) for p in source.glob("attempts/*/*") if p.is_file()]
        expected += [str(p.relative_to(source)) for p in source.glob("branches/*/receipts.jsonl")]
        for relative in expected:
            target = out / "raw" / iid / relative
            assert target.is_file(), relative
            original = pilot / iid / relative if relative == "record.json" else source / relative
            # Copies are byte-identical except that the local checkout path is dropped.
            assert target.read_bytes() == original.read_bytes().replace((str(repo) + "/").encode(), b"")
    assert not list(out.rglob("worker.jsonl"))
    assert not list(out.rglob("*.log"))
    for p in out.rglob("*.html"):
        assert FOOTER in Page(p).plain


def test_index_outcomes_headlines_and_progress_order(bundle):
    build(bundle)
    page = Page(bundle[2] / "index.html")
    rows = {iid: next(r for r in page.rows if iid in r) for iid in (VERIFIED, REJECTED, APPEAL)}
    assert "VERIFIED on first verdict" in rows[VERIFIED]
    assert "REJECTED" in rows[REJECTED]
    assert "VERIFIED on appeal" in rows[APPEAL]
    assert page.plain.index(REJECTED) < page.plain.index(APPEAL) < page.plain.index(VERIFIED)
    assert "95%" in page.plain
    assert "Receipts: false fixes shipped" in page.plain
    assert "Model cost per verified fix" in page.plain


def test_each_attempt_predicates_official_grade_and_appeal(bundle):
    build(bundle)
    out = bundle[2]
    for iid in (VERIFIED, REJECTED, APPEAL):
        page = Page(out / f"run/{iid}.html")
        result = json.loads((bundle[0] / f"runs/{iid}/result.json").read_text())
        for attempt in result["attempts"]:
            assert f"Attempt {attempt['number']}" in page.plain
            for predicate in attempt["verdict"]["predicates"]:
                evidence = re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", lambda m: m.group()[:8], predicate["evidence"]) if predicate["id"] == "R5_provenance" else predicate["evidence"]
                row = next(r for r in page.rows if predicate["id"] in r and evidence in r)
                assert ("PASS" if predicate["passed"] else "FAIL") in row
        assert "SWE-rebench's official grader:" in page.plain
        assert "Agrees with the gate" in page.plain
    assert "Fix the source and keep tests unchanged." in Page(out / f"run/{APPEAL}.html").plain
    assert "No patch shipped" in Page(out / f"run/{REJECTED}.html").plain


def test_untrusted_strings_are_escaped_everywhere(bundle):
    payload = '<script>alert(1)</script><img src=x onerror="alert(2)"> & "quoted"'
    repo, _, out = bundle
    p = repo / f"runs/{VERIFIED}/result.json"
    result = json.loads(p.read_text())
    result["attempts"][0]["worker"]["summary"] = payload
    result["attempts"][0]["worker"]["claims"]["files_changed"] = [payload]
    p.write_text(json.dumps(result))
    for name, field in (("input.json", "issue"), ("plan.json", "approach")):
        p = repo / "runs" / VERIFIED / name
        value = json.loads(p.read_text()); value[field] = payload; p.write_text(json.dumps(value))
    build(bundle, title=payload)
    assert html.escape(payload, quote=True) in (out / f"run/{VERIFIED}.html").read_text()
    assert html.escape(payload, quote=True) in (out / f"receipt/{VERIFIED}.html").read_text()
    for p in out.rglob("*.html"):
        assert "<script>" not in p.read_text()
        assert "img" not in Page(p).tags


def test_tokenfactory_cost_has_no_dollar_unit_or_combined_total(bundle):
    repo, pilot, out = bundle
    p = pilot / VERIFIED / "record.json"
    record = json.loads(p.read_text()); record["cost"]["sandbox_dollars_estimate"] = 123.456789
    p.write_text(json.dumps(record))
    build(bundle)
    page = Page(out / "run" / f"{VERIFIED}.html").plain
    assert "Token Factory reported cost: 123.457 (unit not published)" in page
    for folder in ("run", "receipt"):
        page = Page(out / folder / f"{VERIFIED}.html").plain
        assert "$123.457" not in page and "$123.456789" not in page
    index = Page(out / "index.html").plain
    total = index.split("Token Factory reported sandbox cost over all runs:")[1].split("(unit not published)")[0]
    assert "$" not in total
    assert "Total dollars" not in Page(out / "index.html").plain


@pytest.mark.parametrize("iid", ["../escape", "a/b", 'x\" onclick=\"alert(1)', "", ".", "..", "a\n"])
def test_unsafe_instance_id_refused(bundle, iid):
    p = bundle[1] / VERIFIED / "record.json"
    record = json.loads(p.read_text()); record["instance_id"] = iid; p.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="instance id"):
        build(bundle)
    assert not (bundle[2] / "index.html").exists()


def test_two_builds_are_byte_identical(bundle, tmp_path):
    build(bundle)
    second = tmp_path / "second"
    build_site([bundle[1]], second, repo_root=bundle[0])
    def contents(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert contents(bundle[2]) == contents(second)


def test_every_generated_relative_link_resolves(bundle):
    build(bundle)
    for p in bundle[2].rglob("*.html"):
        for link in Page(p).links:
            url = urlsplit(link)
            if url.netloc in ALLOWED_EXTERNAL and url.scheme == "https":
                continue
            assert not url.scheme and not url.netloc, (p, link)
            target = (p.parent / unquote(url.path)).resolve()
            assert target.is_relative_to(bundle[2]) and target.is_file(), (p, link)


@pytest.mark.parametrize("status,gate,outcome", [("infra_error", None, "infrastructure error"), ("ran", None, "NO VERDICT"), ("ran", "ERROR", "NO VERDICT")])
def test_minimal_run_with_missing_optional_files(bundle, status, gate, outcome):
    repo, pilot, out = bundle
    p = pilot / VERIFIED / "record.json"
    record = json.loads(p.read_text());record.update(status=status, reason="Sandbox unavailable", attempts=[], final=None)
    if gate:
        record["final"] = {"gate_status":gate,"verified_fix":False,"official_resolved":None}
    p.write_text(json.dumps(record))
    shutil.rmtree(repo / "runs" / VERIFIED)
    build(bundle)
    assert outcome in next(r for r in Page(out / "index.html").rows if VERIFIED in r)
    page = Page(out / f"run/{VERIFIED}.html").plain
    assert "not recorded" in page and "Sandbox unavailable" in page


def test_cli_builds_from_current_repo_root(bundle, monkeypatch, capsys):
    repo, pilot, out = bundle
    monkeypatch.chdir(repo)
    assert main(["site", str(pilot), "--out", str(out), "--title", "Review receipts"]) == 0
    assert "Review receipts" in Page(out / "index.html").plain
    assert "3" in capsys.readouterr().out


def test_repeated_instance_across_pilots_has_distinct_pages(bundle, tmp_path):
    repo, pilot, out = bundle
    other = repo / "other-pilot"
    shutil.copytree(pilot, other)
    summary = build_site([pilot, other], out, repo_root=repo)
    assert summary.instances == 6
    pages = list((out / "run").rglob("*.html"))
    assert len(pages) == 6
    # The first pilot given keeps short URLs; a repeat is namespaced by its directory.
    assert (out / "run" / f"{VERIFIED}.html").is_file()
    assert (out / "run" / "other-pilot" / f"{VERIFIED}.html").is_file()
    assert not list(out.rglob("pilot-*"))
    for p in out.rglob("*.html"):
        for link in Page(p).links:
            if urlsplit(link).netloc in ALLOWED_EXTERNAL:
                continue
            assert (p.parent / urlsplit(link).path).resolve().is_file()


def test_record_paths_cannot_escape_repo_root(bundle):
    p = bundle[1] / VERIFIED / "record.json"
    record = json.loads(p.read_text()); record["run_dir"] = "../outside"
    p.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="repository root"):
        build(bundle)


def test_shipped_false_done_preserves_gate_verdict_patch_and_official_result(bundle):
    p = bundle[1] / VERIFIED / "record.json"
    record = json.loads(p.read_text())
    record["final"].update(verified_fix=False, official_resolved=False)
    record["attempts"][0].update(official_resolved=False, agreement="gate_looser")
    p.write_text(json.dumps(record))
    build(bundle)
    row = next(r for r in Page(bundle[2] / "index.html").rows if VERIFIED in r)
    assert "VERIFIED on first verdict" in row
    assert "not resolved" in row
    page = Page(bundle[2] / f"run/{VERIFIED}.html")
    assert "Gate was looser" in page.plain
    assert "diff --git" in page.plain


def test_rebuild_in_same_output_directory_is_deterministic(bundle):
    build(bundle)
    first = {str(p.relative_to(bundle[2])): p.read_bytes() for p in bundle[2].rglob("*") if p.is_file()}
    build(bundle)
    second = {str(p.relative_to(bundle[2])): p.read_bytes() for p in bundle[2].rglob("*") if p.is_file()}
    assert first == second


def test_output_symlinks_cannot_write_outside_site(bundle, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    bundle[2].mkdir()
    (bundle[2] / "raw").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="output"):
        build(bundle)
    assert not list(outside.iterdir())


def test_each_agent_command_only_appears_in_its_attempt(bundle):
    p = bundle[0] / f"runs/{APPEAL}/branches/agent1/receipts.jsonl"
    receipts = [json.loads(line) for line in p.read_text().splitlines()]
    first_diff = next(n for n, r in enumerate(receipts) if r["kind"] == "diff")
    receipts[0]["cmd"] = "FIRST_ATTEMPT_ONLY"
    receipts[first_diff + 1]["cmd"] = "APPEAL_ATTEMPT_ONLY"
    p.write_text("".join(json.dumps(r) + "\n" for r in receipts))
    build(bundle)
    page = (bundle[2] / f"run/{APPEAL}.html").read_text()
    split = page.index("<h2>Attempt 2")
    assert "FIRST_ATTEMPT_ONLY" in page[:split]
    assert "FIRST_ATTEMPT_ONLY" not in page[split:]
    assert "APPEAL_ATTEMPT_ONLY" not in page[:split]
    assert "APPEAL_ATTEMPT_ONLY" in page[split:]


def test_image_base_commit_is_not_confused_with_snapshot_commit(bundle):
    p = bundle[0] / f"runs/{VERIFIED}/branches/base/receipts.jsonl"
    receipt = {"kind": "command", "cmd": "git commit -m snapshot && git rev-parse HEAD", "stdout_tail": "a" * 40}
    p.write_text(json.dumps(receipt) + "\n" + p.read_text())
    build(bundle)
    page = Page(bundle[2] / f"run/{VERIFIED}.html")
    assert "4a1fc06 (image tag)" in page.plain
    assert "Base commit aaaaaaaaaa" not in page.plain


def test_witness_artifact_supplies_spec_before_and_after_when_branch_file_missing(bundle):
    repo = bundle[0]
    branch = repo / f"runs/{VERIFIED}/branches/w1/receipts.jsonl"
    target = repo / f"runs/{VERIFIED}/attempts/1/witness/receipts.jsonl"
    target.parent.mkdir()
    shutil.copyfile(branch, target)
    branch.unlink()
    build(bundle)
    page = Page(bundle[2] / f"receipt/{VERIFIED}.html")
    assert "test_metadata_dictionary_keys: failed -> passed" in page.plain


def test_untrusted_commands_predicates_digests_and_diff_are_escaped(bundle):
    repo, _, out = bundle
    payload = '<script>alert(9)</script>'
    p = repo / f"runs/{VERIFIED}/attempts/1/verdict.json"
    verdict = json.loads(p.read_text())
    verdict["predicates"][0]["evidence"] = payload
    verdict["claim_evidence"] = payload
    p.write_text(json.dumps(verdict))
    p = repo / f"runs/{VERIFIED}/disclosure.json"
    disclosure = json.loads(p.read_text())
    disclosure["model"]["model"] = payload
    disclosure["test_digests"] = {payload: payload}
    p.write_text(json.dumps(disclosure))
    p = repo / f"runs/{VERIFIED}/branches/agent1/receipts.jsonl"
    rows = [json.loads(line) for line in p.read_text().splitlines()]
    rows[0].update(cmd=payload, path=payload, tree_digest=payload)
    p.write_text("".join(json.dumps(row) + "\n" for row in rows))
    p = repo / f"runs/{VERIFIED}/attempts/1/filtered.diff"
    p.write_text(p.read_text() + "+" + payload + "\n")
    build(bundle)
    for p in out.rglob("*.html"):
        assert "<script>" not in p.read_text()
    for folder in ("run", "receipt"):
        assert html.escape(payload, quote=True) in (out / folder / f"{VERIFIED}.html").read_text()


def test_missing_plan_file_is_explicit_even_with_embedded_plan(bundle):
    repo = bundle[0]
    result_path = repo / f"runs/{VERIFIED}/result.json"
    result = json.loads(result_path.read_text())
    result["plan"] = {"files_to_edit": ["twine/package.py"], "approach": "EMBEDDED_PLAN_ONLY"}
    result_path.write_text(json.dumps(result))
    (repo / f"runs/{VERIFIED}/plan.json").unlink()
    build(bundle)
    page = Page(bundle[2] / f"run/{VERIFIED}.html")
    assert "Approach not recorded" in page.plain
    assert "EMBEDDED_PLAN_ONLY" not in page.plain


def test_rejected_run_summary_counts_the_attempted_patch_without_claiming_shipment(bundle):
    build(bundle)
    summary = Page(bundle[2] / f"run/{REJECTED}.html").plain.split("Open receipt", 1)[0]
    assert "Final attempted patch:" in summary
    assert "files," in summary and "added and" in summary and "removed lines" in summary
    assert "No patch shipped" in summary


def test_raw_copies_drop_the_local_checkout_path(bundle):
    repo, pilot, out = bundle
    build(bundle)
    copied = out / "raw" / VERIFIED / "record.json"
    original = (pilot / VERIFIED / "record.json").read_text()
    assert str(repo) in original
    text = copied.read_text()
    assert str(repo) not in text
    assert json.loads(text)["run_dir"] == json.loads(original)["run_dir"].removeprefix(str(repo) + "/")
    assert "local checkout path is removed" in Page(out / "run" / f"{VERIFIED}.html").plain


def test_raw_copies_drop_other_checkouts_and_the_home_directory(bundle, monkeypatch):
    repo, pilot, out = bundle
    home = repo.parent / "home" / "someone"
    monkeypatch.setenv("HOME", str(home))
    other = home / "dev" / "other-checkout"
    record_path = pilot / VERIFIED / "record.json"
    record = json.loads(record_path.read_text())
    record["note"] = f"{other}/pilot/x/log.txt and {home}/.local/share/uv/python"
    record_path.write_text(json.dumps(record))
    build(bundle, strip_prefixes=[other])
    text = (out / "raw" / VERIFIED / "record.json").read_text()
    assert str(home) not in text
    assert "pilot/x/log.txt" in text and "~/.local/share/uv/python" in text


def test_index_leads_with_report_and_plain_metrics(bundle):
    build(bundle)
    source = (bundle[2] / "index.html").read_text()
    report = build_report_from_directory(bundle[1])
    assert f'<h1>{html.escape(report.headline, quote=True)}</h1>' in source
    page = Page(bundle[2] / "index.html").plain
    assert "3 SWE-rebench-V2 tasks held out from development" in page
    assert "NVIDIA Nemotron 3 Super on Nebius Token Factory wrote every fix" in page
    assert "Unguarded agent: 'done' that was false" in page
    assert "Receipts: verified fixes" in page
    assert "on the first verdict," in page and "after one appeal" in page
    assert "95% interval" in page and "Wilson" not in page
    assert "Nemotron tokens at Token Factory's listed prices" in page
    assert f'${report.configuration_b.cost_per_verified_fix.model_dollars:.2f}' in page
    assert "How to read this" in page
    assert "Official = SWE-rebench's grader, run separately." in page
    assert 'href="https://github.com/zeyusuntt/receipts/blob/main/REPORT-v2.md" rel="noopener"' in source
    assert 'href="https://github.com/zeyusuntt/receipts" rel="noopener"' in source
    assert 'Re-verify a receipt' in page
    assert f'href="receipt/{REJECTED}.html"' in source


@pytest.mark.parametrize("name,title", [
    ("v2-P", "Primary sample: 100 held-out tasks, Nemotron 3 Super"),
    ("v2-arm-lightning", "Exploratory: the first 30 tasks again with Nemotron 3.5 Lightning"),
    ("other-sample", "other-sample"),
])
def test_pilot_titles_with_directory_fallback(bundle, name, title):
    repo, pilot, out = bundle
    renamed = repo / name
    pilot.rename(renamed)
    build_site([renamed], out, repo_root=repo)
    assert f'<h2>{title}</h2>' in (out / "index.html").read_text()


def test_index_model_name_is_derived_from_disclosure(bundle):
    for path in (bundle[0] / "runs").glob("*/disclosure.json"):
        data = json.loads(path.read_text())
        data["model"]["model"] = "nvidia/nemotron-3.5-lightning"
        path.write_text(json.dumps(data))
    build(bundle)
    assert "NVIDIA Nemotron 3.5 Lightning on Nebius Token Factory wrote every fix" in Page(bundle[2] / "index.html").plain


def test_index_task_count_and_model_ignore_infrastructure_records(bundle):
    repo, pilot, out = bundle
    record = json.loads((pilot / VERIFIED / "record.json").read_text())
    record.update(instance_id="synthetic__infra-2", status="infra_error", run_dir="runs/infra-2",
                  attempts=[], final=None, reason="Sandbox unavailable")
    path = pilot / "synthetic__infra-2" / "record.json"
    path.parent.mkdir()
    path.write_text(json.dumps(record))
    build(bundle)
    page = Page(out / "index.html").plain
    assert "3 SWE-rebench-V2 tasks held out from development" in page
    assert "NVIDIA Nemotron 3 Super on Nebius Token Factory wrote every fix" in page


def test_run_costs_and_plan_paths_are_readable(bundle):
    path = bundle[1] / VERIFIED / "record.json"
    record = json.loads(path.read_text())
    record["cost"].update(tokens=904972, model_dollars=.2755434, sandbox_lifetime_seconds=208.952124)
    path.write_text(json.dumps(record))
    build(bundle)
    source = (bundle[2] / f"run/{VERIFIED}.html").read_text()
    page = Page(bundle[2] / f"run/{VERIFIED}.html").plain
    assert "904,972 tokens" in page and "$0.28" in page and "3 min 29 s" in page
    assert '<li><code>twine/package.py</code></li>' in source


@pytest.mark.parametrize("kind,cmd,extra,display", [
    ("command", "/opt/receipts-abcd/bin/busybox mkdir -p /opt/receipts/reports && python -I /opt/receipts-abcd/receipts_pytest.py --no-header -rA --tb=line --color=no -p no:cacheprovider -W ignore::DeprecationWarning tests/test_example.py -k 'copy time' -o junit_family=xunit1 -p no:cacheprovider -rA --continue-on-collection-errors --junitxml=/opt/receipts/reports/a.xml", {}, "pytest tests/test_example.py -k 'copy time'"),
    ("write", "cp /incoming/blob /repo/fs/ftpfs.py", {"path": "fs/ftpfs.py"}, "write fs/ftpfs.py"),
    ("apply", "git apply /incoming/patch.diff", {"patch_sha256": "abcdef012345" * 5}, "apply patch abcdef012345"),
    ("apply", "git apply /incoming/patch.diff", {}, "apply patch"),
    ("verification", "python -I /opt/receipts/receipts_pytest.py --no-header -rA tests/test_memoryfs.py -o junit_family=xunit1 --junitxml=/tmp/test.xml", {}, "pytest (witness) tests/test_memoryfs.py"),
    ("verification", "pytest --no-header -rA tests/test_memoryfs.py --junitxml=/tmp/test.xml", {}, "pytest (witness) tests/test_memoryfs.py"),
    ("verification", "python -m pytest --no-header tests/test_memoryfs.py", {}, "pytest (witness) tests/test_memoryfs.py"),
    ("diff", "git diff --cached", {}, "capture patch"),
    ("command", "git status --short", {}, "git status --short"),
    ("command", "python -I /tmp/receipts_pytest.py --no-header tests/test_memoryfs.py", {}, "python -I /tmp/receipts_pytest.py --no-header tests/test_memoryfs.py"),
    ("command", "echo 'unterminated", {}, "echo 'unterminated"),
    ("command", "echo 7123a1d4-2cc8-452d-b976-de33ecdfe08e", {"image_after": "7123a1d4-2cc8-452d-b976-de33ecdfe08e"}, "echo 7123a1d4"),
])
def test_display_commands_keep_exact_command_in_details(bundle, kind, cmd, extra, display):
    path = bundle[0] / f"runs/{VERIFIED}/branches/agent1/receipts.jsonl"
    receipt = {"kind": kind, "cmd": cmd, "exit_code": 0, **extra}
    path.write_text(json.dumps(receipt) + "\n")
    build(bundle)
    source = (bundle[2] / f"run/{VERIFIED}.html").read_text()
    assert f'<code class="display-command">{html.escape(display, quote=True)}</code>' in source
    assert f'<details><summary>exact command</summary><pre>{html.escape(cmd, quote=True)}</pre></details>' in source


def test_long_agent_lane_hides_only_middle_steps(bundle):
    path = bundle[0] / f"runs/{VERIFIED}/branches/agent1/receipts.jsonl"
    path.write_text("".join(json.dumps({"kind": "command", "cmd": f"STEP_{n:02d}"}) + "\n" for n in range(20)))
    build(bundle)
    source = (bundle[2] / f"run/{VERIFIED}.html").read_text()
    middle = re.search(r'<details class="all-steps"><summary>show all 20 steps</summary>(.*?)</table></div></details>', source).group(1)
    assert "STEP_08" in middle and "STEP_15" in middle
    assert "STEP_07" not in middle and "STEP_16" not in middle
    outside = source.replace(middle, "")
    for n in list(range(8)) + list(range(16, 20)):
        assert f"STEP_{n:02d}" in outside
    assert "STEP_08" not in outside


def test_claims_are_a_short_list_and_audit_has_evidence(bundle):
    build(bundle)
    source = (bundle[2] / f"run/{VERIFIED}.html").read_text()
    claims = re.search(r'<ul class="claims">(.*?)</ul>', source).group(1)
    assert "Target tests pass: yes" in claims
    assert "Full suite passes: no" in claims
    assert "Files changed: twine/package.py" in claims
    assert "Ran tests: yes" in claims
    assert "{" not in claims and "}" not in claims
    assert "contradicted: claimed green; own last run had 1 failed" in Page(bundle[2] / f"run/{VERIFIED}.html").plain


@pytest.mark.parametrize("resolved,agreement,words", [
    (True, "agree_pass", "Agrees with the gate"),
    (False, "agree_fail", "Agrees with the gate"),
    (True, "gate_stricter", "Gate was stricter"),
    (False, "gate_looser", "Gate was looser"),
])
def test_official_grade_in_words(bundle, resolved, agreement, words):
    path = bundle[1] / VERIFIED / "record.json"
    record = json.loads(path.read_text())
    record["attempts"][0].update(official_resolved=resolved, agreement=agreement)
    path.write_text(json.dumps(record))
    build(bundle)
    page = Page(bundle[2] / f"run/{VERIFIED}.html").plain
    assert f"SWE-rebench's official grader: {'resolved' if resolved else 'not resolved'}" in page
    assert words in page


def test_receipt_is_concise_and_pr_is_ready_to_use(bundle):
    build(bundle)
    source = (bundle[2] / f"receipt/{VERIFIED}.html").read_text()
    paper = source.split('<section class="paper">')[1].split('</section>')[0]
    assert "24 of 24 previously passing tests still pass" in paper
    assert '<dt>removed or new skips</dt><dd>none</dd>' in paper
    assert '<dt>dropped</dt><dd>none</dd>' in paper
    assert "fresh sandbox from checkpoint 7123a1d4, patch digest matches" in paper
    assert "attempt 1 verified" in paper
    assert "test_metadata_dictionary_keys: failed -&gt; passed" in paper
    assert "thinking off · temperature 1.0 · top_p 0.95" in paper
    for internal in ("test_digests", "lock digest", "tests digests", "checkpoint</dt>", "claims</dt>", "base_url", "{", "}"):
        assert internal not in paper
    page = Page(bundle[2] / f"receipt/{VERIFIED}.html").plain
    issue = json.loads((bundle[0] / f"runs/{VERIFIED}/input.json").read_text())["issue"].splitlines()[0]
    assert f"Fixes {VERIFIED}: {issue}." in page
    assert "Verified by Receipts on a fresh sandbox the agent never touched:" in page
    assert "- spec tests: 3 failed before, pass now" in page
    assert "- no tests removed or skipped; no test or config edits" in page
    assert f"- re-verify: uv run receipts reverify receipts/{VERIFIED}.json" in page
    assert "Written with NVIDIA Nemotron 3 Super on Nebius Token Factory; reviewed and submitted by [your name]." in page
    assert 'full record' in source
    assert 'attempt 1 rejected · attempt 2 verified' in Page(bundle[2] / f"receipt/{APPEAL}.html").plain


def test_rejected_pr_explains_first_failed_check(bundle):
    build(bundle)
    page = Page(bundle[2] / f"receipt/{REJECTED}.html").plain
    assert "Not ready to submit: Previously passing tests regressed:" in page
    assert "test_orphans_in_non_showcontent_markdown (failed)" in page
    assert "Verified by Receipts on a fresh sandbox" not in page
    assert "no claim: branch ended without a finish call" in page
    assert 'pyproject.toml' in page


def test_no_verdict_pr_does_not_claim_verification(bundle):
    repo, pilot, out = bundle
    path = pilot / VERIFIED / "record.json"
    record = json.loads(path.read_text())
    record.update(attempts=[], final=None, status="infra_error", reason="Sandbox unavailable")
    path.write_text(json.dumps(record))
    shutil.rmtree(repo / "runs" / VERIFIED)
    build(bundle)
    page = Page(out / f"receipt/{VERIFIED}.html").plain
    assert "Not ready to submit: Sandbox unavailable" in page
    assert "Verified by Receipts on a fresh sandbox" not in page


def test_uuid_shortening_and_long_evidence_details_preserve_full_text(bundle):
    path = bundle[0] / f"runs/{VERIFIED}/attempts/1/verdict.json"
    verdict = json.loads(path.read_text())
    uuid = "7123a1d4-2cc8-452d-b976-de33ecdfe08e"
    evidence = "long evidence <script> " + "x" * 700
    verdict["predicates"][0]["evidence"] = evidence
    path.write_text(json.dumps(verdict))
    build(bundle)
    source = (bundle[2] / f"run/{VERIFIED}.html").read_text()
    row = next(r for r in Page(bundle[2] / f"run/{VERIFIED}.html").rows if "R5_provenance" in r)
    assert "7123a1d4" in row and uuid not in row
    assert f'<summary>full evidence</summary><pre>{html.escape(evidence, quote=True)}</pre>' in source
    cell = re.search(r'<td>(long evidence.*?)</td>', source).group(1)
    assert len(html.unescape(cell.split('<details>')[0])) <= 601


@pytest.mark.parametrize("cost,display", [(.0046, "$0.005"), (.01, "$0.01"), (.4144, "$0.41")])
def test_small_model_cost_precision(bundle, cost, display):
    path = bundle[1] / VERIFIED / "record.json"
    record = json.loads(path.read_text())
    record["cost"]["model_dollars"] = cost
    path.write_text(json.dumps(record))
    build(bundle)
    for folder in ("run", "receipt"):
        assert display in Page(bundle[2] / folder / f"{VERIFIED}.html").plain


def test_receipt_quotes_only_first_finish_sentence(bundle):
    path = bundle[0] / f"runs/{VERIFIED}/result.json"
    result = json.loads(path.read_text())
    result["attempts"][0]["worker"]["summary"] = "Fixed fs/ftpfs.py. Kept MemoryFS working too."
    path.write_text(json.dumps(result))
    build(bundle)
    source = (bundle[2] / f"receipt/{VERIFIED}.html").read_text()
    assert '<dt>said</dt><dd>&quot;Fixed fs/ftpfs.py.&quot;</dd>' in source
    assert "Kept MemoryFS working too" not in source
    assert "Kept MemoryFS working too" in Page(bundle[2] / f"run/{VERIFIED}.html").plain


def test_receipt_keeps_failed_preservation_evidence_and_dropped_paths(bundle):
    path = bundle[0] / f"runs/{VERIFIED}/attempts/1/verdict.json"
    verdict = json.loads(path.read_text())
    for predicate in verdict["predicates"]:
        if predicate["id"] in {"R2_pass_to_pass", "R3_no_shrink", "R5_provenance"}:
            predicate.update(passed=False, evidence="EVIDENCE_" + predicate["id"])
    path.write_text(json.dumps(verdict))
    result_path = bundle[0] / f"runs/{VERIFIED}/result.json"
    result = json.loads(result_path.read_text())
    result["attempts"][0]["dropped_paths"] = ["tests/scratch.py"]
    result_path.write_text(json.dumps(result))
    build(bundle)
    source = (bundle[2] / f"receipt/{VERIFIED}.html").read_text()
    assert '<dt>kept</dt><dd>EVIDENCE_R2_pass_to_pass</dd>' in source
    assert '<dt>removed or new skips</dt><dd>EVIDENCE_R3_no_shrink</dd>' in source
    assert '<dt>witness</dt><dd>EVIDENCE_R5_provenance</dd>' in source
    assert '<dt>dropped</dt><dd>tests/scratch.py</dd>' in source


def test_spec_collection_errors_count_as_failures_before_fix(bundle):
    path = bundle[0] / f"runs/{VERIFIED}/baseline.json"
    baseline = json.loads(path.read_text())
    for run in baseline["runs"]:
        run["failed"] = []
        run["collection_errors"] = ["tests/test_package.py"]
    path.write_text(json.dumps(baseline))
    build(bundle)
    page = Page(bundle[2] / f"receipt/{VERIFIED}.html").plain
    assert "test_metadata_dictionary_keys: error -> passed" in page
    assert "- spec tests: 3 failed before, pass now" in page


def test_verified_pr_handles_missing_issue_title(bundle):
    path = bundle[0] / f"runs/{VERIFIED}/input.json"
    inp = json.loads(path.read_text())
    inp["issue"] = ""
    path.write_text(json.dumps(inp))
    build(bundle)
    assert f"Fixes {VERIFIED}: not recorded." in Page(bundle[2] / f"receipt/{VERIFIED}.html").plain


def test_spec_short_names_keep_the_class_so_same_named_tests_differ():
    from receipts.site import _test_short_name
    assert _test_short_name("tests/test_ftpfs.py::TestFTPFS::test_getinfo_modified") == "TestFTPFS::test_getinfo_modified"
    assert _test_short_name("tests/test_ftpfs.py::TestFTPFSNoMLSD::test_getinfo_modified") == "TestFTPFSNoMLSD::test_getinfo_modified"
    assert _test_short_name("tests/test_x.py::test_metadata_dictionary_keys") == "test_metadata_dictionary_keys"
