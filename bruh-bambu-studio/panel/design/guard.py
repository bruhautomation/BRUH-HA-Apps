"""What a design script may do, checked before it is ever run.

A design script is Python a model wrote, and the panel runs it. It runs in
a separate process with no Supervisor token and a time limit
(`runner.py`), but it still runs as the add-on's own user, beside the
printers' access codes. So it is read first: geometry needs CadQuery,
cadkit, math and numpy, and nothing that reaches a file, a process, the
network or the interpreter's insides. A script that wants more is refused
with the line that asked, and the refusal goes back to brAIn to fix.

This is a guard against a model wandering, not a sandbox against an
adversary — the words that drive it are an admin's, typed into a panel
only an admin can open.
"""
from __future__ import annotations

import ast

ALLOWED_IMPORTS = {"cadquery", "cadkit", "math", "numpy", "typing", "dataclasses",
                   "itertools", "functools", "collections", "__future__"}
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals",
                   "locals", "vars", "getattr", "setattr", "delattr", "input",
                   "breakpoint", "memoryview", "os", "sys", "subprocess", "socket",
                   "importlib", "builtins", "shutil", "pathlib"}
MAX_BYTES = 200_000


def check(source: str) -> list[str]:
    """Every reason the script may not run; empty means it may."""
    if len(source.encode()) > MAX_BYTES:
        return [f"The script is over {MAX_BYTES // 1000} KB."]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"Line {exc.lineno}: {exc.msg}"]
    problems: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"Line {line}: import {alias.name} is not allowed.")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS or node.level:
                problems.append(f"Line {line}: from {node.module} import is not allowed.")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"Line {line}: {node.id} is not allowed in a design script.")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            problems.append(f"Line {line}: .{node.attr} is not allowed in a design script.")
    allowed = ", ".join(sorted(ALLOWED_IMPORTS - {"__future__"}))
    if problems:
        problems.append(f"Design scripts may import only {allowed}.")
    return problems[:12]
