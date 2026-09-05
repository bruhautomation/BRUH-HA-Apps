"""`brain doctor --deep` — every face of brAIn, one real round trip each.

`brain doctor` (``scripts/ha-selftest.sh``) answers *is the plumbing
connected*: a token is present, the MCP server completes a handshake, the
panel answers, a daemon has a pid. Every one of those can be true while
the thing a person actually uses is broken — a credential that expired on
a Tuesday, a listener holding a folder open with nothing behind it, an
allow-list that stopped letting a read through. So this asks the other
question: **does each face work end to end, right now, on this install**,
and it asks it the only way that can be trusted, by doing the thing.

BRight's `director_check` is the shape: walk the chain, do a real trivial
round trip, and make the sentence at the break name the switch or the log
to look at. Two differences, both because there are eight faces here
rather than one chain:

* **Every stage is reported**, not just the first break. "The chat works
  and the automation listener does not" is the answer, and stopping at
  the first failure would hide the half that matters.
* **A stage whose precondition failed is SKIPPED with the reason**, never
  run. If the credential does not work for a no-tool run it will not work
  for an analyst run either, and eight identical auth failures is a report
  nobody reads past line one.

Six rules hold the rest of it up.

**Opt-in, costed, and never on a timer.** A deep run spends a handful of
Claude turns — the design page's own words — so it happens when somebody
asks, lazily, the way the auth re-check does. There is no schedule, no
option that turns one on, and no way for it to happen while nobody is
looking.

**Every stage cleans up after itself, and the cleanup is verified.** The
synthetic fact is not in `memory.md` afterwards; the synthetic finding is
in neither the store nor the settled ledger; the helper is back to the
name it had, and gone entirely if the stage created it. A leftover is a
**failure of that stage**, reported as one — a self-test that litters is
a self-test people stop running.

**Optional is not broken.** `assist` with the Assist integration switched
off is `skipped`, not `failed`, and says which switch; so is
`automation_task` with the automation listener off, and `fixer_dry` when
`protected_entities` covers the helper it would rename. That is
`health.py`'s rule, applied to a report with the same job.

**The shipped configuration, not a test one.** `protected_entities`, the
allow list and the deny list are read from the same environment the real
runs read them from. A deep run that proved a configuration nobody has is
a deep run that proves nothing.

**A timeout is reported by name.** Every stage carries its own budget and
a timeout comes back as `timeout` with that stage's sentence — never as
"not authenticated", which is the shape of failure this add-on has
shipped twice.

**Every Claude turn is journaled and counted.** The runs claim the
``doctor`` source before they start (``run_sources``), so the Chats rail
does not offer them as conversations somebody had, and the tokens go
through ``usage_store`` like any other run, so the usage pill moves and
the popover attributes the movement to something.

What this module deliberately does NOT own: the three things only the
panel can do — ending a finding, reversing one, and running the
consolidator — arrive as :class:`Hooks`. A second implementation of an
ending here would be the same press teaching brAIn two different things
depending on who asked, which is the bug ``_end_finding`` was extracted
to prevent.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import atomic_write
import chat_session
import engine
import findings_store
import journal
import undo_store

# The face every run here is filed under. It is in ``run_sources.SOURCES``
# so a probe never shows up in the rail as something a person typed.
SOURCE = "doctor"

# Everything a deep run or a rehearsal creates in the house carries this,
# so `ha-selftest.sh` can say "nothing was left behind" by looking for one
# string rather than by knowing the list.
PREFIX = "brain_test_"

# The last completed run. Written so `/api/diagnostics` — and through it
# the mirror, the integration's Download-diagnostics button and `brain
# report` — can carry the verdict without holding a deep run in memory
# across a restart.
DEEP_FILE = Path(os.environ.get("BRAIN_DOCTOR_DEEP_FILE",
                                "/data/doctor-deep.json"))

# The automation bridge's two folders, in the shape the integration writes
# and the listener reads. Named here rather than imported because the
# listener is a shell script and the integration is a different process:
# this is the wire format, and `tests/test_doctor_deep.py` drives the real
# claim contract against it.
SHARED_DIR = Path(os.environ.get("BRAIN_SHARED_DIR", "/config/.brain"))
TASKS_DIR = SHARED_DIR / "tasks"
TASK_RESULTS_DIR = SHARED_DIR / "task_results"
# The listener claims a task by renaming it before it does any work, so an
# un-renamed file after the grace window is PROOF that nothing is
# listening rather than a guess at a slow answer — director_check's rule,
# and the reason "nobody picked this up" and "nobody answered" are two
# different sentences here.
CLAIM_GRACE_S = 30

# The helper `fixer_dry` renames. An `input_boolean` because it is the
# cheapest thing in Home Assistant that has a name worth changing and no
# effect on anything when it changes.
FIXER_HELPER = f"input_boolean.{PREFIX}doctor"
FIXER_HELPER_NAME = "brAIn deep check"
FIXER_RENAMED = "brAIn deep check (renamed)"

# Per-stage budgets. A deep run is a handful of minutes at worst and each
# number is the one the face it tests already lives under: the
# consolidator's own 480s, the analyst's search budget, the bridge's
# window.
TIMEOUTS = {
    "snapshot_claude": 120,
    "analyst_tools": 240,
    "chat": 180,
    "automation_task": 90,
    "assist": 90,
    "memory": 480,
    "findings_undo": 30,
    "fixer_dry": 480,
}

# The report's vocabulary. `skipped` is not a lesser `failed`: it is the
# answer "I did not look", and the two must never be added together.
OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"

# The stages, in order, with what each one needs to have passed first. The
# order is the report's order and the names are its vocabulary; the design
# page names them and the CLI prints them, so they are a contract.
STAGES: list[dict] = [
    {"name": "snapshot_claude", "title": "Claude, no tools",
     "proves": "the credential works for a plain run, and the JSON "
               "extractor can read a real reply",
     "needs": ()},
    {"name": "analyst_tools", "title": "Analyst tools",
     "proves": "MCP reaches the model, the allow list lets a read "
               "through, and the deny list blocks an acting tool",
     "needs": ("snapshot_claude",)},
    {"name": "chat", "title": "Chat session",
     "proves": "the stream-json session spawns, speaks and ends a turn",
     "needs": ()},
    {"name": "automation_task", "title": "Automation listener",
     "proves": "a task is claimed and answered inside the bridge's window",
     "needs": ()},
    {"name": "assist", "title": "Assist",
     "proves": "the worker pool answers through Home Assistant's own "
               "front door",
     "needs": ()},
    {"name": "memory", "title": "Memory",
     "proves": "a queued fact reaches memory.md and can be taken out again",
     "needs": ("snapshot_claude",)},
    {"name": "findings_undo", "title": "Findings and undo",
     "proves": "the store, the settled ledger, the memory line and the "
               "undo token all round-trip, and nothing is left behind",
     "needs": ()},
    {"name": "fixer_dry", "title": "Fixer",
     "proves": "the one path that can change the house can, and puts it "
               "back",
     "needs": ("analyst_tools",)},
]
STAGE_NAMES = [s["name"] for s in STAGES]


class Hooks:
    """The operations the panel owns, handed in rather than copied.

    Three of the eight stages act on stores whose one writer is the
    server: ending a finding is three things at once (the row, the settled
    key, the memory line), reversing one is those three backwards, and the
    consolidator is a subprocess the panel starts and reads back. Each has
    exactly one implementation in `server.py` and this is how a stage
    reaches it — so a deep run exercises the code a button exercises,
    which is the only version worth testing.

    Every hook is awaited. ``ws`` is the one that is not a panel store: it
    runs a list of Home Assistant WebSocket commands, which is how the
    assist stage speaks to Core and how the fixer stage reads a helper's
    name back.
    """

    def __init__(self, *, end_finding, undo_finding, queue_memory,
                 drop_memory, inbox_pending, memory_text, consolidate,
                 record_usage, ws, model="", options=None):
        self.end_finding = end_finding          # (finding, verb, note) -> (payload, fact)
        self.undo_finding = undo_finding        # (entry) -> (restored, payload)
        self.queue_memory = queue_memory        # (fact, source) -> None
        self.drop_memory = drop_memory          # (source, fact) -> bool
        self.inbox_pending = inbox_pending      # () -> int
        self.memory_text = memory_text          # () -> str
        self.consolidate = consolidate          # () -> (ok, error)
        self.record_usage = record_usage        # (result, run_id) -> dict
        self.ws = ws                            # (commands) -> list
        self.model = model
        self.options = options or {}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _result(state: str, sentence: str, detail: str = "") -> dict:
    return {"state": state, "sentence": sentence, "detail": detail[:600]}


def _ok(sentence: str, detail: str = "") -> dict:
    return _result(OK, sentence, detail)


def _fail(sentence: str, detail: str = "") -> dict:
    return _result(FAILED, sentence, detail)


def _skip(sentence: str, detail: str = "") -> dict:
    return _result(SKIPPED, sentence, detail)


def _engine_failure(result: dict, what: str, timeout_message: str) -> dict:
    """A failed engine envelope as a sentence naming what to go and read.

    ``journal.classify`` already owns the vocabulary for *why* a run
    failed; this turns its word into the one line a person can act on, and
    a timeout comes back as a timeout rather than as an authentication
    problem it is not.
    """
    outcome = journal.classify(result, timeout_message)
    error = str(result.get("error") or "no reply")
    sentences = {
        "timeout": f"{what} passed its limit and was stopped. The model is "
                   "slow, or the run is bigger than the budget — the "
                   "add-on log has the last thing it said.",
        "auth": f"{what} could not authenticate. Sign in again from "
                "⚙ Settings → Claude account, or run `claude /login` in "
                "the Terminal tab.",
        "no_cli": "The Claude Code CLI is not in this image — nothing "
                  "here can run until it is back. Restart the add-on.",
        "max_turns": f"{what} hit the turn limit before answering.",
        "denied": f"{what} was refused a tool it needed.",
        "crash": f"{what} exited without an answer. The add-on log carries "
                 "its stderr.",
    }
    return {"outcome": outcome,
            "sentence": sentences.get(
                outcome, f"{what} failed: {error[:200]}"),
            "detail": journal.scrub(error)}


def _journal_stage(name: str, result: dict, seconds: float) -> None:
    """One journal line per stage, whatever happened to it.

    The engine journals its own runs (source ``doctor``, because that is
    what is passed to it), so this is the other half: the stages that
    never touch Claude, and the outcome of the stage as a stage rather
    than of the invocation inside it.
    """
    outcome = {OK: "ok", SKIPPED: "ok", FAILED: "error"}[result["state"]]
    journal.record(SOURCE, outcome,
                   ok=result["state"] != FAILED,
                   duration_s=seconds,
                   error="" if result["state"] != FAILED
                         else result["sentence"],
                   extra={"stage": name, "state": result["state"]})


# ---------------------------------------------------------------------------
# The stages
# ---------------------------------------------------------------------------

SNAPSHOT_SYSTEM = ("You are a connectivity check. Reply with the exact JSON "
                   "object the user asks for and nothing else — no prose, "
                   "no code fence.")
SNAPSHOT_PROMPT = ('Reply with exactly this JSON object and nothing else: '
                   '{"doctor": "ok"}')


async def stage_snapshot_claude(hooks: Hooks) -> dict:
    """A no-tool run, and a reply the extractor has to be able to read.

    Two things at once on purpose. `validate_auth` already proves a
    credential answers; what it cannot prove is that the *shape* of the
    answer survives `engine.extract_json`, which is the step every insight
    card depends on and the one whose failure reads as "the card didn't
    generate".
    """
    timeout = TIMEOUTS["snapshot_claude"]
    message = f"Claude timed out after {timeout}s"
    result = await asyncio.to_thread(
        engine.run_claude, SNAPSHOT_PROMPT, SNAPSHOT_SYSTEM, hooks.model,
        timeout, 2, SOURCE)
    hooks.record_usage(result, "doctor-snapshot")
    if not result.get("ok"):
        bad = _engine_failure(result, "The no-tool run", message)
        return _fail(bad["sentence"], bad["detail"])
    obj = engine.extract_json(result.get("text") or "")
    if not isinstance(obj, dict) or obj.get("doctor") != "ok":
        return _fail(
            "Claude answered, and the reply was not the JSON that was "
            "asked for — which is the same failure an insight card reports "
            "as 'unparseable'. The model or its prompt has moved.",
            f"reply: {str(result.get('text') or '')[:300]}")
    return _ok("A no-tool run answered, and the extractor read it.",
               f"model {result.get('meta', {}).get('model') or hooks.model or 'default'}")


ANALYST_SYSTEM = (
    "You are running a connectivity check on a Home Assistant add-on's "
    "tool wiring. Do exactly what the user asks, then reply with the exact "
    "JSON object requested and nothing else — no prose, no code fence.")
ANALYST_PROMPT = (
    "Two steps, in order.\n"
    "1. Call the get_areas tool and count the areas it returns.\n"
    "2. Attempt to call the call_service tool with domain 'homeassistant', "
    "service 'update_entity' and entity_id 'sun.sun'. This is expected to "
    "be refused; do not work around the refusal, do not use any other "
    "tool to achieve it, and do not retry.\n\n"
    'Then reply with exactly: {"areas": <the count from step 1>, '
    '"call_service": "refused"} — or "ran" instead of "refused" if the '
    "call actually went through.")


async def stage_analyst_tools(hooks: Hooks) -> dict:
    """A read that must work, and an acting call that must not.

    The allow list and the deny list are asserted from both ends in
    `engine`, and `tests/test_security.py` checks the deny list against the
    MCP server's own tool names. Neither of those can tell you whether the
    wiring holds *on this install*: an MCP server that failed to start, a
    `.mcp.json` a plugin poisoned, a settings file that widened the
    permissions. This is the only thing that can.
    """
    timeout = TIMEOUTS["analyst_tools"]
    message = f"the analysis passed its {timeout}s limit and was stopped"
    result = await asyncio.to_thread(
        engine.run_analyst, ANALYST_PROMPT, ANALYST_SYSTEM, hooks.model,
        timeout, 8, SOURCE)
    hooks.record_usage(result, "doctor-analyst")
    if not result.get("ok"):
        bad = _engine_failure(result, "The analyst run", message)
        return _fail(bad["sentence"], bad["detail"])
    obj = engine.extract_json(result.get("text") or "")
    if not isinstance(obj, dict):
        return _fail(
            "The analyst answered and the reply was not the JSON that was "
            "asked for, so nothing can be said about the tools.",
            f"reply: {str(result.get('text') or '')[:300]}")
    areas = obj.get("areas")
    if not isinstance(areas, int) or areas < 0:
        return _fail(
            "The analyst could not read the house's areas, so the MCP "
            "server is not reaching the model. Check `.mcp.json` and the "
            "MCP section of `brain doctor`.",
            f"reply: {json.dumps(obj)[:300]}")
    if obj.get("call_service") != "refused":
        return _fail(
            "An acting tool was NOT refused on an unattended run — the "
            "deny list is not holding. Nothing scheduled may be allowed to "
            "change the house; report this.",
            f"reply: {json.dumps(obj)[:300]}")
    return _ok(f"Read {areas} areas through MCP, and call_service was "
               "refused.", f"areas: {areas}")


async def stage_chat(hooks: Hooks) -> dict:
    """One message on a session of its own, then closed.

    It never joins the registry and never becomes the attached session, so
    nothing on screen moves and no live conversation is evicted to make
    room for it: the whole point of holding several chats is that an
    answer being written survives you looking elsewhere, and a self-check
    that took one away to prove the chat works would be exactly wrong.

    Which is also why a full registry is a **skip** rather than an
    eviction — with the cap's own sentence, because that sentence names
    the count and the setting.
    """
    live = [s for s in chat_session.registry().sessions() if s.alive()]
    cap = chat_session.max_sessions()
    if len(live) >= cap:
        busy = sum(1 for s in live if s.state == "busy")
        return _skip(
            f"{len(live)} chat session(s) are already open and brAIn keeps "
            f"{cap} alive at once (chat_max_sessions in Settings). This "
            "check will not close somebody's conversation to run itself — "
            "close one and try again.",
            f"{busy} of them are mid-answer")

    session = chat_session.ChatSession()
    queue = session.subscribe()
    try:
        await session.start()
        if not session.alive():
            return _fail(
                "The chat session would not spawn. `brain doctor` will say "
                "whether the CLI is there; the add-on log carries its "
                "stderr.",
                session.error or "")
        await session.send("Reply with exactly: OK")
        text = await _await_chat_result(queue, TIMEOUTS["chat"])
    except asyncio.TimeoutError:
        return _fail(
            f"The chat session spawned and did not finish a turn inside "
            f"{TIMEOUTS['chat']}s. The add-on log carries what it said.")
    except Exception as exc:  # noqa: BLE001 — a stage reports, it does not raise
        return _fail(f"The chat session failed: {str(exc)[:200]}")
    finally:
        session.unsubscribe(queue)
        try:
            await session.stop()
        except Exception:  # noqa: BLE001 — the stop is the cleanup, and a
            # cleanup that raises must not replace the stage's own answer.
            pass
        _forget_chat_transcript(session.session_id)
    if text is None:
        return _fail("The chat session ended its turn with an error.",
                     session.error or "")
    return _ok("A chat session spawned, answered and closed.",
               f"reply: {text[:120]}")


async def _await_chat_result(queue: asyncio.Queue, timeout: int) -> str | None:
    """Read the session's own event stream until the turn ends.

    Subscribing rather than polling ``state``: the state goes back to
    ``ready`` on an error too, and "it stopped being busy" is not the same
    claim as "it finished a turn".

    **A failed turn never emits a `result`.** `_normalise` turns an
    `is_error` envelope into an error *notice* and returns no result event
    at all — so a loop waiting only for `result` waits out the whole budget
    and reports a turn that ended in one second as a timeout. Found by
    driving the fixture's `error` mode: the test took the full 180s and
    passed, which is the shape of failure this whole file exists to catch.
    """
    said = ""
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise asyncio.TimeoutError
        event = await asyncio.wait_for(queue.get(), timeout=left)
        kind = event.get("type")
        if kind == "text":
            said = str(event.get("text") or "") or said
        elif kind == "result":
            return said
        elif kind == "notice" and event.get("level") == "error":
            return None
        elif kind == "state" and event.get("state") == "error":
            return None


def _forget_chat_transcript(session_id: str | None) -> None:
    """Take the probe's transcript back off disk.

    A deep run must not leave a conversation behind for somebody to find
    in the rail and wonder about. Claude Code's own store still holds the
    conversation — that is the CLI's, not ours, and the run is claimed as
    ``doctor`` so the rail does not offer it.
    """
    if not session_id:
        return
    path = chat_session.transcript_path(session_id)
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        # A transcript we could not take back is a stray conversation in a
        # store the rail already filters by source — cosmetic, and not
        # worth failing a stage that otherwise worked.
        pass


async def stage_automation_task(hooks: Hooks) -> dict:
    """The integration's own wire format, driven by hand.

    Written exactly the way `bridge.run_task` writes it, because the thing
    being tested is the contract between two processes and a test of a
    paraphrase of it is a test of the paraphrase. Three answers, not two:
    nothing claimed the file (the listener is not running), it was claimed
    and nothing came back (the listener is running and its Claude run is
    not), or it worked.
    """
    if not _flag(hooks.options, "enable_automation_integration", True):
        return _skip(
            "The Automation integration is switched off "
            "(enable_automation_integration on the Configuration tab), so "
            "there is no listener to answer. Nothing is wrong.")
    if not TASKS_DIR.is_dir():
        return _fail(
            f"{TASKS_DIR} does not exist, so the automation listener has "
            "never started. Turn the Automation integration on and restart "
            "the add-on.")

    timeout = TIMEOUTS["automation_task"]
    task_id = uuid.uuid4().hex
    task_file = TASKS_DIR / f"{task_id}.json"
    result_file = TASK_RESULTS_DIR / f"{task_id}.json"
    task = {"id": task_id, "notify": False, "ts": time.time(),
            "timeout": timeout,
            "prompt": "Reply with exactly the word READY and nothing else."}
    try:
        TASK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        # Atomic, and 0644 rather than the mkstemp default: the listener
        # runs as a different user from the panel, and a task it cannot
        # read is a task nothing will ever claim. Same reason the bridge
        # writes through a scratch name — the listener globs `*.json` and
        # would otherwise be able to pick up half a request.
        atomic_write.write_json(task_file, task, mode=0o644)
    except OSError as exc:
        return _fail(
            f"brAIn could not write a task into {TASKS_DIR} ({exc}). The "
            "listener runs as a different user; a folder it cannot read "
            "from is one nothing will ever answer.")

    try:
        claimed = await _wait_gone(task_file, CLAIM_GRACE_S)
        if not claimed:
            return _fail(
                f"Nothing claimed the task in {CLAIM_GRACE_S}s. The "
                "listener claims by renaming the file before it does any "
                "work, so an untouched file means nothing is watching — "
                "check the add-on log for 'Automation listener starting'.")
        answer = await _wait_file(result_file, timeout)
        if answer is None:
            return _fail(
                f"The listener took the task and nothing came back inside "
                f"{timeout}s. It is running and its Claude run is not — "
                "the per-task log is under /config/.brain/logs/.")
        text = str((answer or {}).get("result") or "")
        status = str((answer or {}).get("status") or "")
        if status and status not in ("completed", "ok"):
            return _fail(f"The listener answered with status {status!r}.",
                         text[:300])
        return _ok("A task was claimed and answered.", f"reply: {text[:120]}")
    finally:
        # Whatever happened, neither folder keeps our file: an unclaimed
        # task would otherwise be picked up minutes later by a listener
        # that came back, and a result nobody read is what the listener's
        # own sweep exists to clear.
        for path in (task_file, result_file):
            try:
                path.unlink()
            except OSError:
                # The listener sweeps both folders on its own timer, so a
                # file we could not take back goes on the next sweep. The
                # stage's answer is above and does not change.
                pass


async def _wait_gone(path: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if not path.exists():
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.4)


async def _wait_file(path: Path, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Not there yet, or half written — both are "keep waiting",
            # which is what the loop below does. The deadline is the only
            # thing that ends this.
            pass
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(0.5)


async def stage_assist(hooks: Hooks) -> dict:
    """A conversation turn through Home Assistant's own front door.

    Not the worker pool's health endpoint, which answers whether a process
    is alive; this goes through `conversation/process` with brAIn's own
    agent id, which is what Assist does, and is therefore the only thing
    that proves a voice command would be answered.
    """
    if not _flag(hooks.options, "enable_assist_integration", True):
        return _skip(
            "The Assist integration is switched off "
            "(enable_assist_integration on the Configuration tab), so "
            "brAIn is not a conversation agent here. Nothing is wrong.")
    try:
        agent = await _assist_agent(hooks)
    except Exception as exc:  # noqa: BLE001
        return _fail("brAIn could not ask Home Assistant which entities it "
                     f"has: {str(exc)[:200]}")
    if not agent:
        return _fail(
            "The Assist integration is on and brAIn has no conversation "
            "entity in Home Assistant, so Assist cannot route to it. "
            "Check that the brAIn integration is loaded "
            "(Settings → Devices & services).")
    try:
        replies = await asyncio.wait_for(
            hooks.ws([{"type": "conversation/process",
                       "text": "Reply with exactly: OK",
                       "agent_id": agent}]),
            timeout=TIMEOUTS["assist"])
    except asyncio.TimeoutError:
        return _fail(
            f"Assist did not answer inside {TIMEOUTS['assist']}s. The "
            "worker pool is the thing to look at — `brain doctor` reports "
            "its health endpoint.")
    except Exception as exc:  # noqa: BLE001
        return _fail(f"The conversation call failed: {str(exc)[:200]}")
    reply = replies[0] if replies else None
    if not reply:
        return _fail(
            "Home Assistant refused the conversation call, so Assist would "
            f"refuse it too. The agent asked for was {agent}.")
    said = _assist_speech(reply)
    if not said:
        return _fail("Assist answered with nothing to say.",
                     json.dumps(reply)[:300])
    return _ok("Assist answered through Home Assistant.",
               f"{agent}: {said[:120]}")


async def _assist_agent(hooks: Hooks) -> str:
    """brAIn's conversation entity, read from the registry rather than guessed.

    The entity id is derived from the device name, which a person may
    rename — so a hardcoded `conversation.brain_agent` would report a
    working Assist as broken on any house that renamed the device.
    """
    rows = (await hooks.ws([{"type": "config/entity_registry/list"}]))[0] or []
    for row in rows:
        eid = str(row.get("entity_id") or "")
        if eid.startswith("conversation.") and row.get("platform") == "brain":
            return eid
    return ""


def _assist_speech(reply: dict) -> str:
    try:
        return str(reply["response"]["speech"]["plain"]["speech"] or "").strip()
    except (KeyError, TypeError):
        return ""


MEMORY_FACT_PREFIX = "brAIn deep check marker"


async def stage_memory(hooks: Hooks) -> dict:
    """A fact in, the document grows, and then the fact is gone again.

    The queue is counted either side of each pass rather than the pass's
    own report being believed, because the consolidator can exit 0 and
    keep the facts — the failure `_consolidate_task` already refuses to
    read as a success.

    Cleanup is the second half of the stage rather than an afterthought:
    the marker is taken out through `FORGET:`, which is the same route
    `brain memory forget` uses, and the stage FAILS if the document still
    holds it. A self-test that writes into somebody's memory and leaves it
    there has done more harm than the check was worth.
    """
    marker = f"{MEMORY_FACT_PREFIX} {int(time.time())} — ignore this line."
    before = await asyncio.to_thread(hooks.inbox_pending)
    await asyncio.to_thread(hooks.queue_memory, marker, SOURCE)
    queued = await asyncio.to_thread(hooks.inbox_pending)
    if queued <= before:
        await asyncio.to_thread(hooks.drop_memory, SOURCE, marker)
        return _fail(
            "The fact did not reach the memory inbox, so nothing anywhere "
            "in brAIn can teach it anything. Check that "
            "/config/.brain/memory/inbox is writable.")

    ok, error = await _consolidate(hooks)
    if not ok:
        await asyncio.to_thread(hooks.drop_memory, SOURCE, marker)
        return _fail(
            "The consolidator did not file the queue. The add-on log's "
            "[brain-memory] lines say why; the fact this check queued has "
            "been taken back out.", error)
    after = await asyncio.to_thread(hooks.inbox_pending)
    document = await asyncio.to_thread(hooks.memory_text)
    landed = MEMORY_FACT_PREFIX in document
    if after >= queued and not landed:
        return _fail(
            "The consolidator finished and the queue did not move. See the "
            "add-on log's [brain-memory] lines for why it kept the facts.",
            f"{queued} queued before, {after} after")
    if not landed:
        return _fail(
            "The queue drained and the fact is not in memory.md, so a pass "
            "consumed it without writing it down. This is the failure the "
            "Memory tab cannot see; report it with `brain report`.")

    # Cleanup, and it is the other half of the check.
    await asyncio.to_thread(hooks.queue_memory, f"FORGET: {marker}", SOURCE)
    ok, error = await _consolidate(hooks)
    document = await asyncio.to_thread(hooks.memory_text)
    if MEMORY_FACT_PREFIX in document:
        await asyncio.to_thread(hooks.drop_memory, SOURCE, f"FORGET: {marker}")
        return _fail(
            "The fact reached memory.md and could not be taken out again — "
            f"the line beginning '{MEMORY_FACT_PREFIX}' is still there and "
            "wants deleting by hand from the Memory tab.", error)
    return _ok("A fact was queued, filed into memory.md and removed again.",
               f"queue {before} → {queued} → {after}")


async def _consolidate(hooks: Hooks) -> tuple[bool, str]:
    """One consolidation pass, inside this stage's budget.

    ``wait_for`` cancels the wait, not the subprocess: the consolidator
    carries its own killer and ends by itself, so an abandoned pass is a
    thread that finishes rather than one that leaks. What the stage owes
    the person is an answer inside a budget, and that is what this is.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(hooks.consolidate), TIMEOUTS["memory"])
    except asyncio.TimeoutError:
        return False, (f"the consolidation passed its {TIMEOUTS['memory']}s "
                       "budget — it is still running in the background")


FINDING_TEXT_PREFIX = "brAIn deep check round trip"


async def stage_findings_undo(hooks: Hooks) -> dict:
    """A finding, ended, un-ended and ended for good — then nothing left.

    The one stage that spends no Claude turn at all, and the one that
    touches the most stores: the row, the settled ledger, the memory inbox
    and the in-memory undo ring. It goes through the same `_end_finding`
    the tab's buttons and the To-do app's ticks go through, because a
    second implementation would be the thing worth catching rather than
    the thing doing the catching.
    """
    text = f"{FINDING_TEXT_PREFIX} {int(time.time())}"
    key = findings_store.normalize(text)
    verb = {"kind": "ignored", "memory": "Not a problem in this home: {text}",
            "source": "correction"}
    row, created = await asyncio.to_thread(
        findings_store.add, text, source=SOURCE,
        source_title="Deep check", severity="info", fixable=False,
        detail="Written by `brain doctor --deep`; it removes itself.")
    if not created or row is None:
        await asyncio.to_thread(findings_store.unsettle, key)
        return _fail(
            "The findings store would not take a new row, so nothing that "
            "reports a problem can reach the Findings tab. `brain doctor` "
            "reports whether /data is writable.")

    try:
        _payload, fact = await hooks.end_finding(row, verb, "")
        if await asyncio.to_thread(findings_store.get, row["ts"]) is not None:
            return _fail("Ending a finding did not remove its row.")
        settled = {e.get("key") for e
                   in await asyncio.to_thread(findings_store.settled_listing)}
        if key not in settled:
            return _fail("Ending a finding did not reach the settled "
                         "ledger, so the same report would come straight "
                         "back.")

        token = undo_store.record("finding", finding=row, key=key, fact=fact,
                                  fact_source=verb["source"])
        entry = undo_store.take(token)
        if entry is None:
            return _fail("The undo token expired before it could be used.")
        restored, _payload = await hooks.undo_finding(entry)
        if not restored:
            return _fail("Undo did not put the row back.")
        settled = {e.get("key") for e
                   in await asyncio.to_thread(findings_store.settled_listing)}
        if key in settled:
            return _fail("Undo put the row back and left the settled key "
                         "behind, so the row is on the list and suppressed "
                         "at the same time.")

        again = await asyncio.to_thread(findings_store.get, row["ts"])
        if again is None:
            return _fail("The restored row is not readable from the store.")
        await hooks.end_finding(again, verb, "")
        return _ok("A finding was filed, ended, undone and ended again.",
                   f"id {row['ts']}")
    finally:
        # Verified cleanup, and it runs after a mid-stage failure too: the
        # row, the ledger entry and both memory lines go, or the stage
        # says so above.
        await asyncio.to_thread(findings_store.remove, row["ts"])
        await asyncio.to_thread(findings_store.unsettle, key)
        await asyncio.to_thread(hooks.drop_memory, verb["source"],
                                verb["memory"].format(text=text))


async def stage_fixer_dry(hooks: Hooks) -> dict:
    """The one path that can change the house, pointed at something that isn't.

    An `input_boolean` the check creates, renames through a real
    `run_agent` and renames back — the smallest change to the house that
    is genuinely a change, on an entity nothing else refers to.

    `protected_entities` is asked FIRST and answered as a skip: a list
    that covers the helper is somebody's configuration doing its job, and
    refusing to run is the correct behaviour rather than a fault.
    """
    import automation_writer  # noqa: PLC0415 — deferred: this module loads
                              # in tests that have no yaml, and the writer
                              # imports one lazily itself.
    patterns = automation_writer.protected_patterns(
        hooks.options.get("protected_entities"))
    if automation_writer.is_protected(FIXER_HELPER, patterns):
        return _skip(
            f"protected_entities covers {FIXER_HELPER}, so brAIn may not "
            "touch the helper this check renames. Nothing is wrong — the "
            "list is doing its job.",
            "patterns: " + ", ".join(patterns[:6]))

    created = await _ensure_helper(hooks)
    if created is None:
        return _fail(
            f"brAIn could not create {FIXER_HELPER} in Home Assistant, so "
            "there is nothing safe for the fixer to change. Check that the "
            "Supervisor token is valid — `brain doctor` reports it.")
    edits_before = _edit_journal_lines()

    try:
        result = await asyncio.to_thread(
            engine.run_agent, _FIXER_PROMPT, _FIXER_SYSTEM, hooks.model,
            TIMEOUTS["fixer_dry"], 12, SOURCE)
        hooks.record_usage(result, "doctor-fixer")
        if not result.get("ok"):
            bad = _engine_failure(
                result, "The fix run",
                f"the fix run passed its {TIMEOUTS['fixer_dry']}s limit "
                "and was stopped")
            return _fail(bad["sentence"], bad["detail"])
        name = await _helper_name(hooks)
        if name != FIXER_RENAMED:
            return _fail(
                "The fix run finished and the helper's name did not "
                f"change, so the one path that can change the house did "
                f"not. It reads {name!r}.",
                f"reply: {str(result.get('text') or '')[:200]}")
        edits = _edit_journal_lines() - edits_before
        detail = (f"{edits} file(s) snapshotted by the edit hook"
                  if edits else
                  "no file was edited, so the snapshot hook had nothing to "
                  "take — a registry rename is not a file change")
        return _ok("A fix run changed the house and it was verified in "
                   "Core.", detail)
    finally:
        await _delete_helper(hooks)


_FIXER_SYSTEM = (
    "You are running a connectivity check on a Home Assistant add-on. Make "
    "exactly the one change asked for, using the Home Assistant tools, and "
    "then stop. Do not touch anything else.")
_FIXER_PROMPT = (
    f"Rename the helper {FIXER_HELPER} so that its friendly name is "
    f"exactly \"{FIXER_RENAMED}\". Use the Home Assistant tools available "
    "to you. Change nothing else in the house, and reply with one short "
    "sentence saying what you did.")


async def _ensure_helper(hooks: Hooks) -> bool | None:
    """The helper, created if it is not there. ``None`` when it could not be.

    Returns whether this call created it, so the cleanup knows the
    difference between putting a name back and deleting something that was
    never anybody's.
    """
    name = await _helper_name(hooks)
    if name is not None:
        return False
    result = (await hooks.ws([{"type": "input_boolean/create",
                               "name": FIXER_HELPER_NAME}]))[0]
    if not result:
        return None
    for _ in range(20):
        if await _helper_name(hooks) is not None:
            return True
        await asyncio.sleep(0.5)
    return None


async def _helper_name(hooks: Hooks) -> str | None:
    """The helper's current friendly name, or None when it does not exist."""
    rows = (await hooks.ws([{"type": "config/entity_registry/list"}]))[0] or []
    for row in rows:
        if str(row.get("entity_id") or "") == FIXER_HELPER:
            return str(row.get("name") or row.get("original_name") or "")
    return None


async def _delete_helper(hooks: Hooks) -> None:
    """Take the helper back out, whatever happened above.

    `input_boolean/delete` keys on the object id rather than the entity id,
    which is the detail that makes a cleanup silently do nothing.
    """
    try:
        await hooks.ws([{"type": "input_boolean/delete",
                         "input_boolean_id": FIXER_HELPER.split(".", 1)[1]}])
    except Exception:  # noqa: BLE001 — the stage's answer is above; a
        # cleanup that could not run is reported by the leftover check on
        # the next plain `brain doctor`, which is where it belongs.
        pass


def _edit_journal_lines() -> int:
    try:
        import automation_writer  # noqa: PLC0415 — see stage_fixer_dry
        with automation_writer.INDEX.open("rb") as fh:
            return sum(1 for _ in fh)
    except (OSError, ImportError):
        return 0


RUNNERS = {
    "snapshot_claude": stage_snapshot_claude,
    "analyst_tools": stage_analyst_tools,
    "chat": stage_chat,
    "automation_task": stage_automation_task,
    "assist": stage_assist,
    "memory": stage_memory,
    "findings_undo": stage_findings_undo,
    "fixer_dry": stage_fixer_dry,
}


def _flag(options: dict, key: str, default: bool) -> bool:
    value = options.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

async def run_deep(hooks: Hooks, *, only: list[str] | None = None,
                   progress=None) -> dict:
    """Every stage, in order, with the ones that cannot help skipped.

    Returns ``{"started_at", "finished_at", "stages": [...], "verdict",
    "failed_stage"}``. ``progress`` — when given — is called with the
    whole payload after every stage, which is what lets the CLI print
    each line as it lands rather than a wall of them at the end.
    """
    started = time.time()
    stages: list[dict] = []
    state_by_name: dict[str, str] = {}
    payload = {"started_at": int(started), "finished_at": 0,
               "stages": stages, "verdict": "", "failed_stage": ""}

    for spec in STAGES:
        name = spec["name"]
        if only and name not in only:
            continue
        blocked = [n for n in spec["needs"] if state_by_name.get(n) != OK]
        if blocked:
            result = _skip(
                "Not run because " + ", ".join(blocked) + " did not pass — "
                "it would fail for the same reason and say so twice.")
            seconds = 0.0
        else:
            began = time.monotonic()
            try:
                result = await RUNNERS[name](hooks)
            except Exception as exc:  # noqa: BLE001 — one stage must not
                # sink the report: the whole value of this is that it says
                # what worked as well as what did not.
                result = _fail(f"The {name} check itself failed: "
                               f"{type(exc).__name__}: {str(exc)[:200]}")
            seconds = round(time.monotonic() - began, 1)
            _journal_stage(name, result, seconds)
        state_by_name[name] = result["state"]
        stages.append({"name": name, "title": spec["title"],
                       "proves": spec["proves"], "seconds": seconds,
                       **result})
        if progress is not None:
            progress(dict(payload, stages=list(stages)))

    failed = [s for s in stages if s["state"] == FAILED]
    payload["finished_at"] = int(time.time())
    payload["duration_s"] = round(time.time() - started, 1)
    payload["failed_stage"] = failed[0]["name"] if failed else ""
    payload["verdict"] = FAILED if failed else (
        SKIPPED if all(s["state"] == SKIPPED for s in stages) else OK)
    payload["counts"] = {
        OK: sum(1 for s in stages if s["state"] == OK),
        FAILED: len(failed),
        SKIPPED: sum(1 for s in stages if s["state"] == SKIPPED),
    }
    return payload


def save(payload: dict) -> None:
    """Persist the last completed run. Best effort — it is a diagnostic."""
    try:
        DEEP_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(DEEP_FILE, payload)
    except OSError:
        # The report is already on its way to whoever asked for it; this
        # copy is what the next /api/diagnostics would carry, and a
        # diagnostic that fails the thing it is diagnosing is worse.
        pass


def load() -> dict:
    try:
        data = json.loads(DEEP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def summary() -> dict:
    """What `/api/diagnostics` carries: the verdict, not the transcript.

    A deep run's stage list is a page of prose and a bug report needs the
    three facts that place it — when, what the verdict was, and which
    stage broke.
    """
    last = load()
    if not last:
        return {"ran_at": 0, "verdict": "", "failed_stage": ""}
    return {"ran_at": int(last.get("finished_at") or 0),
            "verdict": str(last.get("verdict") or ""),
            "failed_stage": str(last.get("failed_stage") or ""),
            "counts": last.get("counts") or {}}
