"""Find patch shortcuts using the diff and the executor's post-patch tree."""

from __future__ import annotations

import ast
import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

from receipts.models import ShortcutFinding
from receipts.patchscope import _split_blocks, categorize

_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "env", "node_modules", "build",
    "dist", "site-packages", ".tox", ".eggs",
}
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_Function = ast.FunctionDef | ast.AsyncFunctionDef
_PARSE_ERRORS = (SyntaxError, ValueError, RecursionError, MemoryError)
# Statement lists that can hold a definition; expressions are never walked, so deep
# expressions cannot exhaust the recursion limit.
_BLOCKS = ("body", "orelse", "finalbody", "handlers", "cases")


@dataclass
class _FileChange:
    added: set[int]
    # Each deleted line with the line of the new file it stood before.
    deleted: list[tuple[int, str]]


def _patch_lines(patch_text: str) -> dict[str, _FileChange]:
    files: dict[str, _FileChange] = {}
    for path, _, parseable, lines in _split_blocks(patch_text):
        added: set[int] = set()
        deleted: list[tuple[int, str]] = []
        new_line = None
        for raw in lines[1:]:
            line = raw.rstrip("\r\n")
            hunk = _HUNK.match(line)
            if hunk:
                try:
                    # An empty new range (`+1,0`) names the line before the hunk.
                    new_line = int(hunk[1]) + (1 if hunk[2] == "0" else 0)
                except ValueError:
                    new_line = None
            elif line.startswith("@@"):
                new_line = None
            elif new_line is not None:
                if line.startswith("+"):
                    added.add(new_line)
                    new_line += 1
                elif line.startswith("-"):
                    deleted.append((new_line, line[1:]))
                elif line.startswith(" "):
                    new_line += 1
                elif not line.startswith("\\"):
                    new_line = None
        if parseable:
            change = files.setdefault(path, _FileChange(set(), []))
            change.added.update(added)
            change.deleted.extend(deleted)
    return files


def _before(source: str, change: _FileChange) -> str:
    """The file as it was before the patch: the new file without its added lines, with the
    deleted lines put back where they stood."""
    inserts: dict[int, list[str]] = {}
    for position, text in change.deleted:
        inserts.setdefault(position, []).append(text + "\n")
    lines: list[str] = []
    for number, line in enumerate(source.splitlines(keepends=True), 1):
        lines.extend(inserts.pop(number, ()))
        if number not in change.added:
            lines.append(line)
    for position in sorted(inserts):
        lines.extend(inserts[position])
    return "".join(lines)


def _read_source(root: Path, path: Path) -> str | None:
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            return None
        return resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError, RuntimeError, MemoryError):
        return None


def _parse(source: str) -> ast.AST:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source)


def _name(node: ast.AST) -> str:
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Subscript):
            node = node.value
        else:
            return ""


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Names bound by `import ... as` and `from ... import ... as`, mapped to the imported name."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name.rsplit(".", 1)[-1]
    return aliases


def _bases(cls: ast.ClassDef, aliases: dict[str, str]) -> set[str]:
    names = {_name(base) for base in cls.bases}
    return {aliases.get(name, name) for name in names} - {""}


def _kind(cls: ast.ClassDef, aliases: dict[str, str]) -> str | None:
    """'protocol' for a Protocol class, 'abc' for an abstract base class, else None."""
    bases = _bases(cls, aliases)
    if any(base.endswith("Protocol") for base in bases):
        return "protocol"
    if any(base.endswith("ABC") for base in bases) or any(
            keyword.arg == "metaclass"
            and aliases.get(_name(keyword.value), _name(keyword.value)).endswith("ABCMeta")
            for keyword in cls.keywords):
        return "abc"
    return None


def _declaration(function: _Function) -> bool:
    """An abstract method or a typing overload: a signature, not an implementation."""
    return any(_name(decorator).startswith("abstract") or _name(decorator) == "overload"
               for decorator in function.decorator_list)


def _not_implemented(node: ast.AST) -> bool:
    if not isinstance(node, ast.Raise):
        return False
    exc = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    return ((isinstance(exc, ast.Name) and exc.id == "NotImplementedError")
            or (isinstance(exc, ast.Attribute) and exc.attr == "NotImplementedError"))


def _children(node: ast.AST):
    """The statements directly inside node's blocks (if, try, with, match bodies included)."""
    for field in _BLOCKS:
        for child in getattr(node, field, None) or ():
            if isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case)):
                yield child


def _functions(tree: ast.AST, aliases: dict[str, str]):
    """Yield each function, the kind of class it is a method of, that class (or None), and its
    qualified name (the enclosing classes and functions, then its own name)."""
    pending: list[tuple[ast.AST, str | None, ast.ClassDef | None, tuple[str, ...]]] = [(tree, None, None, ())]
    while pending:
        node, kind, owner, scope = pending.pop()
        for child in _children(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield child, kind, owner, scope + (child.name,)
                # A function defined inside a function is not a method.
                pending.append((child, None, None, scope + (child.name,)))
            elif isinstance(child, ast.ClassDef):
                pending.append((child, _kind(child, aliases), child, scope + (child.name,)))
            else:
                pending.append((child, kind, owner, scope))


def _classes(tree: ast.AST):
    """Yield each class with its qualified name."""
    pending: list[tuple[ast.AST, tuple[str, ...]]] = [(tree, ())]
    while pending:
        node, scope = pending.pop()
        for child in _children(node):
            if isinstance(child, ast.ClassDef):
                yield child, scope + (child.name,)
                pending.append((child, scope + (child.name,)))
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                pending.append((child, scope + (child.name,)))
            else:
                pending.append((child, scope))


def _methods(cls: ast.ClassDef) -> set[str]:
    """Names of the methods a class body defines, including under if, try or with."""
    names: set[str] = set()
    pending: list[ast.AST] = [cls]
    while pending:
        for child in _children(pending.pop()):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(child.name)
            elif not isinstance(child, ast.ClassDef):
                pending.append(child)
    return names


def _is_stub(function: _Function) -> bool:
    """The whole body, after a docstring, only raises NotImplementedError or does nothing.

    A raise for one unsupported case beside real logic is not a stub.
    """
    body = function.body
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    if len(body) != 1:
        return False
    statement = body[0]
    return (isinstance(statement, ast.Pass) or _not_implemented(statement)
            or (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                and statement.value.value is Ellipsis))


@dataclass
class _Before:
    """The definitions of a changed file before the patch, by qualified name."""

    functions: dict[tuple[str, ...], bool]  # whether any definition of that name was a stub
    classes: set[tuple[str, ...]]


def _definitions_before(source: str, change: _FileChange) -> _Before | None:
    try:
        tree = _parse(_before(source, change))
        functions: dict[tuple[str, ...], bool] = {}
        for function, _, _, qualname in _functions(tree, _aliases(tree)):
            # An overload declaration shares the implementation's name but is not its body.
            functions[qualname] = functions.get(qualname, False) or (
                _is_stub(function) and not _declaration(function))
        return _Before(functions, {qualname for _, qualname in _classes(tree)})
    except _PARSE_ERRORS:
        return None


def _module(path: str) -> tuple[str, ...]:
    parts = path[:-3].split("/")
    return tuple(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(tree: ast.AST, path: str) -> tuple[set[tuple[str, ...]], set[tuple[str, ...]]]:
    """Modules a file imports: relative imports as repository paths, absolute ones as dotted names."""
    package = path[:-3].split("/")[:-1]
    resolved: set[tuple[str, ...]] = set()
    absolute: set[tuple[str, ...]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            absolute.update(tuple(alias.name.split(".")) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = tuple(node.module.split(".")) if node.module else ()
            if node.level:
                if node.level - 1 > len(package):
                    continue
                base = tuple(package[:len(package) - (node.level - 1)]) + module
                target = resolved
            else:
                base, target = module, absolute
            target.add(base)
            # `from pkg import mod` imports the submodule pkg.mod.
            target.update(base + (alias.name,) for alias in node.names)
    return resolved, absolute


def _imports_module(imports: tuple[set[tuple[str, ...]], set[tuple[str, ...]]], defining: str) -> bool:
    """Whether a file imports the module that defines a private helper.

    A private name belongs to its module, so a same-named name in a module that does not
    import this one (and defines and calls its own helper) is not a call of this one. An
    absolute import is matched against the end of the module's path, which allows for a
    source directory such as src/.
    """
    module = _module(defining)
    resolved, absolute = imports
    return module in resolved or any(
        dotted and module[len(module) - len(dotted):] == dotted for dotted in absolute
    )


def _sources(root: Path, protected_modules: frozenset[str]):
    """Yield (relative path, text) for each readable Python file outside the tests."""
    def followed(directory: str, name: str) -> bool:
        try:
            return name not in _SKIP_DIRS and not (Path(directory) / name).is_symlink()
        except OSError:
            return False

    for directory, dirs, filenames in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if followed(directory, name))
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = Path(directory) / filename
            relative = path.relative_to(root).as_posix()
            if categorize(relative, protected_modules) == "test":
                continue
            source = _read_source(root, path)
            if source is not None:
                yield relative, source


def _uses(root: Path, protected_modules: frozenset[str], names: set[str]):
    """For each name, the files outside the tests that use it, with the modules each imports.

    A use is a name, an attribute, an imported name or a string equal to it (getattr and
    registries look functions up by name). Comments are not uses.
    """
    uses: dict[str, list[tuple[str, tuple[set[tuple[str, ...]], set[tuple[str, ...]]]]]] = {
        name: [] for name in names
    }
    for relative, source in _sources(root, protected_modules):
        present = {name for name in names if name in source}
        if not present:
            continue
        try:
            tree = _parse(source)
        except _PARSE_ERRORS:
            continue
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                value = node.id
            elif isinstance(node, ast.Attribute):
                value = node.attr
            elif isinstance(node, ast.alias):
                value = node.name
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
            else:
                continue
            if value in present:
                found.add(value)
        if found:
            imports = _imports(tree, relative)
            for name in found:
                uses[name].append((relative, imports))
    return uses


@dataclass
class _Class:
    key: tuple[str, int]
    name: str
    bases: set[str]
    methods: set[str]
    new: bool


class _ClassTree:
    """Every class definition in the tree, kept apart even when two share a name."""

    def __init__(self, root: Path, protected_modules: frozenset[str],
                 files: dict[str, _FileChange], befores: dict[str, _Before | None]):
        self.by_key: dict[tuple[str, int], _Class] = {}
        self.by_name: dict[str, list[_Class]] = {}
        self.children: dict[str, list[_Class]] = {}
        for relative, source in _sources(root, protected_modules):
            try:
                tree = _parse(source)
            except _PARSE_ERRORS:
                continue
            aliases = _aliases(tree)
            change, before = files.get(relative), befores.get(relative)
            for node, qualname in _classes(tree):
                if change is None:
                    new = False
                elif before is not None:
                    new = qualname not in before.classes
                else:
                    new = node.lineno in change.added
                cls = _Class(key=(relative, node.lineno), name=node.name, bases=_bases(node, aliases),
                             methods=_methods(node), new=new)
                self.by_key[cls.key] = cls
                self.by_name.setdefault(cls.name, []).append(cls)
                for base in cls.bases:
                    self.children.setdefault(base, []).append(cls)

    def inherited(self, key: tuple[str, int], name: str) -> bool:
        """Whether an ancestor class, direct or indirect, defines a method of the same name."""
        start = self.by_key.get(key)
        if start is None:
            return False
        seen, expanded = {key}, set()
        pending = list(start.bases)
        while pending:
            base = pending.pop()
            if base in expanded:
                continue
            expanded.add(base)
            for cls in self.by_name.get(base, ()):
                if cls.key in seen:
                    continue
                seen.add(cls.key)
                if name in cls.methods:
                    return True
                pending.extend(cls.bases)
        return False

    def overridden(self, key: tuple[str, int], name: str, new_method: bool) -> bool:
        """Whether a subclass, direct or indirect, overrides the method.

        For an existing method that the patch gutted, only a subclass that existed before the
        patch counts: otherwise a patch could gut a method and add an unused subclass to excuse
        it. A new hook may be implemented by subclasses the patch also adds.
        """
        start = self.by_key.get(key)
        if start is None:
            return False
        seen, expanded = {key}, set()
        pending = [start.name]
        while pending:
            parent = pending.pop()
            if parent in expanded:
                continue
            expanded.add(parent)
            for child in self.children.get(parent, ()):
                if child.key in seen:
                    continue
                seen.add(child.key)
                if name in child.methods and (new_method or not child.new):
                    return True
                pending.append(child.name)
        return False


def find_shortcuts(
    patch_text: str,
    root: Path,
    protected_modules: frozenset[str] = frozenset(),
) -> list[ShortcutFinding]:
    """Read only files inside root. Unreadable or invalid Python is skipped.

    Known limits, all on the side of not flagging: a private method counts as used when any
    file outside the tests uses that attribute name (methods are reached through instances,
    so the defining module need not be imported); classes are matched by name, so two
    same-named base classes in different modules can excuse each other.
    """
    try:
        root = root.resolve()
        files = _patch_lines(patch_text)
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
        return []
    findings: list[ShortcutFinding] = []
    private: list[tuple[str, _Function, tuple[str, int] | None]] = []
    stubs: list[tuple[str, _Function, tuple[str, int] | None, bool]] = []
    befores: dict[str, _Before | None] = {}
    for path, change in files.items():
        if not path.endswith(".py") or categorize(path, protected_modules) != "source":
            continue
        source = _read_source(root, root / path)
        if source is None:
            continue
        try:
            tree = _parse(source)
            functions = list(_functions(tree, _aliases(tree)))
        except _PARSE_ERRORS:
            continue
        before = befores[path] = _definitions_before(source, change)
        for function, kind, owner, qualname in functions:
            name = function.name
            key = (path, owner.lineno) if owner is not None else None
            if before is not None:
                new = qualname not in before.functions
                made_stub = _is_stub(function) and (new or not before.functions[qualname])
            else:
                # The file before the patch could not be rebuilt: judge by the changed lines.
                new = function.lineno in change.added
                made_stub = _is_stub(function) and (new or function.body[-1].lineno in change.added)
            # A decorated function may be registered by its decorator (a CLI command, a
            # route, a plugin hook), so the absence of a direct call proves nothing.
            if new and not function.decorator_list and name.startswith("_") and not (
                    name.startswith("__") and name.endswith("__")):
                private.append((path, function, key))
            # Declarations are exempt, so are a Protocol's methods and an abstract base class's
            # new methods; an existing concrete method of an abstract base class is not.
            exempt = _declaration(function) or kind == "protocol" or (kind == "abc" and new)
            if not exempt and made_stub:
                stubs.append((path, function, key, new))
    if any(stub[2] is not None for stub in stubs) or any(key is not None for _, _, key in private):
        classes = _ClassTree(root, protected_modules, files, befores)
        # A base-class method that a subclass overrides is a hook, the documented use of
        # NotImplementedError, the same as an abstract method.
        stubs = [(path, function, key, new) for path, function, key, new in stubs
                 if key is None or not classes.overridden(key, function.name, new)]
        # A private method that overrides an ancestor's is called wherever the ancestor's is.
        private = [(path, function, key) for path, function, key in private
                   if key is None or not classes.inherited(key, function.name)]
    for path, function, _, _ in stubs:
        findings.append(ShortcutFinding(
            kind="stub", path=path, name=function.name, line=function.lineno,
            detail=f"{function.name} is a stub (its body only raises NotImplementedError or does nothing)",
        ))
    if private:
        uses = _uses(root, protected_modules, {function.name for _, function, _ in private})
        for path, function, key in private:
            called = any(key is not None or user == path or _imports_module(imports, path)
                         for user, imports in uses[function.name])
            if not called:
                findings.append(ShortcutFinding(
                    kind="uncalled_private_helper", path=path, name=function.name, line=function.lineno,
                    detail=f"private helper {function.name} is added by the patch but nothing outside the tests calls it",
                ))
    return sorted(findings, key=lambda finding: (finding.path, finding.line or 0, finding.kind))
