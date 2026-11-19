"""Architecture fitness tests: the modules form a pipeline, never a cycle.

Imports may only point backwards along the pipeline described in
docs/ARCHITECTURE.md.  If you add an import that is not in this table, either
the table (and the document) need to change on purpose, or the import is a
design mistake.
"""
import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "pawk_ng"

ALLOWED = {
    "errors": set(),
    "values": {"errors"},
    "lexer": {"errors"},
    "translate": {"errors", "lexer"},
    "parser": {"errors", "lexer", "translate"},
    "namespace": {"errors", "values"},
    "records": {"errors", "namespace", "values"},
    "inputs": {"errors", "namespace", "records", "values"},
    "runtime": {"errors", "inputs", "namespace", "parser", "records", "values"},
    "cli": {"errors", "runtime", "__init__"},
    "__init__": {"errors", "parser", "runtime", "values"},
    "__main__": {"cli"},
}


def internal_imports(module):
    tree = ast.parse((PACKAGE / ("%s.py" % module)).read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            found.add(node.module or "__init__")
    return found


def test_every_module_is_in_the_table():
    modules = {p.stem for p in PACKAGE.glob("*.py")}
    assert modules == set(ALLOWED)


def test_imports_follow_the_pipeline():
    for module, allowed in ALLOWED.items():
        extra = internal_imports(module) - allowed
        assert not extra, "%s imports %s, which is not allowed" % (module, sorted(extra))


def test_there_are_no_import_cycles():
    graph = {m: internal_imports(m) for m in ALLOWED}
    done, visiting = set(), []

    def visit(m):
        assert m not in visiting, "import cycle: %s" % " -> ".join([*visiting, m])
        if m in done:
            return
        visiting.append(m)
        for dep in graph[m]:
            visit(dep)
        visiting.pop()
        done.add(m)

    for m in graph:
        visit(m)


def test_modules_stay_small_enough_to_read():
    for path in PACKAGE.glob("*.py"):
        lines = len(path.read_text().splitlines())
        assert lines <= 300, "%s has %d lines: split it" % (path.name, lines)
