"""Assemble the Cloud Run build context for the live judge page.

Usage, from the repository root: python live/run/build.py OUT_DIR
"""

import ast
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def preset_ids() -> list[str]:
    """PRESET_IDS from src/receipts/live.py, read without importing the package (Cloud Shell has only Python)."""
    tree = ast.parse((ROOT / "src" / "receipts" / "live.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "PRESET_IDS" for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise SystemExit("PRESET_IDS not found in src/receipts/live.py")


def main(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name in ("pyproject.toml", "LICENSE"):
        shutil.copy2(ROOT / name, out / name)
    shutil.copytree(ROOT / "src", out / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("Dockerfile", "README.md"):
        shutil.copy2(ROOT / "live" / "run" / name, out / name)
    for iid in preset_ids():
        record = ROOT / "pilot" / "v2-P" / iid / "record.json"
        run_dir = Path(json.loads(record.read_text(encoding="utf-8"))["run_dir"])
        for source in (record, ROOT / run_dir / "input.json"):
            target = out / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    print(f"Build context in {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
