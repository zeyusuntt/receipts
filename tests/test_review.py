import asyncio
import hashlib

import pytest

from receipts.llm import FakeModel
from receipts.verify import review


PATCH = """diff --git a/src/pkg/mod.py b/src/pkg/mod.py
--- a/src/pkg/mod.py
+++ b/src/pkg/mod.py
@@ -1,4 +1,5 @@
 def resolve(glob):
-    return search(glob)
+    root = repo_root()
+    return search(root / glob)

 VALUE = 1
@@ -10,2 +11,2 @@ def other():
-    return 1
+    return 2
     # end
diff --git a/tests/test_mod.py b/tests/test_mod.py
--- a/tests/test_mod.py
+++ b/tests/test_mod.py
@@ -1 +1,2 @@
 import mod
+assert mod.resolve("x")
"""

ISSUE = """The default case set should be found wherever the process is started.
A glob the caller passes explicitly should keep working as it does now."""


def test_annotate_numbers_added_and_context_lines_with_new_file_numbers():
    text, lines = review.annotate_patch(PATCH)
    assert "+    2 |     root = repo_root()" in text
    assert "+    3 |     return search(root / glob)" in text
    assert "     1 | def resolve(glob):" in text
    assert "-      |     return search(glob)" in text
    assert "+   11 |     return 2" in text
    assert lines == {"src/pkg/mod.py": {1, 2, 3, 4, 5, 11, 12}}


def test_annotate_leaves_out_test_files():
    text, lines = review.annotate_patch(PATCH)
    assert "tests/test_mod.py" not in text
    assert "tests/test_mod.py" not in lines


def test_annotate_empty_new_range_and_no_newline_marker():
    patch = ("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
             "@@ -2 +1,0 @@\n-    audit()\n@@ -5,1 +4,1 @@\n-x = 1\n+x = 2\n\\ No newline at end of file\n")
    text, lines = review.annotate_patch(patch)
    assert "-      |     audit()" in text
    assert "+    4 | x = 2" in text
    assert "\\ No newline at end of file" in text
    assert lines == {"src/a.py": {4}}


def objection(requirement="A glob the caller passes explicitly should keep working as it does now.",
              location="src/pkg/mod.py:3", problem="a relative explicit glob is joined to the repository root"):
    return review.ReviewObjection(requirement=requirement, location=location, problem=problem)


LINES = {"src/pkg/mod.py": {1, 2, 3, 4, 5, 11, 12}}


@pytest.mark.parametrize("requirement", [
    "A glob the caller passes explicitly should keep working as it does now.",
    "a glob the caller passes   explicitly should keep working",
    '"A glob the caller passes explicitly should keep working as it does now"',
    "The default case set should be found wherever the process is started. A glob",
])
def test_ground_accepts_verbatim_quotes(requirement):
    assert review.ground(objection(requirement=requirement), ISSUE, LINES)


@pytest.mark.parametrize("location", ["src/pkg/mod.py:3", "b/src/pkg/mod.py:11", "a/src/pkg/mod.py:1"])
def test_ground_accepts_locations_in_the_annotated_hunks(location):
    assert review.ground(objection(location=location), ISSUE, LINES)


@pytest.mark.parametrize("changed", [
    {"requirement": "explicit globs must still work"},          # a paraphrase
    {"requirement": "keep working"},                            # too short to be a requirement
    {"location": "src/pkg/other.py:3"},                         # not a file in the patch
    {"location": "src/pkg/mod.py:7"},                           # not a line in the hunks
    {"location": "src/pkg/mod.py"},                             # no line
    {"location": "src/pkg/mod.py:x"},
    {"location": "src/pkg/mod.py:0"},
    {"problem": "   "},
])
def test_ground_rejects_ungrounded_objections(changed):
    assert not review.ground(objection(**changed), ISSUE, LINES)


def run(coro):
    return asyncio.run(coro)


def test_review_returns_grounded_objections_and_drops_the_rest():
    grounded = objection()
    ungrounded = objection(requirement="the code should be nicer to read")
    model = FakeModel(json_objects=[{"objections": [grounded.model_dump(), ungrounded.model_dump()]}])
    result = run(review.review_patch(model, ISSUE, ["tests/test_mod.py::test_resolve"], PATCH))
    assert result.objections == [grounded]
    assert result.dropped == [ungrounded]
    assert result.error is None
    request = model.requests[0]
    assert request["system"] == review.SYSTEM_PROMPT
    assert request["user"].startswith("Issue:\n" + ISSUE + "\n\nTests the patch already passes:\n"
                                      "tests/test_mod.py::test_resolve\n\nPatch (source files only;")
    assert "tests/test_mod.py b/" not in request["user"]
    assert result.prompt_sha256 == hashlib.sha256(
        (request["system"] + "\n\n" + request["user"]).encode("utf-8")).hexdigest()


def test_review_with_no_objection():
    result = run(review.review_patch(FakeModel(json_objects=[{"objections": []}]), ISSUE, [], PATCH))
    assert result.objections == [] and result.dropped == [] and result.error is None


def test_a_failed_review_never_objects():
    class Broken:
        async def complete_json(self, system, user, schema):
            raise RuntimeError("provider down")

    result = run(review.review_patch(Broken(), ISSUE, [], PATCH))
    assert result.objections == []
    assert result.error == "RuntimeError: provider down"


def test_a_patch_without_source_files_is_not_reviewed():
    patch = PATCH[PATCH.index("diff --git a/tests"):]
    model = FakeModel()
    result = run(review.review_patch(model, ISSUE, [], patch))
    assert result.objections == [] and model.requests == []


def test_a_long_patch_is_cut_at_a_line_and_only_shown_lines_ground():
    body = "".join(f"+line_{i} = {i}\n" for i in range(4000))
    patch = f"diff --git a/src/big.py b/src/big.py\n--- a/src/big.py\n+++ b/src/big.py\n@@ -0,0 +1,4000 @@\n{body}"
    early = objection(requirement="The default case set should be found wherever the process is started",
                      location="src/big.py:3")
    unseen = early.model_copy(update={"location": "src/big.py:3999"})
    model = FakeModel(json_objects=[{"objections": [early.model_dump(), unseen.model_dump()]}])
    result = run(review.review_patch(model, ISSUE, [], patch))
    user = model.requests[0]["user"]
    assert user.endswith("[patch truncated]\n")
    assert "line_3999" not in user and "line_3 = 3" in user
    assert result.objections == [early] and result.dropped == [unseen]


def test_a_unicode_line_separator_inside_a_line_does_not_shift_numbers():
    patch = ("diff --git a/src/mod.py b/src/mod.py\n--- a/src/mod.py\n+++ b/src/mod.py\n"
             "@@ -1,2 +1,2 @@\n-# old\n+# new\u2028continued\n-value = 1\n+value = 2\n")
    _, lines = review.annotate_patch(patch)
    assert lines == {"src/mod.py": {1, 2}}


def test_the_patch_ending_newline_is_not_a_context_line():
    patch = "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    assert review.annotate_patch(patch)[1] == {"src/a.py": {1}}


def test_a_repository_directory_named_a_is_not_taken_for_a_diff_prefix():
    lines = {"a/api.py": {8}}
    assert review.ground(objection(location="a/api.py:8"), ISSUE, lines)
    assert review.ground(objection(location="b/a/api.py:8"), ISSUE, lines)


@pytest.mark.parametrize("location", ["src/pkg/mod.py:\u00b2", "src/pkg/mod.py:" + "9" * 40, "src/pkg/mod.py:-3"])
def test_unusual_line_numbers_are_not_grounded_and_do_not_raise(location):
    assert not review.ground(objection(location=location), ISSUE, LINES)


def test_review_records_the_reviewer_usage():
    from receipts.cost import TokenUsage
    answer = review.ReviewAnswer(objections=[], usage=TokenUsage(prompt=1000, completion=100))
    model = FakeModel(json_objects=[answer])
    result = run(review.review_patch(model, ISSUE, [], PATCH))
    assert result.usage == TokenUsage(prompt=1000, completion=100)
    assert "usage" not in review.ReviewAnswer.model_json_schema()["properties"]
