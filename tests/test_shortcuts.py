from difflib import unified_diff
import pytest

from receipts.verify import shortcuts


PATH = "src/pkg/mod.py"


def patch(path, before, after):
    return f"diff --git a/{path} b/{path}\n" + "".join(unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}",
    ))


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def check(root, after, before="", path=PATH, protected_modules=frozenset()):
    write(root, path, after)
    return shortcuts.find_shortcuts(patch(path, before, after), root, protected_modules)


def test_uncalled_private_helper(tmp_path):
    findings = check(tmp_path, "def _helper():\n    return 1\n")
    assert [f.model_dump() for f in findings] == [{
        "kind": "uncalled_private_helper", "path": PATH, "name": "_helper", "line": 1,
        "detail": "private helper _helper is added by the patch but nothing outside the tests calls it",
    }]


@pytest.mark.parametrize(("reference_path", "reference"), [
    ("src/pkg/other.py", "from pkg.mod import _helper\nvalue = _helper()\n"),
    ("src/pkg/other.py", "from .mod import _helper\nvalue = _helper()\n"),
    ("src/pkg/other.py", "import pkg.mod\nvalue = pkg.mod._helper()\n"),
    (PATH, "value = _helper()\n"),
])
def test_private_helper_referenced_in_source(tmp_path, reference_path, reference):
    after = "def _helper():\n    return 1\n"
    if reference_path == PATH:
        after += reference
    else:
        write(tmp_path, reference_path, reference)
    assert check(tmp_path, after) == []


def test_same_named_private_helper_in_an_unrelated_module_is_not_a_call(tmp_path):
    # Another module defines and calls its own _helper; it never imports pkg.mod.
    write(tmp_path, "src/other_pkg/campaign.py", "def _helper():\n    return 2\n\nvalue = _helper()\n")
    assert [f.kind for f in check(tmp_path, "def _helper():\n    return 1\n")] == [
        "uncalled_private_helper",
    ]


def test_existing_private_function_with_a_changed_signature_is_not_new(tmp_path):
    # The patch rewrites the def line of a function that already existed.
    before = "def _list(env, key):\n    return 1\n"
    after = "def _list(env, key, output=None):\n    return 1\n"
    assert check(tmp_path, after, before) == []


@pytest.mark.parametrize("decorator", ["@click.command()", "@register", "@app.route('/x')"])
def test_decorated_private_function_may_be_registered_by_its_decorator(tmp_path, decorator):
    assert check(tmp_path, f"{decorator}\ndef _helper():\n    return 1\n") == []


def test_relative_import_from_another_directory_is_not_a_call(tmp_path):
    write(tmp_path, "src/other_pkg/user.py", "from .mod import _helper\nvalue = _helper()\n")
    assert [f.kind for f in check(tmp_path, "def _helper():\n    return 1\n")] == [
        "uncalled_private_helper",
    ]


def test_private_helper_only_referenced_by_tests(tmp_path):
    write(tmp_path, "tests/test_mod.py", "assert _helper() == 1\n")
    assert [f.kind for f in check(tmp_path, "def _helper():\n    return 1\n")] == [
        "uncalled_private_helper",
    ]


@pytest.mark.parametrize("name", ["helper", "__helper__"])
def test_public_and_dunder_functions_are_allowed(tmp_path, name):
    assert check(tmp_path, f"def {name}():\n    return 1\n") == []


def test_private_method_called_by_another_method(tmp_path):
    assert check(tmp_path, "class C:\n    def _x(self):\n        return 1\n"
                 "    def value(self):\n        return self._x()\n") == []


def test_nested_async_private_helper(tmp_path):
    findings = check(tmp_path, "def outer():\n    async def _helper():\n        return 1\n    return 2\n")
    assert [(f.kind, f.name, f.line) for f in findings] == [
        ("uncalled_private_helper", "_helper", 2),
    ]


@pytest.mark.parametrize("directory", [
    ".git", "__pycache__", ".venv", "venv", "env", "node_modules", "build",
    "dist", "site-packages", ".tox", ".eggs",
])
def test_private_helper_search_skips_generated_directories(tmp_path, directory):
    write(tmp_path, f"{directory}/reference.py", "_helper()\n")
    assert len(check(tmp_path, "def _helper():\n    return 1\n")) == 1


@pytest.mark.parametrize("body", [
    '    raise NotImplementedError("x")\n',
    '    """Implement later."""\n    # TODO\n    raise NotImplementedError\n',
    "    pass\n", "    ...\n",
])
def test_added_stub(tmp_path, body):
    findings = check(tmp_path, "def helper():\n" + body)
    assert [(f.kind, f.name, f.line, f.detail) for f in findings] == [
        ("stub", "helper", 1, "helper is a stub (its body only raises NotImplementedError or does nothing)"),
    ]


@pytest.mark.parametrize("after", [
    "@abstractmethod\ndef helper():\n    pass\n",
    "@abc.abstractmethod\nasync def helper():\n    raise NotImplementedError\n",
    "class P(Protocol):\n    def helper(self):\n        ...\n",
    "class P(typing.Protocol[int]):\n    def helper(self):\n        ...\n",
    "class P(abc.ABC):\n    def helper(self):\n        raise NotImplementedError\n",
])
def test_abstract_stubs_are_allowed(tmp_path, after):
    assert check(tmp_path, after) == []


def test_untouched_stub_is_allowed(tmp_path):
    before = "def helper():\n    raise NotImplementedError\n"
    assert check(tmp_path, before + "\nVALUE = 1\n", before) == []


def test_raise_for_an_unsupported_case_inside_real_logic_is_not_a_stub(tmp_path):
    # The upstream fix of pybamm-4196 does this: one case raises, the others are implemented.
    before = "def helper(x):\n    return x + 1\n"
    after = ("def helper(x):\n    if x < 0:\n        raise NotImplementedError\n"
             "    if x == 0:\n        raise NotImplementedError('zero')\n    return x + 1\n")
    assert check(tmp_path, after, before) == []


@pytest.mark.parametrize("body", ["    raise NotImplementedError\n", "    pass\n", '    """Later."""\n    ...\n'])
def test_existing_function_gutted_to_a_stub_is_flagged(tmp_path, body):
    before = "def helper(x):\n    y = x * 2\n    return y + 1\n"
    assert [(f.kind, f.name, f.line) for f in check(tmp_path, "def helper(x):\n" + body, before)] == [
        ("stub", "helper", 1),
    ]


def test_existing_base_method_gutted_to_a_hook_that_subclasses_override_is_allowed(tmp_path):
    # The upstream fix of pybamm-4196: the base method becomes a hook, a subclass implements it.
    write(tmp_path, "src/pkg/interpolant.py",
          "from pkg.mod import Function\n\nclass Interpolant(Function):\n    def _diff(self):\n        return 1\n")
    before = "class Function:\n    def _diff(self):\n        return 2\n"
    after = "class Function:\n    def _diff(self):\n        raise NotImplementedError('implement in a subclass')\n"
    assert check(tmp_path, after, before) == []


def test_nested_raise_belongs_only_to_inner_function(tmp_path):
    after = "def outer():\n    def inner():\n        raise NotImplementedError\n    return inner\n"
    assert [(f.kind, f.name) for f in check(tmp_path, after)] == [("stub", "inner")]


def test_removing_existing_logic_alone_is_not_a_shortcut(tmp_path):
    # Correct upstream fixes delete 25 or more lines (natcap-invest-787, pytorch_geometric-7654,
    # pystac-561), so a count of removed lines cannot tell a shortcut from a refactor.
    before = "".join(f"value_{i} = {i}\n" for i in range(60))
    assert check(tmp_path, "VALUE = 0\n", before) == []


def test_syntax_error_skips_the_file(tmp_path):
    assert check(tmp_path, "def _broken(:\n    pass\n") == []


@pytest.mark.parametrize("path,protected", [
    ("tests/test_mod.py", frozenset()), ("conftest.py", frozenset()),
    ("notes.txt", frozenset()), ("pytest.py", frozenset({"pytest"})),
])
def test_only_source_python_files_are_checked(tmp_path, path, protected):
    assert check(tmp_path, "def _helper():\n    pass\n", path=path, protected_modules=protected) == []


@pytest.mark.parametrize("text", ["", "not a diff", "diff --git nonsense\n+def _helper():\n",
                                       "diff --git a/a.py b/a.py\n@@ malformed @@\n+pass\n"])
def test_bad_patch_does_not_raise(tmp_path, text):
    assert shortcuts.find_shortcuts(text, tmp_path) == []


def test_missing_source_does_not_raise(tmp_path):
    assert shortcuts.find_shortcuts(patch(PATH, "", "def _helper():\n    pass\n"), tmp_path) == []


def test_search_does_not_follow_links_outside_root(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    write(tmp_path, "outside.py", "_helper()\n")
    (root / "link.py").symlink_to(tmp_path / "outside.py")
    (root / "linked").symlink_to(tmp_path, target_is_directory=True)
    findings = check(root, "def _helper():\n    return 1\n")
    assert [f.kind for f in findings] == ["uncalled_private_helper"]


def test_changed_source_symlink_does_not_read_outside_root(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    write(tmp_path, "outside.py", "def _helper():\n    pass\n")
    (root / "mod.py").symlink_to(tmp_path / "outside.py")
    assert shortcuts.find_shortcuts(patch("mod.py", "", "def _helper():\n    pass\n"), root) == []


def test_findings_are_sorted_by_path_line_and_kind(tmp_path):
    after = "def _later():\n    pass\n\ndef _first():\n    return 1\n"
    write(tmp_path, "z.py", after)
    write(tmp_path, "a.py", after.replace("_later", "_other").replace("_first", "_last"))
    text = patch("z.py", "", after) + patch("a.py", "", (tmp_path / "a.py").read_text())
    findings = shortcuts.find_shortcuts(text, tmp_path)
    assert [(f.path, f.line, f.kind) for f in findings] == [
        ("a.py", 1, "stub"), ("a.py", 1, "uncalled_private_helper"),
        ("a.py", 4, "uncalled_private_helper"), ("z.py", 1, "stub"),
        ("z.py", 1, "uncalled_private_helper"), ("z.py", 4, "uncalled_private_helper"),
    ]


@pytest.mark.parametrize("subclasses", [
    # A direct subclass in another file overrides the hook.
    "from pkg.mod import Function\n\nclass Sin(Function):\n    def _diff(self, mode):\n        return 3\n",
    # An override two levels down, through an intermediate class that does not override it.
    "import pkg.mod\n\nclass Specific(pkg.mod.Function):\n    pass\n\n"
    "class Cos(Specific):\n    def _diff(self, mode):\n        return 4\n",
])
def test_new_base_method_stub_that_a_subclass_overrides_is_a_hook(tmp_path, subclasses):
    # Python's documented use of NotImplementedError: a base-class method derived classes override.
    write(tmp_path, "src/pkg/functions.py", subclasses)
    before = "class Function:\n    def value(self):\n        return 1\n"
    after = before + "\n    def _diff(self, mode):\n        raise NotImplementedError\n\n    def use(self):\n        return self._diff(1)\n"
    assert check(tmp_path, after, before) == []


GUTTED_BEFORE = "class Function:\n    def diff(self, mode):\n        return mode + 1\n"
GUTTED_AFTER = "class Function:\n    def diff(self, mode):\n        raise NotImplementedError\n"


@pytest.mark.parametrize("subclasses", [
    "class Sin(Function):\n    def other(self):\n        return 3\n",  # a subclass that does not override it
    "class Unrelated:\n    def diff(self, mode):\n        return 3\n",  # same name, not a subclass
])
def test_stub_method_no_subclass_overrides_is_still_flagged(tmp_path, subclasses):
    write(tmp_path, "src/pkg/functions.py", subclasses)
    assert [(f.kind, f.name) for f in check(tmp_path, GUTTED_AFTER, GUTTED_BEFORE)] == [("stub", "diff")]


def test_overrides_in_tests_do_not_make_a_hook(tmp_path):
    write(tmp_path, "tests/test_mod.py", "class Fake(Function):\n    def diff(self, mode):\n        return 3\n")
    assert [(f.kind, f.name) for f in check(tmp_path, GUTTED_AFTER, GUTTED_BEFORE)] == [("stub", "diff")]


@pytest.mark.parametrize("base", [
    "class Function:\n    def _diff(self):\n        return 1\n",
    # Two levels up, through an intermediate class that does not define it.
    "class Symbol:\n    def _diff(self):\n        return 1\n\nclass Function(Symbol):\n    pass\n",
])
def test_new_private_method_that_overrides_an_ancestor_is_called_by_dispatch(tmp_path, base):
    # The upstream fix of pybamm-4196 adds Interpolant._function_diff; the base class calls it.
    write(tmp_path, "src/pkg/functions.py", base)
    after = "from pkg.functions import Function\n\nclass Interpolant(Function):\n    def _diff(self):\n        return 2\n"
    assert check(tmp_path, after) == []


def test_new_private_method_with_an_unrelated_same_named_method_is_uncalled(tmp_path):
    write(tmp_path, "src/pkg/other.py", "class Other:\n    def _diff(self):\n        return 1\n")
    after = "class Interpolant:\n    def _diff(self):\n        return 2\n"
    assert [(f.kind, f.name) for f in check(tmp_path, after)] == [("uncalled_private_helper", "_diff")]


def test_new_method_that_only_raises_in_a_leaf_class_is_flagged(tmp_path):
    # A subclass method added only to refuse the call is a stub, even though the base defines it.
    write(tmp_path, "src/pkg/base.py", "class OperatorBase:\n    def jacobian(self, u):\n        return u\n")
    before = "class NumpyOperator(OperatorBase):\n    def apply(self, u):\n        return u\n"
    after = before + "\n    def jacobian(self, u):\n        raise NotImplementedError\n"
    assert [(f.kind, f.name) for f in check(tmp_path, after, before)] == [("stub", "jacobian")]


# Review findings on the first version of the override rules.

@pytest.mark.parametrize(("user_path", "user"), [
    ("src/pkg/sub/use.py", "from ..mod import _helper\nvalue = _helper()\n"),
    ("src/app.py", "from pkg import mod\nvalue = mod._helper()\n"),
    ("src/pkg/use.py", "from . import mod as m\nvalue = m._helper()\n"),
    ("src/pkg/use.py", "from .mod import _helper as h\nvalue = h()\n"),
])
def test_imports_resolved_from_the_syntax_tree_are_calls(tmp_path, user_path, user):
    write(tmp_path, user_path, user)
    assert check(tmp_path, "def _helper():\n    return 1\n") == []


@pytest.mark.parametrize(("user_path", "user"), [
    ("src/pkg/other.py", "# pkg.mod _helper\nVALUE = 1\n"),
    (PATH, "# _helper is kept for later\n"),
])
def test_a_comment_is_not_a_call(tmp_path, user_path, user):
    after = "def _helper():\n    return 1\n"
    if user_path == PATH:
        after += user
    else:
        write(tmp_path, user_path, user)
    assert [f.kind for f in check(tmp_path, after)] == ["uncalled_private_helper"]


def test_a_name_in_a_string_counts_as_a_use(tmp_path):
    # getattr and registries look a function up by name; that is a use, not dead code.
    assert check(tmp_path, "def _helper():\n    return 1\n\nVALUE = getattr(object, '_helper', None)\n") == []


def test_override_of_a_same_named_base_class_in_another_module_is_called(tmp_path):
    write(tmp_path, "src/pkg/foo.py", "class Foo:\n    def _hook(self):\n        return 1\n"
                                      "    def run(self):\n        return self._hook()\n")
    after = "from . import foo\n\nclass Foo(foo.Foo):\n    def _hook(self):\n        return 2\n"
    assert check(tmp_path, after) == []


def test_hook_overridden_by_a_same_named_subclass_in_another_module_is_allowed(tmp_path):
    write(tmp_path, "src/pkg/other.py",
          "from pkg import mod\n\nclass Foo(mod.Foo):\n    def run(self):\n        return 2\n")
    before = "class Foo:\n    def run(self):\n        return 1\n"
    after = "class Foo:\n    def run(self):\n        raise NotImplementedError\n"
    assert check(tmp_path, after, before) == []


def test_conditional_override_makes_a_hook(tmp_path):
    write(tmp_path, "src/pkg/impl.py",
          "from pkg.mod import Base\n\nclass Impl(Base):\n    if True:\n        def run(self):\n            return 1\n")
    before = "class Base:\n    def run(self):\n        return 2\n"
    after = "class Base:\n    def run(self):\n        raise NotImplementedError\n"
    assert check(tmp_path, after, before) == []


def test_conditional_private_method_that_overrides_an_ancestor_is_called(tmp_path):
    write(tmp_path, "src/pkg/base.py", "class Base:\n    def _hook(self):\n        return 1\n")
    after = ("from pkg.base import Base\n\nclass Impl(Base):\n    try:\n        def _hook(self):\n"
             "            return 2\n    except Exception:\n        pass\n")
    assert check(tmp_path, after) == []


def test_override_in_a_class_the_patch_adds_does_not_excuse_a_gutted_method(tmp_path):
    before = "class Function:\n    def diff(self):\n        return 1\n"
    after = ("class Function:\n    def diff(self):\n        raise NotImplementedError\n\n"
             "class Dodge(Function):\n    def diff(self):\n        return None\n")
    assert [(f.kind, f.name) for f in check(tmp_path, after, before)] == [("stub", "diff")]


def test_nested_function_in_an_abstract_class_is_not_abstract(tmp_path):
    after = ("from abc import ABC\n\nclass Factory(ABC):\n    def build(self):\n"
             "        def work():\n            pass\n        return work\n")
    assert [(f.kind, f.name) for f in check(tmp_path, after)] == [("stub", "work")]


def test_qualified_not_implemented_error_is_a_stub(tmp_path):
    after = "import builtins\n\ndef work():\n    raise builtins.NotImplementedError\n"
    assert [(f.kind, f.name) for f in check(tmp_path, after)] == [("stub", "work")]


def test_many_subclasses_and_stubs_stay_fast(tmp_path):
    import time
    subclasses = "".join(f"class C{i}(C0):\n    pass\n\n" for i in range(1, 3000))
    write(tmp_path, "src/pkg/subs.py", "from pkg.mod import C0\n\n" + subclasses)
    before = "class C0:\n" + "".join(f"    def m{i}(self):\n        return {i}\n" for i in range(30))
    after = "class C0:\n" + "".join(f"    def m{i}(self):\n        raise NotImplementedError\n" for i in range(30))
    start = time.monotonic()
    assert len(check(tmp_path, after, before)) == 30
    assert time.monotonic() - start < 10


def test_deep_expressions_do_not_hide_findings(tmp_path):
    deep = "Factory" + "[0]" * 1000
    write(tmp_path, "src/pkg/deep.py", f"class Deep({deep}):\n    pass\n")
    after = f"class Deep2({deep}):\n    pass\n\nclass C:\n    def run(self):\n        raise NotImplementedError\n"
    assert [(f.kind, f.name) for f in check(tmp_path, after)] == [("stub", "run")]


# Second review: definitions are compared with the file as it was before the patch.

def test_private_method_called_on_an_instance_from_another_module_is_called(tmp_path):
    # The class is re-exported by the package, so the caller never imports the defining module.
    write(tmp_path, "src/pkg/__init__.py", "from .mod import C\n")
    write(tmp_path, "src/use.py", "from pkg import C\nresult = C()._x()\n")
    assert check(tmp_path, "class C:\n    def _x(self):\n        return 1\n") == []


def test_hook_overridden_through_an_aliased_base_is_allowed(tmp_path):
    write(tmp_path, "src/pkg/sub.py",
          "from pkg.mod import Base as Parent\n\nclass Sub(Parent):\n    def run(self):\n        return 2\n")
    before = "class Base:\n    def run(self):\n        return 1\n"
    after = "class Base:\n    def run(self):\n        raise NotImplementedError\n"
    assert check(tmp_path, after, before) == []


@pytest.mark.parametrize("header", [
    "from abc import ABC as Parent\n\nclass API(Parent):\n",
    "import abc\n\nclass API(metaclass=abc.ABCMeta):\n",
])
def test_aliased_abstract_bases_are_abstract(tmp_path, header):
    assert check(tmp_path, header + "    def run(self):\n        raise NotImplementedError\n") == []


def test_rewording_an_existing_stub_is_not_a_new_stub(tmp_path):
    before = "def f():\n    raise NotImplementedError('old')\n"
    after = "def f():\n    raise NotImplementedError('new')\n"
    assert check(tmp_path, after, before) == []


def test_deleting_the_logic_before_a_surviving_raise_makes_a_stub(tmp_path):
    before = "def f():\n    audit()\n    raise NotImplementedError\n"
    after = "def f():\n    raise NotImplementedError\n"
    assert [(f.kind, f.name) for f in check(tmp_path, after, before)] == [("stub", "f")]


def test_a_deleted_same_named_class_does_not_make_an_added_class_old(tmp_path):
    before = ("class Base:\n    def run(self):\n        return 1\n\n"
              "class Holder:\n    class Dodge:\n        pass\n")
    after = ("class Base:\n    def run(self):\n        raise NotImplementedError\n\n"
             "class Dodge(Base):\n    def run(self):\n        return None\n")
    assert [(f.kind, f.name) for f in check(tmp_path, after, before)] == [("stub", "run")]


def test_a_deleted_same_named_method_does_not_make_an_added_one_old(tmp_path):
    before = "class Old:\n    def _helper(self, x):\n        return x\n"
    after = "class New:\n    def _helper(self):\n        return 1\n"
    assert [(f.kind, f.name) for f in check(tmp_path, after, before)] == [("uncalled_private_helper", "_helper")]


def test_many_same_named_subclasses_stay_fast(tmp_path):
    import time
    write(tmp_path, "src/pkg/subs.py",
          "from pkg import mod\n\n" + "class Foo(mod.Foo):\n    pass\n\n" * 3000)
    before = "class Foo:\n" + "".join(f"    def m{i}(self):\n        return {i}\n" for i in range(30))
    after = "class Foo:\n" + "".join(f"    def m{i}(self):\n        raise NotImplementedError\n" for i in range(30))
    start = time.monotonic()
    assert len(check(tmp_path, after, before)) == 30
    assert time.monotonic() - start < 10


def test_unreadable_directory_does_not_raise(tmp_path):
    import os
    if os.geteuid() == 0:
        pytest.skip("root can read any directory")
    blocked = tmp_path / "src" / "blocked"
    (blocked / "child").mkdir(parents=True)
    blocked.chmod(0o400)
    try:
        findings = check(tmp_path, "class C:\n    def run(self):\n        raise NotImplementedError\n")
    finally:
        blocked.chmod(0o700)
    assert [(f.kind, f.name) for f in findings] == [("stub", "run")]


# Third review.

OVERLOADS = ("from typing import overload\n\n@overload\ndef parse(x: str) -> int: ...\n"
             "@overload\ndef parse(x: bytes) -> int: ...\n")


def test_overload_declarations_are_not_stubs(tmp_path):
    assert check(tmp_path, OVERLOADS + "def parse(x):\n    return int(x)\n") == []


def test_gutted_implementation_beside_overloads_is_a_stub(tmp_path):
    before = OVERLOADS + "def parse(x):\n    return int(x)\n"
    after = OVERLOADS + "def parse(x):\n    pass\n"
    assert [(f.kind, f.name, f.line) for f in check(tmp_path, after, before)] == [("stub", "parse", 7)]


def test_existing_concrete_method_of_an_abc_gutted_is_a_stub(tmp_path):
    before = "from abc import ABC\n\nclass Store(ABC):\n    def save(self, value):\n        return persist(value)\n"
    after = "from abc import ABC\n\nclass Store(ABC):\n    def save(self, value):\n        pass\n"
    assert [(f.kind, f.name) for f in check(tmp_path, after, before)] == [("stub", "save")]


def test_new_hook_implemented_by_new_subclasses_is_allowed(tmp_path):
    # A fix that introduces a small hierarchy: the base hook and its implementations are all new.
    after = ("class Exporter:\n    def write(self, rows):\n        raise NotImplementedError\n\n"
             "class CsvExporter(Exporter):\n    def write(self, rows):\n        return len(rows)\n")
    assert check(tmp_path, after) == []


def test_zero_context_deletion_rebuilds_the_old_file(tmp_path):
    write(tmp_path, PATH, "def f():\n    raise NotImplementedError\n")
    text = (f"diff --git a/{PATH} b/{PATH}\n--- a/{PATH}\n+++ b/{PATH}\n"
            "@@ -2 +1,0 @@\n-    audit()\n")
    assert [(f.kind, f.name) for f in shortcuts.find_shortcuts(text, tmp_path)] == [("stub", "f")]
