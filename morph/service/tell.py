"""Tell brAIn: hold anything in Edit, say what should change, and brAIn
changes it.

This is the critical half of Morph (docs/design/morph-ui.md §7), and it is
deliberately almost unrestrained: the person describes a change and brAIn
may make whatever it takes — the dashboard, Morph's card code, or the house
behind it (automations, scripts, helpers, scenes). The owner chose
**act at once** for house changes too, so nothing here asks for a plan
first; what makes that safe is what brAIn already enforces and what Morph
adds around it:

* ``protected_entities`` holds at brAIn's MCP chokepoint and in its shell
  hook, whatever this prompt says;
* every file brAIn edits under /config is snapshotted by its own edit hook,
  so ``brain undo`` reverts a house change;
* every change under /config/morph is ONE commit here, made the moment the
  answer lands, so Undo in the same prompt is a revert of exactly that.

Four things make it a conversation about what the person is LOOKING at,
rather than a text box that sends a sentence somewhere:

* **A picture first.** The panel photographs what was held the moment it
  is held (`frontend/snap.js`) and the integration files it under
  ``/config/.morph/shots``; the prompt tells brAIn to read that picture
  before anything else, because "this" means what is on the screen and the
  YAML only says what is configured. A picture that could not be taken is
  said, and the panel's own text of the card is sent instead.
* **The dashboard, not the house.** A Tell changes /config/morph. Home
  Assistant itself (entity ids, names, automations, helpers) is changed
  only when the words ask for that in as many words; otherwise brAIn does
  the dashboard half and says what the house half would be. The one caller
  that may change the house without being asked in words is Undo's
  follow-up, which is putting back a house change a Tell made.
* **What brAIn is doing, while it does it.** brAIn's task-progress hook
  writes a line per tool call; this turns them into steps the panel shows.
* **Morph's own code is the house's to change too.** When the request needs
  Morph itself changed (the header, the layout, a built-in card type),
  brAIn copies that module into /config/morph/frontend/ and changes the
  copy (``morphcode.py``), so it is one commit and Undo puts Morph's own
  back. Then the panel asks whether to send the change to Morph's
  developers as an issue; nothing is filed until somebody says yes.

A tell is a job with a state file the integration reads directly
(``/config/.morph/tells/<id>.json``), so the panel can poll it without a
round trip and a reload of the page does not lose it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

import brain
import devloop
import gitrepo
import learning
import morphcode
import paths
import settings
import store
import wording

log = logging.getLogger("morph.tell")

TIMEOUT_S = 900
MAX_WORDS = wording.MAX_TEXT   # a person's words and any context sent with them
MAX_WRITTEN = 20000             # what Morph writes itself (a merge names files and paths)
LESSONS_CHARS = 4000
MAX_STEPS = 60
VIEW_CHARS = 1500
TARGET_CHARS = 12000
HISTORY_TURNS = 6
SHOT_ID = re.compile(r"^[a-f0-9]{32}$")
SCOPES = ("ui", "house")
# Where a Tell came from. It decides the line that says so in the prompt,
# whether there can be a picture, and what counts as the person's words.
ORIGINS = ("panel", "suggestion", "question", "undo", "redo")

# The schema is the one place each answer field's rule is written: the
# prompt names the fields and AGENTS.md points here. ``reload`` is not
# required because Morph derives it (a commit reloads); ``changed`` was
# split in two because one list mixing files and Home Assistant changes
# left Undo guessing which lines were the house's.
RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "files", "home_assistant"],
    "properties": {
        "summary": {"type": "string",
                    "description": "One or two sentences a person reads: what you did. When the change bends "
                                   "one of AGENTS.md's design rules, say which."},
        "files": {"type": "array", "items": {"type": "string"},
                  "description": "Each file under /config/morph you changed, as a path in that folder "
                                 "(dashboard.yaml, cards/x.js, frontend/y.js). Empty when none."},
        "home_assistant": {"type": "array", "items": {"type": "string"},
                           "description": "Each change you made in Home Assistant itself (an automation, "
                                          "a helper, an entity, a scene), one per line, so Undo can hand "
                                          "the list back to you. Empty when none."},
        "reload": {"type": "boolean",
                   "description": "Optional: true to make the page reload even though nothing under "
                                  "/config/morph changed. Morph reloads after any change of its own."},
        "needs_person": {"type": "string",
                         "description": "Only when something is left that a person has to do by hand."},
        "lesson": {"type": "string",
                   "description": "Optional: one durable rule about how this household wants its "
                                  "DASHBOARD to look or behave, only when the request taught one. Never a "
                                  "fact about the house."},
        "saw": {"type": "string",
                "description": "Only when the request came with a screenshot: one sentence saying what in "
                               "it the request is about."},
        "facts": {"type": "array", "maxItems": 6,
                  "items": {"type": "object", "additionalProperties": False, "required": ["fact"],
                            "properties": {
                                "fact": {"type": "string"},
                                "subject": {"type": "string",
                                            "description": "The entity id, `area:<id>`, `person:<id>` "
                                                           "or `house` the fact is about."},
                                "confidence": {"type": "string", "enum": ["high", "medium"],
                                               "description": "high only when you read it off Home "
                                                              "Assistant or the person said it."}}},
                  "description": "Durable facts about the HOUSE this request taught you (what a device "
                                 "is, where it is, which sensor measures what). Morph queues them for "
                                 "brAIn's memory, whose consolidator decides what to keep."},
        "question": {
            "type": "object", "additionalProperties": False, "required": ["text", "options"],
            "properties": {
                "text": {"type": "string", "description": "The question, in one sentence a person reads."},
                "options": {"type": "array", "minItems": 2, "maxItems": 3,
                            "items": {"type": "object", "additionalProperties": False,
                                      "required": ["label", "request"],
                                      "properties": {
                                          "label": {"type": "string",
                                                    "description": "The button, under 60 characters."},
                                          "request": {"type": "string",
                                                      "description": "What Morph sends you as the next "
                                                                     "request when this is pressed, in the "
                                                                     "person's voice, whole: it is sent on "
                                                                     "its own."},
                                          "home_assistant": {"type": "boolean",
                                                             "description": "True when this answer changes "
                                                                            "Home Assistant itself."}}}},
            },
            "description": "A choice that belongs to the person, asked as buttons (AGENTS.md, “When to "
                           "ask instead of act”). Use it rather than needs_person whenever the person "
                           "only has to pick.",
        },
        "waiting": {"type": "array", "items": {"type": "string"},
                    "description": "Only when making paused changes to Morph's own code again: the file "
                                   "names still waiting on the person's answer to `question`. Morph keeps "
                                   "exactly those paused."},
        "code_issue": {
            "type": "object", "additionalProperties": False, "required": ["title", "detail"],
            "properties": {
                "title": {"type": "string",
                          "description": "Under 90 characters: what Morph itself should do differently."},
                "detail": {"type": "string",
                           "description": "What you changed in Morph's own code here and why, so Morph's "
                                          "developers can make it part of Morph for everybody."},
            },
            "description": "Whenever you changed Morph's OWN code (a file in /config/morph/frontend/), "
                           "or doing this properly needs it and you could not. Morph asks the person "
                           "whether to send it to Morph's developers as an issue; never file one yourself.",
        },
    },
}

# What was held, named with its article so a sentence can use it whole
# ("the story line", never "the story line “story”" or "the Morph's own
# code"). A label is added only where it names one of several things.
KIND_WORDS = {
    "card": "the card", "section": "the section", "floor": "the floor heading",
    "story": "the story line", "upcoming": "the Coming up timeline",
    "scenes": "the house-wide scenes line", "dashboard": "the whole dashboard",
    "code": "Morph's own code",
}
LABELLED = ("card", "section", "floor", "code")

# Where the thing a Tell is about actually lives. The story and Coming up
# are drawn by Morph's own code from the house's state; dashboard.yaml only
# switches them, so sending brAIn to dashboard.yaml for "the story is
# wrong" sent it to the one file that could not fix it.
WHERE_LIVES = {
    "card": "This card is in /config/morph/dashboard.yaml; its part of the file is below.",
    "section": "This section is in /config/morph/dashboard.yaml; its part of the file is below.",
    "floor": "This floor is in /config/morph/dashboard.yaml; its part of the file is below.",
    "scenes": "The scenes line is `scenes:` at the top of /config/morph/dashboard.yaml (below).",
    "story": ("The story line is drawn by Morph's own code (morph-panel.js, storyFacts) from the "
              "house's state, led by brAIn's situation sentence when brAIn has one. dashboard.yaml only "
              "switches it on or off (`story:`, below): what it says is changed in Morph's code or in "
              "brAIn, not in that file."),
    "upcoming": ("Coming up is drawn by Morph's own code (upcoming.js gathers its events, morph-panel.js "
                 "places it). dashboard.yaml only switches it on or off (`coming_up:`, below): what it "
                 "shows is changed in Morph's code, not in that file."),
    "dashboard": "The dashboard is /config/morph/dashboard.yaml; the file is below.",
    "code": ("This is Morph's own code: this house's copy in /config/morph/frontend/, against Morph's "
             "own in {shipped}/ (read-only)."),
}


def what_of(target: dict) -> str:
    """The thing a Tell is about, as words a sentence can carry."""
    kind = target.get("kind") or "dashboard"
    words = KIND_WORDS.get(kind, f"the {kind}")
    label = str(target.get("label") or "").strip()[:120]
    if kind == "code" and label:
        return f"Morph's own {label}"
    if kind in LABELLED and label:
        return f"{words} “{label}”"
    return words

_RUNNING: dict[str, asyncio.Task] = {}

# Set by morphd to its own publish, which writes the mirror and returns it:
# a finished Tell republishes at once (tell.py cannot import morphd).
ON_PUBLISH = None


def _state_path(tid: str):
    return paths.TELLS / f"{tid}.json"


def read_state(tid: str) -> dict | None:
    if not tid or not all(c.isalnum() or c == "-" for c in tid):
        return None
    return paths.read_json(_state_path(tid))


def _save(state: dict) -> None:
    state["updated"] = time.time()
    paths.write_json(_state_path(state["id"]), state)


def _step(state: dict, text: str, tone: str = "") -> None:
    state.setdefault("steps", []).append({"t": text, "tone": tone, "at": time.time()})
    _save(state)


def shot_path(shot: str):
    """The picture the panel took, if it is one Morph filed. The id comes
    off the wire, so it is checked for shape before it becomes a path."""
    if not isinstance(shot, str) or not SHOT_ID.match(shot):
        return None
    path = paths.SHOTS / f"{shot}.png"
    return path if path.is_file() else None


def clean_view(view) -> dict:
    """What the panel showed, as text: a fallback beside the picture, and
    the whole of it when no picture could be taken."""
    if not isinstance(view, dict):
        return {}
    out = {}
    for key in ("w", "h"):
        try:
            out[key] = max(0, min(10000, int(view.get(key) or 0)))
        except (TypeError, ValueError):
            pass  # a size that is not a number is no size
    text = re.sub(r"\s+", " ", str(view.get("text") or "")).strip()
    if text:
        out["text"] = text[:VIEW_CHARS]
    err = str(view.get("error") or "").strip()
    if err:
        out["error"] = err[:200]
    return out


def describe_call(row: dict) -> str:
    """One line of brAIn's progress, in words a person reads. An empty
    answer is a call not worth a line (its own to-do list, a sub-task)."""
    tool = str(row.get("tool") or "")
    what = str(row.get("what") or "").strip()
    short = what.replace(str(paths.MORPH_DIR) + "/", "").replace("/config/", "")
    if tool in ("TodoWrite", "TodoRead", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
                "ToolSearch", "Skill"):
        return ""
    if tool == "Read":
        if "/.morph/shots/" in what:
            return "Looking at the screenshot"
        return f"Reading {short}" if short else "Reading a file"
    if tool in ("Edit", "MultiEdit", "NotebookEdit"):
        return f"Editing {short}" if short else "Editing a file"
    if tool == "Write":
        return f"Writing {short}" if short else "Writing a file"
    if tool in ("Glob", "Grep"):
        return f"Searching for {short[:60]}" if short else "Searching"
    if tool == "Bash":
        return f"Running {short[:70]}" if short else "Running a command"
    if tool.startswith("mcp__"):
        words = tool.split("__")[-1].replace("_", " ").strip().capitalize()
        return f"{words} · {short[:70]}" if short else words
    if tool in ("WebFetch", "WebSearch"):
        return f"Looking up {short[:70]}" if short else "Looking something up"
    if tool == "Agent":
        return "Handing part of it to a helper"
    return f"{tool} · {short[:70]}" if short else tool


def progress(tid: str, seen: int) -> tuple[list[str], int]:
    """New lines of brAIn's progress since ``seen``, described. A missing
    file is an older brAIn without the hook: nothing to add, not a fault."""
    rows = paths.read_jsonl(paths.BRAIN_PROGRESS / f"{tid}.jsonl", limit=2000)
    lines = [describe_call(r) for r in rows[seen:]]
    return [x for x in lines if x], len(rows)


clip_lines = store.clip_lines


def target_yaml(target: dict) -> str:
    """The current YAML of what was held, so brAIn edits what is there
    rather than what it imagines. A part of the file is Morph's normalized
    form of it (ids and defaults filled in); the whole dashboard is the
    file's own text. Either way it is cut on a line with a marker."""
    kind, tid = target.get("kind"), target.get("id")
    if kind == "code":
        return ""  # a change to Morph's own module: the request names the files to read
    dash, _, text = store.read()
    import yaml
    rest = "Read /config/morph/dashboard.yaml for the rest."

    def dump(obj) -> str:
        return clip_lines(yaml.safe_dump(obj, sort_keys=False, allow_unicode=True), TARGET_CHARS, rest)
    for fl in dash.get("floors") or []:
        if kind == "floor" and fl.get("id") == tid:
            return dump(fl)
        for sec in fl.get("sections") or []:
            if kind == "section" and sec.get("id") == tid:
                return dump(sec)
            for g in sec.get("groups") or []:
                for c in g.get("cards") or []:
                    if kind == "card" and c.get("id") == tid:
                        return dump(c)
    if kind == "scenes":
        return dump({"scenes": dash.get("scenes") or []})
    if kind == "story":
        return dump({"story": dash.get("story", True)})
    if kind == "upcoming":
        return dump({"coming_up": dash.get("coming_up", True)})
    return clip_lines(text, TARGET_CHARS, rest)


def target_for(kind: str, tid: str) -> dict:
    """A target named the way the panel names a held thing: the card or
    section's own words and its path. A suggestion's Do it used to send
    the suggestion's TITLE as the card's name ("the card 'Move the hallway
    above…'"), which is a card that does not exist."""
    dash, _, _ = store.read()
    if kind == "card":
        for fl in dash.get("floors") or []:
            for sec in fl.get("sections") or []:
                for g in sec.get("groups") or []:
                    for c in g.get("cards") or []:
                        if c.get("id") == tid:
                            words = _cards({"floors": [{"sections": [sec]}]})[tid][0]
                            ent = c.get("entity") or ""
                            return {"kind": "card", "id": tid, "label": words, "entity": ent,
                                    "path": f"{fl.get('title')} › {sec.get('title')} › {words}"
                                            + (f" · {ent}" if ent else "")}
    if kind == "section":
        for fl in dash.get("floors") or []:
            for sec in fl.get("sections") or []:
                if sec.get("id") == tid:
                    return {"kind": "section", "id": tid, "label": sec.get("title") or "",
                            "path": f"{fl.get('title')} › {sec.get('title')}"}
    return {"kind": "dashboard", "path": "The whole dashboard"}


def card_type(card_id: str) -> str:
    """The held card's type, so an issue about it says which code to open."""
    dash, _, _ = store.read()
    for fl in dash.get("floors") or []:
        for sec in fl.get("sections") or []:
            for g in sec.get("groups") or []:
                for c in g.get("cards") or []:
                    if c.get("id") == card_id:
                        return str(c.get("type") or "")[:80]
    return ""


def lessons() -> str:
    """The household's rules, each marked with who wrote it, newest kept
    when they do not all fit — and the cut said, rather than sliced
    mid-word off the front of the file."""
    rows = learning.read_lessons(tagged=True)
    kept, size = [], 0
    for ln in reversed(rows):
        if size + len(ln) + 3 > LESSONS_CHARS:
            break
        kept.append(f"- {ln}")
        size += len(ln) + 3
    kept.reverse()
    cut = len(rows) - len(kept)
    if cut:
        kept.insert(0, f"(… {cut} older line{'' if cut == 1 else 's'} cut; Read /config/morph/LEARNED.md "
                       "for them.)")
    return "\n".join(kept)


# ------------------------------------------------------------- read back

from dashdiff import FLAG_WORDS, MAX_SHOWS, _cards, _sections, describe_change  # noqa: E402,F401 — re-exported


def read_back(base: str, commit: str) -> dict:
    """Read the dashboard back after a Tell and say what is true NOW.

    ``files`` is what the commit touched; ``unreadable`` is the parser's
    sentence when dashboard.yaml no longer reads (Morph goes on showing the
    last version that did, so nothing the change meant is on screen);
    ``dropped`` is what Morph could not use out of a file that does read;
    ``shows`` is the difference a person would see."""
    files = gitrepo.changed_files(commit) if commit else []
    out = {"files": files, "shows": [], "dropped": [], "unreadable": ""}
    if "dashboard.yaml" not in files:
        return out
    new, problems, _ = store.read()
    if problems and problems[0].startswith(store.UNREADABLE):
        out["unreadable"] = problems[0][:300]
        return out
    before = gitrepo.file_at(base, "dashboard.yaml") if base else None
    old, old_problems = store.load_text(before) if before is not None else (store.empty(), [])
    out["dropped"] = [p[:200] for p in problems if p not in old_problems][:6]
    out["shows"] = describe_change(old, new)
    return out


ORIGIN_LINES = {
    "panel": "",
    "suggestion": ("Origin: this came from a suggestion Morph made (“{note}”), and the person pressed Do it. "
                   "The words above are Morph's instruction, not theirs."),
    "question": "Origin: this is the answer the person pressed to your question “{note}”.",
    "undo": ("Origin: this is Undo. The person took back a change a Tell made; Morph has already put "
             "/config/morph back, and these words are Morph's."),
    "redo": ("Origin: Morph is asking, not a person. An update paused a change this house made to "
             "Morph's own code, and somebody pressed Make it again."),
}


def _history_lines(previous: list[dict], earlier: int) -> list[str]:
    """The conversation so far, each turn as what was ASKED, what brAIn
    SAID, and what Morph SAW when it read the files back — never Morph's
    own sentence passed off as brAIn's answer."""
    if not previous:
        return []
    out = ["EARLIER IN THIS CONVERSATION (oldest at the top):"]
    if earlier:
        out.append(f"({earlier} earlier turn{'' if earlier == 1 else 's'} not shown.)")
    for p in previous:
        said = p.get("summary")
        line = f"- asked “{p.get('text')}”"
        if said:
            line += f" → you said: “{said}”"
        shows = p.get("shows")
        if isinstance(shows, list) and shows:
            line += " → Morph read back: " + " ".join(str(x) for x in shows[:4])
        elif "shows" in p:
            line += " → Morph read back: nothing on the dashboard changed."
        elif not said and p.get("say"):
            line += f" → Morph said: {p.get('say')}"  # a turn from before the two were kept apart
        out.append(line)
    return out + [""]


def build_prompt(target: dict, words: str, current: str, previous: list[dict] | None = None,
                 *, shot=None, view: dict | None = None, scope: str = "ui", origin: str = "panel",
                 note: str = "", earlier: int = 0, context: str = "") -> str:
    """The prompt a Tell hands brAIn, built around ONE procedure: look at
    what was held, read the request, find where the thing lives, keep to the
    scope, follow the household's rules, change the files, answer. Each rule
    is said once; the details live in AGENTS.md, which brAIn reads as it
    needs, so a rule changed there is not contradicted here."""
    kind = target.get("kind") or "dashboard"
    origin = origin if origin in ORIGINS else "panel"
    path = str(target.get("path") or "")[:240]
    entity = str(target.get("entity") or "")[:120]
    what = what_of(target)
    view = view or {}
    lines = ["MORPH · a change request for this house's dashboard (Morph, in /config/morph).", ""]

    # 1. What to look at first — the one "first" in the prompt.
    if shot:
        lines += [
            f"LOOK FIRST: Read {shot} with your Read tool. It is a picture Morph took of {what} the moment",
            "the person asked" + (", after your last change in this conversation" if previous else "")
            + ". It is what they mean by “this”: identify in the picture what the request is about, and",
            "change only that. Say in `saw` what it is.",
        ]
        if view.get("text"):
            lines.append(f"The same thing as text: {view['text']}")
        lines.append("")
    elif view:
        why = view.get("error") or "the panel could not draw it"
        lines += [f"Morph could not take a picture of {what} this time ({why}).",
                  "What the panel showed, as text"
                  + (f" ({view['w']}×{view['h']} px)" if view.get("w") and view.get("h") else "")
                  + f": {view.get('text') or '(nothing readable)'}", ""]

    # 2. The request.
    if context:
        lines += ["Sent with the request (context, not the person's words):", context, ""]
    lines += ["THE REQUEST", f"Asked: “{words}”", f"Target: {what}"]
    if path:
        lines.append(f"Where: {path}")
    if entity:
        lines.append(f"Entity: {entity}")
    said = ORIGIN_LINES[origin].format(note=str(note or "")[:200])
    if said:
        lines.append(said)
    elif not shot and not view:
        lines.append("There is no picture: nothing on screen was held for this request.")
    lines.append("")
    lines += _history_lines(previous or [], earlier)

    # 3. Where the thing lives — not for Undo's follow-up, which is about
    # Home Assistant and must not be handed the dashboard to "fix".
    if origin != "undo":
        lines.append("WHERE THIS LIVES")
        lines.append(WHERE_LIVES.get(kind, WHERE_LIVES["dashboard"]).format(shipped=paths.SHIPPED))
        if current.strip():
            form = ("the file as it is" if kind == "dashboard" else
                    "Morph's normalized form of it (ids and defaults filled in); edit the real file, "
                    "keeping its own layout")
            lines += [f"This is {form}:", "```yaml", current.strip(), "```"]
        lines.append("")

    # 4. Scope.
    if scope == "house":
        lines += [
            "Scope: this request is about Home Assistant itself, as well as the dashboard. You may change",
            "automations, scripts, scenes, helpers and entities as it asks. protected_entities still holds.",
            "",
        ]
    else:
        lines += [
            "Scope: everything the request needs. You are brAIn with the chat's reach. If the result needs",
            "Home Assistant to change too (a template sensor the card reads, an automation or script a",
            "button runs, a helper, a renamed entity), make those changes as well, check them, and list each",
            "in home_assistant so Undo can hand it back. Never stop at the dashboard half. Leave alone",
            "anything the request does not need. protected_entities still holds. Showing a protected entity on the",
            "dashboard is fine; acting on one is not.",
            "",
        ]

    # 5. The household's rules.
    learned = lessons()
    if learned.strip():
        lines += ["HOUSEHOLD RULES (/config/morph/LEARNED.md; follow them unless the request says otherwise.",
                  "A line marked (you) is one the household wrote itself):", learned.strip(), ""]

    # 6. How.
    lines += [
        "HOW",
        "- Make the change now, by writing the files: the person pressed Send and is watching, and",
        "  describing a change in your answer changes nothing. A Morph dashboard is",
        "  /config/morph/dashboard.yaml, never a Lovelace dashboard.",
        "- Make the smallest change that does what was asked.",
        "- Never run git in /config/morph: Morph commits your change as one commit when you answer, and",
        "  that commit is what Undo reverts.",
        "- Morph then reads /config/morph back and tells the person what is different on screen, so a",
        "  summary that claims more than the files carry is shown to be wrong.",
        "- Nothing about Morph is out of reach. If dashboard.yaml cannot express it, change Morph's own",
        f"  code: copy the module from {paths.SHIPPED}/ to /config/morph/frontend/ and edit the copy.",
        "  Never say you cannot change Morph's code.",
        "- Use `question` only for a choice that is the person's to make (AGENTS.md, “When to ask",
        "  instead of act”); otherwise act.",
        "- Everything else — the schema, the card types, custom cards, Morph's own code, checking your",
        "  change — is in /config/morph/AGENTS.md. Read the sections you need.",
        "",
        "ANSWER with the JSON object the schema describes (each field's description says when):",
        "summary, files, home_assistant, and when they apply saw, needs_person, question, lesson,",
        "code_issue and facts. What you learned about the HOUSE goes to brAIn's memory:",
        "put it in `facts`, because remember_fact is refused in a task run like this one.",
    ]
    return "\n".join(lines)


def start(target: dict, words: str, previous_id: str = "", *, shot: str = "",
          view: dict | None = None, scope: str = "ui", origin: str = "panel", note: str = "",
          person_words: str | None = None, context: str = "") -> dict:
    """Begin a tell. Returns its state; the work continues in a task.

    ``scope`` is never read off the wire: a request from the panel is a
    dashboard request whatever its target says. "house" is passed by Undo's
    follow-up (which puts back a house change a Tell made) and by an answer
    to brAIn's question whose button said it changes Home Assistant.

    ``person_words`` rides beside the prompt to brAIn, which judges an
    action against what the PERSON asked rather than against everything
    Morph wrote around it: the words as typed, the suggestion text a person
    approved, the option they pressed, or the sentence Morph wrote for
    Undo. A redo nobody typed carries none."""
    # What a person (or a card) sends fits in MAX_WORDS with any context it
    # sent beside it; what Morph writes (a merge of every paused copy) names
    # files and paths and is allowed more room. The context gives way, never
    # the words, and a cut is said in the text (wording.py).
    fitted = wording.fit(words, context, cap=MAX_WORDS if origin == "panel" else MAX_WRITTEN)
    words, context = fitted["words"], fitted["context"]
    if not words:
        return {"error": "Say what should change."}
    if not brain.available():
        return {"error": brain.status()["sentence"]}
    origin = origin if origin in ORIGINS else "panel"
    target = {k: str(v)[:240] for k, v in (target or {}).items()
              if k in ("kind", "id", "label", "path", "entity")}
    previous: list[dict] = []
    earlier = 0
    prev = read_state(previous_id) if previous_id else None
    if prev:
        turn = {"text": prev.get("text"), "summary": prev.get("summary") or ""}
        if "shows" in prev:
            turn["shows"] = list(prev.get("shows") or [])[:4]
        if not turn["summary"] and prev.get("say"):
            turn["say"] = prev.get("say")
        previous = list(prev.get("history") or []) + [turn]
        earlier = int(prev.get("earlier") or 0) + max(0, len(previous) - HISTORY_TURNS)
    tid = brain.new_id("morph")
    state = {"id": tid, "text": words, "target": target, "phase": "sending", "steps": [],
             "started": time.time(), "history": previous[-HISTORY_TURNS:], "earlier": earlier,
             "scope": scope if scope in SCOPES else "ui", "view": clean_view(view),
             "origin": origin, "note": str(note or "")[:300], "context": context,
             "person_words": person_words if person_words is not None
             else "" if origin == "redo" else words}
    if target.get("kind") == "code" and target.get("id") == morphcode.MERGE_ALL:
        # Merge all: the copies paused NOW are this merge's, so the answer
        # to a question about one of them continues with what is left.
        state["merge"] = morphcode.paused()
    picture = shot_path(shot)
    if picture and origin != "undo":
        state["shot"] = shot
    _save(state)
    _RUNNING[tid] = asyncio.get_running_loop().create_task(_run(state))
    return state


def activity() -> list[dict]:
    """What brAIn is doing for Morph right now, for the strip at the top of
    the dashboard: the panel that started a tell may have been closed."""
    out = []
    for tid in list(_RUNNING):
        st = read_state(tid) or {}
        if st.get("phase") in ("done", "failed", None):
            continue
        steps = st.get("steps") or []
        target = st.get("target") or {}
        out.append({"id": tid, "text": st.get("text", "")[:200], "phase": st.get("phase"),
                    "kind": target.get("kind", ""), "target": target.get("id", ""),
                    "label": target.get("label", ""), "path": target.get("path", ""),
                    "step": steps[-1]["t"] if steps else "", "started": st.get("started")})
    return out


async def _run(state: dict) -> None:
    tid = state["id"]
    try:
        await asyncio.to_thread(gitrepo.commit_pending)
        base = await asyncio.to_thread(gitrepo.head)
        target = state["target"]
        origin = state.get("origin") or "panel"
        where = target.get("path") or what_of(target)
        _step(state, f"Reading {where}")
        # Undo's follow-up is about Home Assistant; handing it the dashboard
        # invites it to "fix" a file Morph has just put back.
        current = "" if origin == "undo" else await asyncio.to_thread(target_yaml, target)
        if target.get("kind") == "card":
            state["card_type"] = await asyncio.to_thread(card_type, target.get("id") or "")
        picture = shot_path(state.get("shot") or "")
        if picture:
            _step(state, "Took a picture of it for brAIn")
        elif state.get("view"):
            _step(state, "No picture this time — sending what the panel showed as text"
                  + (f" ({state['view']['error']})" if (state.get("view") or {}).get("error") else ""),
                  "bad")
        prompt = build_prompt(target, state["text"], current, state.get("history"),
                              shot=picture, view=state.get("view"), scope=state.get("scope", "ui"),
                              origin=origin, note=state.get("note") or "",
                              earlier=int(state.get("earlier") or 0),
                              context=state.get("context") or "")
        state["payload"] = prompt
        model = settings.load().get("tell_model") or ""
        await asyncio.to_thread(brain.submit, tid, prompt, schema=RESULT_SCHEMA,
                                tools="full", timeout=TIMEOUT_S, model=model,
                                person_words=state.get("person_words", state["text"]))
        state["phase"] = "waiting"
        _step(state, f"Handed to brAIn as task {tid}")
        deadline = time.time() + brain.CLAIM_GRACE_S
        while not brain.claimed(tid):
            if time.time() > deadline:
                brain.withdraw(tid)
                state["phase"] = "failed"
                state["say"] = ("Nothing picked the request up. brAIn's Automation integration "
                                "has to be on for Morph to reach it.")
                _step(state, "Nothing is listening", "bad")
                return
            await asyncio.sleep(brain.POLL_S)
        state["phase"] = "working"
        _step(state, "brAIn is on it")
        deadline = time.time() + TIMEOUT_S + 120
        res = None
        seen = 0
        while res is None:
            if time.time() > deadline:
                state["phase"] = "failed"
                state["say"] = "brAIn did not answer in time. Anything it finished is still committed."
                break
            seen = await asyncio.to_thread(_follow, state, seen)
            res = await asyncio.to_thread(brain.result, tid)
            if res is None:
                await asyncio.sleep(brain.POLL_S)
        await asyncio.to_thread(_follow, state, seen)
        data, text, error = brain.answer_data(res) if res else (None, "", "timeout")
        summary = wording.clip((data or {}).get("summary") or text, 1200)
        asked = clean_question((data or {}).get("question"))
        if target.get("kind") == "code" and not error and data is not None and state.get("phase") != "failed":
            # brAIn was asked to make this house's change work on the Morph
            # installed now and answered: whether it edited a copy or judged
            # it already fits, that copy is in use again. Recorded before
            # the commit so Undo takes the records with the copies — one
            # commit for a whole Merge all. A file still WAITING on the
            # person's answer to `question` (the update rewrote the code the
            # change was in, and brAIn would not guess) stays paused until
            # they pick; a question with no `waiting` list leaves every file
            # paused, because nothing about which one it was is guessed.
            names = state.get("merge") or [target.get("id") or ""]
            waiting = (data or {}).get("waiting")
            if asked and not isinstance(waiting, list):
                accept = []
            else:
                held = {str(w).strip() for w in (waiting or []) if isinstance(w, str)}
                accept = [n for n in names if n not in held]
            done = [n for n in accept if await asyncio.to_thread(morphcode.accept, n)]
            if done:
                state["merged"] = done
                _step(state, "Recorded " + (f"{done[0]} as made" if len(done) == 1
                                            else f"{len(done)} changes as made") + " for this Morph", "good")
            if state.get("merge") and len(done) < len(names):
                state["still_paused"] = [n for n in names if n not in done]
        commit = await asyncio.to_thread(
            gitrepo.commit,
            f"brAIn: {summary or state['text']}"[:200] + f"\n\nAsked: “{state['text']}”\nTask: {tid}",
            "brain")
        if commit:
            state["commit"] = commit
            files = await asyncio.to_thread(gitrepo.changed_files, commit)
            _step(state, "Changed " + ", ".join(files[:6]), "good")
        state["summary"] = summary
        house = house_changes(data)
        if house:
            state["house"] = house
            _step(state, "In Home Assistant: " + "; ".join(house[:4]), "good")
        # Read the dashboard back, and publish it now rather than on the
        # watcher's next pass, so what the person is told and what their
        # screen shows are the same file (house report: "it says it's
        # making changes, but none of them are applied").
        back = await asyncio.to_thread(read_back, base, commit)
        if ON_PUBLISH:
            mirror = await asyncio.to_thread(ON_PUBLISH)
            if isinstance(mirror, dict) and mirror.get("revision"):
                state["revision"] = mirror["revision"]
        state["shows"] = back["shows"]
        if back["dropped"]:
            state["dropped"] = back["dropped"]
        if any(f.startswith("cards/") for f in back["files"]):
            state["cards"] = True
        # The phase is decided now and written only with the final save: a
        # state file reading "done" is the panel's signal that everything
        # after this (the lesson, the outcome) has landed too.
        phase, say = state.get("phase"), state.get("say")
        if error and phase != "failed":
            phase, say = "failed", summary or f"brAIn could not finish this ({error})."
        elif phase != "failed":
            phase, say = outcome(state, summary, commit, back)
        if state.get("unchanged") or back["unreadable"]:
            _step(state, "Read the dashboard back: " + ("it does not read" if back["unreadable"]
                                                          else "nothing on it changed"), "bad")
        elif back["shows"]:
            _step(state, "Read the dashboard back: " + str(len(back["shows"])) + " change"
                  + ("" if len(back["shows"]) == 1 else "s") + " on screen", "good")
        state["needs_person"] = str((data or {}).get("needs_person") or "")[:600]
        if asked:
            state["question"] = asked
        state["saw"] = str((data or {}).get("saw") or "")[:400]
        issue = (data or {}).get("code_issue")
        code_files = [f.split("/", 1)[1] for f in (await asyncio.to_thread(gitrepo.changed_files, commit) if commit else [])
                      if f.startswith("frontend/") and f.endswith(".js") and f.count("/") == 1]
        if code_files:
            # Morph changed itself: the page has to reload to run the new
            # code, and the person is asked whether Morph should have it for
            # everybody — whether or not brAIn remembered to say so.
            state["code"] = code_files
            _step(state, "Changed Morph's own " + ", ".join(code_files[:4]), "good")
        if target.get("kind") == "code":
            # Making a paused change again (or answering its merge question)
            # re-makes a change this house already has; it was offered as an
            # issue when it was first made, and asking again would file it
            # twice.
            pass
        elif isinstance(issue, dict) and str(issue.get("title") or "").strip():
            state["code_issue"] = {"title": str(issue["title"]).strip()[:140],
                                   "detail": str(issue.get("detail") or "").strip()[:1500]}
        elif code_files:
            state["code_issue"] = {"title": (summary or state["text"])[:140],
                                   "detail": "brAIn changed Morph's own " + ", ".join(code_files) + " for this."}
        if state.get("code_issue"):
            state["issue"] = "asked"
        state["phase"], state["say"] = phase, say
        state["reload"] = bool(commit) or bool((data or {}).get("reload"))
        filed = await asyncio.to_thread(queue_facts, (data or {}).get("facts"), tid)
        if filed:
            state["facts_filed"] = filed
            _step(state, f"Queued {filed} fact{'' if filed == 1 else 's'} about the house for brAIn's memory", "good")
        lesson = str((data or {}).get("lesson") or "").strip()
        # A lesson from a run that failed taught nothing anybody saw work.
        if lesson and state["phase"] != "failed":
            await asyncio.to_thread(learning.add_lesson, lesson, "tell")
        await asyncio.to_thread(learning.record_outcome, {
            "kind": "tell", "id": tid, "text": state["text"], "target": target.get("kind"),
            "commit": commit, "base": base, "phase": state["phase"], "error": error,
            "needs_person": bool(state["needs_person"]), "at": time.time()})
        # A run that failed (signed out, slow, out of turns) is brAIn's
        # weather, not a fault in Morph's code. What IS Morph's is an answer
        # that came back and could not be read: that is the contract between
        # the two failing, and nobody would report it by hand.
        if res and not error and data is None:
            await asyncio.to_thread(
                devloop.note_fault, "Tell", "brAIn's answer to a request could not be read",
                f"Target: {target.get('kind')}\nAnswer: {text[:800]}")
        _save(state)
    except Exception as exc:  # noqa: BLE001 — a tell must always end in a sentence
        log.exception("tell %s failed", tid)
        state["phase"] = "failed"
        state["say"] = f"Morph could not finish handing this over: {exc}"
        _save(state)
    finally:
        _RUNNING.pop(tid, None)


QUESTION_CHARS = 300
LABEL_CHARS = 60
REQUEST_CHARS = 1200


def clean_question(q) -> dict | None:
    """brAIn's question as the panel may show it: two or three buttons,
    each carrying the request it sends. Anything that is not that shape is
    no question."""
    if not isinstance(q, dict):
        return None
    text = str(q.get("text") or "").strip()[:QUESTION_CHARS]
    opts = []
    for o in q.get("options") or []:
        if not isinstance(o, dict):
            continue
        label = str(o.get("label") or "").strip()[:LABEL_CHARS]
        request = wording.clip(o.get("request"), REQUEST_CHARS)
        if label and request:
            opts.append({"label": label, "request": request, "home_assistant": o.get("home_assistant") is True})
    if not text or not 2 <= len(opts) <= 3:
        return None
    return {"text": text, "options": opts}


def answer_question(tid: str, choice) -> dict:
    """The person pressed one of the answers brAIn offered. The next tell
    is started from the option STORED with the tell, never from words off
    the wire, and it may change Home Assistant only when that option said
    so on the button the person pressed."""
    state = read_state(tid)
    if not state or not state.get("question"):
        return {"error": "That question is gone."}
    if state.get("answered") is not None:
        return {"error": "That question was already answered."}
    opts = state["question"]["options"]
    try:
        i = int(choice)
    except (TypeError, ValueError):
        return {"error": "That is not one of the answers."}
    if not 0 <= i < len(opts):
        return {"error": "That is not one of the answers."}
    opt = opts[i]
    target = state.get("target") or {}
    words = opt["request"]
    if target.get("kind") == "code" and target.get("id") == morphcode.MERGE_ALL:
        # The answer settles one conflict; the same merge carries on with
        # every copy still paused, so one press of Merge all ends with
        # nothing left to press but the conflicts themselves.
        rest = morphcode.paused()
        if rest:
            words += ("\n\nThen carry on with the rest of this merge.\n"
                      + morphcode.redo_all_words(rest, os.environ.get("ADDON_VERSION", "dev")))
    st = start(target, words, tid,
               scope="house" if opt.get("home_assistant") else "ui",
               origin="question", note=state["question"].get("text") or "",
               person_words=opt["request"])
    if "error" not in st:
        state["answered"] = i
        _save(state)
    return st


MAX_FACTS = 6
FACT_CHARS = 400
# brAIn's facts store keeps `person:` subjects (facts_store.KEPT_PREFIXES),
# so a fact about who uses a room is filed under that person.
SUBJECT_RE = re.compile(r"^(?:[a-z_]+\.[a-z0-9_]+|area:[a-z0-9_]+|person:[a-z0-9_]+|house)$")
CONFIDENCES = ("high", "medium")


def queue_facts(facts, tid: str) -> int:
    """File what a Tell learned about the house in brAIn's memory inbox,
    the way remember_fact does (one JSONL file, one line per fact). A Tell
    is a task run, where brAIn's action gate refuses remember_fact because
    nobody asked to remember anything, so the facts ride in the answer and
    the consolidator still decides what is worth keeping. Nothing is
    written when brAIn's memory folder is not there."""
    if not isinstance(facts, list) or not facts:
        return 0
    memory = paths.BRAIN_SHARED / "memory"
    if not memory.is_dir():
        return 0
    now = int(time.time())
    rows = []
    for f in facts[:MAX_FACTS]:
        if not isinstance(f, dict):
            continue
        text = " ".join(str(f.get("fact") or "").split())[:FACT_CHARS]
        if not text:
            continue
        # The model says how sure it is; one that does not say is not
        # promoted to "high" on Morph's word.
        conf = str(f.get("confidence") or "").strip().lower()
        row = {"ts": now, "source": "morph", "fact": text,
               "confidence": conf if conf in CONFIDENCES else "medium", "run_id": tid}
        subject = str(f.get("subject") or "").strip().lower()
        if SUBJECT_RE.match(subject):
            row["subject"] = subject
        rows.append(row)
    if not rows:
        return 0
    inbox = memory / "inbox"
    try:
        inbox.mkdir(exist_ok=True)
        path = inbox / f"{now}-morph-{tid[-10:]}.jsonl"
        paths.write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        paths.hand_to_brain(path)
    except OSError as exc:
        log.warning("could not queue %d fact(s) for brAIn: %s", len(rows), exc)
        return 0
    return len(rows)


def _morph_file(line: str) -> bool:
    """Whether one of an older answer's "changed" lines is a file in
    /config/morph rather than something in Home Assistant. Only a fallback
    now: an answer in today's schema says which is which itself."""
    low = line.lower().strip()
    return ("morph" in low or low.startswith(("dashboard.yaml", "cards/", "frontend/", "learned.md"))
            or low in ("dashboard", "the dashboard"))


def house_changes(data) -> list[str]:
    """What a Tell changed in Home Assistant itself — the list Undo hands
    back to brAIn. Read from ``home_assistant`` when the answer has it;
    an answer with only the old mixed ``changed`` list is sorted by
    `_morph_file`, which guesses from the words."""
    data = data if isinstance(data, dict) else {}
    if isinstance(data.get("home_assistant"), list):
        rows = data["home_assistant"]
    else:
        rows = [c for c in (data.get("changed") or []) if isinstance(c, str) and not _morph_file(c)]
    return [str(x).strip()[:200] for x in rows if str(x).strip()][:20]


def outcome(state: dict, summary: str, commit: str, back: dict) -> tuple[str, str]:
    """The phase and the sentence a finished Tell ends on, decided from
    what the files say rather than from what brAIn said it did. The
    sentence is never "done" over a dashboard that did not change."""
    said = f" brAIn said: “{summary}”" if summary else ""
    if back["unreadable"]:
        return "failed", ("Not applied: " + back["unreadable"] + ". Morph is still showing the "
                          "dashboard as it was. Undo puts the file back, or tell brAIn to fix it.")
    morph_files = [f for f in back["files"] if f != "LEARNED.md"]
    if not morph_files and not state.get("house"):
        state["unchanged"] = True
        if state.get("scope") == "house":
            return "done", summary or "brAIn answered without changing anything."
        if (state.get("target") or {}).get("kind") == "code":
            return "done", "brAIn changed nothing in Morph's code." + said
        return "done", "Nothing on the dashboard changed." + said
    if morph_files == ["dashboard.yaml"] and not back["shows"]:
        state["unchanged"] = True
        return "done", "brAIn rewrote dashboard.yaml, but nothing on the dashboard is different." + said
    text = summary or "Done."
    if back["dropped"]:
        text += " Morph could not use part of it: " + "; ".join(back["dropped"][:3]) + "."
    return "done", text


def _follow(state: dict, seen: int) -> int:
    """Copy brAIn's new progress lines onto the tell as steps, dropping a
    line that only repeats the one before it."""
    lines, seen = progress(state["id"], seen)
    if not lines:
        return seen
    steps = state.setdefault("steps", [])
    for line in lines:
        if steps and steps[-1].get("t") == line:
            continue
        steps.append({"t": line, "tone": "", "at": time.time(), "brain": True})
    if len(steps) > MAX_STEPS:
        # The first few say what was asked and handed over; keep those and
        # the newest, and count what was folded between them.
        head, tail = steps[:4], steps[-(MAX_STEPS - 5):]
        folded = int(state.get("folded") or 0) + len(steps) - len(head) - len(tail)
        state["folded"] = folded
        steps[:] = head + tail
    _save(state)
    return seen


def answer_issue(tid: str, verb: str) -> dict:
    """The person's answer to "send this as an issue?". Yes files it in
    Morph's development-loop ledger (and so on to brAIn's loop, which still
    holds a new report for review); No is remembered so it is not asked
    again in this conversation."""
    state = read_state(tid)
    if not state or not state.get("code_issue"):
        return {"ok": False, "error": "There is no issue to send for this one."}
    if verb == "no":
        state["issue"] = "declined"
        _save(state)
        learning.record_outcome({"kind": "issue", "id": tid, "verb": "no", "at": time.time()})
        return {"ok": True}
    if verb != "send":
        return {"ok": False, "error": "Unknown answer."}
    if state.get("issue") == "sent":
        return {"ok": True, "already": True}
    if not settings.load()["report_code_issues"]:
        return {"ok": False, "error": "“Report Morph’s own problems” is off in Morph's Settings, "
                                      "so nothing reaches brAIn's development loop. Turn it on and "
                                      "press Send again."}
    issue = state["code_issue"]
    target = state.get("target") or {}
    detail = "\n".join([
        "Somebody asked for this in Morph's editor and chose to send it as an issue.",
        "",
        f"Asked: {state.get('text')}",
        f"About: {what_of(target)}"
        + (f" (card type {state['card_type']})" if state.get("card_type") else ""),
        f"What brAIn saw: {state['saw']}" if state.get("saw") else "",
        f"What brAIn did meanwhile: {state.get('say') or ''}",
        "",
        "What Morph would need:",
        issue.get("detail") or "(not said)",
    ])
    if state.get("code") and state.get("commit"):
        # The change this house made to Morph's own code, as a patch, so it
        # can be made part of Morph for everybody.
        # Not the kept originals under frontend/.base/: they are Morph's own
        # file, and a whole module in the patch buries the change.
        patch = gitrepo.diff(state["commit"], "frontend/", limit=3600, exclude="frontend/.base/")
        if patch.strip():
            detail += ("\n\nThe change, made in /config/morph/frontend/ (a copy of Morph's own "
                       "custom_components/morph/frontend/):\n```diff\n" + patch + "\n```")
    devloop.note_fault("Tell", issue["title"], detail, source="person")
    state["issue"] = "sent"
    _save(state)
    learning.record_outcome({"kind": "issue", "id": tid, "verb": "send", "title": issue["title"],
                             "at": time.time()})
    return {"ok": True}


def undo(tid: str) -> dict:
    """Put back what one tell did. The dashboard half is a git revert, made
    here and exact. The house half (an automation brAIn wrote, a helper it
    made) is brAIn's to reverse — its edit hook snapshotted every file — so
    it goes back to brAIn as a request naming what to put back, and the
    answer lands in the same place as any other tell."""
    state = read_state(tid)
    if not state or not (state.get("commit") or state.get("house")):
        return {"ok": False, "error": "There is nothing to put back for this one."}
    out: dict = {"ok": True}
    if state.get("commit") and not state.get("undone"):
        ok, detail = gitrepo.revert(state["commit"],
                                    f"Undid brAIn: {state.get('say') or state.get('text')}"[:200])
        if not ok:
            return {"ok": False, "error": detail}
        state["undone"] = detail
        out["commit"] = detail
    if state.get("house") and not state.get("house_undo"):
        follow = start({"kind": "dashboard", "path": "Putting back Home Assistant changes"},
                       "Put back the Home Assistant changes you made for Morph task "
                       f"{tid} (asked: “{state.get('text')}”). You changed: "
                       + "; ".join(state["house"]) + ". Use brain undo for files you edited; "
                       "reverse anything else (a helper, an entity) directly. Do not touch "
                       "/config/morph — Morph has already put the dashboard back.", scope="house",
                       origin="undo")
        if follow.get("id"):
            state["house_undo"] = follow["id"]
            out["follow"] = follow["id"]
    _save(state)
    learning.record_outcome({"kind": "undo", "id": tid, "commit": state.get("commit"),
                             "at": time.time()})
    return out


def prune(max_age_s: int = 7 * 86400) -> None:
    now = time.time()
    for pattern, folder in (("*.json", paths.TELLS), ("*.png", paths.SHOTS)):
        try:
            for p in folder.glob(pattern):
                if now - p.stat().st_mtime > max_age_s:
                    os.unlink(p)
        except OSError:
            pass  # an old file another prune already removed; nothing to tidy


def json_payload(state: dict) -> str:
    return json.dumps({"id": state.get("id"), "prompt": state.get("payload", ""),
                       "person_words": state.get("person_words", state.get("text", "")),
                       "tools": "full", "schema": RESULT_SCHEMA}, indent=2)
