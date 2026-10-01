from .helpers import predicate, setup_attack, verify


async def test_test_file_mode_change_is_rejected_as_test_edit(tmp_path):
    attack = await setup_attack(tmp_path)
    changed = await attack.ex.run(attack.agent, "chmod +x tests/test_calc.py", 30)
    assert changed.exit_code == 0

    result, verdict = await verify(
        attack,
        files_changed=["tests/test_calc.py"],
        green_claim=False,
        tests_run=False,
    )

    assert result.dropped == ["tests/test_calc.py"]
    assert verdict.status == "REJECTED"
    assert not predicate(verdict, "R1_fail_to_pass").passed
    assert not predicate(verdict, "R4_patch_scope").passed
