from .helpers import FAKE_PYTEST, setup_attack, verify


async def test_root_sourceless_pytest_bytecode_forges_green_junit_and_passes(tmp_path):
    attack = await setup_attack(tmp_path)
    await attack.ex.write_file(attack.agent, "payload.py", FAKE_PYTEST)
    built = await attack.ex.run(
        attack.agent,
        "python -m py_compile payload.py && cp __pycache__/payload.*.pyc pytest.pyc && rm payload.py",
        30,
    )
    assert built.exit_code == 0
    own = await attack.ex.run_pytest(attack.agent, "tests", 60)
    assert own.exit_code == 1 and own.junit is not None and own.junit.collected == 4

    result, verdict = await verify(attack, files_changed=["pytest.pyc"])

    assert result.patch.diff.files[0].category == "shadow"
    assert result.filtered_patch == ""
    assert verdict.status == "REJECTED"
