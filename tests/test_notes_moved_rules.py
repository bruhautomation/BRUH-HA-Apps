"""No rule in the notes disappears without saying where it went (plan 2.6).

``docs/notes/*.md`` are consolidated monthly by the development loop: one
pull request per note dedupes it, folds superseded bullets and moves
history to ``docs/notes/history/``. A consolidation that shortens a note by
dropping a rule is the loop closing issues rather than fixing them, one
level up, so this holds every bolded rule lead sentence (``- **…**``)
that a branch removes from a note, relative to ``git merge-base HEAD
origin/main``: the same sentence must still exist under ``docs/notes/``
(``history/`` included), or a pointer line ``moved: <sentence> -> <path>``
must say where it went.

The comparison is against the working tree, so it also holds a change not
yet committed. Without ``origin/main`` (a shallow checkout, a fresh clone
with no remote) the branch check skips; the rules it applies are tested
on their own below either way.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "docs" / "notes"

# The bold may wrap onto following lines, but never past a blank line or
# into the next bullet.
_LEAD = re.compile(r"^[ \t]*(?:[-*+]|\d+\.)[ \t]+\*\*"
                   r"((?:(?!\n[ \t]*(?:\n|[-*+][ \t]|\d+\.[ \t])).)+?)\*\*",
                   re.MULTILINE | re.DOTALL)
_MOVED = re.compile(r"^\s*(?:[-*+]\s+)?moved:\s*(.+?)\s*->\s*(\S+)\s*$", re.MULTILINE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def lead_rules(text: str) -> list[str]:
    """Every bolded lead sentence of a bullet, whitespace folded (a lead may
    wrap across lines)."""
    out = []
    for m in _LEAD.finditer(text):
        lead = _norm(m.group(1))
        if len(lead) < 8:
            continue
        out.append(lead)
    return out


def pointers(text: str) -> set[str]:
    return {_norm(m.group(1)).strip("*`").strip() for m in _MOVED.finditer(text)}


def missing_rules(before: dict[str, str], after: dict[str, str]) -> list[tuple[str, str]]:
    """(note, rule) for every rule in ``before``'s notes that ``after`` (all
    of docs/notes, history included) neither keeps nor points to."""
    everything = _norm("\n".join(after.values()))
    moved = set()
    for text in after.values():
        moved |= pointers(text)
    out = []
    for name, text in sorted(before.items()):
        for rule in lead_rules(text):
            if rule in everything or f"**{rule}**" in everything:
                continue
            if rule in moved or rule.rstrip(".") in {m.rstrip(".") for m in moved}:
                continue
            out.append((name, rule))
    return out


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


class TestTheRules(unittest.TestCase):
    BEFORE = {"panel.md": (
        "# panel\n\nsummary\n\n"
        "- **The 16px text floor is load-bearing** (`style.css`). Because iOS zooms.\n"
        "- **A tooltip never holds\n  the only name** of a control.\n"
        "- **Undo is one press** everywhere.\n")}

    def test_leads_are_found_across_line_wraps(self):
        self.assertEqual(lead_rules(self.BEFORE["panel.md"]), [
            "The 16px text floor is load-bearing",
            "A tooltip never holds the only name",
            "Undo is one press"])

    def test_an_unclosed_bold_does_not_swallow_the_next_bullet(self):
        text = "- **Unclosed lead and more\n- **Next rule here** text.\n"
        self.assertEqual(lead_rules(text), ["Next rule here"])

    def test_a_kept_folded_or_moved_rule_passes(self):
        after = {
            "panel.md": ("# panel\n\nsummary\n\n- **The 16px text floor is load-bearing** "
                         "and so is **Undo is one press**, folded together.\n"
                         "moved: A tooltip never holds the only name -> "
                         "docs/notes/history/panel.md\n"),
        }
        self.assertEqual(missing_rules(self.BEFORE, after), [])

    def test_a_rule_moved_to_history_passes(self):
        after = {"panel.md": "- **The 16px text floor is load-bearing**\n- **Undo is one press**\n",
                 "history/panel.md": "- **A tooltip never holds the only name** (2.4).\n"}
        self.assertEqual(missing_rules(self.BEFORE, after), [])

    def test_a_dropped_rule_fails(self):
        after = {"panel.md": "- **The 16px text floor is load-bearing**\n"
                             "moved: Undo is one press -> docs/notes/actions-safety.md\n"}
        self.assertEqual(missing_rules(self.BEFORE, after),
                         [("panel.md", "A tooltip never holds the only name")])

    def test_a_reworded_rule_is_a_dropped_rule(self):
        after = {"panel.md": "- **The 16 px text floor matters**\n- **A tooltip never "
                             "holds the only name**\n- **Undo is one press**\n"}
        self.assertEqual(len(missing_rules(self.BEFORE, after)), 1)


class TestThisBranch(unittest.TestCase):
    @pytest.mark.slow
    def test_no_rule_left_the_notes_without_a_pointer(self):
        if _git("rev-parse", "--verify", "--quiet", "origin/main") is None:
            self.skipTest("origin/main is not available in this checkout")
        base = (_git("merge-base", "HEAD", "origin/main") or "").strip()
        if not base:
            self.skipTest("no merge base with origin/main")
        listing = _git("ls-tree", "-r", "--name-only", base, "--", "docs/notes/") or ""
        before = {}
        for path in listing.split():
            if path.endswith(".md"):
                text = _git("show", f"{base}:{path}")
                if text is not None:
                    before[path[len("docs/notes/"):]] = text
        after = {str(p.relative_to(NOTES)): p.read_text(encoding="utf-8")
                 for p in NOTES.rglob("*.md")}
        gone = missing_rules(before, after)
        self.assertEqual(gone, [], "rules removed from docs/notes with no copy and no "
                         "'moved: <sentence> -> <path>' line:\n"
                         + "\n".join(f"  {n}: {r}" for n, r in gone))


if __name__ == "__main__":
    unittest.main()
