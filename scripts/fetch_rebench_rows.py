"""Extract SWE-rebench-V2 Python rows, without the gold patch, from the pinned parquet.

Run with network access:
    uv run --no-project --with pyarrow python scripts/fetch_rebench_rows.py PARQUET OUT_DIR
The parquet is downloaded from the revision named in REVISION.
"""
import datetime
import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

DATASET = "nebius/SWE-rebench-V2"
REVISION = "475dd5e8703bb5fb22dd3c60b5d038b019eba1e0"
URL = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/data/train-00000-of-00001.parquet"
KEEP = ["instance_id", "repo", "base_commit", "image_name", "test_patch", "problem_statement",
        "FAIL_TO_PASS", "PASS_TO_PASS", "install_config", "language"]


def main(parquet: str, out_dir: str) -> None:
    table = pq.read_table(parquet, columns=KEEP)
    rows = [r for r in table.to_pylist() if r["language"] == "python"]
    rows.sort(key=lambda r: r["instance_id"])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "rebench-v2-python.jsonl").open("w") as fh:
        for r in rows:
            assert "patch" not in r
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    digest = hashlib.sha256(Path(parquet).read_bytes()).hexdigest()
    (out / "rebench-v2-python.meta.json").write_text(json.dumps({
        "dataset": DATASET, "revision": REVISION, "source_url": URL, "parquet_sha256": digest,
        "python_rows": len(rows), "extracted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dropped_fields": ["patch", "interface", "meta"],
    }, indent=2) + "\n")
    print(len(rows), "rows")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
