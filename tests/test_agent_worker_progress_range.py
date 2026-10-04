from receipts.agent.worker import _read_range


def test_read_range_formats_the_lines_a_read_covered():
    assert _read_range({"path": "a.py"}) == ""
    assert _read_range({"path": "a.py", "start_line": 120, "end_line": 180}) == ":120-180"
    assert _read_range({"path": "a.py", "start_line": 40}) == ":40-"
    assert _read_range({"path": "a.py", "view_range": [10, 20]}) == ":10-20"
    assert _read_range({"path": "a.py", "view_range": "10,20"}) == ":10-20"
    assert _read_range({"path": "a.py", "view_range": [5, -1]}) == ":5-"
    assert _read_range({"path": "a.py", "view_range": "x"}) == ""
