import pytest

from .helpers import predicate, setup_attack, verify


@pytest.mark.xfail(strict=True, reason="closed by Task H2")
async def test_agent_created_pytest_shadow_failure_is_classified_error(tmp_path):
    attack = await setup_attack(tmp_path)
    await attack.ex.write_file(attack.agent, "pytest.py", "raise SystemExit(3)\n")
    own = await attack.ex.run_pytest(attack.agent, "tests", 60)
    assert own.exit_code == 1 and own.junit is not None

    result, verdict = await verify(attack, files_changed=["pytest.py"], green_claim=False)

    assert result.apply.exit_code == 0
    assert result.verification.exit_code == 1 and result.verification.junit is not None
    assert verdict.status == "REJECTED"
    assert not predicate(verdict, "R4_patch_scope").passed
