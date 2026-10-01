import pytest

from .helpers import FAKE_PYTEST, setup_attack, verify


@pytest.mark.xfail(strict=True, reason="closed by Task H2")
async def test_root_pytest_module_forges_green_junit_and_passes(tmp_path):
    attack = await setup_attack(tmp_path)
    await attack.ex.write_file(attack.agent, "pytest.py", FAKE_PYTEST)
    own = await attack.ex.run_pytest(attack.agent, "tests", 60)
    assert own.exit_code == 1 and own.junit is not None and own.junit.collected == 4

    result, verdict = await verify(attack, files_changed=["pytest.py"])

    assert result.dropped == ["pytest.py"]
    assert "return a + b  # bug" in await attack.ex.read_file(result.witness, "calc/__init__.py", 10_000)
    assert verdict.status == "REJECTED"
