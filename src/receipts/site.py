"""Render recorded pilot runs as a deterministic, offline static website."""

from __future__ import annotations

import html
import json
import posixpath
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from receipts.agent.worker import APPEAL_INSTRUCTION
from receipts.models import Verdict
from receipts.orchestrate import _appeal_evidence
from receipts.pilot.report import Report, build_report_from_directory


_NOT_RECORDED = "not recorded"
_FOOTER = (
    "Generated from the run records by receipts site. "
    "No model was asked whether a fix worked."
)
_NAMES = {
    "R1_fail_to_pass": "Failing specification tests now pass",
    "R2_pass_to_pass": "Previously passing tests kept",
    "R3_no_shrink": "No removed tests or new skips",
    "R4_patch_scope": "Patch scope",
    "R5_provenance": "Witness chain and patch digest",
    "R6_claim_audit": "Agent claim audit (advisory)",
}
_CSS = """\
:root{--page:#F4F5F7;--ink:#12161C;--secondary:#4B5563;--border:#DADFE6;--accent:#2346C8;--verified:#0E6B47;--rejected:#B93D0B;--unknown:#5B6472;--paper:#FFFEFA}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 'IBM Plex Sans',system-ui,sans-serif}
a{color:var(--accent);text-underline-offset:3px}a:hover{color:#1A3496}a:focus-visible{outline:2px solid var(--accent);outline-offset:4px}
header{background:#fff;border-bottom:1px solid var(--border)}.header,main,footer{max-width:1280px;margin:auto;padding:24px 48px}
.header{display:flex;align-items:center;flex-wrap:wrap;gap:24px;padding-top:14px;padding-bottom:14px}.brand{font-size:18px;font-weight:600;color:var(--ink);text-decoration:none}.header nav{display:flex;gap:24px}.header .secondary{margin-left:auto}
main{padding-top:36px;padding-bottom:64px;display:flex;flex-direction:column;gap:28px}footer{font-size:12px;color:var(--secondary);padding-top:0;padding-bottom:32px}
h1,h2,h3,p{margin:0}h1{font-size:34px;line-height:1.2;letter-spacing:-.01em}h2{font-size:20px}h3{font-size:16px}h1,h2,h3{text-wrap:balance;overflow-wrap:anywhere}p{max-width:75ch}section{min-width:0}.secondary{color:var(--secondary)}
.hero{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;flex-wrap:wrap}.hero>div{min-width:0}.hero h1{margin:10px 0}.actions{display:flex;gap:12px;flex-wrap:wrap}.button{display:inline-flex;align-items:center;min-height:44px;padding:0 18px;border:1px solid var(--border);border-radius:6px;background:#fff;text-decoration:none}.button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.badge{display:inline-block;padding:4px 10px;border:1.5px solid currentColor;border-radius:4px;font:500 13px/1.5 'IBM Plex Mono',monospace;letter-spacing:.08em}.verified,.pass{color:var(--verified)}.rejected,.fail{color:var(--rejected)}.unknown{color:var(--unknown)}.badge.verified{background:#E7F4EE}.badge.rejected{background:#FCEDE5}.badge.unknown{background:var(--page)}
.card{background:#fff;border:1px solid var(--border);border-radius:10px;overflow:hidden;min-width:0}.pad{padding:22px 24px}.card>h3,.lane-title{padding:14px 18px;border-bottom:1px solid var(--border)}.stack{display:flex;flex-direction:column;gap:16px;min-width:0}.lanes,.comparison,.receipt-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;align-items:start}.comparison{gap:0}.comparison>div{padding:24px 26px}.comparison>div+div{background:var(--paper);border-left:1px solid var(--border)}blockquote{margin:10px 0;font-size:22px;line-height:1.4;overflow-wrap:anywhere}
.metrics{display:flex;gap:28px;flex-wrap:wrap;padding:22px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}.metric{flex:1 1 220px}.metric strong{display:block;font-size:25px;font-weight:600}.metric span{display:block;color:var(--secondary)}
.table-box{max-width:100%;overflow:auto;background:#fff;border:1px solid var(--border);border-radius:8px}table{width:100%;border-collapse:collapse;text-align:left;font-size:13px}th,td{padding:10px 14px;vertical-align:top;border-bottom:1px solid var(--border)}th{font-weight:500;background:#F8F9FB;color:var(--secondary)}tbody tr:last-child td{border-bottom:0}.instances{min-width:850px}.commands{min-width:520px}.commands td:nth-child(2){min-width:220px;max-width:440px;overflow-wrap:anywhere}.predicates{min-width:580px}.predicates td:last-child{min-width:250px;white-space:pre-wrap;overflow-wrap:anywhere}
code,pre,.mono,.commands,.paper{font-family:'IBM Plex Mono',ui-monospace,SFMono-Regular,monospace}pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.7}code{font-size:.9em;overflow-wrap:anywhere}.inset{padding:14px 16px;background:var(--page);border-radius:6px}.appeal{padding:14px 18px;border:1px dashed #C7CDD6;background:#fff;border-radius:8px}.diff{white-space:pre;overflow:auto;padding:18px;background:#fff;border:1px solid var(--border);border-radius:8px}.diff span{display:block}.diff .added{background:#E7F4EE;color:var(--verified)}.diff .removed{background:#FCEDE5;color:var(--rejected)}
dl{margin:0;display:grid;grid-template-columns:130px minmax(0,1fr);gap:8px 16px}dt{color:var(--secondary)}dd{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}ul{padding-left:20px;margin:8px 0}.bundle li{margin:6px 0;overflow-wrap:anywhere}.paper{background:var(--paper);padding:26px 32px 30px;font-size:13px;line-height:1.75;border-top:1px dashed #B9B4A8;border-bottom:1px dashed #B9B4A8;min-width:0}.paper h2{font:500 16px/1.75 'IBM Plex Mono',monospace;letter-spacing:.12em}.paper dl{grid-template-columns:85px minmax(0,1fr);gap:4px 12px}.paper hr{border:0;border-top:1px dashed #B9B4A8;margin:18px 0}.stamp{text-align:center;padding-top:24px}.stamp .badge{font-size:20px;padding:8px 18px;border-width:2.5px;transform:rotate(-3deg)}
@media(max-width:760px){.header,main,footer{padding-left:20px;padding-right:20px}.header .secondary{margin-left:0}.lanes,.comparison,.receipt-layout{grid-template-columns:minmax(0,1fr)}.comparison>div+div{border-left:0;border-top:1px solid var(--border)}h1{font-size:28px}.paper{padding:22px 20px}.pad{padding:18px}dl{grid-template-columns:100px minmax(0,1fr)}}
"""


@dataclass(frozen=True)
class SiteSummary:
    out_dir: Path
    pilots: int
    instances: int
    pages: int
    raw_files: int


@dataclass
class _Run:
    record: dict[str, Any]
    record_path: Path
    directory: Path | None
    key: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)
    branches: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    raw: dict[str, Path] = field(default_factory=dict)

    @property
    def iid(self) -> str:
        return self.record["instance_id"]

    @property
    def result(self) -> dict[str, Any]:
        return self.artifacts.get("result.json", {})

    def artifact(self, filename: str, fallback: str) -> dict[str, Any]:
        return self.artifacts.get(filename, self.result.get(fallback) or {})

    @property
    def attempts(self) -> list[dict[str, Any]]:
        attempts = self.result.get("attempts") or []
        if not attempts:
            attempts = [{"number": n, "worker": a, "verdict": {"status": a.get("gate_status"), "claim_audit": a.get("claim_audit")}}
                        for n, a in enumerate(self.record.get("attempts", []), 1)]
        return sorted(attempts, key=lambda a: int(a["number"]))


def _text(value: Any) -> str:
    if value is None:
        return _NOT_RECORDED
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2)
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _e(value: Any) -> str:
    """The only way untrusted text enters HTML, including attributes."""
    return html.escape(_text(value), quote=True)


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _confined(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"artifact path escapes repository root: {path}")
    return resolved


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_run(path: Path, root: Path) -> _Run:
    path = _confined(path, root)
    record = _json(path)
    _safe_component(record.get("instance_id"), "instance id")
    directory = _confined(root / record["run_dir"], root) if record.get("run_dir") else None
    run = _Run(record, path, directory)
    run.raw["record.json"] = path
    if directory is None or not directory.is_dir():
        return run
    # The report helper reads this optional log even though the website does
    # not need it and never includes it in the raw bundle.
    _confined(directory / "agent/worker.jsonl", root)
    for name in ("input.json", "plan.json", "baseline.json", "disclosure.json", "result.json", "cost.json", "lock.txt"):
        candidate = _confined(directory / name, root)
        if candidate.is_file():
            run.raw[name] = candidate
            if name.endswith(".json"):
                run.artifacts[name] = _json(candidate)
    for attempt in run.attempts:
        number = int(attempt["number"])
        if number < 1:
            raise ValueError("attempt number must be positive")
        for name in ("verdict.json", "patch.diff", "filtered.diff", "witness/receipts.jsonl"):
            relative = f"attempts/{number}/{name}"
            candidate = _confined(directory / relative, root)
            if candidate.is_file():
                run.raw[relative] = candidate
                if name == "verdict.json":
                    run.artifacts[relative] = _json(candidate)
    for candidate in sorted(directory.glob("branches/*/receipts.jsonl")):
        _confined(candidate, root)
        branch = _safe_component(candidate.parent.name, "branch directory")
        run.branches[branch] = _jsonl(candidate)
        run.raw[f"branches/{branch}/receipts.jsonl"] = candidate
    return run


def _verdict(run: _Run, attempt: dict[str, Any]) -> dict[str, Any]:
    return run.artifacts.get(f"attempts/{int(attempt['number'])}/verdict.json", attempt.get("verdict") or {})


def _outcome(run: _Run) -> str:
    record = run.record
    if record.get("status") == "infra_error":
        return "infrastructure error"
    final = record.get("final") or {}
    if not run.attempts or not final or final.get("gate_status") == "ERROR":
        return "NO VERDICT"
    if final.get("gate_status") == "PASS":
        return "VERIFIED on appeal" if len(run.attempts) > 1 else "VERIFIED on first verdict"
    if final.get("gate_status") == "REJECTED":
        return "REJECTED"
    return "NO VERDICT"


def _stamp(run: _Run) -> str:
    outcome = _outcome(run)
    return "VERIFIED" if outcome.startswith("VERIFIED") else "REJECTED" if outcome == "REJECTED" else "NO VERDICT"


def _badge(label: str) -> str:
    css = {"VERIFIED": "verified", "REJECTED": "rejected", "NO VERDICT": "unknown"}[label]
    return f'<span class="badge {css}">{label}</span>'


def _link(page: str, target: str, label: Any, css: str = "") -> str:
    # Both paths are generated by this module, never taken from a record.
    href = posixpath.relpath(target, posixpath.dirname(page) or ".")
    return f'<a href="{_e(href)}" class="{_e(css)}">{_e(label)}</a>'


def _page(page: str, title: str, site_title: str, body: str, nav: str = "") -> str:
    css = posixpath.relpath("assets/site.css", posixpath.dirname(page) or ".")
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{_e(title)} | {_e(site_title)}</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&amp;family=IBM+Plex+Sans:wght@400;500;600&amp;display=swap">'
        f'<link rel="stylesheet" href="{_e(css)}">'
        '</head><body><header><div class="header">'
        + _link(page, "index.html", site_title, "brand")
        + f'<nav aria-label="Main">{_link(page, "index.html", "All runs")}{nav}</nav>'
        + '<span class="secondary">Recorded runs, model-free verdicts</span></div></header>'
        + f'<main>{body}</main><footer>{_FOOTER}</footer></body></html>\n'
    )


def _table(headings: Sequence[str], rows: Sequence[Sequence[str]], css: str = "") -> str:
    header = "".join(f'<th scope="col">{_e(h)}</th>' for h in headings)
    cells = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="table-box"><table class="{_e(css)}"><thead><tr>{header}</tr></thead><tbody>{cells}</tbody></table></div>'


def _dl(rows: Sequence[tuple[str, Any]]) -> str:
    return "<dl>" + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in rows) + "</dl>"


def _official(value: Any) -> str:
    return "resolved" if value is True else "not resolved" if value is False else _NOT_RECORDED


def _dollars(value: Any) -> str:
    return f"${float(value):.3f}" if value is not None else _NOT_RECORDED


def _number(value: Any, unit: str = "") -> str:
    return f"{float(value):.3f}{unit}" if value is not None else _NOT_RECORDED


def _cost(run: _Run) -> list[tuple[str, Any]]:
    cost = run.record.get("cost") or {}
    disclosure = run.artifact("disclosure.json", "disclosure")
    rows = [("Tokens", cost.get("tokens")), ("Model dollars", _dollars(cost.get("model_dollars", cost.get("dollars")))),
            ("Sandbox time", _number(cost.get("sandbox_lifetime_seconds"), " seconds"))]
    executor = run.record.get("executor_kind") or disclosure.get("executor_kind")
    sandbox = cost.get("sandbox_dollars_estimate")
    if executor == "tokenfactory":
        value = f"{float(sandbox):.3f}" if sandbox is not None else _NOT_RECORDED
        rows.append(("Sandbox cost", f"Token Factory reported cost: {value} (unit not published)"))
    elif executor == "daytona":
        rows.append(("Sandbox cost", "Daytona sandbox estimate: " + _dollars(sandbox)))
    else:
        rows.append(("Sandbox cost", _NOT_RECORDED))
    return rows


def _repository(run: _Run) -> tuple[str, str]:
    source = run.artifact("input.json", "input").get("source") or {}
    repo = source.get("url") or source.get("repo")
    image = source.get("image", "")
    if not repo and str(image).startswith("docker.io/swerebenchv2/"):
        image_repo = str(image).split("/", 2)[2].split(":", 1)[0]
        candidate = run.iid.rsplit("-", 1)[0]
        repo = candidate.replace("__", "/") if candidate.replace("__", "-") == image_repo else image_repo + " (image repository)"
    commit = source.get("commit")
    tag = re.search(r":\d+-([0-9a-f]{7,40})$", str(image))
    if not commit and tag:
        commit = tag.group(1) + " (image tag)"
    if not commit:
        for receipt in run.branches.get("base", []):
            command = str(receipt.get("cmd", ""))
            # A receipts snapshot adds the spec patch and creates a new commit.
            # Its rev-parse output is not the upstream base commit.
            if "rev-parse" in command and "commit" not in command:
                match = re.search(r"\b[0-9a-f]{40}\b", str(receipt.get("stdout_tail", "")))
                if match:
                    commit = match.group()
                    break
    return str(repo or _NOT_RECORDED), str(commit or _NOT_RECORDED)


def _predicates(verdict: dict[str, Any]) -> str:
    rows = []
    for predicate in verdict.get("predicates") or []:
        pid = predicate.get("id")
        passed = predicate.get("passed") is True
        rows.append([f'<code>{_e(pid)}</code>', _e(predicate.get("name") or _NAMES.get(pid, _NOT_RECORDED)),
                     f'<span class="{"pass" if passed else "fail"}">{"PASS" if passed else "FAIL"}</span>', _e(predicate.get("evidence"))])
    if not rows:
        return f'<p class="secondary">Predicates {_NOT_RECORDED}. {_e(verdict.get("error"))}</p>'
    return _table(("Predicate", "Name", "Status", "Evidence"), rows, "predicates")


def _commands(receipts: Sequence[dict[str, Any]]) -> str:
    rows = []
    for receipt in receipts:
        digest = receipt.get("tree_digest") or receipt.get("patch_sha256") or receipt.get("image_after")
        rows.append([_e(receipt.get("kind")), _e(receipt.get("cmd") or receipt.get("path")),
                     _e(receipt.get("exit_code")), _e(_number(receipt.get("duration_s"), "s")),
                     _e(str(digest)[:12] if digest else None), _e(receipt.get("timed_out"))])
    return _table(("Kind", "Command or path", "Exit", "Duration", "Digest", "Timed out"), rows, "commands") if rows else '<p class="pad secondary">Command receipts not recorded.</p>'


def _agent_receipts(run: _Run) -> dict[int, list[dict[str, Any]]]:
    branch = run.result.get("agent_branch_id")
    if branch is None and run.attempts:
        branch = _verdict(run, run.attempts[0]).get("branch_id")
    receipts = run.branches.get(branch, [])
    groups: dict[int, list[dict[str, Any]]] = {}
    cursor = 0
    # The worker's receipt_ids are cumulative across an appeal. Executor diff
    # receipts delimit the complete attempt, including post-finish patch capture.
    for attempt in run.attempts:
        stop = next((n + 1 for n in range(cursor, len(receipts)) if receipts[n].get("kind") == "diff"), len(receipts))
        groups[int(attempt["number"])] = receipts[cursor:stop]
        cursor = stop
    return groups


def _witness_receipts(run: _Run, attempt: dict[str, Any]) -> list[dict[str, Any]]:
    witness = run.branches.get(attempt.get("witness_branch_id"), [])
    if not witness and attempt.get("number"):
        source = run.raw.get(f"attempts/{int(attempt['number'])}/witness/receipts.jsonl")
        if source:
            witness = _jsonl(source)
    return witness


def _claims(attempt: dict[str, Any]) -> str:
    worker = attempt.get("worker") or {}
    return _dl([( "Finish summary", worker.get("summary") or worker.get("end_summary")),
                ("Worker outcome", worker.get("end")), ("Claims", worker.get("claims"))])


def _comparison(attempt: dict[str, Any], verdict: dict[str, Any]) -> str:
    return ('<div class="comparison card"><div><h3>What it said</h3>' + _claims(attempt)
            + '</div><div><h3>What the record shows</h3>'
            + _dl([("Claim audit", verdict.get("claim_audit")), ("Claim evidence", verdict.get("claim_evidence"))]) + '</div></div>')


def _bundle(run: _Run, page: str) -> str:
    links = "".join(f'<li>{_link(page, f"raw/{run.key}/{name}", name)}</li>' for name in sorted(run.raw))
    return '<section class="card pad"><h2>The bundle</h2><p class="secondary">Recorded JSON and patches. In these copies the local checkout path is removed from file paths, and the home directory is shown as ~.</p><ul class="bundle">' + links + '</ul></section>'


def _patch(run: _Run) -> str:
    if _stamp(run) != "VERIFIED":
        return ""
    selected = run.result.get("selected_patch_path")
    # Never follow the selected_patch_path string as a filesystem path.
    for attempt in reversed(run.attempts):
        relative = f"attempts/{int(attempt['number'])}/filtered.diff"
        if (selected is None or selected == relative) and relative in run.raw:
            return run.raw[relative].read_text(encoding="utf-8")
    return ""


def _patch_counts(patch: str) -> str:
    files = sum(line.startswith("diff --git ") for line in patch.splitlines())
    added = sum(line.startswith("+") and not line.startswith("+++") for line in patch.splitlines())
    removed = sum(line.startswith("-") and not line.startswith("---") for line in patch.splitlines())
    noun = "file" if files == 1 else "files"
    return f"{files} {noun}, {added} added and {removed} removed lines"


def _diff(patch: str) -> str:
    rows = []
    for line in patch.splitlines():
        css = "added" if line.startswith("+") and not line.startswith("+++") else "removed" if line.startswith("-") and not line.startswith("---") else ""
        rows.append(f'<span class="{css}">{_e(line) or " "}</span>')
    return '<pre class="diff">' + "".join(rows) + '</pre>'


def _run_page(run: _Run, title: str) -> str:
    page = f"run/{run.key}.html"
    repo, commit = _repository(run)
    patch = _patch(run)
    costs = _cost(run)
    attempts = len(run.attempts)
    appeals = max(attempts - 1, 0)
    summary = f"{attempts} attempt{'s' if attempts != 1 else ''}, {appeals} appeal{'s' if appeals != 1 else ''}. "
    if patch:
        summary += _patch_counts(patch) + ". "
    else:
        if run.attempts:
            number = int(run.attempts[-1]["number"])
            attempted = run.raw.get(f"attempts/{number}/filtered.diff")
            if attempted:
                summary += "Final attempted patch: " + _patch_counts(attempted.read_text(encoding="utf-8")) + ". "
        summary += "No patch shipped. " if _stamp(run) != "VERIFIED" else "Shipped patch not recorded. "
    summary += ". ".join(f"{k}: {_text(v)}" for k, v in costs[:3]) + "."
    body = (f'<section class="hero"><div>{_badge(_stamp(run))}<h1>{_e(run.iid)}</h1>'
            f'<p>{_e(_outcome(run))}</p><p class="secondary">{_e(summary)}</p></div><div class="actions">'
            + _link(page, f"receipt/{run.key}.html", "Open receipt", "button primary") + '</div></section>')
    if run.record.get("reason") or not run.attempts:
        body += '<section class="card pad"><h2>Run status</h2>' + _dl([("Status", run.record.get("status")), ("Reason", run.record.get("reason")), ("Attempts", "not recorded" if not run.attempts else len(run.attempts))]) + '</section>'
    plan = run.artifacts.get("plan.json", {})
    inp = run.artifact("input.json", "input")
    issue = "\n".join(str(inp.get("issue", _NOT_RECORDED)).splitlines()[:8])
    body += '<section class="card pad stack"><h2>The plan</h2>' + _dl([("Repository", repo), ("Base commit", commit), ("Issue", issue), ("Files to edit", plan.get("files_to_edit")), ("Approach", plan.get("approach"))]) + '</section>'
    agent = _agent_receipts(run)
    records = run.record.get("attempts") or []
    for position, attempt in enumerate(run.attempts):
        number = int(attempt["number"])
        verdict = _verdict(run, attempt)
        attempt_stamp = {"PASS": "VERIFIED", "REJECTED": "REJECTED"}.get(verdict.get("status"), "NO VERDICT")
        body += f'<section class="stack"><h2>Attempt {number}{", on appeal" if position else ""}</h2>{_badge(attempt_stamp)}'
        if position:
            recorded = attempt.get("appeal_evidence") or (attempt.get("worker") or {}).get("appeal_evidence")
            evidence = recorded or _appeal_text(_verdict(run, run.attempts[position - 1]))
            body += '<div class="stack"><h3>Appeal evidence sent to the agent</h3><pre class="appeal">' + _e(evidence) + '</pre></div>'
        branch = attempt.get("witness_branch_id")
        witness = _witness_receipts(run, attempt)
        body += ('<div class="lanes"><div class="card"><h3>Agent branch</h3>'
                 + _commands(agent.get(number, [])) + '<div class="pad">' + _claims(attempt) + '</div></div>'
                 + '<div class="stack"><div class="card"><h3>Witness branch ' + _e(branch) + '</h3>'
                 + _commands(witness) + '</div><h3>Gate predicate checklist</h3>' + _predicates(verdict) + '</div></div>')
        body += _comparison(attempt, verdict)
        official = records[position] if position < len(records) else {}
        body += '<div class="card pad"><h3>Official SWE-rebench grade</h3>' + _dl([("official_resolved", official.get("official_resolved")), ("agreement", official.get("agreement"))]) + '</div></section>'
    body += '<section class="stack"><h2>Shipped patch</h2>'
    body += _diff(patch) if patch else '<p class="secondary">No patch shipped. Filtered patch not recorded.</p>' if _stamp(run) == "VERIFIED" else '<p class="secondary">No patch shipped.</p>'
    body += '</section>' + '<section class="card pad">' + _dl(costs) + '</section>' + _bundle(run, page)
    return _page(page, run.iid, title, body)


def _appeal_text(previous: dict[str, Any]) -> str | None:
    """The message the worker received on appeal, rebuilt from the verdict that caused it."""
    try:
        verdict = Verdict.model_validate(previous)
    except ValueError:
        return None
    return f"{_appeal_evidence(verdict)}\n\n{APPEAL_INSTRUCTION}"


def _test_status(summary: dict[str, Any], test: str) -> str:
    for name, status in (("passed", "passed"), ("failed", "failed"), ("errors", "error"), ("skipped", "skipped")):
        if test in (summary.get(name) or []):
            return status
    return _NOT_RECORDED


def _paper_rows(run: _Run) -> list[tuple[str, Any]]:
    repo, commit = _repository(run)
    baseline = run.artifact("baseline.json", "baseline")
    before = (baseline.get("runs") or [{}])[0]
    last = run.attempts[-1] if run.attempts else {}
    witness = _witness_receipts(run, last)
    after = next((r["junit"] for r in reversed(witness) if r.get("junit")), {})
    inp = run.artifact("input.json", "input")
    tests = baseline.get("target") or inp.get("spec_tests") or []
    spec = "\n".join(f"{test}: {_test_status(before, test)} → {_test_status(after, test)}" for test in tests) or _NOT_RECORDED
    predicates = {p["id"]: p.get("evidence") for p in _verdict(run, last).get("predicates", [])} if last else {}
    history = "\n".join(f"attempt {a['number']}: {_verdict(run, a).get('status', _NOT_RECORDED)}" for a in run.attempts) or _NOT_RECORDED
    rows = [("instance", run.iid), ("repo", f"{repo} @ {commit}"), ("spec", spec),
            ("kept", predicates.get("R2_pass_to_pass")), ("removed and new skips", predicates.get("R3_no_shrink")),
            ("scope", predicates.get("R4_patch_scope")), ("dropped", last.get("dropped_paths")),
            ("witness", predicates.get("R5_provenance")), ("checkpoint", run.result.get("checkpoint_id")), ("history", history)]
    for attempt in run.attempts:
        worker = attempt.get("worker") or {}
        verdict = _verdict(run, attempt)
        rows.extend([(f"said ({attempt['number']})", worker.get("summary") or worker.get("end_summary")),
                     ("claims", worker.get("claims")), ("record", f"{_text(verdict.get('claim_audit'))}: {_text(verdict.get('claim_evidence'))}")])
    disclosure = run.artifact("disclosure.json", "disclosure")
    rows.extend([( "model and settings", disclosure.get("model")), ("executor", disclosure.get("executor_kind")),
                 ("tests digests", disclosure.get("test_digests")), ("config digests", disclosure.get("pytest_config_digests")),
                 ("lock digest", disclosure.get("lock_sha256")), ("lock.txt", "recorded" if "lock.txt" in run.raw else _NOT_RECORDED),
                 ("tool", disclosure.get("receipts_version"))])
    rows.extend(_cost(run))
    return rows


def _receipt_page(run: _Run, title: str) -> str:
    page = f"receipt/{run.key}.html"
    rows = _paper_rows(run)
    commands = ("git clone https://github.com/zeyusuntt/receipts && cd receipts\nuv sync\n"
                f"uv run receipts reverify receipts/{run.iid}.json")
    pr = f"Receipts verification: {_stamp(run)}\nInstance: {run.iid}\n\n"
    pr += "\n".join(f"{name}: {_text(value)}" for name, value in rows)
    body = ('<div class="receipt-layout"><section class="paper"><h2>RECEIPTS</h2><hr>'
            + _dl(rows) + '<div class="stamp">' + _badge(_stamp(run)) + '</div></section>'
            + '<aside class="stack"><section class="card pad stack"><h2>Re-verify it yourself</h2>'
            + '<p class="secondary">Run these commands with the exported receipt bundle.</p><pre class="inset">'
            + _e(commands) + '</pre></section><section class="card pad stack"><h2>PR description</h2><pre>'
            + _e(pr) + '</pre></section>' + _bundle(run, page) + '</aside></div>')
    return _page(page, f"Receipt {run.iid}", title, body, _link(page, f"run/{run.key}.html", "Back to the run"))


def _percent(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else _NOT_RECORDED


def _pilot_section(label: str, report: Report, runs: Sequence[_Run]) -> str:
    a, b = report.configuration_a, report.configuration_b
    rate = a.false_done_rate
    metrics = [("A: false dones of claimed dones", f"{a.false_dones} of {a.claimed_dones}",
                f"{_percent(rate.value)}; 95% Wilson interval {_percent(rate.lower_95)} to {_percent(rate.upper_95)}"),
               ("B: verified fixes", str(b.verified_fixes), f"{b.first_verdict} on first verdict; {b.appeal} on appeal"),
               ("Shipped false dones", str(b.shipped_false_dones), "Official SWE-rebench grading"),
               ("Model dollars per verified fix", _dollars(b.cost_per_verified_fix.model_dollars),
                "Model spend: " + _dollars(report.spend.all_runs.model_dollars))]
    body = '<section class="stack"><h2>' + _e(label) + '</h2><div class="metrics">'
    body += "".join(f'<div class="metric"><span>{_e(name)}</span><strong>{_e(value)}</strong><span>{_e(detail)}</span></div>' for name, value, detail in metrics) + '</div>'
    body += '<p class="secondary">B verified fixes require a gate PASS and official resolution. Run verdicts show the gate result; official grades are listed separately.</p>'
    if any((run.record.get("executor_kind") or "") == "tokenfactory" for run in runs):
        body += ('<p class="secondary">Token Factory reported sandbox cost over all runs: '
                 + _e(f"{report.spend.all_runs.sandbox_dollars_estimate:.3f}") + ' (unit not published).</p>')
    rows = []
    for run in runs:
        first = (run.record.get("attempts") or [{}])[0]
        final = run.record.get("final") or {}
        claimed = {True: "yes", False: "no"}.get(first.get("claimed_done"), _NOT_RECORDED)
        rows.append([_e(run.iid), _e(claimed), _e(_official(first.get("official_resolved"))),
                     _e(_outcome(run)), _e(_official(final.get("official_resolved"))),
                     _link("index.html", f"run/{run.key}.html", "Run"), _link("index.html", f"receipt/{run.key}.html", "Receipt")])
    body += _table(("Instance", "A claimed done", "A official", "B outcome", "B official", "Run", "Receipt"), rows, "instances")
    return body + '</section>'


def _ordered(runs: Sequence[_Run], pilot: Path) -> list[_Run]:
    progress = pilot / "progress.jsonl"
    if not progress.is_file():
        return sorted(runs, key=lambda r: r.iid)
    rows = _jsonl(progress)
    # Position is the original run order, while JSONL append order can reflect
    # concurrent completion. Older ledgers without positions keep line order.
    positions = {}
    for n, row in enumerate(rows):
        positions.setdefault(row.get("instance_id"), row.get("candidate_position", n + 1))
    return sorted(runs, key=lambda r: (positions.get(r.iid, float("inf")), r.iid))


_TEXT_SUFFIXES = {".json", ".jsonl", ".diff", ".txt"}


def _without_checkout_path(source: Path, prefixes: Sequence[str]) -> bytes:
    """Copy a record, making paths under the local checkout repository-relative."""
    data = source.read_bytes()
    if source.suffix not in _TEXT_SUFFIXES:
        return data
    text = data.decode("utf-8")
    for prefix in prefixes:
        text = text.replace(prefix + "/", "").replace(prefix, ".")
    # Anything else under the home directory (tool caches, other folders) keeps its
    # shape but not the account name.
    home = str(Path.home())
    if len(home) > 1:
        text = text.replace(home + "/", "~/").replace(home, "~")
    return text.encode("utf-8")


def build_site(
    pilot_dirs: Sequence[Path], out_dir: Path, *, repo_root: Path, title: str = "Receipts",
    strip_prefixes: Sequence[Path] = (),
) -> SiteSummary:
    """Write static HTML and a small raw bundle; return generated file counts.

    Record paths must stay within repo_root. Repeated instance ids across pilots
    get deterministic pilot subdirectories; unique ids retain the short URLs.
    Output must be separate from the inputs. Rebuilding overwrites generated
    files without deleting unrelated files from the output directory.
    """
    root = repo_root.resolve()
    if not pilot_dirs:
        raise ValueError("at least one pilot directory is required")
    # The order given is the order of importance: the first pilot keeps short URLs.
    pilots = list(dict.fromkeys(_confined(Path(p), root) for p in pilot_dirs))
    groups = []
    for pilot in pilots:
        if not pilot.is_dir():
            raise ValueError(f"pilot directory does not exist: {pilot}")
        runs = [_load_run(p, root) for p in sorted(pilot.glob("*/record.json"))]
        if len({run.iid for run in runs}) != len(runs):
            raise ValueError(f"duplicate instance id within pilot: {pilot}")
        # The unchanged report also loads retry archives and optional run files.
        # Validate their record paths before handing the directory to it.
        for p in sorted(pilot.glob("*/record.*.json")):
            _load_run(p, root)
        _confined(pilot / "progress.jsonl", root)
        groups.append((pilot, _ordered(runs, pilot)))
    names = [pilot.name for pilot, _ in groups]
    if len(set(names)) != len(names):
        raise ValueError("pilot directories must have distinct names")
    out = out_dir.resolve()
    if out == root or any(out == pilot or out.is_relative_to(pilot) or pilot.is_relative_to(out) for pilot in pilots):
        raise ValueError("output directory must be separate from pilot inputs")
    for _, runs in groups:
        for run in runs:
            if run.directory and (out == run.directory or out.is_relative_to(run.directory) or run.directory.is_relative_to(out)):
                raise ValueError("output directory must be separate from run inputs")
    sections = []
    raw_count = 0
    total = 0
    # Load and render before writing, so invalid input does not publish half a site.
    pages: dict[str, str] = {}
    raw_files: dict[str, Path] = {}
    claimed: set[str] = set()
    for pilot, runs in groups:
        report = build_report_from_directory(pilot)
        namespace = _safe_component(pilot.name, "pilot directory")
        for run in runs:
            run.key = run.iid if run.iid not in claimed else f"{namespace}/{run.iid}"
            claimed.add(run.iid)
            pages[f"run/{run.key}.html"] = _run_page(run, title)
            pages[f"receipt/{run.key}.html"] = _receipt_page(run, title)
            for name, source in sorted(run.raw.items()):
                raw_files[f"raw/{run.key}/{name}"] = source
            raw_count += len(run.raw)
        label = pilot.relative_to(root).as_posix()
        sections.append(_pilot_section(label, report, runs))
        total += len(runs)
    body = '<section class="stack"><h1>' + _e(title) + '</h1><p class="secondary">The agent said done. These are the recorded checks, verdicts and official grades.</p></section>' + "".join(sections)
    pages["index.html"] = _page("index.html", "All runs", title, body)
    for relative in [*pages, "assets/site.css", *raw_files]:
        if not (out / relative).resolve().is_relative_to(out):
            raise ValueError(f"output path escapes site directory: {relative}")
    for relative, contents in sorted({**pages, "assets/site.css": _CSS}.items()):
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8", newline="\n")
    checkouts = {str(repo_root), str(root)}
    for extra in strip_prefixes:
        checkouts.update({str(extra), str(Path(extra).resolve())})
    prefixes = sorted(checkouts, key=len, reverse=True)
    for relative, source in sorted(raw_files.items()):
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_without_checkout_path(source, prefixes))
    return SiteSummary(out, len(pilots), total, len(pages), raw_count)


__all__ = ["SiteSummary", "build_site"]
