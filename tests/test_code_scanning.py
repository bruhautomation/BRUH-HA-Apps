#!/usr/bin/env python3
"""The CodeQL families that keep coming back, kept out at the source.

The repo's workflow runs `security-and-quality` over Python and JavaScript,
and its findings arrive in the Security tab — which is a page nobody opens
between releases. The first two below were swept before (`bbeefd1`, "Close
the CodeQL alerts, and say why the quiet handlers are quiet") and both came
back the moment new code was written, because a sweep is a moment and a rule
is a test.

None of them is a security bug. They are here because of what the alerts
*mean* in this codebase:

* **An empty handler with no comment.** The query is "this `except` does
  nothing but `pass` and there is no explanatory comment" — and in a
  codebase whose comments carry the reasoning, the missing comment is the
  real finding: every one of these is a decision to ignore a failure, and
  the next reader has to be able to tell a deliberate one from a swallowed
  bug.
* **An implicit string concatenation inside a list or a tuple.** Two
  adjacent string literals are one string, so it is exactly what a missing
  comma looks like — and a missing comma in a list of prompt lines is a
  message that silently loses a sentence, which nothing else here would
  catch. Where the concatenation is intended, `+` says so.
* **A module-level logger nothing logs through.** This one has shipped
  three times, always the same way: a new module starts from the shape of
  an existing one, and the logger arrives with the boilerplate before there
  is anything to say. It is not a bug — it is a module whose author has not
  yet decided what it reports, and the honest answer is either a log line or
  no logger. It is here rather than in a review comment on the third pull
  request in a row.

Every check here reads the real files with `ast`, so it measures the code
rather than a description of it, and each names the file and line so a
failure is actionable without opening the query.

What is deliberately **not** here is `py/import-and-import-from`, which
CodeQL raised on `tests/test_thermal.py` and which was fixed in place. A
repo-wide sweep found eighteen more, and nearly every one is `import
unittest` beside `from unittest.mock import patch` — which is how Python
is written. A rule the repo does not believe is a rule somebody turns off,
and the alerts arrive on a pull request anyway, which is where that one
was caught.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Everything the CodeQL workflow analyses. `.git` is excluded by walking from
# the tracked trees rather than the root, and a directory that does not exist
# in a partial checkout is simply skipped.
PYTHON_TREES = ("brain", "bright", "bruh-minecraft-server", "bruh-print",
                "tests", "branding")


def python_files() -> list[Path]:
    out: list[Path] = []
    for tree in PYTHON_TREES:
        base = REPO_ROOT / tree
        if base.is_dir():
            out.extend(sorted(base.rglob("*.py")))
    return out


def parsed(path: Path) -> tuple[ast.AST, list[str]] | None:
    """The file's tree and its lines, or None if it will not parse.

    A file that does not parse is not this test's business — the suite has
    plenty that would fail first — and swallowing the error here is what
    stops a syntax error being reported as a code-scanning finding.
    """
    try:
        source = path.read_text(encoding="utf-8")
        return ast.parse(source), source.splitlines()
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


class TestEveryQuietHandlerSaysWhyItIsQuiet(unittest.TestCase):
    """py/empty-except: an `except` whose body is `pass` and nothing else."""

    def test_no_empty_handler_is_silent(self):
        offenders = []
        for path in python_files():
            got = parsed(path)
            if got is None:
                continue
            tree, lines = got
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
                    continue
                # The comment may sit anywhere between the `except` line and
                # the `pass` — above it, or trailing either one — which is
                # the same window the query reads.
                window = range(node.lineno, node.body[0].lineno + 1)
                if not any("#" in lines[i - 1] for i in window):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            "an `except` that does nothing but `pass` needs a comment saying "
            "what is being ignored and why that is the right answer — "
            "without one, a deliberate silence and a swallowed bug read the "
            "same: " + ", ".join(offenders),
        )


class TestNoListLooksLikeItIsMissingAComma(unittest.TestCase):
    """py/implicit-string-concatenation-in-list."""

    def test_concatenation_in_a_sequence_is_explicit(self):
        offenders = []
        for path in python_files():
            got = parsed(path)
            if got is None:
                continue
            tree, _lines = got
            for node in ast.walk(tree):
                if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                    continue
                if len(node.elts) < 2:
                    continue
                for elt in node.elts:
                    # An implicit concatenation is one Constant spanning more
                    # than one line: the parser has already joined the pieces,
                    # so the span is the only trace left of how it was written.
                    if (isinstance(elt, ast.Constant)
                            and isinstance(elt.value, str)
                            and elt.end_lineno
                            and elt.end_lineno > elt.lineno):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}:{elt.lineno}")
        self.assertEqual(
            offenders, [],
            "two adjacent string literals inside a list or tuple are one "
            "string, which is what a missing comma looks like — join them "
            "with `+` where the concatenation is meant: " + ", ".join(offenders),
        )


class TestNoLoggerNothingLogsThrough(unittest.TestCase):
    """py/unused-global-variable, on the one shape that keeps coming back.

    A `log = logging.getLogger(...)` that nothing ever calls is a module
    that arrived carrying another one's boilerplate. The fix is a log line
    or no logger, and either beats a name the next reader has to check the
    whole file for uses of.
    """

    def test_every_module_logger_is_logged_through(self):
        offenders = []
        for path in python_files():
            got = parsed(path)
            if got is None:
                continue
            tree, _lines = got
            made: dict[str, int] = {}
            for node in tree.body:            # module level only
                if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                    continue
                target, call = node.targets[0], node.value
                if not isinstance(target, ast.Name):
                    continue
                if not isinstance(call, ast.Call):
                    continue
                fn = call.func
                if isinstance(fn, ast.Attribute) and fn.attr == "getLogger":
                    made[target.id] = node.lineno
            if not made:
                continue
            # Any load of the name anywhere below — including inside a
            # nested function, which is where nearly every real use is.
            used = {n.id for n in ast.walk(tree)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            for name, line in made.items():
                if name not in used:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{line} ({name})")
        self.assertEqual(
            offenders, [],
            "a module-level logger that nothing logs through is a module "
            "carrying another one's boilerplate — write the log line or drop "
            "the logger: " + ", ".join(offenders),
        )



if __name__ == "__main__":
    unittest.main()
