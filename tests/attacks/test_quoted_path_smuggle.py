from .helpers import predicate, setup_attack, verify


async def test_quoted_test_path_cannot_smuggle_test_edit_into_witness(tmp_path):
    attack = await setup_attack(tmp_path)
    source = await attack.ex.write_file(
        attack.agent,
        "calc/__init__.py",
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n",
    )
    test_path = "tests/test_\nx.py"
    test_file = await attack.ex.write_file(
        attack.agent,
        test_path,
        "def test_spec():\n    assert True\n",
    )
    assert source.exit_code == 0 and test_file.exit_code == 0

    result, verdict = await verify(
        attack,
        files_changed=["calc/__init__.py", test_path],
        green_claim=False,
        tests_run=False,
    )

    assert any(item.category == "unparseable" for item in result.patch.diff.files)
    assert result.filtered_patch == ""
    assert result.dropped == [
        "calc/__init__.py",
        '"a/tests/test_\\nx.py" "b/tests/test_\\nx.py"',
    ]
    assert verdict.status == "REJECTED"
    assert "R4_patch_scope" in verdict.failed_predicate_ids()
    assert not predicate(verdict, "R4_patch_scope").passed
