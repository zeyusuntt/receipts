"""Render recorded pilot runs as a deterministic, offline static website."""

from __future__ import annotations

import html
import json
import posixpath
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from receipts.agent.worker import APPEAL_INSTRUCTION
from receipts.models import Verdict
from receipts.orchestrate import _appeal_evidence
from receipts.pilot.report import Report, build_report_from_directory


_NOT_RECORDED = "not recorded"
_PILOT_TITLES = {
    "v2-P": "Primary sample: 100 held-out tasks, Nemotron 3 Super",
    "v2-arm-lightning": "Exploratory: the first 30 tasks again with Nemotron 3.5 Lightning",
}
_FOOTER = "Generated from the run records by receipts site."
_NAMES = {
    "R1_fail_to_pass": "Failing specification tests now pass",
    "R2_pass_to_pass": "Previously passing tests kept",
    "R3_no_shrink": "No removed tests or new skips",
    "R4_patch_scope": "Patch scope",
    "R5_provenance": "Witness chain and patch digest",
    "R7_no_shortcuts": "No shortcut in the patch",
    "R8_review": "Independent reviews did not both object",
    "R8_review_advisory": "Independent review, advisory",
    "R6_claim_audit": "Agent claim audit (advisory)",
}
_CSS = """\
:root{--bg:#fff;--panel:#f3f4f2;--ink:#1d2124;--muted:#565d63;--rule:#d5d8d4;--link:#1f4f7a;--ok:#0d6831;--bad:#b42318;--unknown:#565d63;--sans:'Red Hat Text',system-ui,sans-serif;--mono:'Red Hat Mono',ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans)}
a{color:var(--link);text-decoration-color:#9fb3c8;text-underline-offset:3px}a:hover{text-decoration-color:currentColor}a:focus-visible,summary:focus-visible{outline:2px solid var(--link);outline-offset:2px}
header{border-bottom:1px solid var(--rule)}.header,main,footer{max-width:1280px;margin:auto;padding:14px 24px}
.header{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 18px;padding-top:9px;padding-bottom:9px}.brand{font:600 15px/1.5 var(--mono);color:var(--ink);text-decoration:none}.header nav{display:flex;gap:16px;flex-wrap:wrap;font-size:14px}.header .secondary{margin-left:auto;font-size:13px}
main{padding-top:18px;padding-bottom:48px;display:flex;flex-direction:column;gap:30px}footer{font-size:12px;color:var(--muted);padding-top:0;padding-bottom:24px}
h1,h2,h3,p{margin:0}h1{font-size:21px;line-height:1.3;font-weight:600}h2{font-size:16px;line-height:1.35;font-weight:600}h3{font-size:14px;font-weight:600}h1,h2,h3{overflow-wrap:anywhere}p{max-width:80ch}section{min-width:0}.secondary,.meta{color:var(--muted)}.meta{font-size:14px}
.hero{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;flex-wrap:wrap}.hero>div{min-width:0}.hero h1{margin:8px 0}.actions{display:flex;gap:10px;flex-wrap:wrap}
.button{display:inline-flex;align-items:center;min-height:36px;padding:0 14px;border:1px solid var(--rule);background:var(--panel);color:var(--ink);text-decoration:none;font-size:14px}.button:hover{border-color:var(--muted)}.button.primary{border-color:var(--link);color:var(--link);background:#fff}
.badge{display:inline-block;padding:0 6px;border:1px solid currentColor;font:600 12px/1.7 var(--mono)}.verified,.pass,.ok{color:var(--ok)}.rejected,.fail,.bad{color:var(--bad)}.unknown{color:var(--unknown)}
.card{background:#fff;border:1px solid var(--rule);min-width:0}.pad{padding:16px 18px}.card>h3,.lane-title{padding:10px 14px;border-bottom:1px solid var(--rule);background:var(--panel)}.stack{display:flex;flex-direction:column;gap:12px;min-width:0}.stack>.badge{align-self:flex-start}.lanes,.comparison,.receipt-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start}.comparison{gap:0}.comparison>div{padding:16px 18px;display:flex;flex-direction:column;gap:10px}.comparison>div+div{border-left:1px solid var(--rule)}blockquote{margin:8px 0;font-size:18px;line-height:1.4;overflow-wrap:anywhere}
.metrics{display:flex;gap:24px;flex-wrap:wrap;padding:14px 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}.metric{flex:1 1 200px}.metric strong{display:block;font:600 20px/1.4 var(--mono)}.metric span{display:block;color:var(--muted);font-size:14px}
.table-box{max-width:100%;overflow:auto;border:1px solid var(--rule)}table{width:100%;border-collapse:collapse;text-align:left;font-size:13px}th,td{padding:7px 10px;vertical-align:top;border-bottom:1px solid var(--rule)}th{font-weight:600;background:var(--panel);color:var(--muted)}tbody tr:last-child td{border-bottom:0}.instances{min-width:850px}.instances td:first-child{font-family:var(--mono)}.commands{min-width:520px}.commands td:nth-child(2){min-width:220px;max-width:440px;overflow-wrap:anywhere}.predicates{min-width:580px}.predicates td:last-child{min-width:250px;white-space:pre-wrap;overflow-wrap:anywhere}
code,pre,.mono,.commands,.paper{font-family:var(--mono)}pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.55}code{font-size:.92em;overflow-wrap:anywhere}.inset,.term{padding:10px 12px;background:var(--panel);border:1px solid var(--rule)}.appeal{padding:10px 12px;border:1px dashed var(--rule)}.diff{white-space:pre;overflow:auto;padding:12px;border:1px solid var(--rule)}.diff span{display:block}.diff .added{background:#e8f3ec;color:var(--ok)}.diff .removed{background:#fbeceb;color:var(--bad)}
dl{margin:0;display:grid;grid-template-columns:130px minmax(0,1fr);gap:6px 14px}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}ul{padding-left:20px;margin:6px 0}.bundle li{margin:4px 0;overflow-wrap:anywhere}
.paper{background:var(--panel);border:1px solid var(--rule);padding:18px 22px;font-size:13px;line-height:1.65;min-width:0}.paper h2{font:600 14px/1.6 var(--mono)}.paper dl{grid-template-columns:100px minmax(0,1fr);gap:4px 12px}.paper hr{border:0;border-top:1px dashed var(--rule);margin:12px 0}.stamp{padding-top:16px}.stamp .badge{font-size:15px;padding:2px 10px}
details{font-family:var(--sans);white-space:normal}summary{cursor:pointer;padding:4px 0;color:var(--link)}details pre{padding:8px 0}.all-steps>summary{padding:8px 14px}.claims{font-size:14px}.files{margin:0}.index-lead{max-width:1000px}.index-lead h1{font-size:28px;line-height:1.25}.paper dt{font-size:12px}.paper dd{white-space:pre-line}
.intro{display:flex;flex-direction:column;gap:8px}.intro h1{font-size:27px;line-height:1.25;font-weight:700}.intro p{font-size:16px;max-width:68ch}.totals p,.roles p,.check p{font-size:14px}
.lead-grid{display:grid;grid-template-columns:minmax(0,1.9fr) minmax(0,1fr);gap:28px;align-items:start}.run-log,.side,.totals,.roles,.check,.limits{display:flex;flex-direction:column;gap:8px;min-width:0}.side{gap:22px}
.log{font:12.5px/1.5 var(--mono)}.log td{padding:2px 10px;border-bottom:0}.log td:first-child{color:var(--muted);white-space:nowrap;width:1%}.log td:nth-child(2){overflow-wrap:anywhere}.log td:last-child{white-space:nowrap;text-align:right;font-weight:600;width:1%}.log tr.group th{padding:5px 10px 3px;color:var(--ink);text-align:left;border-top:1px solid var(--rule);border-bottom:0}.log tr.group:first-child th{border-top:0}
.kv{font-size:14px}.kv td{padding:6px 10px 6px 0;border-bottom:1px solid var(--rule)}.kv td:first-child{color:var(--muted);width:48%}.totals .kv td:last-child{font:600 14px/1.5 var(--mono);text-align:right;padding-right:0}.kv tbody tr:last-child td{border-bottom:1px solid var(--rule)}
.check-grid{display:flex;flex-direction:column;gap:12px}.check-grid>div{display:flex;flex-direction:column;gap:8px;min-width:0}.term{white-space:pre;overflow-x:auto;overflow-wrap:normal}.check h3{margin-top:4px}
.limits ul{margin:0;display:flex;flex-direction:column;gap:6px;max-width:90ch;font-size:14px}
@media(max-width:900px){.lead-grid{grid-template-columns:minmax(0,1fr)}}
@media(max-width:760px){.header,main,footer{padding-left:16px;padding-right:16px}.header .secondary{margin-left:0}.lanes,.comparison,.receipt-layout{grid-template-columns:minmax(0,1fr)}.comparison>div+div{border-left:0;border-top:1px solid var(--rule)}.index-lead h1{font-size:22px}.paper{padding:14px}dl{grid-template-columns:100px minmax(0,1fr)}.log tr:not(.group){display:grid;grid-template-columns:auto minmax(0,1fr);padding:2px 0}.log td{padding:0 10px}.log td:first-child,.log td:last-child{grid-row:1;width:auto}.log td:last-child{grid-column:2}.log td:nth-child(2){grid-row:2;grid-column:1/-1;padding-left:18px}.log tr.detail:not(.group){display:none}.intro h1{font-size:20px}.term{font-size:11.5px}}
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
        for name in ("verdict.json", "review.json", "patch.diff", "filtered.diff", "witness/receipts.jsonl"):
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
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Red+Hat+Mono:wght@400;500;600&amp;family=Red+Hat+Text:wght@400;500;700&amp;display=swap">'
        f'<link rel="stylesheet" href="{_e(css)}">'
        '</head><body><header><div class="header">'
        + _link(page, "index.html", site_title, "brand")
        + f'<nav aria-label="Main">{_link(page, "index.html", "All runs")}{nav}'
        + f'<a href="{_REPO_URL}/blob/main/REPORT-v2.md" rel="noopener">Report</a>'
        + f'<a href="{_REPO_URL}" rel="noopener">Code</a></nav>'
        + '</div></header>'
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


def _dollars(value: Any, *, decimals: int | None = None) -> str:
    if value is None:
        return _NOT_RECORDED
    amount = float(value)
    precision = decimals if decimals is not None else 2 if amount >= .01 else 3
    return f"${amount:.{precision}f}"


def _duration(value: Any) -> str:
    if value is None:
        return _NOT_RECORDED
    minutes, seconds = divmod(int(float(value) + .5), 60)
    return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"


def _short_ids(value: Any) -> str:
    return re.sub(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b",
                  lambda m: m.group()[:8], _text(value))


def _model_name(run: _Run) -> str:
    model = run.artifact("disclosure.json", "disclosure").get("model") or {}
    name = model.get("model") if isinstance(model, dict) else model
    if str(name).startswith("nvidia/nemotron-3-super"):
        return "NVIDIA Nemotron 3 Super"
    if str(name).startswith("nvidia/nemotron-3.5-lightning"):
        return "NVIDIA Nemotron 3.5 Lightning"
    return _text(name)


def _model_settings(run: _Run) -> str:
    model = run.artifact("disclosure.json", "disclosure").get("model") or {}
    if not isinstance(model, dict):
        return _model_name(run)
    thinking = {True: "on", False: "off"}.get(model.get("thinking"), _NOT_RECORDED)
    return (f"{_model_name(run)}\nthinking {thinking} · temperature {_text(model.get('temperature'))}"
            f" · top_p {_text(model.get('top_p'))}")


def _number(value: Any, unit: str = "") -> str:
    return f"{float(value):.3f}{unit}" if value is not None else _NOT_RECORDED


def _cost(run: _Run) -> list[tuple[str, Any]]:
    cost = run.record.get("cost") or {}
    disclosure = run.artifact("disclosure.json", "disclosure")
    tokens = cost.get("tokens")
    rows = [("Tokens", f"{int(tokens):,} tokens" if tokens is not None else _NOT_RECORDED),
            ("Model cost", _dollars(cost.get("model_dollars", cost.get("dollars")))),
            ("Sandbox time", _duration(cost.get("sandbox_lifetime_seconds")))]
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
        evidence = predicate.get("evidence")
        display = _short_ids(evidence) if pid == "R5_provenance" else _text(evidence)
        rows.append([f'<code>{_e(pid)}</code>', _e(predicate.get("name") or _NAMES.get(pid, _NOT_RECORDED)),
                     f'<span class="{"pass" if passed else "fail"}">{"PASS" if passed else "FAIL"}</span>',
                     _evidence_cell(display, _text(evidence))])
    if not rows:
        return f'<p class="secondary">Predicates {_NOT_RECORDED}. {_e(verdict.get("error"))}</p>'
    return _table(("Predicate", "Name", "Status", "Evidence"), rows, "predicates")


def _evidence_cell(display: str, full: str) -> str:
    if len(display) <= 600:
        return _e(display)
    return _e(display[:599] + "…") + '<details><summary>full evidence</summary><pre>' + _e(full) + '</pre></details>'


def _pytest_args(command: str, *, witness: bool = False) -> list[str] | None:
    """Simplify only the recorded trusted runner, retaining meaningful test options."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    runner = next((i for i, token in enumerate(tokens)
                   if re.fullmatch(r"/opt/receipts(?:-[A-Za-z0-9]+)?/receipts_pytest\.py", token)
                   and i >= 2 and tokens[i - 1] == "-I"), None)
    if runner is None and witness:
        if tokens[:1] == ["pytest"]:
            runner = 0
        elif tokens[:3] == ["python", "-m", "pytest"]:
            runner = 2
    if runner is None:
        return None
    args = []
    tokens = tokens[runner + 1:]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--no-header", "-rA", "--tb=line", "--color=no", "--continue-on-collection-errors"} or token.startswith("--junitxml="):
            i += 1
        elif (token, tokens[i + 1] if i + 1 < len(tokens) else None) in {
            ("-p", "no:cacheprovider"), ("-W", "ignore::DeprecationWarning"), ("-o", "junit_family=xunit1"),
        }:
            i += 2
        elif token == "--junitxml" and i + 1 < len(tokens):
            i += 2
        else:
            args.append(token)
            i += 1
    return args


def _display_command(receipt: dict[str, Any]) -> str:
    kind = receipt.get("kind")
    command = _text(receipt.get("cmd") or receipt.get("path"))
    if kind == "write":
        return "write " + _text(receipt.get("path"))
    if kind == "apply":
        digest = receipt.get("patch_sha256") or (receipt.get("diff") or {}).get("patch_sha256")
        return "apply patch" + (" " + str(digest)[:12] if digest else "")
    if kind == "diff":
        return "capture patch"
    args = _pytest_args(command, witness=kind == "verification")
    if args is not None:
        prefix = "pytest (witness)" if kind == "verification" else "pytest"
        return prefix + (" " + shlex.join(args) if args else "")
    if kind == "verification":
        return "pytest (witness)" + (" " + command if receipt.get("cmd") else "")
    return _short_ids(command)


def _commands(receipts: Sequence[dict[str, Any]], *, collapse: bool = False) -> str:
    rows = []
    for receipt in receipts:
        digest = receipt.get("tree_digest") or receipt.get("patch_sha256") or receipt.get("image_after")
        command = '<code class="display-command">' + _e(_display_command(receipt)) + '</code>'
        if receipt.get("cmd"):
            command += '<details><summary>exact command</summary><pre>' + _e(receipt["cmd"]) + '</pre></details>'
        digest_text = _short_ids(digest)
        exit_text = _text(receipt.get("exit_code")) + (" (timed out)" if receipt.get("timed_out") else "")
        rows.append([_e(receipt.get("kind")), command,
                     _e(exit_text), _e(_number(receipt.get("duration_s"), "s")),
                     _e(digest_text[:12] if digest else None)])
    headings = ("Kind", "Command", "Exit", "Duration", "Digest")
    if collapse and len(rows) > 12:
        return (_table(headings, rows[:8], "commands")
                + f'<details class="all-steps"><summary>show all {len(rows)} steps</summary>'
                + _table(headings, rows[8:-4], "commands") + '</details>'
                + _table(headings, rows[-4:], "commands"))
    return _table(headings, rows, "commands") if rows else '<p class="pad secondary">Command receipts not recorded.</p>'


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
    claims = worker.get("claims")
    if isinstance(claims, dict):
        rows = []
        for key, label in (("target_tests_pass", "Target tests pass"), ("full_suite_pass", "Full suite passes"),
                           ("files_changed", "Files changed"), ("tests_run", "Ran tests")):
            value = claims.get(key)
            if key == "files_changed" and isinstance(value, list):
                value = ", ".join(_text(path) for path in value) or "none"
            elif isinstance(value, bool):
                value = "yes" if value else "no"
            rows.append(f"<li>{_e(label + ': ' + _text(value))}</li>")
        claim_text = '<ul class="claims">' + "".join(rows) + '</ul>'
    else:
        claim_text = '<p class="secondary">Claims ' + _e(claims) + '</p>'
    return _dl([( "Finish summary", worker.get("summary") or worker.get("end_summary")),
                ("Worker outcome", worker.get("end"))]) + claim_text


def _claim_audit(verdict: dict[str, Any]) -> str:
    audit = verdict.get("claim_audit")
    if audit == "no_claim":
        audit = "no claim"
    evidence = verdict.get("claim_evidence")
    return f"{_text(audit)}: {_text(evidence)}" if evidence else f"{_text(audit)}: claim evidence {_NOT_RECORDED}"


def _comparison(attempt: dict[str, Any], verdict: dict[str, Any]) -> str:
    return ('<div class="comparison card"><div><h3>What it said</h3>' + _claims(attempt)
            + '</div><div><h3>What the record shows</h3>'
            + '<p>' + _e(_claim_audit(verdict)) + '</p></div></div>')


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
    files = plan.get("files_to_edit")
    file_list = ('<ul class="files">' + "".join('<li><code>' + _e(path) + '</code></li>' for path in files) + '</ul>'
                 if isinstance(files, list) and files else _e(_NOT_RECORDED if files is None else "none"))
    body += ('<section class="card pad stack"><h2>The plan</h2>'
             + _dl([("Repository", repo), ("Base commit", commit), ("Issue", issue)])
             + '<dl><dt>Files to edit</dt><dd>' + file_list + '</dd></dl>'
             + _dl([("Approach", plan.get("approach"))]) + '</section>')
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
                 + _commands(agent.get(number, []), collapse=True) + '<div class="pad">' + _claims(attempt) + '</div></div>'
                 + '<div class="stack"><div class="card"><h3>Witness branch ' + _e(_short_ids(branch)) + '</h3>'
                 + _commands(witness) + '</div><h3>Gate predicate checklist</h3>' + _predicates(verdict) + '</div></div>')
        body += _comparison(attempt, verdict)
        official = records[position] if position < len(records) else {}
        agreement = {"agree_pass": "Agrees with the gate", "agree_fail": "Agrees with the gate",
                     "gate_stricter": "Gate was stricter", "gate_looser": "Gate was looser"}.get(official.get("agreement"), _NOT_RECORDED)
        body += ('<div class="card pad stack"><h3>'
                 + _e("SWE-rebench's official grader: " + _official(official.get("official_resolved")))
                 + '</h3><p>' + _e(agreement) + '</p></div></section>')
    body += '<section class="stack"><h2>Shipped patch</h2>'
    body += _diff(patch) if patch else '<p class="secondary">No patch shipped. Filtered patch not recorded.</p>' if _stamp(run) == "VERIFIED" else '<p class="secondary">No patch shipped.</p>'
    disclosure = run.artifact("disclosure.json", "disclosure")
    body += ('</section><section class="card pad stack"><h2>Model and costs</h2>'
             + _dl([("Model", _model_settings(run)), *costs])
             + '<details><summary>Full environment disclosure</summary><pre>' + _e(disclosure) + '</pre></details></section>'
             + _bundle(run, page))
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
    if test.split("::", 1)[0] in (summary.get("collection_errors") or []):
        return "error"
    return _NOT_RECORDED


def _spec_results(run: _Run) -> list[tuple[str, str, str]]:
    baseline = run.artifact("baseline.json", "baseline")
    before = (baseline.get("runs") or [{}])[0]
    last = run.attempts[-1] if run.attempts else {}
    witness = _witness_receipts(run, last)
    after = next((r["junit"] for r in reversed(witness) if r.get("junit")), {})
    inp = run.artifact("input.json", "input")
    tests = baseline.get("target") or inp.get("spec_tests") or []
    return [(test, _test_status(before, test), _test_status(after, test)) for test in tests]


def _kept(predicate: dict[str, Any]) -> str:
    evidence = _text(predicate.get("evidence"))
    count = re.match(r"(\d+) baseline-passing tests still pass", evidence)
    if predicate.get("passed") is True and count:
        n = int(count.group(1))
        return f"{n:,} of {n:,} previously passing tests still pass"
    return evidence


def _test_short_name(test: str) -> str:
    """`file::Class::method` keeps `Class::method`, so same-named tests stay distinct."""
    parts = test.split("::")
    return "::".join(parts[-2:]) if len(parts) >= 3 else parts[-1]


def _said(attempt: dict[str, Any]) -> str:
    """The first sentence of the agent's finish summary, quoted."""
    worker = attempt.get("worker") or {}
    summary = worker.get("summary") or worker.get("end_summary")
    return '"' + re.split(r"(?<=[.!?])\s+|\n", _text(summary), maxsplit=1)[0] + '"' if summary else _NOT_RECORDED


def _paper_rows(run: _Run) -> list[tuple[str, Any]]:
    repo, commit = _repository(run)
    last = run.attempts[-1] if run.attempts else {}
    verdict = _verdict(run, last) if last else {}
    spec = "\n".join(f"{_test_short_name(test)}: {before} -> {after}"
                     for test, before, after in _spec_results(run)) or _NOT_RECORDED
    predicates = {p["id"]: p for p in verdict.get("predicates", [])}
    r3 = predicates.get("R3_no_shrink", {})
    r5 = predicates.get("R5_provenance", {})
    checkpoint = run.result.get("checkpoint_id")
    witness = (f"fresh sandbox from checkpoint {_short_ids(checkpoint)}, patch digest matches"
               if r5.get("passed") is True else _short_ids(r5.get("evidence")))
    history = " · ".join(f"attempt {a['number']} " + {"PASS": "verified", "REJECTED": "rejected"}.get(
        _verdict(run, a).get("status"), "no verdict") for a in run.attempts) or _NOT_RECORDED
    said = _said(last)
    dropped = last.get("dropped_paths")
    dropped_text = "\n".join(_text(path) for path in dropped) if dropped else "none" if last else _NOT_RECORDED
    rows = [("instance", run.iid), ("repo", f"{repo} @ {commit}"), ("spec", spec),
            ("kept", _kept(predicates.get("R2_pass_to_pass", {}))),
            ("removed or new skips", "none" if r3.get("passed") is True else r3.get("evidence")),
            ("scope", predicates.get("R4_patch_scope", {}).get("evidence")), ("dropped", dropped_text),
            ("witness", witness), ("history", history), ("said", said), ("record", _claim_audit(verdict)),
            ("model", _model_settings(run))]
    rows.extend((label.lower(), value) for label, value in _cost(run)[:3])
    return rows


def _pr_description(run: _Run) -> str:
    verdict = _verdict(run, run.attempts[-1]) if run.attempts else {}
    if _stamp(run) != "VERIFIED":
        failed = next((p for p in verdict.get("predicates", []) if p.get("passed") is False
                       and p.get("id") != "R6_claim_audit"), None)
        failures = {"R1_fail_to_pass": "Specification tests still fail", "R2_pass_to_pass": "Previously passing tests regressed",
                    "R3_no_shrink": "Tests removed or newly skipped", "R4_patch_scope": "Patch outside allowed scope",
                    "R5_provenance": "Witness provenance or patch digest mismatch",
                    "R7_no_shortcuts": "The patch takes a shortcut",
                    "R8_review": "The independent review objects"}
        reason = (f"{failures.get(failed.get('id'), _NOT_RECORDED)}: {_text(failed.get('evidence'))}"
                  if failed else verdict.get("error") or run.record.get("reason") or "verification verdict not recorded")
        return "Not ready to submit: " + _text(reason)
    issue = _text(run.artifact("input.json", "input").get("issue")).split("\n", 1)[0].strip() or _NOT_RECORDED
    count = sum(before in {"failed", "error"} and after == "passed" for _, before, after in _spec_results(run))
    predicates = {p["id"]: p for p in verdict.get("predicates", [])}
    return (f"Fixes {run.iid}: {issue.rstrip('.')}.\n\n"
            "Verified by Receipts on a fresh sandbox the agent never touched:\n"
            f"- spec tests: {count} failed before, pass now\n"
            f"- {_kept(predicates.get('R2_pass_to_pass', {}))}\n"
            "- no tests removed or skipped; no test or config edits\n"
            f"- re-verify: uv run receipts reverify receipts/{run.iid}.json\n\n"
            f"Written with {_model_name(run)} on Nebius Token Factory; reviewed and submitted by [your name].")


def _receipt_page(run: _Run, title: str) -> str:
    page = f"receipt/{run.key}.html"
    rows = _paper_rows(run)
    commands = ("git clone https://github.com/zeyusuntt/receipts && cd receipts\nuv sync\n"
                f"uv run receipts reverify receipts/{run.iid}.json")
    pr = _pr_description(run)
    body = ('<div class="receipt-layout"><section class="paper"><h2>RECEIPTS</h2><hr>'
            + _dl(rows) + '<div class="stamp">' + _badge(_stamp(run)) + '</div></section>'
            + '<aside class="stack"><section class="card pad stack"><h2>Re-verify it yourself</h2>'
            + '<p class="secondary">Run these commands with the exported receipt bundle.</p><pre class="inset">'
            + _e(commands) + '</pre></section><section class="card pad stack"><h2>PR description</h2><pre>'
            + _e(pr) + '</pre></section><p>' + _link(page, f"run/{run.key}.html", "full record") + '</p></aside></div>')
    return _page(page, f"Receipt {run.iid}", title, body, _link(page, f"run/{run.key}.html", "full record"))


def _percent(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else _NOT_RECORDED


def _pilot_section(label: str, report: Report, runs: Sequence[_Run]) -> str:
    a, b = report.configuration_a, report.configuration_b
    rate = a.false_done_rate
    metrics = [("Unguarded agent: 'done' that was false", f"{a.false_dones} of {a.claimed_dones}",
                f"{_percent(rate.value)}, 95% interval {_percent(rate.lower_95)} to {_percent(rate.upper_95)}"),
               ("Receipts: verified fixes", str(b.verified_fixes), f"{b.first_verdict} on the first verdict, {b.appeal} after one appeal"),
               ("Receipts: false fixes shipped", str(b.shipped_false_dones), "checked by SWE-rebench's official grader"),
               ("Model cost per verified fix", _dollars(b.cost_per_verified_fix.model_dollars, decimals=2),
                "Nemotron tokens at Token Factory's listed prices")]
    body = '<section class="stack"><h2>' + _e(label) + '</h2><div class="metrics">'
    body += "".join(f'<div class="metric"><span>{_e(name)}</span><strong>{_e(value)}</strong><span>{_e(detail)}</span></div>' for name, value, detail in metrics) + '</div>'
    body += '<p class="secondary">Verified fixes require a gate PASS and official resolution. Run verdicts show the gate result; official grades are listed separately.</p>'
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
    body += ("<p class=\"secondary\"><strong>How to read this</strong>: Unguarded agent = the agent's own 'done' on its first try. "
             "Receipts = the same agent behind a witness sandbox and a model-free gate, with one appeal. "
             "Official = SWE-rebench's grader, run separately.</p>")
    body += _table(("Instance", "Unguarded: claimed done", "Unguarded: official", "Receipts outcome", "Receipts: official", "Run", "Receipt"), rows, "instances")
    return body + '</section>'


_REPO_URL = "https://github.com/zeyusuntt/receipts"
_DECISIVE = {"R1_fail_to_pass", "R2_pass_to_pass", "R3_no_shrink", "R4_patch_scope", "R5_provenance",
             "R7_no_shortcuts", "R8_review"}


def _featured_problem(run: _Run) -> str | None:
    """Why this run cannot open the site; the headline claims all of these."""
    records = run.record.get("attempts") or []
    if len(run.attempts) < 2 or not records:
        return "it has no appeal"
    if records[0].get("claimed_done") is not True:
        return "its first attempt did not claim done"
    if _verdict(run, run.attempts[0]).get("status") != "REJECTED":
        return "its first attempt was not rejected"
    if _stamp(run) != "VERIFIED":
        return "it did not end verified"
    return None


def _failed_lines(verdict: dict[str, Any]) -> list[str]:
    """The decisive checks an attempt failed, with test ids shortened to Class::test."""
    lines = []
    for predicate in verdict.get("predicates") or []:
        if predicate.get("passed") is True or predicate.get("id") not in _DECISIVE:
            continue
        evidence = _short_ids(predicate.get("evidence"))
        if predicate.get("id") == "R1_fail_to_pass":
            for item in evidence.split("; "):
                test, _, outcome = item.rpartition(" ")
                lines.append(f"{_test_short_name(test)} {outcome}" if test else item)
        else:
            lines.append(evidence)
    return lines[:3] + ([f"and {len(lines) - 3} more"] if len(lines) > 3 else [])


def _passed_lines(run: _Run, attempt: dict[str, Any], verdict: dict[str, Any]) -> list[str]:
    predicates = {p.get("id"): p for p in verdict.get("predicates") or []}
    spec = _spec_results(run)
    lines = [f"{sum(after == 'passed' for _, _, after in spec)} of {len(spec)} target tests pass" if spec
             else "target tests: " + _NOT_RECORDED,
             _kept(predicates.get("R2_pass_to_pass", {}))]
    if predicates.get("R3_no_shrink", {}).get("passed") is True:
        lines.append("no test removed or newly skipped")
    return lines


def _still_failing(run: _Run, attempt: dict[str, Any]) -> int:
    """Tests that failed before any patch and still fail: why a verified witness run can exit non-zero."""
    before = ((run.artifact("baseline.json", "baseline").get("runs") or [{}])[0].get("failure_text") or {})
    after = next((r["junit"] for r in reversed(_witness_receipts(run, attempt)) if r.get("junit")), {})
    return len(set(after.get("failure_text") or {}) & set(before) - {test for test, _, _ in _spec_results(run)})


def _junit_counts(junit: dict[str, Any]) -> str:
    counts = []
    for key in ("passed", "failed", "errors"):
        value = junit.get(key)
        n = len(value) if isinstance(value, list) else value if isinstance(value, int) else 0
        if n:
            counts.append(f"{n} {key}")
    return ", ".join(counts) or "no tests"


def _log_row(label: str, text: str, status: str = "", css: str = "", row: str = "") -> str:
    # Long test ids and paths may break after "::" or "/" on narrow screens, never mid-name.
    breakable = _e(text).replace("::", "::<wbr>").replace("/", "/<wbr>")
    return (f'<tr class="{_e(row)}"><td>{_e(label)}</td><td>{breakable}</td>'
            f'<td class="{_e(css)}">{_e(status)}</td></tr>')


def _exit_css(code: Any) -> str:
    return "ok" if code == 0 else "bad" if isinstance(code, int) else ""


def _run_log(run: _Run, report: Report) -> str:
    """The featured run as a dense log: what the agent said, what the witness ran, what decided."""
    page = "index.html"
    repo, commit = _repository(run)
    issue = _text(run.artifact("input.json", "input").get("issue")).split("\n", 1)[0].strip() or _NOT_RECORDED
    records = run.record.get("attempts") or []
    agent = _agent_receipts(run)
    rows = []
    for position, attempt in enumerate(run.attempts):
        number = int(attempt["number"])
        verdict = _verdict(run, attempt)
        if position:
            recorded = attempt.get("appeal_evidence") or (attempt.get("worker") or {}).get("appeal_evidence")
            appeal = recorded or _appeal_text(_verdict(run, run.attempts[position - 1]))
            rows.append('<tr class="group"><th colspan="3">appeal: the gate\'s evidence goes back to the agent once</th></tr>')
            rows.append(_log_row("sent", _text(appeal).split("\n", 1)[0]))
        rows.append(f'<tr class="group"><th colspan="3">attempt {number}</th></tr>')
        steps = len(agent.get(number, []))
        rows.append(_log_row("agent", f"{steps} steps, then said {_said(attempt)}"))
        for receipt in _witness_receipts(run, attempt):
            code = receipt.get("exit_code")
            if receipt.get("junit"):
                rows.append(_log_row("witness", _display_command(receipt), _junit_counts(receipt["junit"]), row="detail"))
            else:
                rows.append(_log_row("witness", _display_command(receipt), f"exit {_text(code)}", _exit_css(code),
                                     row="detail"))
        passed = verdict.get("status") == "PASS"
        for line in (_passed_lines(run, attempt, verdict) if passed else _failed_lines(verdict)):
            rows.append(_log_row("gate", line, "pass" if passed else "fail", "ok" if passed else "bad"))
        still = _still_failing(run, attempt) if passed else 0
        if still:
            rows.append(_log_row("note", f"{still} tests that already failed before any patch still fail; "
                                         "the gate protects tests that passed"))
        rows.append(_log_row("verdict", "R1 to R5 and R7 on the witness run",
                             "VERIFIED" if passed else "REJECTED", "ok" if passed else "bad"))
        official = records[position].get("official_resolved") if position < len(records) else None
        rows.append(_log_row("grader", "SWE-rebench's official grader", _official(official),
                             {True: "ok", False: "bad"}.get(official, "")))
    cost = run.record.get("cost") or {}
    tokens = cost.get("tokens")
    total = (f"{int(tokens):,} tokens, " if tokens is not None else "")
    total += f"{_dollars(cost.get('model_dollars', cost.get('dollars')))} of model tokens, "
    total += f"{_duration(run.record.get('wall_time_s'))} wall time"
    rows.append('<tr class="group"><th colspan="3">total</th></tr>' + _log_row("cost", total))
    return ('<section class="run-log" aria-labelledby="featured-run">'
            f'<h2 id="featured-run">One of the {report.ran_tasks:,} runs: {_e(run.iid)}</h2>'
            f'<p class="meta">{_e(repo)} at {_e(commit)}. Issue: {_e(issue)}. Model: {_e(_model_name(run))}. '
            + _link(page, f"receipt/{run.key}.html", "receipt") + ", "
            + _link(page, f"run/{run.key}.html", "every command") + "</p>"
            '<div class="table-box"><table class="log"><tbody>' + "".join(rows) + '</tbody></table></div></section>')


def _totals(report: Report) -> str:
    a, b = report.configuration_a, report.configuration_b
    rate = a.false_done_rate
    comparison = (f"Without Receipts, the same agent said \"done\" on {a.claimed_dones} tasks, and SWE-rebench's grader "
                  f"found {a.false_dones} of its {a.claimed_dones} claims false ({_percent(rate.value)}, 95% interval "
                  f"{_percent(rate.lower_95)} to {_percent(rate.upper_95)}). With Receipts it shipped {b.verified_fixes} "
                  f"fixes, {b.appeal} of them after the appeal, and {b.shipped_false_dones} of "
                  f"{b.verified_fixes + b.shipped_false_dones} shipped fixes were false.")
    method = (f"Model tokens cost {_dollars(b.cost_per_verified_fix.model_dollars, decimals=2)} per verified fix. "
              "The tasks were chosen by a rule committed before the first run.")
    return ('<section class="totals"><h2>' + _e(f"All {report.ran_tasks:,} held-out tasks") + '</h2>'
            f'<p>{_e(comparison)}</p><p>{_e(method)} '
            f'<a href="{_REPO_URL}/blob/main/REPORT-v2.md" rel="noopener">The pre-registered report</a></p></section>')


_ROLES = """\
<section class="roles"><h2>Models</h2>
<p>NVIDIA Nemotron 3 Super 120B-A12B writes the fix on Nebius Token Factory, with five tools, in a Token Factory Sandbox of its own. A second sandbox, forked from the checkpoint taken before the agent started, runs your tests again, and the gate decides from that run.</p>
<p>Two more Nemotron 3 Super calls then review a passing patch, and the receipt records their objections as advice. That review was added on October 16, after the 100-task run, so the receipts here do not have it.</p><p>In the experiments, SWE-rebench's own grader graded every patch again.</p>
</section>"""

# Output of `receipts reverify` recorded from a fresh clone, shown next to the command for that receipt.
_RECORDED_REVERIFY = {
    "pyfilesystem__pyfilesystem2-462": ("on a fresh clone, Docker on a Mac, October 26, 2026", """\
Re-verifying pyfilesystem__pyfilesystem2-462 on Docker

  ✓ Digests          3 digests, all 6166a7470cf2...  AGREES  (0.0s)
  · Checkpoint       rebuilt from docker.io/swerebenchv2/pyfilesystem-pyfilesystem2:462-ac8a91a  (302.8s)
  ✓ Filter           6166a7470cf2...  AGREES  (0.4s)
  ✓ Witness patch    6166a7470cf2...  AGREES  (48.8s)
  ✓ Gate verdict     PASS  AGREES  (48.8s)
  ✓ Failed checks    none  AGREES  (48.8s)
  ✓ Official grade   resolved  AGREES  (45.3s)

Every check agrees with the receipt. (424s)"""),
}


def _check(run: _Run, live_url: str | None = None) -> str:
    reverify = ("git clone https://github.com/zeyusuntt/receipts\ncd receipts\nuv sync\n"
                f"uv run receipts reverify \\\n  receipts/{run.iid}.json")
    fix = ("uv run receipts fix \\\n  --repo https://github.com/you/your-repo \\\n"
           "  --commit <commit with your failing test> \\\n  --install \"pip install -e .\" \\\n"
           "  --test tests/test_parse.py::test_empty_string \\\n  --issue-file issue.md \\\n"
           "  --executor docker --out runs/my-fix")
    recorded = _RECORDED_REVERIFY.get(run.iid)
    output = (f'<div><h3>Its output {_e(recorded[0])}</h3><pre class="term">{_e(recorded[1])}</pre></div>'
              if recorded else "")
    live = (f'<h3>Run it live</h3><p><a href="{_e(live_url)}" rel="noopener">Run it live</a> on one of five preset '
            'tasks from the experiment, with the judge code from the Devpost testing notes. One run at a time, under '
            'a spending cap; each step shows the model or tool that did it.</p>') if live_url else ""
    return ('<section class="check" id="check"><h2>Reproduce</h2>' + live +
            '<p>Re-verifying needs Docker and no account or key. It rebuilds the checkpoint, replays the '
            "patch through the same gate in a fresh container, runs SWE-rebench's grader, and must agree with the "
            "receipt on every check. The first run downloads the task's image.</p>"
            '<div class="check-grid"><div><h3>Re-verify this receipt</h3>'
            f'<pre class="term">{_e(reverify)}</pre>'
            f'<p>All 100 on GitHub\'s machines: fork the repository and run the '
            f'<a href="{_REPO_URL}/blob/main/.github/workflows/reverify.yml" rel="noopener">Re-verify receipts</a> workflow '
            f'(<a href="{_REPO_URL}/actions/runs/39019908268" rel="noopener">October 17 run</a>: every check agreed, '
            '37 minutes).</p></div>' + output + '</div>'
            '<h3>Run it on your repository</h3><p>Python with pytest. Commit a failing test, then point '
            'Receipts at that commit. This calls Nemotron, so it needs a Nebius Token Factory key '
            f'(<a href="{_REPO_URL}#use-it-on-a-repository" rel="noopener">setup</a>).</p>'
            f'<pre class="term">{_e(fix)}</pre></section>')


_LIMITS = f"""\
<section class="limits"><h2>What it does not prove</h2><ul>
<li>A fix is only as good as the failing test. On bug fixes from AERead, a project outside any benchmark, Receipts verified 13 patches; two independent readings found 5 correct, 3 partial and 5 wrong, and all 8 that are not correct pass their target tests (<a href="{_REPO_URL}/blob/main/trials/aeread/RESULTS.md" rel="noopener">results</a>).</li>
<li>The independent review was built to veto. A rule fixed in advance allowed it to reject at most 3 of the 66 fixes the official grader accepts; it rejected 10, so it only advises.</li>
<li>Code that detects it is under test can pass any test-based gate, including the official grader.</li>
<li>Python repositories tested with pytest only. Tests that need the network cannot pass in the sandbox; in the experiments those tasks were excluded before any agent ran, and listed.</li>
</ul></section>"""


def _lead(run: _Run, report: Report, live_url: str | None = None) -> str:
    model = _model_name(run)
    b = report.configuration_b
    shipped = b.verified_fixes + b.shipped_false_dones
    accepted = f"all {shipped}" if not b.shipped_false_dones else f"{b.verified_fixes} of the {shipped}"
    headline = (f"SWE-rebench's grader accepted {accepted} fixes this coding agent shipped "
                f"on {report.ran_tasks:,} held-out tasks")
    intro = (f'<section class="intro"><h1>{_e(headline)}</h1>'
             f'<p>You write a failing test and {_e(model)} writes the fix. The tests then run again in a fresh '
             'sandbox forked from before the agent started, and plain Python decides whether the fix ships. Below is '
             'one run, step by step, as recorded.</p></section>')
    return (intro + '<div class="lead-grid">' + _run_log(run, report)
            + '<div class="side">' + _totals(report) + _ROLES + _check(run, live_url) + '</div></div>' + _LIMITS)


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
    strip_prefixes: Sequence[Path] = (), featured: str | None = None, live_url: str | None = None,
) -> SiteSummary:
    """Write static HTML and a small raw bundle; return generated file counts.

    Record paths must stay within repo_root. Repeated instance ids across pilots
    get deterministic pilot subdirectories; unique ids retain the short URLs.
    Output must be separate from the inputs. Rebuilding overwrites generated
    files without deleting unrelated files from the output directory.
    With `featured`, the index opens on that run of the first pilot, which must be
    a claimed done that was rejected and then verified on appeal.
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
    lead = ""
    first_report: Report | None = None
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
        if first_report is None:
            first_report = report
        if not lead:
            models = list(dict.fromkeys(_model_name(run) for run in runs
                                        if run.record.get("status") == "ran" and _model_name(run) != _NOT_RECORDED))
            model = ", ".join(models) if models else _NOT_RECORDED
            description = (f"{report.ran_tasks:,} SWE-rebench-V2 tasks held out from development and chosen by a rule fixed in advance. "
                           f"{model} on Nebius Token Factory wrote every fix; a clean Token Factory Sandbox and plain code checked it; "
                           "SWE-rebench's own grader graded it again.")
            lead = ('<section class="stack index-lead"><h1>' + _e(report.headline) + '</h1><p>'
                    + _e(description) + '</p><div class="actions">'
                    + '<a href="https://github.com/zeyusuntt/receipts/blob/main/REPORT-v2.md" rel="noopener" class="button">Read the report</a>'
                    + '<a href="https://github.com/zeyusuntt/receipts" rel="noopener" class="button">Repository</a>'
                    + (_link("index.html", f"receipt/{runs[0].key}.html", "Re-verify a receipt", "button primary") if runs else "")
                    + '</div></section>')
        label = _PILOT_TITLES.get(pilot.name, pilot.name)
        sections.append(_pilot_section(label, report, runs))
        total += len(runs)
    if featured is not None:
        run = next((r for r in groups[0][1] if r.iid == featured), None)
        problem = "it is not in the first pilot" if run is None else _featured_problem(run)
        if problem:
            raise ValueError(f"featured run {featured!r} cannot open the site: {problem}")
        lead = _lead(run, first_report, live_url)
    body = lead + "".join(sections)
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
