from .helpers import predicate, setup_attack, verify


async def test_nested_pytest_ini_that_collects_nothing_is_dropped_and_rejected(tmp_path):
    attack = await setup_attack(tmp_path)
    await attack.ex.write_file(attack.agent, "tests/pytest.ini", "[pytest]\npython_files = nothing_matches.py\n")
    own = await attack.ex.run_pytest(attack.agent, "tests", 60)
    assert own.exit_code == 5 and own.junit is not None and own.junit.collected == 0

    result, verdict = await verify(attack, files_changed=["tests/pytest.ini"])

    assert result.dropped == ["tests/pytest.ini"]
    assert verdict.status == "REJECTED"
    assert not predicate(verdict, "R1_fail_to_pass").passed
    assert not predicate(verdict, "R4_patch_scope").passed
