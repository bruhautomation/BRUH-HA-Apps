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

A tell is a job with a state file the integration reads directly
(``/config/.morph/tells/<id>.json``), so the panel can poll it without a
round trip and a reload of the page does not lose it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import brain
import gitrepo
import learning
import paths
import settings
import store

log = logging.getLogger("morph.tell")

TIMEOUT_S = 900
MAX_WORDS = 4000
LESSONS_CHARS = 4000

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
                   "description": "Optional: one durable lesson about how this household wants its dashboard."},
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


def lessons() -> str:
    try:
        text = paths.LEARNED.read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[-LESSONS_CHARS:]


def build_prompt(target: dict, words: str, current: str, previous: list[dict] | None = None) -> str:
    kind = target.get("kind") or "dashboard"
    label = str(target.get("label") or "")[:120]
    path = str(target.get("path") or "")[:240]
    entity = str(target.get("entity") or "")[:120]
    lines = [
        "MORPH · a change request from the dashboard editor.",
        "",
        "Morph is this house's dashboard. It lives in /config/morph: dashboard.yaml is the",
        "dashboard, cards/ holds custom card code, AGENTS.md is how it works (READ IT FIRST),",
        "and LEARNED.md is what this household has taught Morph about how it wants things.",
        "",
        f"Target: the {KIND_WORDS.get(kind, kind)}" + (f" “{label}”" if label else ""),
    ]
    if path:
        lines.append(f"Where: {path}")
    if entity:
        lines.append(f"Entity: {entity}")
    lines += ["", f"Asked: “{words}”", ""]
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
    lines += [
        "Do whatever this takes, now — the person pressed Send and is watching. You may change:",
        "- the Morph dashboard (/config/morph/dashboard.yaml), keeping every existing id;",
        "- Morph card code (/config/morph/cards/*.js, registered in dashboard.yaml as described in AGENTS.md);",
        "- anything in Home Assistant behind it: automations, scripts, scenes, helpers, entities.",
        "Make the change directly; do not ask for confirmation and do not only describe it.",
        "",
        "Rules that still hold:",
        "- Never run git in /config/morph: Morph commits your change the moment you answer, and that",
        "  commit is what the person's Undo reverts.",
        "- protected_entities still applies; if the request needs one, say so in needs_person.",
        "- Keep dashboard.yaml valid YAML in Morph's schema (AGENTS.md); an unknown card type is",
        "  passed to Lovelace as-is, so a Lovelace card's YAML is always a valid card.",
        "- Prefer the smallest change that does what was asked.",
        "",
        "Answer with the JSON object the schema describes: summary (what you did, for the person),",
        "changed, reload (true if the dashboard changed), needs_person only if something is left for",
        "a person, and lesson only if the request taught a durable preference about this dashboard.",
    ]
    return "\n".join(lines)


def start(target: dict, words: str, previous_id: str = "") -> dict:
    """Begin a tell. Returns its state; the work continues in a task."""
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
             "started": time.time(), "history": previous[-6:]}
    _save(state)
    _RUNNING[tid] = asyncio.get_running_loop().create_task(_run(state))
    return state


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
        prompt = build_prompt(target, state["text"], current, state.get("history"))
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
        while res is None:
            if time.time() > deadline:
                state["phase"] = "failed"
                state["say"] = "brAIn did not answer in time. Anything it finished is still committed."
                break
            res = await asyncio.to_thread(brain.result, tid)
            if res is None:
                await asyncio.sleep(brain.POLL_S)
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
        state["reload"] = bool(commit) or bool((data or {}).get("reload"))
        lesson = str((data or {}).get("lesson") or "").strip()
        if lesson:
            await asyncio.to_thread(learning.add_lesson, lesson, f"told: “{state['text']}”")
        await asyncio.to_thread(learning.record_outcome, {
            "kind": "tell", "id": tid, "text": state["text"], "target": target.get("kind"),
            "commit": commit, "base": base, "phase": state["phase"], "error": error,
            "needs_person": bool(state["needs_person"]), "at": time.time()})
        if state["phase"] == "failed" and error not in ("", "auth", "paused", "budget"):
            import devloop
            await asyncio.to_thread(
                devloop.note_fault, "Tell", f"A request brAIn could not finish ({error})",
                f"Target: {target.get('kind')}\nAsked: {state['text']}\nAnswer: {state.get('say')}")
        _save(state)
    except Exception as exc:  # noqa: BLE001 — a tell must always end in a sentence
        log.exception("tell %s failed", tid)
        state["phase"] = "failed"
        state["say"] = f"Morph could not finish handing this over: {exc}"
        _save(state)
    finally:
        _RUNNING.pop(tid, None)


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
                       "/config/morph — Morph has already put the dashboard back.")
        if follow.get("id"):
            state["house_undo"] = follow["id"]
            out["follow"] = follow["id"]
    _save(state)
    learning.record_outcome({"kind": "undo", "id": tid, "commit": state.get("commit"),
                             "at": time.time()})
    return out


def prune(max_age_s: int = 7 * 86400) -> None:
    try:
        now = time.time()
        for p in paths.TELLS.glob("*.json"):
            if now - p.stat().st_mtime > max_age_s:
                p.unlink()
    except OSError:
        pass  # an old tell file another prune already removed; nothing to tidy


def json_payload(state: dict) -> str:
    return json.dumps({"id": state.get("id"), "prompt": state.get("payload", ""),
                       "tools": "full", "schema": RESULT_SCHEMA}, indent=2)
