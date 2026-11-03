#!/usr/bin/env python3
"""Nothing the integration imports from inside the event loop opens a file.

Home Assistant imports an integration's own module in an executor, but a
module imported LATER, from inside an `async def`, is imported on the event
loop — and Home Assistant logs every blocking call there: "Detected
blocking call to open ... by custom integration 'brain'" four times a
start, from Morph's half (`morph/const.py` read `manifest.json` at import
to learn the version), which `async_setup_entry` imported lazily (#637).

The rule, checked over the source: every local module imported inside an
`async def` of the integration runs no file read at import time — not
directly at module level, and not through a function the module level
calls. A module that has to read a file at import is imported in the
executor instead (`hass.async_add_import_executor_job`), which takes its
import out of this list.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "brain" / "custom_components" / "brain"
READS = {"open", "read_text", "read_bytes", "load"}


def _local_modules(pkg_dir: Path, node: ast.ImportFrom, here: Path) -> list[Path]:
    """The files a relative import inside `here` would execute."""
    if not node.level:
        return []
    base = here.parent
    for _ in range(node.level - 1):
        base = base.parent
    names = []
    if node.module:
        names.append(node.module.replace(".", "/"))
    else:
        names.extend(a.name for a in node.names)
    out = []
    for name in names:
        target = base / name
        if target.is_dir():
            out.extend(sorted(target.glob("*.py")))
        elif target.with_suffix(".py").exists():
            out.append(target.with_suffix(".py"))
    return out


def _call_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _reads_at_import(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    found = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for call in (n for n in ast.walk(stmt) if isinstance(n, ast.Call)):
            name = _call_name(call)
            if name in READS:
                found.append(f"{path.name}:{call.lineno} {name}()")
            elif name in funcs:
                for inner in ast.walk(funcs[name]):
                    if isinstance(inner, ast.Call) and _call_name(inner) in READS:
                        found.append(f"{path.name}:{call.lineno} {name}() "
                                     f"reads at line {inner.lineno}")
                        break
    return found


class TestNoFileIsReadOnTheLoop(unittest.TestCase):
    def test_lazy_imports_read_no_file_at_import(self):
        bad = []
        for path in sorted(ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)):
                for node in (n for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)):
                    for mod in _local_modules(ROOT, node, path):
                        for read in _reads_at_import(mod):
                            bad.append(f"{path.relative_to(ROOT)}:{node.lineno} "
                                       f"({fn.name}) imports {read}")
        self.assertEqual(bad, [])

    def test_the_rule_sees_a_read_through_a_helper(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "m.py"
            mod.write_text("def _v():\n    with open('x') as f:\n        return f.read()\n"
                           "V = _v()\n", encoding="utf-8")
            self.assertTrue(_reads_at_import(mod))


if __name__ == "__main__":
    unittest.main()
