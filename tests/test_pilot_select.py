import json
from pathlib import Path

import pytest

from receipts.pilot.select import candidates, write_candidates


DATA = Path(__file__).parent / "data" / "rebench_rows_sample.jsonl"


def _rows() -> list[dict]:
    return [
        json.loads(line)
        for line in DATA.read_text(encoding="utf-8").splitlines()
    ]


def _row(instance_id: str) -> dict:
    return next(row for row in _rows() if row["instance_id"] == instance_id)


def _candidate_ids(rows: list[dict]) -> list[str]:
    return [instance.instance_id for instance in candidates(rows)]


def test_candidates_reject_non_python_rows():
    rows = [_row("bad-language"), _row("alpha")]

    assert _candidate_ids(rows) == ["alpha"]


def test_candidates_reject_commands_that_do_not_start_with_pytest():
    rows = [_row("bad-command"), _row("alpha")]

    assert _candidate_ids(rows) == ["alpha"]


@pytest.mark.parametrize("instance_id", ["no-fail-to-pass", "too-many-fail-to-pass"])
def test_candidates_require_one_to_three_fail_to_pass_entries(instance_id: str):
    rows = [_row(instance_id), _row("alpha")]

    assert _candidate_ids(rows) == ["alpha"]


def test_candidates_order_by_digest_not_input_or_instance_id_order():
    rows = [_row("beta"), _row("alpha"), _row("zeta")]

    assert _candidate_ids(rows) == ["zeta", "alpha", "beta"]
    assert _candidate_ids(list(reversed(rows))) == ["zeta", "alpha", "beta"]


def test_candidates_keep_digest_first_repository_case_insensitively():
    rows = [_row("same-repo-earlier"), _row("same-repo-later")]

    assert _candidate_ids(rows) == ["same-repo-later"]


def test_candidates_never_store_the_gold_patch():
    selected = candidates(_rows())

    assert selected
    assert all("patch" not in instance.model_dump() for instance in selected)
    assert all(not hasattr(instance, "patch") for instance in selected)


def test_write_candidates_includes_revision_and_selected_ids(tmp_path: Path):
    meta_path = tmp_path / "rows.meta.json"
    meta_path.write_text(json.dumps({"revision": "revision-abc123"}), encoding="utf-8")
    out_path = tmp_path / "pilot" / "candidates.txt"

    write_candidates(DATA, meta_path, out_path)

    assert out_path.read_text(encoding="utf-8") == (
        "# dataset revision revision-abc123\n"
        "# rules 1-3 of PREREGISTRATION.md\n"
        "same-repo-later\n"
        "delta\n"
        "zeta\n"
        "epsilon\n"
        "alpha\n"
        "gamma\n"
        "beta\n"
    )
