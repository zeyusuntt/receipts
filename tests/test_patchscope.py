import hashlib
import subprocess

from receipts.patchscope import categorize, filter_patch, summarize_patch


def test_categorize_paths():
    assert categorize("src/pkg/core.py") == "source"
    assert categorize("tests/test_core.py") == "test"
    assert categorize("pkg/tests/unit/test_a.py") == "test"
    assert categorize("pkg/core_test.py") == "test"
    assert categorize("conftest.py") == "pytest_config"
    assert categorize("pkg/deep/conftest.py") == "pytest_config"
    assert categorize("pytest.ini") == "pytest_config"
    assert categorize("tox.ini") == "pytest_config"
    assert categorize("pyproject.toml") == "pytest_config"
    assert categorize("setup.cfg") == "pytest_config"
    assert categorize("README.md") == "other"
    assert categorize("../escape.py") == "outside"
    assert categorize("/etc/passwd") == "outside"


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
