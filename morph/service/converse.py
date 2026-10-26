"""Ask's conversations: brAIn's chat, with a dashboard in front of it.

docs/design/morph-vision.md §13.3–13.4. When brAIn's interpreter reads
what somebody typed into Morph's Ask line as a question or a conversation
(rather than a rule, a fact, or a change to the dashboard), Morph hands it
to brAIn as a ``conversation`` task: the automation listener runs it as
brAIn's chat would (the chat channel, so the action gate asks rather than
denies — or, with "Let brAIn act without asking" on, allows), resumes the
session the last turn used, and answers with the session id. The
conversation is NOT claimed as a machine run, so it is the person's own
conversation in brAIn's Ask tab too, and can be picked up there.

The state rides in the same folder as a Tell's (``/config/.morph/tells``),
so the panel follows it with ``morph/tell_status`` and brAIn's steps arrive
the same way. Nothing here commits anything: a conversation is not a
change to the dashboard.
"""
from __future__ import annotations

import asyncio
import re
import time

import brain
import settings
import tell
import wording

TIMEOUT_S = 600
# Sized for a card's context AND what somebody said (wording.py): the old
# 2000 was a slice off the end, and the end is where the person's words were.
MAX_TEXT = wording.MAX_TEXT
SESSION = re.compile(r"^[A-Za-z0-9-]{8,80}$")
_RUNNING: dict = {}

PROMPT = """Someone typed this into the Ask line of Morph, the house's dashboard,
which is brAIn's face. Answer them as brAIn's chat would: read the house with
your tools when the answer depends on it, say it plainly in a few sentences,
and name devices by their friendly names (the page lifts what you name).
You have the same reach as the chat. If they asked you to change something,
in Home Assistant or on the dashboard (/config/morph/dashboard.yaml, read
/config/morph/AGENTS.md first, never run git there), do all of it, check it,
and say in one sentence what changed.

They wrote:
"""

CONTEXT_LEAD = """The card they were using sent this with their words. It is context for
the question, not what they said:
"""


def prompt_for(words: str, context: str = "") -> str:
    """The prompt: Morph's frame, a card's context if it sent one, and the
    person's words LAST, whole."""
    if not context:
        return PROMPT + words
    return CONTEXT_LEAD + context + "\n\n" + PROMPT + words


def start(words: str, session: str = "", context: str = "") -> dict:
    """``words`` are what the person said; ``context`` is what a card sends
    beside them (the readings, the history it shows). The context is what
    gives way when the two are too long together, never the words."""
    fitted = wording.fit(words, context, cap=MAX_TEXT)
    words, context = fitted["words"], fitted["context"]
    if not words:
        return {"error": "Say something first."}
    if not brain.available():
        return {"error": brain.status()["sentence"]}
    session = session if SESSION.match(str(session or "")) else ""
    tid = brain.new_id("conv")
    state = {"id": tid, "kind": "conversation", "text": words, "phase": "sending", "steps": [],
             "started": time.time(), "session_in": session}
    if context:
        state["context"] = context
    if fitted["context_cut"]:
        state["cut"] = "context"
    tell._save(state)
    _RUNNING[tid] = asyncio.get_running_loop().create_task(_run(state))
    return state


async def _run(state: dict) -> None:
    tid = state["id"]
    try:
        model = settings.load().get("tell_model") or ""
        await asyncio.to_thread(brain.submit, tid,
                                prompt_for(state["text"], state.get("context") or ""), tools="full",
                                timeout=TIMEOUT_S, model=model, person_words=state["text"],
                                memory=True, kind="conversation",
                                session_id=state.get("session_in") or "")
        state["phase"] = "waiting"
        tell._step(state, "Handed to brAIn")
        deadline = time.time() + brain.CLAIM_GRACE_S
        while not brain.claimed(tid):
            if time.time() > deadline:
                brain.withdraw(tid)
                state["phase"] = "failed"
                state["say"] = ("Nothing picked the question up. brAIn's Automation integration "
                                "has to be on for Morph to reach it.")
                tell._save(state)
                return
            await asyncio.sleep(brain.POLL_S)
        state["phase"] = "working"
        tell._step(state, "brAIn is thinking")
        deadline = time.time() + TIMEOUT_S + 60
        res = None
        seen = 0
        while res is None:
            if time.time() > deadline:
                break
            seen = await asyncio.to_thread(tell._follow, state, seen)
            res = await asyncio.to_thread(brain.result, tid)
            if res is None:
                await asyncio.sleep(brain.POLL_S)
        if res is None:
            state["phase"] = "failed"
            state["say"] = "brAIn did not answer in time."
        else:
            _, text, error = brain.answer_data(res)
            state["session_id"] = str(res.get("session_id") or "")[:80]
            state["say"] = (text or "").strip()[:4000] or ("brAIn could not answer: " + error if error else "No answer.")
            state["phase"] = "failed" if error else "done"
        tell._save(state)
    except Exception as exc:  # noqa: BLE001 — a conversation that breaks says so
        state["phase"] = "failed"
        state["say"] = f"Morph could not finish this: {exc}"
        tell._save(state)
    finally:
        _RUNNING.pop(tid, None)


def running() -> list[str]:
    return list(_RUNNING)


__all__ = ["start", "running", "prompt_for", "PROMPT", "MAX_TEXT"]
