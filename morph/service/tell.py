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
* **Morph's own code is an issue somebody chooses to send.** When the
  request needs Morph itself changed, the answer carries ``code_issue`` and
  the panel asks whether to send it; nothing is filed until they say yes.

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
import paths
import settings
import store

log = logging.getLogger("morph.tell")

TIMEOUT_S = 900
MAX_WORDS = 4000
LESSONS_CHARS = 4000
MAX_STEPS = 60
VIEW_CHARS = 1500
SHOT_ID = re.compile(r"^[a-f0-9]{32}$")
SCOPES = ("ui", "house")

RESULT_SCHEMA = {
    "type": "object",
    "required": ["summary", "changed", "reload"],
    "properties": {
        "summary": {"type": "string", "description": "One or two sentences a person reads: what you did."},
        "changed": {"type": "array", "items": {"type": "string"},
                    "description": "Each file or Home Assistant thing you changed, one per line."},
        "reload": {"type": "boolean", "description": "True when the dashboard should reload."},
        "needs_person": {"type": "string",
                         "description": "Only when something is left that a person has to do by hand."},
        "lesson": {"type": "string",
                   "description": "Optional: one durable lesson about how this household wants its "
                                  "DASHBOARD to look or behave. Never a fact about the house."},
        "saw": {"type": "string",
                "description": "One sentence: what in the screenshot this request is about."},
        "code_issue": {
            "type": "object", "required": ["title", "detail"],
            "properties": {
                "title": {"type": "string", "description": "Under 90 characters: what Morph cannot do."},
                "detail": {"type": "string",
                           "description": "What Morph's code would need, and what you did instead."},
            },
            "description": "Only when doing this properly needs Morph's OWN code changed (a built-in "
                           "card type, the layout, the panel), not dashboard.yaml or a cards/*.js "
                           "file. Morph asks the person whether to send it as an issue.",
        },
    },
}

KIND_WORDS = {
    "card": "card", "section": "section", "floor": "floor heading", "story": "story line",
    "upcoming": "Coming up timeline", "scenes": "house-wide scenes line", "dashboard": "whole dashboard",
}

_RUNNING: dict[str, asyncio.Task] = {}


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


def target_yaml(target: dict) -> str:
    """The current YAML of what was held, so brAIn edits what is there
    rather than what it imagines."""
    dash, _, text = store.read()
    kind, tid = target.get("kind"), target.get("id")
    import yaml
    for fl in dash.get("floors") or []:
        if kind == "floor" and fl.get("id") == tid:
            return yaml.safe_dump(fl, sort_keys=False, allow_unicode=True)
        for sec in fl.get("sections") or []:
            if kind == "section" and sec.get("id") == tid:
                return yaml.safe_dump(sec, sort_keys=False, allow_unicode=True)
            for g in sec.get("groups") or []:
                for c in g.get("cards") or []:
                    if kind == "card" and c.get("id") == tid:
                        return yaml.safe_dump(c, sort_keys=False, allow_unicode=True)
    if kind == "scenes":
        return yaml.safe_dump({"scenes": dash.get("scenes") or []}, sort_keys=False)
    if kind in ("story", "upcoming"):
        return yaml.safe_dump({kind if kind == "story" else "coming_up":
                               dash.get("story" if kind == "story" else "coming_up")})
    return text[:20000]


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
    try:
        text = paths.LEARNED.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[-LESSONS_CHARS:]


def build_prompt(target: dict, words: str, current: str, previous: list[dict] | None = None,
                 *, shot=None, view: dict | None = None, scope: str = "ui") -> str:
    kind = target.get("kind") or "dashboard"
    label = str(target.get("label") or "")[:120]
    path = str(target.get("path") or "")[:240]
    entity = str(target.get("entity") or "")[:120]
    what = f"the {KIND_WORDS.get(kind, kind)}" + (f" “{label}”" if label else "")
    lines = [
        "MORPH · a change request from the dashboard editor.",
        "",
        "Morph is this house's dashboard. It lives in /config/morph: dashboard.yaml is the",
        "dashboard, cards/ holds custom card code, AGENTS.md is how it works (READ IT FIRST),",
        "and LEARNED.md is what this household has taught Morph about how it wants things.",
        "",
        f"Target: {what}",
    ]
    if path:
        lines.append(f"Where: {path}")
    if entity:
        lines.append(f"Entity: {entity}")
    lines += ["", f"Asked: “{words}”", ""]
    view = view or {}
    if shot:
        lines += [
            "WHAT THEY ARE LOOKING AT — do this before anything else:",
            f"Read {shot} with your Read tool. It is a screenshot Morph took of {what} at the",
            "moment they asked" + (", AFTER your last change in this conversation" if previous else "")
            + ". It is what they mean by “this”; the YAML below says what is configured, not",
            "what it looks like. Fix what the picture shows is wrong, and say in `saw` what in the",
            "picture the request is about.",
        ]
        if view.get("text"):
            lines.append(f"The same {KIND_WORDS.get(kind, kind)} as text: {view['text']}")
        lines.append("")
    elif not view:
        lines += ["This request did not come from something held on screen (a suggestion, or an",
                  "Undo), so there is no picture of it.", ""]
    else:
        why = view.get("error") or "the panel could not draw it"
        lines += [f"Morph could not take a picture of {what} this time ({why}).",
                  "What the panel showed, as text"
                  + (f" ({view['w']}×{view['h']} px)" if view.get("w") and view.get("h") else "")
                  + f": {view.get('text') or '(nothing readable)'}", ""]
    if previous:
        lines.append("Earlier in this same conversation about this target:")
        for p in previous[-4:]:
            lines.append(f"- asked “{p.get('text')}” → you answered: {p.get('say')}")
        lines.append("")
    lines += ["Current YAML of the target:", "```yaml", current.strip()[:12000], "```", ""]
    learned = lessons()
    if learned.strip():
        lines += ["What this household has taught Morph (follow it unless the request says otherwise):",
                  learned.strip(), ""]
    lines += ["Do it now — the person pressed Send and is watching. Do not ask for confirmation and",
              "do not only describe the change.", ""]
    if scope == "house":
        lines += [
            "Scope: this request is about Home Assistant itself, as well as the dashboard. You may",
            "change automations, scripts, scenes, helpers and entities as it asks.",
        ]
    else:
        lines += [
            "Scope: THE DASHBOARD ONLY. Change /config/morph/dashboard.yaml and /config/morph/cards/*.js",
            "(registered in dashboard.yaml as AGENTS.md describes). Look at Home Assistant with your",
            "read tools as much as you need to get the dashboard right, but do NOT change Home",
            "Assistant itself — entity ids, names, areas, automations, scripts, scenes, helpers,",
            "integrations — unless the request asks for that change in Home Assistant in so many",
            "words (“change the entity ID”, “rename the device”, “make an automation that…”).",
            "If doing this properly would need a Home Assistant change they did not ask for, do the",
            "dashboard part and say in needs_person exactly what would have to change in Home",
            "Assistant, so they can ask for it.",
        ]
    lines += [
        "",
        "Rules that still hold:",
        "- Never run git in /config/morph: Morph commits your change the moment you answer, and that",
        "  commit is what the person's Undo reverts.",
        "- protected_entities still applies; if the request needs one, say so in needs_person.",
        "- Keep dashboard.yaml valid YAML in Morph's schema (AGENTS.md); an unknown card type is",
        "  passed to Lovelace as-is, so a Lovelace card's YAML is always a valid card.",
        "- Prefer the smallest change that does what was asked.",
        "- What you learn about the HOUSE (what a device is, where it is, who uses it) is brAIn's",
        "  memory: record it with remember_fact. LEARNED.md and `lesson` are only for how this",
        "  household wants its DASHBOARD to look and behave.",
        "- If doing this properly needs Morph's OWN code changed — a built-in card type that is",
        "  wrong or cannot do this, the layout, the panel — and not dashboard.yaml or a cards/*.js",
        "  file, fill code_issue and do the best you can meanwhile. Do not file anything yourself:",
        "  Morph asks the person whether to send it.",
        "",
        "Answer with the JSON object the schema describes: summary (what you did, for the person),",
        "saw, changed, reload (true if the dashboard changed), needs_person only if something is",
        "left for a person, lesson only if the request taught a durable preference about this",
        "dashboard, and code_issue only as described above.",
    ]
    return "\n".join(lines)


def start(target: dict, words: str, previous_id: str = "", *, shot: str = "",
          view: dict | None = None, scope: str = "ui") -> dict:
    """Begin a tell. Returns its state; the work continues in a task.

    ``scope`` is never read off the wire: a request from the panel is a
    dashboard request whatever its target says, and only Undo's follow-up
    (which puts back a house change a Tell made) passes "house"."""
    words = str(words or "").strip()[:MAX_WORDS]
    if not words:
        return {"error": "Say what should change."}
    if not brain.available():
        return {"error": brain.status()["sentence"]}
    target = {k: str(v)[:240] for k, v in (target or {}).items()
              if k in ("kind", "id", "label", "path", "entity")}
    previous: list[dict] = []
    prev = read_state(previous_id) if previous_id else None
    if prev:
        previous = list(prev.get("history") or []) + [{"text": prev.get("text"), "say": prev.get("say")}]
    tid = brain.new_id("morph")
    state = {"id": tid, "text": words, "target": target, "phase": "sending", "steps": [],
             "started": time.time(), "history": previous[-6:],
             "scope": scope if scope in SCOPES else "ui", "view": clean_view(view)}
    picture = shot_path(shot)
    if picture:
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
        where = target.get("path") or " ".join(
            x for x in (KIND_WORDS.get(target.get("kind"), "the dashboard"),
                        f"“{target['label']}”" if target.get("label") else "") if x)
        _step(state, f"Reading {where}")
        current = await asyncio.to_thread(target_yaml, target)
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
                              shot=picture, view=state.get("view"), scope=state.get("scope", "ui"))
        state["payload"] = prompt
        model = settings.load().get("tell_model") or ""
        await asyncio.to_thread(brain.submit, tid, prompt, schema=RESULT_SCHEMA,
                                tools="full", timeout=TIMEOUT_S, model=model)
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
        summary = str((data or {}).get("summary") or text or "").strip()[:1200]
        commit = await asyncio.to_thread(
            gitrepo.commit,
            f"brAIn: {summary or state['text']}"[:200] + f"\n\nAsked: “{state['text']}”\nTask: {tid}",
            "brain")
        if commit:
            state["commit"] = commit
            files = await asyncio.to_thread(gitrepo.changed_files, commit)
            _step(state, "Changed " + ", ".join(files[:6]), "good")
        changed = [str(x)[:200] for x in ((data or {}).get("changed") or [])][:20]
        house = [c for c in changed if "morph" not in c.lower()]
        if house:
            state["house"] = house
            _step(state, "In Home Assistant: " + "; ".join(house[:4]), "good")
        if error and state.get("phase") != "failed":
            state["phase"] = "failed"
            state["say"] = summary or f"brAIn could not finish this ({error})."
        elif state.get("phase") != "failed":
            state["phase"] = "done"
            state["say"] = summary or ("Done." if commit else "brAIn answered without changing anything.")
        state["needs_person"] = str((data or {}).get("needs_person") or "")[:600]
        state["saw"] = str((data or {}).get("saw") or "")[:400]
        issue = (data or {}).get("code_issue")
        if isinstance(issue, dict) and str(issue.get("title") or "").strip():
            state["code_issue"] = {"title": str(issue["title"]).strip()[:140],
                                   "detail": str(issue.get("detail") or "").strip()[:1500]}
            state["issue"] = "asked"
        state["reload"] = bool(commit) or bool((data or {}).get("reload"))
        lesson = str((data or {}).get("lesson") or "").strip()
        if lesson:
            await asyncio.to_thread(learning.add_lesson, lesson, f"told: “{state['text']}”")
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
        f"About: the {KIND_WORDS.get(target.get('kind'), target.get('kind') or 'dashboard')}"
        + (f" (card type {state['card_type']})" if state.get("card_type") else ""),
        f"What brAIn saw: {state['saw']}" if state.get("saw") else "",
        f"What brAIn did meanwhile: {state.get('say') or ''}",
        "",
        "What Morph would need:",
        issue.get("detail") or "(not said)",
    ])
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
        follow = start({"kind": "dashboard", "label": "Undo"},
                       "Put back the Home Assistant changes you made for Morph task "
                       f"{tid} (asked: “{state.get('text')}”). You changed: "
                       + "; ".join(state["house"]) + ". Use brain undo for files you edited; "
                       "reverse anything else (a helper, an entity) directly. Do not touch "
                       "/config/morph — Morph has already put the dashboard back.", scope="house")
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
                       "tools": "full", "schema": RESULT_SCHEMA}, indent=2)
