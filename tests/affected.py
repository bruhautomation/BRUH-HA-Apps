#!/usr/bin/env python3
"""Which tests a change can break, so a development loop runs those and not the whole suite.

The suite is eight and a half thousand tests and six minutes run serially,
and the habit it trains is re-running all of it after every edit — which is
the right habit for CI and the wrong one for the fortieth edit of an
afternoon. This answers the narrower question: given the files that moved,
which test files could notice. It is a SELECTION, never a verdict: CI still
runs everything, and the one thing this may not do is go quiet about a
change it cannot place. So every rule below errs towards selecting too
much, and a code change no rule can place selects the whole suite and says
so — a slow run is a cost somebody sees, where a selection that silently
missed is a green tick over a break.

    python3 tests/affected.py brain/panel/findings_store.py
    python3 tests/affected.py --base origin/main          # what this branch moved
    python3 tests/affected.py --run                       # ...and run it
    python3 tests/affected.py --measures brain/panel/app.js   # the browser measures

Output is one path per line on stdout (the literal ``tests/`` when the
answer is the whole suite), and one line per changed path on stderr saying
which rule placed it and why. Stdlib only, and it resolves the repository
from its own location, so it runs from any directory. It never imports
pytest: it is the thing that decides whether pytest runs at all. ``--run``
hands the selection to ``python3 -m pytest -q -n auto --dist loadfile`` and
exits with pytest's status (``--lf`` passes through); without
``pytest-xdist`` installed it says so and runs serially rather than failing
on an option pytest does not know.

The rules, in the order a path is tried
---------------------------------------

**Shared test infrastructure selects the whole suite.** ``tests/conftest.py``,
``tests/fake_*.py``, ``tests/*_env.py``, anything under ``tests/corpus/``,
``pytest.ini`` and ``tests/requirements-dev.txt`` are read by tests that do
not name them — an autouse fixture, a fake CLI found through an environment
variable, a frozen house replayed by a test that globs the directory — so no
mention-based rule can see who depends on them.

**A test file selects itself.** A deleted one selects nothing, because there
is nothing left to run.

**Prose, pictures and CI select only the tests that read them by name.**
``*.md``, ``CHANGELOG*``, ``LICENSE``, images, ``.gitignore``, ``ruff.toml``
and anything under ``docs/``, ``.github/`` or ``.claude/`` select a test only
when that test names the file in a string literal (``"DOCS.md"``,
``".github" / "scripts" / "check-version-bump.sh"``) — the shape of a read,
where a mention in a docstring is the shape of a citation — and, for a file
below the top level, names its folder too, because ``README.md`` and
``ci.yml`` are names several files share. With no such test they select
nothing, and say so. This is the one class that may select nothing, and it
is deliberately not "always nothing": a design note nobody reads cannot fail
a test, while ``test_check_version_bump.py`` really does run a script under
``.github/`` and ``test_brain_addon.py`` really does read ``DOCS.md``.

**A helper beside the tests selects the tests that import it** (this file
and ``test_affected.py`` are the example), by the module rule below.

**A Python module selects the tests that import it.** "Import" means one of
the shapes a test in this repository actually uses: ``import X``,
``from X import``, ``import_module("X")``, ``sys.modules.pop("X")``,
``patch("X.…")``, or the file's own name, ``"X.py"`` (how a test that loads a
module from its path names it). The match is on those contexts and never on
the bare word, because ``house``, ``gate``, ``cases``, ``today`` and
``security`` are module names here and ordinary English in every docstring.
A test whose file name contains the stem as whole ``_``-separated words is
selected too (``house`` selects ``test_house_book.py`` and not
``test_household.py``). A submodule of ``checks`` or ``devloop`` also
matches ``from checks import devices`` and ``checks.devices``, and — because
``checks/__init__.py`` imports every check — the importers of the package.
This is DIRECT importers only: a module reached through ``server.py`` is
exercised by every test that imports the server, and following that chain
makes nearly any change select a third of the suite. ``--transitive`` follows
it, for when that is the question.

**The integration is loaded whole.** A file under
``brain/custom_components/brain/`` also selects every test that imports
``brain_ha_env``, because that harness imports the package's ``__init__``,
which imports the rest.

**A test that walks a source tree is selected for any change in it.**
``test_atomic_write.py``, ``test_ha_history_query.py``, ``test_numbers_agree.py``
and their kind ``rglob("*.py")`` or ``os.walk`` an add-on and hold every file
to a rule (no ``with_suffix(".tmp")``, no ``?`` pasted into a URL), so they
name no module and any module can break them. A test that does that is
selected for every code change in an add-on it names.

**A script selects the tests that name it, and the tests of the scripts
that call it.** ``brain/scripts``, ``brain/integrations`` and
``brain/ha-mcp-server`` are driven by file name in subprocesses
(``"brain-learn.sh"``), so the basename anywhere in a test is a mention. A
sourced helper (``brain-run-source.sh``) is never driven directly, so one hop
further: the tests of every script in those directories that names it.

**A browser file selects the browser measures.** A ``.js``, ``.css``,
``.html`` or ``.mjs`` under an add-on's ``panel/`` selects every
``tests/manual/measure-*.mjs`` that loads that add-on's panel (they load the
whole page, so any of its files can move what they measure), plus any measure
naming the file; ``lovelace/`` and ``ttyd-assets/`` select the measures that
name them. Pytest tests that read the file by name come too. A changed
measure selects itself, and a measure's helper (``today-fixture.mjs``,
``tabs.mjs``, ``bright_demo_panel.py``) selects the measures that use it.
BRight's and BRUH Print's measures boot that add-on's real server through
its demo panel, so a ``.py`` under their ``panel/`` selects those measures
as well; brAIn's load the page's files and are reached only through them.

**The add-on-wide files select the add-on-wide tests.** ``run.sh``,
``config.yaml``, ``build.yaml``, ``Dockerfile``, ``apparmor.txt`` and
``translations/`` are read by ``test_addon_hardening.py`` (every add-on's
manifest and profile) and each add-on's own ``*_addon.py``, and by any test
that names the file in a string literal and names the add-on beside it — the
``ADDON / "run.sh"`` shape, which is how ``test_permission_mode.py`` lifts a
function out of the real ``run.sh``.

**The other three add-ons are scoped by name.** A change under ``bright/``
selects ``tests/test_bright_*.py``; ``bruh-print/`` selects
``test_bruh_print_*``; ``bruh-minecraft-server/`` selects
``test_minecraft_*``. Beyond those, a test is selected by the module rule
only if it also names the add-on, because ``server``, ``library`` and
``atomic_write`` are stems three add-ons share and ``import server`` in a brAIn
test is not about BRight's.

**Anything else is named or it is everything.** A path no rule above
claims (``repository.yaml``, ``branding/render.mjs``, a JSON under the
integration) selects the tests naming it in a string literal, or naming its
top-level directory. A code or configuration change that no rule can place
selects the whole suite, and stderr names it, because that list is the
useful half of the answer: it is where a test is missing.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WHOLE_SUITE = "tests/"

ADDONS = ("brain", "bright", "bruh-print", "bruh-minecraft-server")
# The prefix each add-on's own tests carry. brAIn has none: it is most of
# the suite, and its tests are named after what they test, not after it.
ADDON_TEST_PREFIX = {
    "bright": "test_bright_",
    "bruh-print": "test_bruh_print_",
    "bruh-minecraft-server": "test_minecraft_",
}
# What a test writes when it means the add-on: its directory, and the
# underscore spelling its integration domain uses.
ADDON_NAMES = {
    "brain": ("brain",),
    "bright": ("bright",),
    "bruh-print": ("bruh-print", "bruh_print"),
    "bruh-minecraft-server": ("bruh-minecraft-server", "bruh_minecraft"),
}
ADDON_WIDE_FILES = {"run.sh", "config.yaml", "build.yaml", "Dockerfile",
                    "apparmor.txt"}
ADDON_WIDE_TESTS = {
    "brain": ("tests/test_addon_hardening.py", "tests/test_brain_addon.py"),
    "bright": ("tests/test_addon_hardening.py", "tests/test_bright_addon.py"),
    "bruh-print": ("tests/test_addon_hardening.py",
                   "tests/test_bruh_print_addon.py"),
    "bruh-minecraft-server": ("tests/test_addon_hardening.py",
                              "tests/test_minecraft_config.py"),
}
# The demo panel a browser measure boots, where it drives the real server
# rather than loading the page's files: a change to that add-on's panel
# Python reaches those measures too. brAIn's own demo_panel.py serves the
# screenshot pipeline, not a measure.
DEMO_SERVERS = {"bright": "bright_demo_panel",
                "bruh-print": "bruh_print_demo_panel"}
# Packages under brain/panel whose submodules are imported through them.
PANEL_PACKAGES = ("checks", "devloop")
SCRIPT_DIRS = ("brain/scripts", "brain/integrations", "brain/ha-mcp-server")
INTEGRATION_DIR = "brain/custom_components/brain/"

WHOLE_SUITE_FILES = {"tests/conftest.py", "pytest.ini",
                     "tests/requirements-dev.txt"}
PROSE_SUFFIXES = {".md", ".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg",
                  ".ico"}
QUIET_DIRS = ("docs/", ".github/", ".claude/")
# ruff.toml is the linter's, and no pytest test reads it.
QUIET_NAMES = {".gitignore", ".gitattributes", "ruff.toml"}
UI_SUFFIXES = {".js", ".css", ".html", ".mjs"}
UI_DIRS = ("panel", "lovelace", "ttyd-assets")
# What a source-tree sweep reads; prose and pictures are not among them.
CODE_SUFFIXES = {".py", ".sh", ".js", ".mjs", ".css", ".html", ".yaml",
                 ".yml", ".json", ".conf"}
_SWEEP = re.compile(
    r"""r?glob\(\s*["'][^"']*\*\.(?:py|sh|js)["']|os\.walk\(""")

# A measure says which panel it loads in one of three ways: the panel's
# path (as a string or a path.join), or the demo panel it boots.
_MEASURE_PANEL = re.compile(
    r"""(brain|bright|bruh-print)['"]?\s*[,/]\s*['"]?panel\b""")
_MEASURE_DEMO = (
    (re.compile(r"bright_demo_panel"), "bright"),
    (re.compile(r"bruh_print_demo_panel"), "bruh-print"),
    (re.compile(r"(?<![\w])demo_panel"), "brain"),
)


# ---------------------------------------------------------------------------
# What the repository holds
# ---------------------------------------------------------------------------


class Index:
    """The sources the rules read, read once.

    ``tests`` maps a repository-relative test path to its text; ``measures``
    and ``scripts`` likewise. A caller may hand any of them in, which is how
    the tests drive a rule over a source they wrote rather than over
    whatever the repository happens to hold today.
    """

    def __init__(self, repo: Path = REPO, *, tests=None, measures=None,
                 scripts=None):
        self.repo = repo
        self.tests = tests if tests is not None else self._read(
            sorted((repo / "tests").glob("test_*.py")))
        self.measures = measures if measures is not None else self._read(
            sorted((repo / "tests" / "manual").glob("measure-*.mjs")))
        if scripts is None:
            files = []
            for d in SCRIPT_DIRS:
                files += [p for p in sorted((repo / d).glob("*"))
                          if p.is_file()]
            scripts = self._read(files)
        self.scripts = scripts
        self._ha_env = None
        self._names: dict[str, frozenset[str]] = {}
        self._sweep: dict[str, set[str]] = {}

    def _read(self, paths) -> dict[str, str]:
        out = {}
        for p in paths:
            try:
                out[p.relative_to(self.repo).as_posix()] = p.read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                continue
        return out

    def exists(self, rel: str) -> bool:
        return (self.repo / rel).is_file()

    def ha_env_users(self) -> set[str]:
        if self._ha_env is None:
            self._ha_env = {t for t in self.tests
                            if _imports(self.names(t), "brain_ha_env")}
        return self._ha_env

    def names(self, test: str) -> frozenset[str]:
        if test not in self._names:
            self._names[test] = import_names(self.tests.get(test, ""))
        return self._names[test]

    def measure_panels(self, rel: str) -> set[str]:
        src = self.measures.get(rel, "")
        found = {m.group(1) for m in _MEASURE_PANEL.finditer(src)}
        for pat, addon in _MEASURE_DEMO:
            if pat.search(src):
                found.add(addon)
        return found


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


_IMPORT_STMT = re.compile(r"^[ \t]*import[ \t]+([\w.]+(?:[ \t]+as[ \t]+\w+)?"
                          r"(?:[ \t]*,[ \t]*[\w.]+(?:[ \t]+as[ \t]+\w+)?)*)",
                          re.M)
_FROM_STMT = re.compile(r"^[ \t]*from[ \t]+([\w.]+)[ \t]+import[ \t]+"
                        r"(\([^)]*\)|[^\n]*)", re.M)
_BY_STRING = re.compile(
    r"""(?:import_module|__import__)\(\s*["']([\w.]+)["']"""
    r"""|sys\.modules(?:\.(?:pop|get|setdefault)\(\s*|\[\s*)["']([\w.]+)["']"""
    r"""|patch(?:\.object)?\(\s*["']([\w.]+)\.\w+["']""")
_PY_FILE = re.compile(r"(?<![\w.-])(\w+)\.py(?![\w])")


def _names_in(body: str) -> list[str]:
    """The names a ``from x import …`` or ``import …`` list binds, not
    counting the alias after an ``as``."""
    words = re.split(r"[\s,()]+", re.sub(r"#[^\n]*", "", body))
    return [w for i, w in enumerate(words)
            if w and w != "as" and (i == 0 or words[i - 1] != "as")]


def import_names(src: str) -> frozenset[str]:
    """Every dotted module name ``src`` reaches in a shape a test uses.

    ``import a.b as c`` gives ``a.b``; ``from a import x`` gives ``a`` and
    ``a.x`` (``x`` may be a submodule, as ``from checks import devices``
    is); ``import_module("a")``, ``sys.modules.pop("a")`` and
    ``patch("a.f")`` give ``a``; ``PANEL / "a.py"`` gives ``file:a``; and
    ``checks.devices`` written anywhere gives itself, the package's own
    submodules being reached as attributes. Read once per test, so asking
    about a hundred modules is a hundred set lookups rather than a hundred
    passes over every file.
    """
    out: set[str] = set()
    for m in _IMPORT_STMT.finditer(src):
        out.update(_names_in(m.group(1)))
    for m in _FROM_STMT.finditer(src):
        module = m.group(1)
        if module.startswith("."):
            continue
        out.add(module)
        out.update(f"{module}.{n}" for n in _names_in(m.group(2))
                   if n.isidentifier())
    for m in _BY_STRING.finditer(src):
        out.add(next(g for g in m.groups() if g))
    out.update(f"file:{m.group(1)}" for m in _PY_FILE.finditer(src))
    for package in PANEL_PACKAGES:
        out.update(f"{package}.{m.group(1)}" for m in re.finditer(
            rf"(?<![\w.]){package}\.(\w+)", src))
    return frozenset(out)


def _imports(names: frozenset[str], stem: str, scope: str = "top") -> bool:
    """Does a test whose ``import_names`` are ``names`` import ``stem``?

    ``scope`` is ``"top"`` for a module imported by its own name, a
    package name for one of its submodules (``checks``), or ``"any"`` for
    the integration's modules, which tests load under an alias of their
    own (``brain_cc.requests``). Only import contexts count — never the
    bare word.
    """
    if f"file:{stem}" in names:
        return True
    for name in names:
        parts = name.split(".")
        if scope == "top":
            if parts[0] == stem:
                return True
        elif scope == "any":
            if stem in parts:
                return True
        elif len(parts) > 1 and parts[0] == scope and parts[1] == stem:
            return True
    return False


def _named_in_filename(test_rel: str, stem: str) -> bool:
    """The stem as whole ``_``-separated words of the test's file name."""
    name = Path(test_rel).stem
    if not name.startswith("test_"):
        return False
    have = name[len("test_"):].split("_")
    want = [w for w in stem.strip("_").split("_") if w]
    if not want:
        return False
    return any(have[i:i + len(want)] == want
               for i in range(len(have) - len(want) + 1))


def _mentions(src: str, basename: str) -> bool:
    """The basename as a whole token anywhere — for scripts, driven by name."""
    return re.search(rf"(?<![\w.-]){re.escape(basename)}(?![\w-])",
                     src) is not None


def _mentions_stem(src: str, basename: str) -> bool:
    """The file named with or without its suffix (``today-fixture.mjs`` or
    ``demo_panel``), as a whole token."""
    stem = Path(basename).stem
    return _mentions(src, basename) or re.search(
        rf"(?<![\w.-]){re.escape(stem)}(?![\w-])", src) is not None


def _reads(src: str, basename: str) -> bool:
    """The basename as (the end of) a string literal: the shape of a read."""
    return re.search(
        rf"""["'](?:[^"'\n]*/)?{re.escape(basename)}["']""", src) is not None


def _reads_here(src: str, rel: str) -> bool:
    """A read of THIS file: its name in a string literal, and — for a file
    below the top level — its folder's name somewhere in the test too.
    ``README.md`` and ``config.yml`` are names a dozen files share, and a
    test reading the add-on's README is not reading ``tests/manual``'s."""
    name = rel.rsplit("/", 1)[-1]
    if not _reads(src, name):
        return False
    if "/" not in rel:
        return True
    parent = rel.rsplit("/", 2)[-2]
    return _mentions(src, parent) or re.search(
        rf"""["'][^"'\n]*{re.escape(parent)}/""", src) is not None


def _names_addon(src: str, addon: str) -> bool:
    for name in ADDON_NAMES[addon]:
        n = re.escape(name)
        if re.search(rf"""["']{n}["']|(?<![\w-]){n}/|{n}\.""", src):
            return True
    return False


# ---------------------------------------------------------------------------
# The selection
# ---------------------------------------------------------------------------


@dataclass
class Selection:
    tests: set[str] = field(default_factory=set)
    measures: set[str] = field(default_factory=set)
    whole: bool = False
    reasons: list[str] = field(default_factory=list)
    # Changed code no rule could place: why the answer is the whole suite.
    unplaced: list[str] = field(default_factory=list)

    def output(self) -> list[str]:
        return [WHOLE_SUITE] if self.whole else sorted(self.tests)


def _rel(path: str, repo: Path = REPO) -> str:
    """A path as the repository names it, whatever directory it was typed in."""
    p = Path(path)
    candidates = [p] if p.is_absolute() else [Path.cwd() / p, repo / p]
    for c in candidates:
        try:
            return c.resolve().relative_to(repo.resolve()).as_posix()
        except (ValueError, OSError):
            continue
    text = p.as_posix()
    return text[2:] if text.startswith("./") else text


def _addon_of(rel: str) -> str | None:
    top = rel.split("/", 1)[0]
    return top if top in ADDONS else None


def _is_quiet(rel: str) -> bool:
    """Prose, pictures, CI and editor config: read by name or not at all."""
    name = rel.rsplit("/", 1)[-1]
    return (rel.startswith(QUIET_DIRS)
            or Path(name).suffix.lower() in PROSE_SUFFIXES
            or name in QUIET_NAMES
            or name.startswith(("CHANGELOG", "LICENSE")))


def _module_tests(index: Index, stem: str, scope: str = "top",
                  among=None) -> set[str]:
    pool = index.tests if among is None else [
        t for t in among if t in index.tests]
    return {t for t in pool
            if _imports(index.names(t), stem, scope)
            or _named_in_filename(t, stem)}


def _relative_imports(src: str) -> set[str]:
    """The names an ``__init__.py`` pulls in with ``from . import`` or ``from .x``."""
    names = set(re.findall(r"^[ \t]*from[ \t]+\.(\w+)[ \t]+import\b", src,
                           re.M))
    for m in re.finditer(r"^[ \t]*from[ \t]+\.[ \t]+import[ \t]+"
                         r"(\([^)]*\)|[^\n]*)", src, re.M):
        body = re.sub(r"#[^\n]*", "", m.group(1))
        names |= {w for w in re.split(r"[\s,()]+", body) if w and w != "as"}
    return names


def _panel_module(index: Index, rel: str) -> tuple[set[str], str]:
    parts = rel.split("/")
    stem = Path(rel).stem
    if len(parts) == 4 and parts[2] in PANEL_PACKAGES:
        package = parts[2]
        if stem == "__init__":
            return _module_tests(index, package), f"import {package}"
        found = _module_tests(index, stem, package)
        why = f"import {package}.{stem}"
        try:
            init = (index.repo / "brain" / "panel" / package
                    / "__init__.py").read_text(encoding="utf-8")
        except OSError:
            init = ""
        if stem in _relative_imports(init):
            found |= _module_tests(index, package)
            why += f" or {package}, whose __init__ imports it"
        return found, why
    if not stem.isidentifier():
        # build-docs.py: run by its file name, never imported.
        return ({t for t, src in index.tests.items()
                 if _mentions(src, Path(rel).name)}, f"name {Path(rel).name}")
    return _module_tests(index, stem), f"import {stem}"


def _script_tests(index: Index, rel: str) -> tuple[set[str], str]:
    name = rel.rsplit("/", 1)[-1]
    stem = Path(name).stem
    found = {t for t, src in index.tests.items() if _mentions(src, name)}
    why = f"name {name}"
    if name.endswith(".py") and stem.isidentifier():
        found |= _module_tests(index, stem)
        why += f" or import {stem}"
    callers = sorted(s for s, src in index.scripts.items()
                     if s != rel and _mentions(src, name))
    hop = set()
    for caller in callers:
        cname = caller.rsplit("/", 1)[-1]
        hop |= {t for t, src in index.tests.items() if _mentions(src, cname)}
    if hop - found:
        shown = ", ".join(c.rsplit("/", 1)[-1] for c in callers[:4])
        more = f" and {len(callers) - 4} more" if len(callers) > 4 else ""
        why += f", or drive a script that calls it ({shown}{more})"
    return found | hop, why


def _ui_measures(index: Index, rel: str, addon: str | None) -> set[str]:
    name = rel.rsplit("/", 1)[-1]
    # A measure naming ``app.js`` means its own add-on's: three panels have
    # one, so a measure that says which panel it loads is held to that.
    found = {m for m, src in index.measures.items() if _mentions(src, name)
             and (not index.measure_panels(m)
                  or addon in index.measure_panels(m))}
    if addon and rel.startswith(f"{addon}/panel/"):
        found |= {m for m in index.measures
                  if addon in index.measure_panels(m)}
    return found


def _sweepers(index: Index, addon: str) -> set[str]:
    """Tests that walk a source tree of ``addon`` rather than naming a file."""
    if addon not in index._sweep:
        prefix = f"tests/{ADDON_TEST_PREFIX.get(addon, '-')}"
        index._sweep[addon] = {
            t for t, src in index.tests.items()
            if _SWEEP.search(src)
            and (t.startswith(prefix) or _names_addon(src, addon))}
    return index._sweep[addon]


def select(paths, index: Index | None = None, transitive: bool = False
           ) -> Selection:
    """The test files and measures a change to ``paths`` can move."""
    index = index or Index()
    sel = Selection()
    rels = sorted({_rel(p, index.repo) for p in paths if str(p).strip()})
    importers: dict[str, set[str]] = {}
    if transitive:
        importers = {r: _transitive(index, [r]) for r in rels}
        rels = sorted(set(rels).union(*importers.values()))

    def say(rel, text):
        sel.reasons.append(f"{rel}: {text}")

    for rel in rels:
        name = rel.rsplit("/", 1)[-1]
        addon = _addon_of(rel)
        suffix = Path(name).suffix

        # Shared test infrastructure.
        if (rel in WHOLE_SUITE_FILES or rel.startswith("tests/corpus/")
                or re.fullmatch(r"tests/fake_[^/]+\.py", rel)
                or re.fullmatch(r"tests/[^/]+_env\.py", rel)):
            sel.whole = True
            say(rel, "whole suite (shared test infrastructure: tests reach "
                     "it without naming it)")
            continue

        # A test file.
        if re.fullmatch(r"tests/test_[^/]+\.py", rel):
            if rel in index.tests or index.exists(rel):
                sel.tests.add(rel)
                say(rel, "itself")
            else:
                say(rel, "nothing (deleted)")
            continue

        # Prose, pictures, CI.
        if _is_quiet(rel) and not (addon and suffix in UI_SUFFIXES):
            found = {t for t, src in index.tests.items()
                     if _reads_here(src, rel)}
            sel.tests |= found
            say(rel, f"{len(found)} test files read it by name" if found
                else "nothing (prose or CI; no test reads it by name)")
            continue

        # The browser measures and what they import.
        if rel.startswith("tests/manual/"):
            measures = {m for m, src in index.measures.items()
                        if m != rel and _mentions_stem(src, name)}
            if re.fullmatch(r"tests/manual/measure-[^/]+\.mjs", rel):
                measures.add(rel)
            found = {t for t, src in index.tests.items() if _reads(src, name)}
            sel.measures |= measures
            sel.tests |= found
            say(rel, f"{len(found)} test files, {len(measures)} measures "
                     "(not part of the pytest suite)")
            continue

        # A helper beside the tests (this file is one).
        if re.fullmatch(r"tests/[^/]+\.py", rel):
            stem = Path(name).stem
            found = _module_tests(index, stem) | {
                t for t, src in index.tests.items() if _reads(src, name)}
            if found:
                sel.tests |= found
                say(rel, f"{len(found)} test files (import {stem})")
            else:
                sel.whole = True
                sel.unplaced.append(rel)
                say(rel, "whole suite (a test helper no test names)")
            continue

        found: set[str] = set()
        measures: set[str] = set()
        why = []
        code = suffix in CODE_SUFFIXES

        # The other three add-ons: their own tests, plus tests naming both.
        if addon and addon != "brain":
            prefix = ADDON_TEST_PREFIX[addon]
            found = {t for t in index.tests
                     if t.startswith(f"tests/{prefix}")}
            scoped = {t for t, src in index.tests.items()
                      if _names_addon(src, addon)}
            stem = Path(name).stem
            if suffix == ".py" and stem.isidentifier() and stem != "__init__":
                found |= _module_tests(index, stem, among=scoped)
            found |= {t for t in scoped if _reads(index.tests[t], name)}
            why.append(f"{prefix}*, and tests naming {addon} and {name}")
            demo = DEMO_SERVERS.get(addon)
            if demo and suffix == ".py" and rel.startswith(f"{addon}/panel/"):
                measures |= {m for m, src in index.measures.items()
                             if _mentions_stem(src, demo + ".py")}

        if addon and ((rel.count("/") == 1 and name in ADDON_WIDE_FILES)
                      or rel.startswith(f"{addon}/translations/")):
            found |= {t for t in ADDON_WIDE_TESTS[addon] if t in index.tests}
            key = "translations" if "/translations/" in rel else name
            found |= {t for t, src in index.tests.items()
                      if (_reads(src, name) or _reads(src, key))
                      and _names_addon(src, addon)}
            why.append("the add-on-wide tests")

        elif addon and suffix in UI_SUFFIXES and any(
                rel.startswith(f"{addon}/{d}/") for d in UI_DIRS):
            measures = _ui_measures(index, rel, addon)
            found |= {t for t, src in index.tests.items()
                      if _reads(src, name)
                      and (addon == "brain" or _names_addon(src, addon))}
            why.append(f"{len(measures)} measures, and tests reading {name}")

        elif addon == "brain" and rel.startswith("brain/panel/") \
                and suffix == ".py":
            got, w = _panel_module(index, rel)
            found |= got
            why.append(w)

        elif addon == "brain" and rel.startswith(
                tuple(d + "/" for d in SCRIPT_DIRS)):
            got, w = _script_tests(index, rel)
            found |= got
            why.append(w)

        elif rel.startswith(INTEGRATION_DIR):
            stem = Path(name).stem
            if suffix == ".py" and stem != "__init__":
                found |= _module_tests(index, stem, "any")
            found |= {t for t, src in index.tests.items()
                      if _reads(src, name)
                      and _mentions(src, "custom_components")}
            found |= index.ha_env_users()
            what = (f"import {stem}" if suffix == ".py" and stem != "__init__"
                    else f"name {name}")
            why.append(f"{what}, or load the integration through "
                       "brain_ha_env")

        elif not why:
            top = rel.split("/", 1)[0]
            found = {t for t, src in index.tests.items()
                     if _reads(src, name)
                     or ("/" in rel and top != "tests" and _reads(src, top))}
            stem = Path(name).stem
            if suffix == ".py" and stem.isidentifier():
                found |= _module_tests(index, stem)
            why.append(f"name {name}")

        # A rule that names no file can still be broken by any of them.
        if found or measures:
            if addon and code:
                found |= _sweepers(index, addon)
            sel.tests |= found
            sel.measures |= measures
            say(rel, f"{len(found)} test files"
                     + (f", {len(measures)} measures" if measures else "")
                     + f" ({'; '.join(why)})")
        elif importers.get(rel):
            say(rel, f"no test of its own; placed through the "
                     f"{len(importers[rel])} modules that import it")
        else:
            sel.whole = True
            sel.unplaced.append(rel)
            say(rel, "whole suite (no test imports or names it, and a "
                     "selection that misses is worse than a slow run)")
    return sel


def _transitive(index: Index, rels) -> set[str]:
    """brAIn Python files that import a changed one, followed to the end.

    Read with ``ast`` rather than a pattern, because these are the sources
    and not the tests: a docstring here mentioning a module is not an import
    and an ``import_module("x")`` call is. Each importer found is then
    selected for by its own rule, as if it had changed too."""
    files = {}
    for d in ("brain/panel", "brain/panel/checks", "brain/panel/devloop",
              *SCRIPT_DIRS):
        for p in sorted((index.repo / d).glob("*.py")):
            rel = p.relative_to(index.repo).as_posix()
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names |= {a.name.split(".")[0] for a in node.names}
                    names |= {a.name.split(".")[-1] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        names |= set(node.module.split("."))
                    names |= {a.name for a in node.names}
                elif (isinstance(node, ast.Call) and node.args
                      and getattr(node.func, "attr",
                                  getattr(node.func, "id", "")) in (
                          "import_module", "__import__")
                      and isinstance(node.args[0], ast.Constant)
                      and isinstance(node.args[0].value, str)):
                    names |= set(node.args[0].value.split("."))
            files[rel] = names
    todo = [Path(r).stem if Path(r).stem != "__init__" else Path(r).parent.name
            for r in rels if r.endswith(".py")]
    seen_stems, out = set(todo), set()
    while todo:
        stem = todo.pop()
        for rel, names in files.items():
            if stem in names and rel not in out:
                out.add(rel)
                s = Path(rel).stem
                if s not in seen_stems:
                    seen_stems.add(s)
                    todo.append(s)
    return out


# ---------------------------------------------------------------------------
# git, pytest, and the command line
# ---------------------------------------------------------------------------


def changed_from_git(base: str, repo: Path = REPO) -> list[str]:
    """What this branch moved since ``base``, plus anything uncommitted."""
    def git(*args):
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True)
        if done.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)}: {done.stderr.strip() or 'failed'}")
        return [line for line in done.stdout.splitlines() if line.strip()]

    out = set(git("diff", "--name-only", f"{base}...HEAD"))
    out |= set(git("diff", "--name-only"))
    out |= set(git("diff", "--name-only", "--cached"))
    out |= set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(out)


def pytest_command(sel: Selection, last_failed: bool = False,
                   parallel: bool | None = None) -> list[str]:
    """The pytest invocation for a selection; ``[]`` when there is none."""
    targets = sel.output()
    if not targets:
        return []
    if parallel is None:
        parallel = importlib.util.find_spec("xdist") is not None
    cmd = [sys.executable, "-m", "pytest", "-q"]
    if parallel:
        cmd += ["-n", "auto", "--dist", "loadfile"]
    if last_failed:
        cmd.append("--lf")
    return cmd + targets


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Which test files a change can break.",
        epilog="With no paths, --base origin/main is assumed.")
    ap.add_argument("paths", nargs="*", help="changed paths")
    ap.add_argument("--base", help="git ref to diff against (default "
                    "origin/main when no paths are given)")
    ap.add_argument("--measures", action="store_true",
                    help="print the browser measures instead of the tests")
    ap.add_argument("--run", action="store_true",
                    help="run pytest over the selection, exit with its status")
    ap.add_argument("--lf", action="store_true",
                    help="with --run, pass --lf to pytest")
    ap.add_argument("--transitive", action="store_true",
                    help="also follow brAIn's own imports (server.py → …)")
    args = ap.parse_args(argv)

    paths = list(args.paths)
    if args.base or not paths:
        try:
            paths += changed_from_git(args.base or "origin/main")
        except (RuntimeError, OSError) as exc:
            print(f"affected: {exc}", file=sys.stderr)
            return 2
    if not paths:
        print("affected: nothing has changed", file=sys.stderr)
        return 0

    sel = select(paths, transitive=args.transitive)
    for line in sel.reasons:
        print(f"affected: {line}", file=sys.stderr)
    if sel.unplaced:
        print("affected: whole suite, because nothing places: "
              + ", ".join(sel.unplaced), file=sys.stderr)

    measures = sorted(sel.measures)
    if args.measures:
        for m in measures:
            print(m)
    else:
        for line in sel.output():
            print(line)
        if measures:
            print("affected: measures: " + " ".join(
                f"node {m}" for m in measures), file=sys.stderr)

    if not args.run:
        return 0
    cmd = pytest_command(sel, last_failed=args.lf)
    if not cmd:
        print("affected: no test files selected, nothing to run",
              file=sys.stderr)
        return 0
    if "-n" not in cmd:
        print("affected: pytest-xdist is not installed, running serially",
              file=sys.stderr)
    print("$ " + shlex.join(cmd), file=sys.stderr, flush=True)
    return subprocess.run(cmd, cwd=REPO).returncode


if __name__ == "__main__":
    sys.exit(main())
