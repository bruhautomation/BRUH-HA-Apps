"""Every instruction brAIn gives Claude, in one place you can read and change.

brAIn sends Claude a dozen different prompts (the chat's identity, the card
contract, the first look, the investigation, the fix plan, the interpreter…)
and reads a handful of files (the generated /config/CLAUDE.md, Morph's
AGENTS.md and LEARNED.md, memory). They used to live in Python constants and
nowhere a person could see them, so "it found some old instruction that
overrides what I told it" had no answer short of reading the source.

This module is the inventory and the override layer:

- ``CATALOG`` names every prompt by a key, says in a sentence what it is for
  and which module attributes carry it. The list is written by hand on
  purpose: a prompt is named here because somebody decided a person should
  be able to read it, and ``tests/test_instructions.py`` fails on a key whose
  attribute no longer exists.
- An override is a file, ``/config/.brain/instructions/<key>.md``. Saving one
  (from ⚙ › Instructions, or by Claude editing the file in the terminal)
  replaces the text every later run is sent: ``apply`` sets the attribute on
  each module that carries it, so a run reads the new words the next time it
  is built. Deleting the file puts the shipped text back.
- The shipped text of every prompt is exported to ``builtin/<key>.md`` beside
  the overrides, read-only by convention, so Claude in the terminal can read
  what brAIn sends without the source.
- An override must keep every placeholder the shipped text has (``{text}``,
  ``%(name)s``): a template missing one fails at the run that formats it,
  which is far from the save that broke it. ``check`` refuses such a save.

Nothing here raises into a caller: an override that cannot be read is the
shipped text, and the reason is in ``state()``.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import sys
from pathlib import Path

import atomic_write

log = logging.getLogger("brain.instructions")

DIR = Path(os.environ.get("BRAIN_INSTRUCTIONS_DIR", "/config/.brain/instructions"))
BUILTIN = "builtin"
MAX_CHARS = 60_000
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")
_PLACEHOLDER_RE = re.compile(r"%\([a-z_]+\)s|\{[a-z_]+\}")

# group → the order the groups are listed in.
GROUPS = ("Conversation", "Cards", "Watching the house", "Fixing", "Messages",
          "Upkeep", "Development")

# key: (title, group, what it is for, [(module, attribute), …])
CATALOG: dict[str, tuple[str, str, str, list[tuple[str, str]]]] = {
    "chat_identity": (
        "Who brAIn is in a conversation", "Conversation",
        "Appended to Claude Code's own prompt in the terminal, a card's " +
        "conversation and every window opened by pressing and holding.",
        [("server", "CHAT_IDENTITY")]),
    "interpret": (
        "Reading what somebody typed", "Conversation",
        "Decides what a sentence on the ask bar, a phone reply or a Repairs " +
        "box means: a question, a rule, an ending for a card.",
        [("interpret", "SYSTEM")]),
    "card_snapshot": (
        "Writing a card (snapshot)", "Cards",
        "The card contract when the house is handed over up front.",
        [("categories", "SYSTEM_PROMPT"), ("server", "SYSTEM_PROMPT")]),
    "card_search": (
        "Writing a card (search)", "Cards",
        "The card contract when the card looks the house up itself — the " +
        "default.",
        [("categories", "ANALYST_SYSTEM"), ("server", "ANALYST_SYSTEM")]),
    "first_look": (
        "The first look", "Watching the house",
        "Every few minutes: which of the new signals is worth anybody's " +
        "attention.",
        [("resident", "FIRST_LOOK_SYSTEM")]),
    "investigate": (
        "Looking into one thing", "Watching the house",
        "What a deeper look is told when one signal needs reading properly.",
        [("resident", "INVESTIGATE_SYSTEM")]),
    "situation": (
        "What the house is doing", "Watching the house",
        "The one line every look reads about the house right now.",
        [("situation", "SYSTEM")]),
    "curiosity": (
        "Why somebody did something", "Watching the house",
        "The one question a day brAIn may ask about a manual action.",
        [("curiosity", "SYSTEM")]),
    "fix_plan": (
        "Planning a fix", "Fixing",
        "Fix on a card: the read-only run that writes what Apply will change.",
        [("fixer", "PLAN_SYSTEM")]),
    "fix_apply": (
        "Making a fix", "Fixing",
        "Apply: the run that carries out the plan somebody approved.",
        [("fixer", "FIX_SYSTEM")]),
    "authoring": (
        "Writing an automation from a sentence", "Fixing",
        "Drafts the automation a typed rule asks for, before it is replayed.",
        [("authoring", "SYSTEM")]),
    "corrections": (
        "How far a correction reaches", "Fixing",
        "When somebody says a card is wrong: one device, a room, or the rule.",
        [("corrections", "SYSTEM")]),
    "brief": (
        "The morning brief", "Messages",
        "The paragraph sent to a phone on a morning there is something to say.",
        [("brief", "SYSTEM")]),
    "weekly": (
        "The weekly report", "Messages",
        "The week's report: what happened, and one thing to do.",
        [("weekly", "SYSTEM")]),
    "dispatch": (
        "When and how to notify", "Messages",
        "Decides whether a finding goes to a phone now, later or not at all, " +
        "and writes the line on the lock screen.",
        [("dispatch", "SYSTEM")]),
    "house_book": (
        "The house book", "Upkeep",
        "How this house works, written sentence by sentence from what brAIn " +
        "has read.",
        [("house_book", "SYSTEM")]),
    "tidy": (
        "Tidying names and rooms", "Upkeep",
        "Proposes better names and rooms for devices, as one table.",
        [("tidy", "SYSTEM")]),
    "memory_cleanup": (
        "Cleaning up memory", "Upkeep",
        "Proposes lines of memory that are wrong, stale or useless.",
        [("memory_cleanup", "SYSTEM")]),
    "upgrades": (
        "Should I update tonight", "Upkeep",
        "Reads a release's notes against this house's configuration.",
        [("upgrades", "SYSTEM")]),
    "sre": (
        "The overnight check", "Upkeep",
        "Reads the night's logs and names root causes, citing each record.",
        [("sre", "SYSTEM")]),
    "deep_review": (
        "Deep review", "Upkeep",
        "The pressed review of the whole house that files nothing.",
        [("deep_review", "SYSTEM")]),
    "devloop_look": (
        "What do you want to fix?", "Development",
        "Development mode: turns the owner's words into one issue.",
        [("devloop.streams", "LOOK_SYSTEM")]),
    "devloop_analyst": (
        "Looking for brAIn's own bugs", "Development",
        "Development mode: reads brAIn's evidence for gaps worth fixing.",
        [("devloop.streams", "ANALYST_SYSTEM")]),
    "devloop_design": (
        "Design review", "Development",
        "Development mode: reads the panel's pictures as a design lead.",
        [("devloop.streams", "DESIGN_SYSTEM")]),
}

# Files that ARE instructions, read where they are. `editable` False is a
# file something else writes (the context generator, the consolidator), so
# the editor shows it and says where it is changed instead.
FILES: dict[str, tuple[str, str, str, str, bool]] = {
    "claude_md": (
        "/config/CLAUDE.md", "Conversation",
        "What Claude Code reads in /config: written by brAIn at every start, " +
        "except the notes block, which is yours (edit it below).",
        "/config/CLAUDE.md", False),
    "claude_md_notes": (
        "Your notes in CLAUDE.md", "Conversation",
        "The block of /config/CLAUDE.md brAIn keeps across every rewrite. " +
        "Anything you want every terminal session to know goes here.",
        "/config/CLAUDE.md#notes", True),
    "memory": (
        "Memory", "Conversation",
        "What brAIn knows about this house. One writer (the consolidator), so " +
        "it is read here and changed by telling brAIn or through Memory.",
        "/config/.brain/memory/memory.md", False),
    "morph_agents": (
        "Morph: how to change the dashboard", "Conversation",
        "What brAIn reads before it changes Morph.",
        "/config/morph/AGENTS.md", True),
    "morph_learned": (
        "Morph: what it has learned", "Conversation",
        "Lessons Morph's learning pass keeps and every Tell reads.",
        "/config/morph/LEARNED.md", True),
}

NOTES_START = "<!-- bruh:user-notes:start -->"
NOTES_END = "<!-- bruh:user-notes:end -->"

_SHIPPED: dict[str, str] = {}
_APPLIED: dict[str, float] = {}
_ERRORS: dict[str, str] = {}


def _module(name: str):
    if name == "server":
        # run.sh starts the panel as a script, so the server is __main__ and
        # importing "server" would load a second copy nobody runs.
        mod = sys.modules.get("server")
        main = sys.modules.get("__main__")
        if mod is None and main is not None and hasattr(main, "CHAT_IDENTITY"):
            return main
    mod = sys.modules.get(name)
    if mod is None:
        mod = importlib.import_module(name)
    return mod


def _current(key: str) -> str | None:
    """The text a prompt's first carrier holds right now."""
    targets = CATALOG[key][3]
    try:
        value = getattr(_module(targets[0][0]), targets[0][1])
    except Exception:  # noqa: BLE001 — a module that will not import is a
        # prompt that cannot be shown, never a page that fails.
        return None
    return value if isinstance(value, str) else None


def shipped(key: str) -> str | None:
    """The text this release ships for a prompt, captured before any
    override was applied."""
    if key not in _SHIPPED:
        text = _current(key)
        if text is None:
            return None
        _SHIPPED[key] = text
    return _SHIPPED[key]


def override_path(key: str) -> Path:
    if not _KEY_RE.match(key or "") or key not in CATALOG:
        raise KeyError(key)
    return DIR / f"{key}.md"


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(text or ""))


def check(key: str, text: str) -> str | None:
    """Why an override cannot be saved, or None."""
    if not isinstance(text, str) or not text.strip():
        return "An empty prompt would leave brAIn with nothing to go on — use Reset instead."
    if len(text) > MAX_CHARS:
        return f"That is {len(text):,} characters; the limit is {MAX_CHARS:,}."
    base = shipped(key)
    if base is not None:
        missing = sorted(placeholders(base) - placeholders(text))
        if missing:
            return ("These placeholders are filled in when the prompt is sent "
                    "and have to stay: " + ", ".join(missing))
    return None


def _set(key: str, text: str) -> None:
    for mod_name, attr in CATALOG[key][3]:
        try:
            setattr(_module(mod_name), attr, text)
        except Exception as exc:  # noqa: BLE001 — one carrier that will not
            # take it is said in state(), the others still do.
            _ERRORS[key] = f"{mod_name}.{attr}: {exc}"


def apply(key: str) -> bool:
    """Put the override for one key in force (or the shipped text when
    there is none). Returns whether an override is in force."""
    base = shipped(key)
    if base is None:
        return False
    path = override_path(key)
    _ERRORS.pop(key, None)
    try:
        text = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        _set(key, base)
        _APPLIED.pop(key, None)
        return False
    except OSError as exc:
        _ERRORS[key] = f"could not read {path}: {exc}"
        _set(key, base)
        _APPLIED.pop(key, None)
        return False
    problem = check(key, text)
    if problem:
        _ERRORS[key] = problem
        _set(key, base)
        _APPLIED.pop(key, None)
        return False
    _set(key, text)
    _APPLIED[key] = mtime
    return True


def sync() -> list[str]:
    """Re-apply every override whose file changed (an edit in the terminal is
    picked up here). Cheap: a stat per key. Never raises."""
    changed = []
    for key in CATALOG:
        try:
            path = override_path(key)
            mtime = path.stat().st_mtime if path.exists() else None
        except OSError:
            mtime = None
        if mtime != _APPLIED.get(key) and (mtime is not None or key in _APPLIED):
            try:
                apply(key)
                changed.append(key)
            except Exception as exc:  # noqa: BLE001
                _ERRORS[key] = str(exc)
    return changed


def apply_all() -> None:
    for key in CATALOG:
        try:
            apply(key)
        except Exception as exc:  # noqa: BLE001
            _ERRORS[key] = str(exc)


def save(key: str, text: str) -> None:
    problem = check(key, text)
    if problem:
        raise ValueError(problem)
    path = override_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write.write_text(path, text, mode=0o644)
    apply(key)


def reset(key: str) -> None:
    path = override_path(key)
    try:
        path.unlink()
    except FileNotFoundError:
        pass  # no override to remove: Restore on the shipped text is a no-op
    apply(key)


README = """# brAIn's instructions

Every prompt brAIn sends Claude, and the files Claude reads.

- `builtin/<key>.md` is what this release ships. It is rewritten at every
  start, so editing it changes nothing.
- `<key>.md` beside this file is an override. Write one (start from the
  builtin copy) and every later run of that kind is sent your text instead.
  Delete it to go back. ⚙ › Instructions in the panel is the same thing.
- Keep every placeholder in `{braces}` or `%(this)s` form: they are filled in
  when the prompt is sent.
"""


def export_builtins() -> int:
    """Write the shipped text of every prompt to builtin/, so Claude in the
    terminal can read it. Skipped where /config/.brain does not exist (a dev
    checkout). Returns how many were written."""
    if not DIR.parent.is_dir():
        return 0
    out = DIR / BUILTIN
    n = 0
    try:
        out.mkdir(parents=True, exist_ok=True)
        atomic_write.write_text(DIR / "README.md", README, mode=0o644)
        for key in CATALOG:
            text = shipped(key)
            if text is not None:
                atomic_write.write_text(out / f"{key}.md", text, mode=0o644)
                n += 1
    except OSError as exc:
        log.warning("could not export brAIn's prompts: %s", exc)
    return n


# ----------------------------------------------------------------- files

def _notes(text: str) -> str:
    start = text.find(NOTES_START)
    end = text.find(NOTES_END)
    if start < 0 or end < start:
        return ""
    return text[start + len(NOTES_START):end].strip("\n")


def read_file(key: str) -> dict:
    title, group, what, where, editable = FILES[key]
    path = Path(where.split("#")[0])
    try:
        text = path.read_text(encoding="utf-8")
        exists = True
    except FileNotFoundError:
        text, exists = "", False
    except OSError as exc:
        return {"text": "", "exists": False, "error": str(exc)}
    if where.endswith("#notes"):
        text = _notes(text)
    return {"text": text, "exists": exists}


def file_refusal(key: str, text: str) -> str | None:
    """Why `text` cannot be written to file `key`, in a sentence, or None."""
    title, group, what, where, editable = FILES[key]
    if not editable:
        return f"{title} is written by brAIn; {what}"
    if not isinstance(text, str) or len(text) > MAX_CHARS:
        return "That is too long to save here."
    path = Path(where.split("#")[0])
    if where.endswith("#notes"):
        try:
            whole = path.read_text(encoding="utf-8")
        except OSError:
            return f"{path} could not be read."
        start = whole.find(NOTES_START)
        end = whole.find(NOTES_END)
        if start < 0 or end < start:
            return "CLAUDE.md has no notes block yet; restart brAIn to have it written."
        return None
    if not path.parent.is_dir():
        return f"{path.parent} does not exist on this house."
    return None


def write_file(key: str, text: str) -> None:
    problem = file_refusal(key, text)
    if problem:
        raise ValueError(problem)
    where = FILES[key][3]
    path = Path(where.split("#")[0])
    if where.endswith("#notes"):
        whole = path.read_text(encoding="utf-8")
        start = whole.find(NOTES_START)
        end = whole.find(NOTES_END)
        body = text.strip("\n")
        whole = (whole[:start + len(NOTES_START)] + "\n"
                 + (body + "\n" if body else "") + whole[end:])
        atomic_write.write_text(path, whole)
        return
    atomic_write.write_text(path, text)


# ----------------------------------------------------------------- listing

def listing() -> list[dict]:
    rows = []
    for key, (title, group, what, targets) in CATALOG.items():
        rows.append({
            "key": key, "kind": "prompt", "title": title, "group": group,
            "what": what, "editable": True,
            "overridden": key in _APPLIED,
            "path": str(DIR / f"{key}.md"),
            "builtin_path": str(DIR / BUILTIN / f"{key}.md"),
            "error": _ERRORS.get(key, ""),
        })
    for key, (title, group, what, where, editable) in FILES.items():
        rows.append({
            "key": key, "kind": "file", "title": title, "group": group,
            "what": what, "editable": editable, "overridden": False,
            "path": where.split("#")[0], "error": "",
        })
    order = {g: i for i, g in enumerate(GROUPS)}
    rows.sort(key=lambda r: (order.get(r["group"], 99), r["kind"] != "file"))
    return rows


def detail(key: str) -> dict:
    if key in CATALOG:
        base = shipped(key) or ""
        current = _current(key) or base
        return {"key": key, "kind": "prompt", "text": current, "shipped": base,
                "overridden": key in _APPLIED, "editable": True,
                "placeholders": sorted(placeholders(base)),
                "path": str(DIR / f"{key}.md"), "error": _ERRORS.get(key, "")}
    if key in FILES:
        title, group, what, where, editable = FILES[key]
        return {"key": key, "kind": "file", "editable": editable,
                "path": where.split("#")[0], **read_file(key)}
    raise KeyError(key)


__all__ = ["CATALOG", "DIR", "FILES", "GROUPS", "apply", "apply_all", "check",
           "detail", "export_builtins", "listing", "read_file", "reset",
           "save", "shipped", "sync", "write_file"]
