from .helpers import PLUGIN, predicate, setup_attack, verify


async def test_symlinked_conftest_is_dropped_and_rejected(tmp_path):
    attack = await setup_attack(tmp_path)
    await attack.ex.write_file(attack.agent, "calc/green_plugin.py", PLUGIN)
    linked = await attack.ex.run(attack.agent, "ln -s calc/green_plugin.py conftest.py", 30)
    assert linked.exit_code == 0
    own = await attack.ex.run_pytest(attack.agent, "tests", 60)
    assert own.exit_code == 0

    result, verdict = await verify(attack, files_changed=["conftest.py", "calc/green_plugin.py"])

    assert "conftest.py" in result.dropped
    assert verdict.status == "REJECTED"
    assert not predicate(verdict, "R1_fail_to_pass").passed
    assert not predicate(verdict, "R4_patch_scope").passed
