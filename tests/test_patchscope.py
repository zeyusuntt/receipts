import hashlib
import subprocess

import pytest

import receipts.patchscope as patchscope
from receipts.models import ChangedFile
from receipts.patchscope import categorize, filter_patch, summarize_patch


def test_categorize_paths():
    assert categorize("src/pkg/core.py") == "source"
    assert categorize("tests/test_core.py") == "test"
    assert categorize("pkg/tests/unit/test_a.py") == "test"
    assert categorize("pkg/core_test.py") == "test"
    assert categorize("conftest.py") == "pytest_config"
    assert categorize("pkg/deep/conftest.py") == "pytest_config"
    assert categorize("pytest.ini") == "pytest_config"
    assert categorize("pytest.toml") == "pytest_config"
    assert categorize(".pytest.toml") == "pytest_config"
    assert categorize("tox.ini") == "pytest_config"
    assert categorize("pyproject.toml") == "pytest_config"
    assert categorize("setup.cfg") == "pytest_config"
    assert categorize("README.md") == "other"
    assert categorize("../escape.py") == "outside"
    assert categorize("/etc/passwd") == "outside"


def test_categorize_executable_artifacts():
    for suffix in (".pyc", ".pyo", ".so", ".pyd", ".dylib", ".pth"):
        assert categorize(f"build/payload{suffix}") == "executable_artifact"


def test_categorize_top_level_protected_module_shadows():
    protected = frozenset({"pytest", "json"})

    assert categorize("pytest.py", protected) == "shadow"
    assert categorize("pytest.pyc", protected) == "shadow"
    assert categorize("pytest.so", protected) == "shadow"
    assert categorize("json/__init__.py", protected) == "shadow"
    assert categorize("pkg/pytest.py", protected) == "source"
    assert categorize("pkg/json/__init__.py", protected) == "source"


def test_default_protected_modules_include_runtime_import_surfaces():
    protected = patchscope.default_protected_modules()

    assert {"json", "pytest", "_pytest", "py", "pluggy", "conftest"} <= protected


PATCH = """diff --git a/src/pkg/core.py b/src/pkg/core.py
index 1111111..2222222 100644
--- a/src/pkg/core.py
+++ b/src/pkg/core.py
@@ -1,3 +1,4 @@
 def add(a, b):
-    return a - b
+    # fixed
+    return a + b
diff --git a/tests/test_core.py b/tests/test_core.py
index 3333333..4444444 100644
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -1,2 +1,2 @@
 def test_add():
-    assert add(1, 2) == 3
+    assert add(1, 2) == 4
"""


def test_summarize_patch_counts_and_categories():
    s = summarize_patch(PATCH)
    assert [f.path for f in s.files] == ["src/pkg/core.py", "tests/test_core.py"]
    core, test = s.files
    assert (core.added, core.deleted, core.category) == (2, 1, "source")
    assert (test.added, test.deleted, test.category) == (1, 1, "test")
    assert s.changed_lines == 5
    assert s.patch_sha256 == hashlib.sha256(PATCH.encode()).hexdigest()


def test_summarize_empty_patch():
    s = summarize_patch("")
    assert s.files == [] and s.changed_lines == 0


def test_quoted_test_path_starts_unparseable_block_and_fails_closed():
    patch = """diff --git a/mod.py b/mod.py
index 1111111..2222222 100644
--- a/mod.py
+++ b/mod.py
@@ -1 +1 @@
-x = 0
+x = 1
diff --git "a/tests/test_\\nx.py" "b/tests/test_\\nx.py"
new file mode 100644
index 0000000..d1f3b4e
--- /dev/null
+++ "b/tests/test_\\nx.py"
@@ -0,0 +1,2 @@
+def test_spec():
+    assert True
"""

    summary = summarize_patch(patch)

    assert [(item.path, item.category) for item in summary.files] == [
        ("mod.py", "source"),
        ('"a/tests/test_\\nx.py" "b/tests/test_\\nx.py"', "unparseable"),
    ]
    assert (summary.files[1].added, summary.files[1].deleted, summary.files[1].status) == (2, 0, None)
    assert filter_patch(patch) == (
        "",
        ["mod.py", '"a/tests/test_\\nx.py" "b/tests/test_\\nx.py"'],
    )


@pytest.mark.parametrize(
    "quoted_path",
    [
        r'tests/test_\tx.py',
        r'tests/test_\"x.py',
        r'tests/test_\\x.py',
    ],
)
def test_quoted_headers_for_tab_quote_and_backslash_are_unparseable(quoted_path):
    raw_header = f'"a/{quoted_path}" "b/{quoted_path}"'
    patch = f"diff --git {raw_header}\nnew file mode 120000\n"

    summary = summarize_patch(patch)

    assert [(item.path, item.category) for item in summary.files] == [
        (raw_header, "unparseable"),
    ]
    assert filter_patch(patch) == ("", [raw_header])


def test_unquoted_path_containing_b_marker_is_parsed_and_kept():
    patch = """diff --git a/pkg/a b/c.py b/pkg/a b/c.py
index 1111111..2222222 100644
--- a/pkg/a b/c.py
+++ b/pkg/a b/c.py
@@ -1 +1 @@
-x = 0
+x = 1
"""

    summary = summarize_patch(patch)

    assert [(item.path, item.category) for item in summary.files] == [
        ("pkg/a b/c.py", "source"),
    ]
    assert filter_patch(patch) == (patch, [])


@pytest.mark.parametrize(
    ("block", "expected_status"),
    [
        (
            """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+x = 1
""",
            "added",
        ),
        (
            """diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
""",
            "deleted",
        ),
        (
            """diff --git a/mod.py b/mod.py
index 1111111..2222222 100644
--- a/mod.py
+++ b/mod.py
@@ -1 +1 @@
-x = 0
+x = 1
""",
            "modified",
        ),
        (
            """diff --git a/tool.py b/tool.py
old mode 100644
new mode 100755
""",
            "modified",
        ),
        (
            """diff --git a/assets/new.bin b/assets/new.bin
new file mode 100644
index 0000000..d00491f
GIT binary patch
literal 1
IcmZPo000310RR91

literal 0
HcmV?d00001

""",
            "added",
        ),
        (
            """diff --git a/assets/data.bin b/assets/data.bin
index 1111111..2222222 100644
GIT binary patch
literal 1
IcmZPo000310RR91

literal 0
HcmV?d00001

""",
            "modified",
        ),
    ],
)
def test_summarize_patch_reports_file_status(block, expected_status):
    summary = summarize_patch(block)

    assert len(summary.files) == 1
    assert summary.files[0].status == expected_status


@pytest.mark.parametrize(
    "metadata",
    [
        "rename from x\n",
        "rename to y\n",
        "copy from x\n",
        "copy to y\n",
        "similarity index 100%\n",
        "dissimilarity index 20%\n",
    ],
)
def test_rename_copy_and_similarity_metadata_make_block_unparseable(metadata):
    patch = f"diff --git a/x b/x\n{metadata}"

    summary = summarize_patch(patch)

    assert [(item.path, item.category, item.status) for item in summary.files] == [
        ("a/x b/x", "unparseable", None),
    ]
    assert filter_patch(patch) == ("", ["a/x b/x"])


def test_changed_file_from_older_record_defaults_status_to_none():
    changed = ChangedFile.model_validate(
        {"path": "mod.py", "added": 1, "deleted": 1, "category": "source"},
    )

    assert changed.status is None


def test_summarize_new_deleted_and_symlink_files():
    patch = """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-gone = True
diff --git a/link.py b/link.py
new file mode 120000
--- /dev/null
+++ b/link.py
@@ -0,0 +1 @@
+/etc/passwd
\\ No newline at end of file
"""
    s = summarize_patch(patch)
    assert [(f.path, f.added, f.deleted, f.category) for f in s.files] == [
        ("new.py", 2, 0, "source"), ("old.py", 0, 1, "source"), ("link.py", 1, 0, "symlink"),
    ]


def test_filter_mixed_patch_keeps_allowed_blocks_byte_for_byte():
    readme = """diff --git a/README.md b/README.md
index 5555555..6666666 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
\\ No newline at end of file
"""
    binary = """diff --git a/assets/data.bin b/assets/data.bin
new file mode 100644
index 0000000..d00491f
GIT binary patch
literal 1
IcmZPo000310RR91

literal 0
HcmV?d00001

"""
    source = PATCH.split("diff --git a/tests/test_core.py", 1)[0]
    filtered, dropped = filter_patch(PATCH + readme + binary)
    assert filtered == source + readme + binary
    assert dropped == ["tests/test_core.py"]


def test_filter_drops_exact_spec_paths_regardless_of_category():
    root_spec = """diff --git a/test.py b/test.py
index 1111111..2222222 100644
--- a/test.py
+++ b/test.py
@@ -1 +1 @@
-EXPECTED = 1
+EXPECTED = 2
"""
    fixture_spec = """diff --git a/config/fixture.yaml b/config/fixture.yaml
index 3333333..4444444 100644
--- a/config/fixture.yaml
+++ b/config/fixture.yaml
@@ -1 +1 @@
-enabled: false
+enabled: true
"""
    source = """diff --git a/src/pkg/core.py b/src/pkg/core.py
index 5555555..6666666 100644
--- a/src/pkg/core.py
+++ b/src/pkg/core.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""
    assert [
        (item.path, item.category)
        for item in summarize_patch(root_spec + fixture_spec + source).files
    ] == [
        ("test.py", "source"),
        ("config/fixture.yaml", "other"),
        ("src/pkg/core.py", "source"),
    ]

    filtered, dropped = filter_patch(
        root_spec + fixture_spec + source,
        spec_paths=frozenset({"test.py", "config/fixture.yaml"}),
    )

    assert filtered == source
    assert dropped == ["test.py", "config/fixture.yaml"]


def test_filter_drops_conftest_anywhere():
    patch = """diff --git a/conftest.py b/conftest.py
new file mode 100644
--- /dev/null
+++ b/conftest.py
@@ -0,0 +1 @@
+ROOT = True
diff --git a/pkg/deep/conftest.py b/pkg/deep/conftest.py
new file mode 100644
--- /dev/null
+++ b/pkg/deep/conftest.py
@@ -0,0 +1 @@
+DEEP = True
"""
    assert filter_patch(patch) == ("", ["conftest.py", "pkg/deep/conftest.py"])


def test_filter_drops_hidden_and_site_packages_paths():
    patch = """diff --git a/.venv/lib/hook.py b/.venv/lib/hook.py
new file mode 100644
--- /dev/null
+++ b/.venv/lib/hook.py
@@ -0,0 +1 @@
+HIDDEN = True
diff --git a/vendor/site-packages/pkg/hook.py b/vendor/site-packages/pkg/hook.py
new file mode 100644
--- /dev/null
+++ b/vendor/site-packages/pkg/hook.py
@@ -0,0 +1 @@
+VENDORED = True
"""
    assert filter_patch(patch) == (
        "", [".venv/lib/hook.py", "vendor/site-packages/pkg/hook.py"],
    )


def test_filter_drops_symlink_block():
    patch = """diff --git a/calc/link.py b/calc/link.py
new file mode 120000
index 0000000..1234567
--- /dev/null
+++ b/calc/link.py
@@ -0,0 +1 @@
+/etc/passwd
\\ No newline at end of file
"""
    assert filter_patch(patch) == ("", ["calc/link.py"])


def test_filter_drops_executable_artifacts_and_protected_shadows():
    patch = """diff --git a/build/payload.pyc b/build/payload.pyc
new file mode 100644
index 0000000..1234567
GIT binary patch
literal 1
IcmZPo000310RR91

literal 0
HcmV?d00001

diff --git a/pytest.py b/pytest.py
new file mode 100644
--- /dev/null
+++ b/pytest.py
@@ -0,0 +1 @@
+raise SystemExit(0)
"""

    assert filter_patch(patch, frozenset({"pytest"})) == (
        "", ["build/payload.pyc", "pytest.py"],
    )


def test_filter_empty_patch():
    assert filter_patch("") == ("", [])


def test_filtered_output_applies_cleanly(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "x.py").write_text("VALUE = 1\n")
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
        cwd=repo, check=True,
    )
    (repo / "src" / "x.py").write_text("VALUE = 2\n")
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert False\n")
    patch = subprocess.run(
        ["git", "-c", "core.quotePath=false", "diff", "--binary"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    filtered, dropped = filter_patch(patch)
    subprocess.run(["git", "restore", "src/x.py", "tests/test_x.py"], cwd=repo, check=True)
    checked = subprocess.run(
        ["git", "apply", "--check", "-"], cwd=repo, input=filtered, capture_output=True, text=True,
    )
    assert dropped == ["tests/test_x.py"]
    assert checked.returncode == 0, checked.stderr
