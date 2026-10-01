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


COLLECTION_ERROR_XML = """<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest" errors="1" failures="0" skipped="0" tests="2"><testcase classname="" name="tests.test_new" file="tests/test_new.py" time="0.000"><error message="collection failure">ImportError while importing test module</error></testcase><testcase classname="tests.test_old" name="test_ok" file="tests/test_old.py" time="0.001" /></testsuite></testsuites>"""


def test_collection_failure_is_a_file_level_error_not_a_test(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text(COLLECTION_ERROR_XML)

    j = parse_junit(path)

    assert j.collection_errors == ["tests/test_new.py"]
    assert j.passed == ["tests/test_old.py::test_ok"]
    assert j.errors == [] and j.failed == [] and j.skipped == []
    assert j.collected == 1
    assert j.all_ids() == {"tests/test_old.py::test_ok"}
    # Tests inside a file that failed to collect did not pass: they count as errors.
    assert j.outcome("tests/test_new.py::test_new") == "error"
    assert j.outcome("tests/test_new.py::TestNew::test_case[1]") == "error"
    # A test in a file that collected fine but is absent is still missing.
    assert j.outcome("tests/test_old.py::test_gone") == "missing"


NESTED_ROOTDIR_XML = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" errors="1" failures="1" skipped="0" tests="3"><properties><property name="receipts_rootdir" value="/repo/pkg" /><property name="receipts_invocation_dir" value="/repo" /></properties><testcase classname="tests.test_k" name="test_a" file="tests/test_k.py" time="0.001" /><testcase classname="tests.test_k.TestK" name="test_b" file="tests/test_k.py" time="0.001"><failure message="boom">x</failure></testcase><testcase classname="" name="tests.test_new" file="tests/test_new.py" time="0.000"><error message="collection failure">ImportError</error></testcase></testsuite></testsuites>"""


def test_ids_are_relative_to_the_invocation_dir_like_pytest_terminal_output(tmp_path):
    """pytest writes junit paths relative to its rootdir but prints node ids relative
    to where it was invoked; SWE-rebench ids come from the printed form."""
    path = tmp_path / "junit.xml"
    path.write_text(NESTED_ROOTDIR_XML)

    j = parse_junit(path)

    assert j.passed == ["pkg/tests/test_k.py::test_a"]
    assert j.failed == ["pkg/tests/test_k.py::TestK::test_b"]
    assert j.collection_errors == ["pkg/tests/test_new.py"]
    assert j.outcome("pkg/tests/test_new.py::test_new") == "error"
