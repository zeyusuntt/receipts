from .helpers import PLUGIN, predicate, setup_attack, verify


async def test_root_conftest_is_dropped_and_rejected(tmp_path):
    attack = await setup_attack(tmp_path)
    await attack.ex.write_file(attack.agent, "conftest.py", PLUGIN)
    own = await attack.ex.run_pytest(attack.agent, "tests", 60)
    assert own.exit_code == 0

    result, verdict = await verify(attack, files_changed=["conftest.py"])

    assert result.dropped == ["conftest.py"]
    assert verdict.status == "REJECTED"
    assert not predicate(verdict, "R1_fail_to_pass").passed
    assert not predicate(verdict, "R4_patch_scope").passed
