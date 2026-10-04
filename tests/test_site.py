from __future__ import annotations

import html
import json
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote

# The only external resources a page may load: the IBM Plex stylesheet and its host.
ALLOWED_EXTERNAL = {"fonts.googleapis.com"}

import pytest

from receipts.cli import main
from receipts.site import build_site


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
    assert "Shipped false dones" in page.plain
    assert "Model dollars per verified fix" in page.plain


def test_each_attempt_predicates_official_grade_and_appeal(bundle):
    build(bundle)
    out = bundle[2]
    for iid in (VERIFIED, REJECTED, APPEAL):
        page = Page(out / f"run/{iid}.html")
        result = json.loads((bundle[0] / f"runs/{iid}/result.json").read_text())
        for attempt in result["attempts"]:
            assert f"Attempt {attempt['number']}" in page.plain
            for predicate in attempt["verdict"]["predicates"]:
                row = next(r for r in page.rows if predicate["id"] in r and predicate["evidence"] in r)
                assert ("PASS" if predicate["passed"] else "FAIL") in row
        assert "official_resolved" in page.plain
        assert "agreement" in page.plain
    assert "Fix the source and keep tests unchanged." in Page(out / f"run/{APPEAL}.html").plain
    assert "No patch shipped" in Page(out / f"run/{REJECTED}.html").plain


def test_untrusted_strings_are_escaped_everywhere(bundle):
    payload = '<script>alert(1)</script><img src=x onerror="alert(2)"> & "quoted"'
    repo, _, out = bundle
    p = repo / f"runs/{VERIFIED}/result.json"
    result = json.loads(p.read_text())
    result["attempts"][0]["worker"]["summary"] = payload
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
    for folder in ("run", "receipt"):
        page = Page(out / folder / f"{VERIFIED}.html").plain
        assert "Token Factory reported cost: 123.457 (unit not published)" in page
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
    summary = build_site([other, pilot], out, repo_root=repo)
    assert summary.instances == 6
    pages = list((out / "run").rglob("*.html"))
    assert len(pages) == 6
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
    assert "gate_looser" in page.plain
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
    assert "test_metadata_dictionary_keys: failed → passed" in page.plain


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
    assert "local checkout path is removed" in Page(out / "receipt" / f"{VERIFIED}.html").plain
