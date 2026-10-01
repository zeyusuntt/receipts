from pathlib import Path

from receipts.junit import node_id, parse_junit

DATA = Path(__file__).parent / "data"


def test_node_id_rebuilds_pytest_ids():
    assert node_id("tests/test_parse.py", "tests.test_parse", "test_ok") == "tests/test_parse.py::test_ok"
    assert node_id("tests/test_parse.py", "tests.test_parse.TestFoo", "test_method") == "tests/test_parse.py::TestFoo::test_method"
    assert node_id("tests/test_parse.py", "tests.test_parse", "test_param[1-2]") == "tests/test_parse.py::test_param[1-2]"
    assert node_id("pkg/sub/test_x.py", "pkg.sub.test_x.A.B", "t") == "pkg/sub/test_x.py::A::B::t"
    # a class named like a module component must survive
    assert node_id("pkg/test_pkg.py", "pkg.test_pkg.pkg", "t") == "pkg/test_pkg.py::pkg::t"


def test_parse_mixed_file():
    j = parse_junit(DATA / "junit_mixed.xml")
    assert j.collected == 7
    assert j.failed == ["tests/test_parse.py::test_empty"]
    assert j.errors == ["tests/test_other.py::test_boom"]
    assert j.skipped == ["tests/test_parse.py::test_skipped"]
    assert j.passed == [
        "tests/test_parse.py::test_ok",
        "tests/test_parse.py::TestFoo::test_method",
        "tests/test_parse.py::test_param[1-2]",
        "tests/test_parse.py::test_param[a b]",
    ]


def test_parse_empty_file_is_zero_collected_not_none():
    j = parse_junit(DATA / "junit_empty.xml")
    assert j is not None and j.collected == 0 and j.passed == []


def test_missing_file_is_none(tmp_path):
    assert parse_junit(tmp_path / "nope.xml") is None
    assert parse_junit(None) is None


def test_garbage_file_is_none(tmp_path):
    p = tmp_path / "bad.xml"
    p.write_text("<not xml")
    assert parse_junit(p) is None
