from receipts.models import PatchScope

from .helpers import predicate, setup_attack, verify


FIXED_CALC = '''def add(a, b):
    return a + b


def sub(a, b):
    return a - b
'''


async def test_root_copy_of_src_package_is_dropped_and_rejected(tmp_path):
    attack = await setup_attack(tmp_path, src_layout=True)
    attack.baseline = attack.baseline.model_copy(
        update={
            "scope": PatchScope(
                protected_names=["calc"],
                c0_top_level=["src/calc"],
            ),
        },
    )
    added = await attack.ex.write_file(
        attack.agent,
        "calc/__init__.py",
        FIXED_CALC,
    )
    assert added.exit_code == 0
    import_check = await attack.ex.run(
        attack.agent,
        "python -c 'from calc import sub; assert sub(5, 3) == 2'",
        60,
    )
    assert import_check.exit_code == 0

    result, verdict = await verify(
        attack,
        files_changed=["calc/__init__.py"],
        green_claim=False,
        tests_run=False,
    )

    assert result.patch.diff.files[0].status == "added"
    assert result.filtered_patch == ""
    assert result.dropped == ["calc/__init__.py"]
    assert verdict.status == "REJECTED"
    assert "R4_patch_scope" in verdict.failed_predicate_ids()
    assert predicate(verdict, "R4_patch_scope").evidence == (
        "patch touches calc/__init__.py (shadows calc, which is protected)"
    )
