"""Compare the full-suite JUnit results of each shipped patch with its upstream fix.

Usage: python compare.py WORK SCREENING_FILE [RUN_SUFFIX]
Reads WORK/fullsuite/<id><suffix>-shipped.xml and <id><suffix>-upstream.xml, writes
WORK/fullsuite-compare-<screening name><suffix>.json.
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

WORK, SCREENING = Path(sys.argv[1]), sys.argv[2]
SUFFIX = sys.argv[3] if len(sys.argv) > 3 else ""
OUT = WORK / "fullsuite"


def statuses(path: Path) -> dict[str, str]:
    result = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        node = f"{case.get('classname')}::{case.get('name')}"
        if case.find("failure") is not None:
            result[node] = "failed"
        elif case.find("error") is not None:
            result[node] = "error"
        elif case.find("skipped") is not None:
            result[node] = "skipped"
        else:
            result[node] = "passed"
    return result


tasks = [json.loads(line)["commit"][:12] for line in (WORK / SCREENING).read_text().splitlines()
         if json.loads(line).get("included")]
report = {}
for task in tasks:
    shipped, upstream = OUT / f"{task}{SUFFIX}-shipped.xml", OUT / f"{task}{SUFFIX}-upstream.xml"
    if not (shipped.exists() and upstream.exists()):
        report[task] = {"missing": [p.name for p in (shipped, upstream) if not p.exists()]}
        continue
    s, u = statuses(shipped), statuses(upstream)
    report[task] = {
        "shipped_counts": {k: list(s.values()).count(k) for k in ("passed", "failed", "error", "skipped")},
        "upstream_counts": {k: list(u.values()).count(k) for k in ("passed", "failed", "error", "skipped")},
        "pass_with_upstream_fail_with_shipped": sorted(n for n, st in u.items() if st == "passed" and s.get(n) in ("failed", "error")),
        "pass_with_upstream_absent_with_shipped": sorted(n for n, st in u.items() if st == "passed" and n not in s),
        "fail_with_upstream_pass_with_shipped": sorted(n for n, st in s.items() if st == "passed" and u.get(n) in ("failed", "error")),
    }
print(json.dumps(report, indent=1))
(WORK / f"fullsuite-compare-{Path(SCREENING).stem}{SUFFIX}.json").write_text(json.dumps(report, indent=1))
