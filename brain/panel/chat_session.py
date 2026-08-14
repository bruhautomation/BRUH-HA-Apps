"""The chat terminal: one long-lived Claude Code session, as events.

The classic terminal is xterm over ttyd over tmux — a character grid, which
is the wrong medium for a phone. A grid cannot reflow, so at ~40 columns a
sentence breaks mid-word and a tool call spends twenty lines saying what a
chip could say in one. This module is the other half of the answer: the same
Claude Code, driven headlessly in ``stream-json`` mode, with its output
turned into a small list of typed events the panel can render as real DOM.

What it is NOT: a second brain. It is the same CLI, the same credential, the
same ``/config`` working directory and therefore the same
``/config/.claude/settings.local.json`` permissions as the Assist listener,
the Automation listener and the Findings fixer. There is one answer to "what
may Claude do here", not two.

Design notes worth keeping:

* **One session, not a pool.** The chat tab is a place, like the terminal
  tab is a place. Two people opening the panel are looking at the same
  conversation, the same way they would be looking at the same tmux.

* **The transcript is ours, not the CLI's.** Claude Code owns the real
  conversation (and resumes it by ``session_id``); we keep a normalised,
  capped copy so a reload can repaint the screen without asking the model
  anything. Losing it costs a scrollback, never context.

* **Events are normalised at the boundary.** The CLI's stream-json shape is
  a moving target across versions; everything that knows about
  ``message.content[].type`` lives in ``_normalise`` and nothing downstream
  does. An event we do not recognise is dropped rather than rendered raw.

* **Stopping is two-stage.** A ``control_request`` interrupt is the polite
  way and is what a recent CLI supports; if the turn has not ended shortly
  after, the process is killed and respawned with ``--resume``. The context
  survives either way, because the CLI wrote it down.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import engine

import atomic_write

# Where the chat runs. /config so the project's settings.local.json (the
# permission set) and CLAUDE.md (the description of this house) both apply —
# the same working directory the listeners use.
WORK_DIR = os.environ.get("BRAIN_CHAT_WORKDIR", "/config")

# The transcript we keep for repainting a reloaded page. Capped hard: this
# is a scrollback, and an unbounded one in a long-lived process is a leak
# with a friendly name.
TRANSCRIPT_FILE = os.environ.get(
    "BRAIN_CHAT_TRANSCRIPT", "/data/chat_transcript.json")
MAX_EVENTS = 600

# Published context windows. Used ONLY to turn a token count into a
# percentage — an unknown model reports its tokens and no percentage, rather
# than a percentage of a window we guessed at.
#
# **The window is a property of the model version, not of the family.** It
# used to be a substring table where every Opus and every Sonnet was 200K,
# which was true when it was written and is now wrong for every model the
# add-on actually runs: Opus and Sonnet went to 1M at 4.6, so a real
# conversation routinely reported "600k / 200k context · 300%". A family
# name alone cannot answer this question, so the version is parsed too and a
# model whose version we cannot read reports no window at all.
WINDOW_1M = 1_000_000
WINDOW_200K = 200_000

# Families whose window depends on the version, and the version at which
# they went to 1M. Haiku is deliberately absent: 4.5 is 200K and there is no
# published 1M Haiku, so it is handled as a flat 200K below.
LONG_CONTEXT_FAMILIES = ("opus", "sonnet", "fable", "mythos")
LONG_CONTEXT_SINCE = (4, 6)

_FAMILIES = "opus|sonnet|haiku|fable|mythos"
# Two orders exist in the wild and both have to parse: `claude-opus-4-8`,
# `claude-sonnet-5`, `claude-haiku-4-5-20251001` put the version *after* the
# family; the 3.x ids (`claude-3-5-sonnet-20241022`) put it before. The minor
# is capped at two digits and followed by a non-digit so a trailing date
# stamp (`claude-opus-4-20250514`) reads as version 4, not version 4.20250514.
_VER_AFTER = re.compile(rf"({_FAMILIES})-?(\d{{1,2}})(?:[-.](\d{{1,2}})(?![0-9]))?")
_VER_BEFORE = re.compile(rf"(\d{{1,2}})(?:[-.](\d{{1,2}}))?-({_FAMILIES})")

# Escape hatch for a model that ships before this table learns about it: set
# it and the panel uses that number for every model. Not a config option —
# the right answer is a code change, and this exists so nobody is stuck
# waiting for one.
WINDOW_OVERRIDE = int(os.environ.get("BRAIN_CONTEXT_WINDOW", "0") or 0)


def model_version(model: str) -> tuple[int, int] | None:
    """(major, minor) parsed out of a resolved model id, or None."""
    lowered = (model or "").lower()
    match = _VER_BEFORE.search(lowered)
    if match:
        return int(match.group(1)), int(match.group(2) or 0)
    match = _VER_AFTER.search(lowered)
    if match:
        return int(match.group(2)), int(match.group(3) or 0)
    return None


def pretty_model(model: str) -> str:
    """`claude-haiku-4-5-20251001` → `Claude Haiku 4.5`.

    Derived here rather than in the panel because the version has to be
    parsed to do it, and that parser already exists for the context window.
    A second copy in JavaScript is a second answer waiting to drift from
    this one, and it did: it read `claude-haiku-4-5` as "Claude Haiku 4"
    and `claude-3-5-sonnet-20241022` as "Claude Sonnet 2" (the date's
    leading digits, taken for a version). The label under the composer is
    the only confirmation a model pick landed, so two models of one family
    printing the same name reads exactly like a picker that does nothing.

    A family we cannot find returns the id verbatim — a made-up pretty name
    for a model id we do not recognise is worse than the id.
    """
    lowered = (model or "").strip().lower()
    family = next((f for f in _FAMILIES.split("|") if f in lowered), "")
    if not family:
        return (model or "").strip()
    version = model_version(lowered)
    name = f"Claude {family.capitalize()}"
    if version is None:
        # A bare tier alias (`opus`) — no version to print, and it is the
        # honest answer: the alias is whatever the account resolves it to.
        return name
    major, minor = version
    return f"{name} {major}.{minor}" if minor else f"{name} {major}"


def context_window(model: str) -> int:
    """The context window for a resolved model id, or 0 if we don't know."""
    if WINDOW_OVERRIDE > 0:
        return WINDOW_OVERRIDE
    lowered = (model or "").lower()
    if "haiku" in lowered:
        return WINDOW_200K
    if not any(family in lowered for family in LONG_CONTEXT_FAMILIES):
        return 0
    version = model_version(lowered)
    if version is None:
        # A family we know and a version we cannot read is still a guess, and
        # the two candidate answers are 5× apart.
        return 0
    return WINDOW_1M if version >= LONG_CONTEXT_SINCE else WINDOW_200K

# A single tool result can be a whole file. The panel shows a preview and
# offers the rest on request, so what we keep is bounded too.
MAX_RESULT_CHARS = 4000
MAX_TEXT_CHARS = 60000

# In stream-json mode the turn cap spans the life of the process rather than
# one exchange, so it is a runaway guard, not a per-answer budget.
MAX_TURNS = int(os.environ.get("BRAIN_CHAT_MAX_TURNS", "400"))

# How long to wait for a polite interrupt before killing the process.
INTERRUPT_GRACE = 5.0

# How long a freshly spawned CLI gets to say its first word before we stop
# watching. The CLI announces itself (system/init) within a couple of
# seconds; a process that DIES inside this window died on startup — which
# with `--resume` on the argv almost always means the conversation is gone
# from the CLI's store (pruned by cleanupPeriodDays, or written by an
# incompatible version). A slow start that merely outlives the window is
# treated as fine, exactly as it was before the window existed.
START_GRACE = float(os.environ.get("BRAIN_CHAT_START_GRACE", "10"))

# How long an approval card may sit unanswered before the call is declined
# on the person's behalf. The interactive CLI waits forever, but a TTY has
# somebody in front of it by definition — a chat tab may have been closed
# mid-turn, and a turn that can never end is worse than a denial that says
# who made it and why.
PERMISSION_TIMEOUT = float(os.environ.get("BRAIN_CHAT_PERMISSION_TIMEOUT", "600"))

# A tool call the permission set refused fails like any other tool call, and
# "that broke" and "brAIn was not allowed to do that" are different things to
# be told — the first sends you debugging, the second sends you to Settings.
# Headless `-p` cannot prompt, so a refusal here is final: the call never
# ran, and the next thing Claude says is written around a gap it could not
# fill. The panel needs to be able to say which happened.
#
# The signal is the CLI's own wording, because nothing structured comes back
# on this path. That makes the match deliberately narrow: **bare "permission
# denied" is not on this list**, because that is what the kernel says when a
# perfectly permitted `Bash` call touches a file it cannot read, and calling
# an ordinary EACCES a policy decision is a worse lie than staying quiet. A
# missed denial reads as an error, which is what it read as before.
_DENIED_RE = re.compile(
    r"requested permissions?"          # "Claude requested permissions to use Bash"
    r"|n[o']t granted"                 # "…but you haven't granted it yet"
    r"|not allowed to (?:use|run)"
    r"|declined to answer",            # a skipped question card — ours, below
    re.I,
)

# The one tool whose "permission request" is really the question itself.
# Interactively the CLI draws its own picker for it; headlessly the request
# arrives as `can_use_tool` like any other, and the *answers* ride back in
# `updatedInput` — the CLI's own permission component does exactly this
# (`{...input, answers: {"<question text>": "<answer>"}}`, multi-select
# comma-separated), so a generic Allow button used to send the tool an empty
# answer sheet and the turn fell over. The panel renders it as a question
# card instead, and the allow path refuses to run without the answers.
QUESTION_TOOL = "AskUserQuestion"

# Tool calls whose "arguments" are really the interesting content, so the
# chip shows that rather than a JSON blob.
_TOOL_SUMMARY_KEYS = (
    "file_path", "path", "pattern", "command", "url", "query",
    "entity_id", "prompt", "description", "notebook_path",
)


def _clip(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "\n… (truncated)"


def question_spec(args: dict) -> list[dict] | None:
    """The questions inside an AskUserQuestion call, in display shape.

    Defensive on purpose: the input is model-written and schema-validated by
    the CLI, but this parses it a second time because a malformed question
    must degrade to the ordinary permission card, never to a card the panel
    cannot draw. None means "not renderable as questions" and the caller
    falls back exactly there.
    """
    raw = args.get("questions")
    if not isinstance(raw, list) or not raw:
        return None
    questions = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        if not text:
            continue
        options = []
        for opt in (item.get("options") or [])[:8]:
            if not isinstance(opt, dict):
                continue
            label = str(opt.get("label") or "").strip()
            if not label:
                continue
            options.append({
                "label": _clip(label, 200),
                "description": _clip(
                    str(opt.get("description") or "").strip(), 500),
            })
        questions.append({
            "question": _clip(text, 1000),
            "header": _clip(str(item.get("header") or "").strip(), 60),
            "options": options,
            "multi": bool(item.get("multiSelect")),
        })
    return questions or None


def tool_summary(name: str, args: dict) -> str:
    """One line describing a tool call, for the collapsed chip.

    The first recognised argument wins, because tool calls are overwhelmingly
    "do this thing to that one named object" — and the name of the object is
    the only part a reader scanning the transcript is looking for.
    """
    if not isinstance(args, dict):
        return ""
    for key in _TOOL_SUMMARY_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return _clip(value.strip().splitlines()[0], 200)
    for value in args.values():
        if isinstance(value, str) and value.strip():
            return _clip(value.strip().splitlines()[0], 200)
    return ""


class ChatSession:
    """One live ``claude`` process, plus the transcript of what it said."""

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.session_id: str | None = None
        # What the CLI says about itself at startup: the model it resolved,
        # the directory it considers the project (which is what
        # `claude --resume` keys conversations by), its version, and whether
        # an API key is paying — see `_session_info`.
        self.info: dict = {}
        # Its slash commands, as it advertises them. Ours to display, not to
        # invent: a hardcoded list goes stale the moment someone adds a
        # command to /config/.claude/commands.
        self.commands: list[dict] = []
        # Set by the server from the same effective-model resolution every
        # other Claude path uses; kept as a plain attribute rather than an
        # import so this module never depends on the web layer.
        self.model = os.environ.get("BRAIN_MODEL", "")
        self.events: list[dict] = []
        # How much of the window the conversation is currently occupying.
        # {"tokens": int, "window": int} — window 0 when the model is one we
        # have no published figure for. Read off the CLI's own usage report
        # for the last turn, because the prompt it sent IS the context.
        self.context: dict = {}
        self.state = "idle"          # idle | starting | ready | busy | error
        self.error = ""
        self._subs: set[asyncio.Queue] = set()
        self._seq = 0
        self._lock = asyncio.Lock()
        self._reader: asyncio.Task | None = None
        self._busy_since = 0.0
        # Set per spawn, the moment the CLI produces any event at all. A
        # process that exits before this is a process that failed to start,
        # which is a different fact from one that died mid-conversation.
        self._first_event: asyncio.Event = asyncio.Event()
        # True when the last start() had to abandon a --resume id and open a
        # fresh session instead. resume() reads it to answer honestly.
        self.resume_fell_back = False
        # The model the LIVE process was actually spawned with. `self.model`
        # is intent — the server refreshes it from settings on every request —
        # and a long-lived process does not follow intent, it follows its
        # argv. Comparing a pick against intent is how the picker learned to
        # answer "already that model" about a process still running the old
        # one; every "is a restart needed" question is asked of this instead.
        self._spawned_model: str | None = None
        # Set when the CLI reports a state only a respawn clears (the turn
        # cap). The next send restarts with --resume first, so the counter
        # resets and the conversation carries on.
        self._respawn_pending = False
        # The approval the turn is waiting on, if any: what the panel's card
        # renders, and — via ``_pending_input`` — the untouched tool input the
        # allow answer must hand back (the CLI validates it against the
        # tool's schema, so the clipped display copy must never go).
        self.pending_permission: dict | None = None
        self._pending_input: dict = {}
        self._permission_timer: asyncio.Task | None = None
        # Cleared when the CLI rejects `--permission-prompt-tool stdio` at
        # startup (a version from before the value existed): the chat then
        # runs exactly as it did before the round-trip — refusals are final
        # and amber — instead of not running at all.
        self._prompt_tool_ok = True
        self._load()

    # -- transcript ------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(Path(TRANSCRIPT_FILE).read_text("utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            events = data.get("events")
            if isinstance(events, list):
                self.events = [e for e in events if isinstance(e, dict)][-MAX_EVENTS:]
                self._seq = max((e.get("seq") or 0) for e in self.events) if self.events else 0
            if isinstance(data.get("session_id"), str):
                self.session_id = data["session_id"]

    def _persist(self) -> None:
        path = Path(TRANSCRIPT_FILE)
        try:
            atomic_write.write_json(
                path, {"session_id": self.session_id, "events": self.events})
        except OSError:
            pass  # a lost scrollback is not worth failing a turn over

    def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "events": self.events,
            "state": self.state,
            "error": self.error,
            "session_id": self.session_id,
            "info": self.info,
            "commands": self.commands,
            "context": self.context,
            # A reload mid-approval must repaint the card, or the turn sits
            # "busy" over a question that is no longer on anyone's screen.
            "permission": self.pending_permission,
        }

    # -- subscribers -----------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        # Bounded: a browser tab that stopped reading (a suspended phone,
        # usually) must not grow a queue until the add-on runs out of memory.
        # An overflowing subscriber is dropped and reconnects to a snapshot,
        # which is strictly better than losing the process it was watching.
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def _emit(self, event: dict, *, keep: bool = True) -> dict:
        self._seq += 1
        event["seq"] = self._seq
        event.setdefault("ts", time.time())
        if keep:
            self.events.append(event)
            if len(self.events) > MAX_EVENTS:
                del self.events[:len(self.events) - MAX_EVENTS]
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # A subscriber this far behind is not consuming. Dropping
                # the queue alone left its stream awaiting a queue nothing
                # would ever feed again — an open connection carrying only
                # pings, which the client reads as "live" while receiving
                # nothing. Swap its oldest buffered event for a poison pill
                # so the stream ends and the client reconnects to a fresh
                # snapshot.
                self._subs.discard(q)
                try:
                    q.get_nowait()
                    q.put_nowait({"event": "__overflow__"})
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    # Raced by the consumer waking up: either it drained the
                    # queue (Empty) or refilled it (Full). Both mean it is
                    # alive after all — no pill needed; unsubscribing was
                    # already done and the stream ends on its own.
                    pass
        return event

    def _take_context(self, usage: object) -> None:
        """Record how full the context is, from one model call's usage.

        The CLI reports what it *sent*, and what it sent is the conversation
        so far — so that call's input tokens are the context in use. Cache
        reads count: a cached prompt is still occupying the window, it is
        just cheaper. Output does not, until it comes back as input on the
        next call, which it will and this will then say so.

        **One call, never the turn.** This used to read the `result` event,
        whose `usage` is the whole turn added up — every model call the CLI
        made while working, each of which re-sent the conversation. A turn
        that ran ten tools therefore reported roughly ten conversations'
        worth of tokens, which is how the pill came to claim several times
        the window it was measuring against. The per-call number lives on
        the `assistant` event, so that is what feeds this; a turn now
        reports the same size whether it took one tool call or thirty.
        """
        if not isinstance(usage, dict):
            return
        tokens = sum(
            value for key, value in usage.items()
            if key in ("input_tokens", "cache_read_input_tokens",
                       "cache_creation_input_tokens")
            and isinstance(value, int) and value > 0
        )
        if tokens <= 0:
            return
        model = (self.info.get("model") or self.model or "")
        context = {"tokens": tokens, "window": context_window(model)}
        if context != self.context:
            self.context = context
            self._emit({"type": "context", **context}, keep=False)

    def _rewindow(self) -> None:
        """Re-derive the window after the CLI announces which model it is.

        The token count is a fact about the conversation and survives a
        model change — the conversation does, that is what --resume is for.
        The *window* is a fact about the model, so a pick that moves from
        Sonnet to Haiku leaves the pill dividing by 1M when the answer is
        200K: it read "42k / 1000k · 4%" for a window it fills 21% of, and
        it stayed wrong until the next turn happened to refresh it. A
        percentage against the wrong denominator is the failure this pill
        was rewritten to stop making, so it is corrected the moment the new
        process says what it is.
        """
        tokens = self.context.get("tokens") or 0
        if tokens <= 0:
            return
        window = context_window(self.info.get("model") or self.model or "")
        if window == self.context.get("window"):
            return
        self.context = {"tokens": tokens, "window": window}
        self._emit({"type": "context", **self.context}, keep=False)

    def _set_commands(self, commands: list) -> None:
        clean = []
        for item in commands:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            # Internal plumbing the CLI exposes but nobody types.
            if name.startswith("__"):
                continue
            clean.append({
                "name": name,
                "description": _clip(item.get("description") or "", 300),
                "hint": _clip(item.get("argumentHint") or "", 60),
            })
        clean.sort(key=lambda c: c["name"])
        if clean == self.commands:
            return
        self.commands = clean
        self._emit({"type": "commands", "commands": clean}, keep=False)

    def _set_state(self, state: str, error: str = "") -> None:
        self.state = state
        self.error = error
        # Not kept in the transcript: state is a fact about now, and a
        # replayed "busy" from last Tuesday is a spinner that never stops.
        self._emit({"type": "state", "state": state, "error": error}, keep=False)

    # -- process ---------------------------------------------------------

    def _argv(self) -> list[str]:
        argv = engine._claude_argv() + [
            "-p",
            "--verbose",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--max-turns", str(MAX_TURNS),
        ]
        if self._prompt_tool_ok:
            # "stdio" routes permission questions back up this pipe as
            # `can_use_tool` control requests — the same wire the Agent SDK's
            # canUseTool callback rides — so a call outside the allow-list
            # becomes a question on the person's screen instead of a silent
            # refusal Claude writes around. Rules still short-circuit: the
            # CLI only asks where the interactive TUI would have prompted.
            argv += ["--permission-prompt-tool", "stdio"]
        if self.model:
            # Kept on the argv even when resuming: a resumed session
            # otherwise continues on the model it remembers, which is the
            # opposite of what a person who just picked one meant. Empty
            # means "the CLI's own choice" — there is nothing to pass, so a
            # resume then does keep the conversation's model.
            argv += ["--model", self.model]
        if self.session_id:
            argv += ["--resume", self.session_id]
        return argv

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> None:
        """Spawn the CLI, resuming the previous conversation if there is one.

        A resume that fails (the CLI's session store was cleared, or the
        conversation is from an incompatible version) is not fatal: it falls
        back to a fresh session, because a chat tab that refuses to open is
        worse than one that has forgotten last week. That fallback is real,
        not aspirational: the spawn is watched until the CLI says its first
        word, and a process that dies before speaking while `--resume` was
        on its argv has its id dropped and is respawned fresh — with a
        notice in the transcript, because a conversation silently losing
        its context is worse than one that says it has.
        """
        async with self._lock:
            if self.alive():
                return
            self.resume_fell_back = False
            self._set_state("starting")
            if not await self._spawn_watched():
                return
            # A process's stderr can only be read once, and three branches
            # below want it — so a dead spawn's tail is taken here and
            # carried, not re-read.
            detail = ""
            if not self._first_event.is_set() and not self.alive():
                detail = await self._stderr_tail(self.proc)
                if self._prompt_tool_ok and "permission-prompt-tool" in detail:
                    # A CLI from before `--permission-prompt-tool stdio`
                    # existed refuses it at startup and names the flag on
                    # stderr. That loses the approval round-trip, not the
                    # chat: drop the flag for this add-on run and try again.
                    self._prompt_tool_ok = False
                    if not await self._spawn_watched():
                        return
                    detail = "" if self._first_event.is_set() or self.alive() \
                        else await self._stderr_tail(self.proc)
            if not self._first_event.is_set() and self.session_id \
                    and not self.alive():
                # Died before speaking, with --resume on the argv: the CLI
                # no longer has this conversation. Fall back to a fresh
                # session rather than leaving a chat tab that cannot open.
                self.resume_fell_back = True
                self.session_id = None
                self._emit({"type": "notice", "text":
                            "Claude Code could not resume this conversation"
                            + (f" ({detail})" if detail else "")
                            + ". The transcript above is still shown, but the "
                            "next message starts a fresh session without its "
                            "context."})
                self._persist()
                if not await self._spawn_watched():
                    return
            if not self.alive() and not self._first_event.is_set():
                # Died before speaking with nothing to resume: a startup
                # failure, and the stderr tail is the only witness. (After a
                # resume fallback this is a new process whose stderr is still
                # unread; on the same process the earlier read is carried.)
                detail = await self._stderr_tail(self.proc) or detail
                self._set_state(
                    "error", detail or "Claude exited before it was ready.")
                return
            self._set_state("ready")

    async def _spawn_watched(self) -> bool:
        """Spawn, then wait for the CLI's first event, its death, or a
        deadline — whichever comes first. False only when the spawn itself
        raised (the state is already set to say so)."""
        try:
            await self._spawn()
        except FileNotFoundError:
            self._set_state("error", "The Claude CLI was not found in this add-on.")
            return False
        except OSError as exc:
            self._set_state("error", f"Could not start Claude: {exc}")
            return False
        proc = self.proc
        assert proc is not None
        waiters = [asyncio.ensure_future(self._first_event.wait()),
                   asyncio.ensure_future(proc.wait())]
        try:
            await asyncio.wait(waiters, timeout=START_GRACE,
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in waiters:
                task.cancel()
        return True

    async def _stderr_tail(self, proc) -> str:
        """Whatever the CLI managed to say on stderr, bounded both ways."""
        if proc is None or proc.stderr is None:
            return ""
        try:
            raw = await asyncio.wait_for(proc.stderr.read(), 2)
            return raw.decode("utf-8", "replace").strip()[-400:]
        except (asyncio.TimeoutError, ValueError, OSError):
            return ""

    async def _spawn(self) -> None:
        self._first_event = asyncio.Event()
        self._drop_pending_permission()
        self._respawn_pending = False
        self.proc = await asyncio.create_subprocess_exec(
            *self._argv(),
            cwd=WORK_DIR if os.path.isdir(WORK_DIR) else None,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=engine._claude_env(),
            limit=1024 * 1024,
        )
        # What this process actually runs, as distinct from what the panel
        # currently wants — see set_model() and send() for who compares them.
        self._spawned_model = self.model
        self._reader = asyncio.create_task(
            self._read_loop(self.proc, self._first_event))
        if self._prompt_tool_ok:
            # The SDK's opening move, and what turns the permission flag on:
            # without an initialize the CLI has no client it trusts to answer
            # `can_use_tool`, so it never asks. Best effort — a CLI that
            # ignores it simply never asks either, which is the old behavior.
            try:
                assert self.proc.stdin is not None
                self.proc.stdin.write((json.dumps({
                    "type": "control_request",
                    "request_id": f"init-{int(time.time() * 1000)}",
                    "request": {"subtype": "initialize"},
                }) + "\n").encode())
                await self.proc.stdin.drain()
            except (OSError, ConnectionResetError, AssertionError):
                # The process is already gone; start() is about to find out.
                pass

    async def _read_loop(self, proc: asyncio.subprocess.Process,
                         first_event: asyncio.Event) -> None:
        assert proc.stdout is not None
        try:
            while True:
                try:
                    line = await proc.stdout.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    # One oversized line (a tool result bigger than the
                    # stream limit). Skip it rather than tearing down a
                    # working session.
                    continue
                if not line:
                    break
                raw = line.decode("utf-8", "replace").strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                # Any parsed event proves the process came up. Not just
                # init: which event a given CLI version sends first is its
                # business, and the watcher only asks "did it speak". Bound
                # per spawn, so a reader winding down after a respawn cannot
                # vouch for a process it never read.
                first_event.set()
                sid = event.get("session_id")
                if isinstance(sid, str) and sid:
                    self.session_id = sid
                # The permission round-trip rides the control channel, not
                # the transcript: the CLI asks, a person answers, and only
                # the tool call's eventual result is conversation.
                if event.get("type") == "control_request":
                    request = event.get("request") or {}
                    if request.get("subtype") == "can_use_tool":
                        self._take_permission_request(event)
                    else:
                        # Anything else the CLI asks over this channel gets
                        # an honest error back, never silence: a control
                        # request is a question the CLI is *waiting on*, and
                        # dropping one from a newer CLI is how a turn hangs
                        # forever on a feature this panel has never heard of.
                        self._refuse_control(event)
                    continue
                if event.get("type") == "control_cancel_request":
                    # The CLI withdrew the question (the turn was
                    # interrupted, usually). A card for it would be a
                    # question nobody is asking anymore.
                    rid = str(event.get("request_id") or "")
                    if self.pending_permission \
                            and self.pending_permission.get("id") == rid:
                        self._drop_pending_permission()
                    continue
                # Two events describe the session rather than the
                # conversation. They are state, not transcript — kept on the
                # session and sent live, so a reconnect gets them in the
                # snapshot instead of waiting for the CLI to repeat itself.
                if event.get("type") == "system":
                    if event.get("subtype") == "init":
                        self.info = _session_info(event)
                        self._emit({"type": "info", "session_id": self.session_id,
                                    **self.info}, keep=False)
                        self._rewindow()
                        if not self.commands and event.get("slash_commands"):
                            self._set_commands([
                                {"name": name} for name in event["slash_commands"]
                                if isinstance(name, str)])
                    elif event.get("subtype") == "commands_changed":
                        self._set_commands(event.get("commands") or [])
                if event.get("type") == "assistant":
                    # Per-call usage — see _take_context on why the turn's
                    # own total is the wrong number here.
                    self._take_context(
                        (event.get("message") or {}).get("usage"))
                for norm in _normalise(event):
                    # Deltas and run stats are live-only: the assistant event
                    # that follows carries the same text as a whole block, so
                    # keeping both would double every answer in the
                    # transcript a reload repaints.
                    self._emit(norm, keep=norm.pop("_keep", True))
                if event.get("type") == "result":
                    if event.get("subtype") == "error_max_turns":
                        # The cap spans this process, however this CLI counts
                        # turns — so only a respawn clears it. Marked here,
                        # applied by the next send(): a restart with --resume
                        # resets the counter and the conversation carries on.
                        self._respawn_pending = True
                    self._busy_since = 0.0
                    self._set_state("ready")
                    self._persist()
        finally:
            # Only the *current* process reports; a reader still winding down
            # after stop() must not overwrite the state its replacement set.
            if proc is self.proc:
                was_busy = self.state == "busy"
                self._busy_since = 0.0
                self._drop_pending_permission()
                if was_busy:
                    # An exit while the user was waiting is a failed turn and
                    # has to say so, with whatever the CLI put on stderr.
                    detail = ""
                    if proc.stderr is not None:
                        try:
                            raw = await asyncio.wait_for(proc.stderr.read(), 2)
                            detail = raw.decode("utf-8", "replace").strip()[-400:]
                        except (asyncio.TimeoutError, ValueError):
                            # Nothing on stderr inside the timeout. The state set below still
                            # reports the failure, just without a detail line.
                            pass
                    self._set_state("error", detail or "The Claude session ended.")
                else:
                    # An exit while idle is just a session that ended.
                    self._set_state("idle")
                self._persist()

    # -- turns -----------------------------------------------------------

    async def send(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError("message too long")
        if self.alive() and self.state == "busy":
            raise RuntimeError("Claude is still answering — stop it first")
        if self.alive() and (self._respawn_pending
                             or self.model != self._spawned_model):
            # The process no longer matches what the panel wants of it — a
            # model chosen in ⚙ or the picker while it was live, or a turn
            # cap only a respawn clears. Both are argv-shaped problems, and
            # the CLI's own store carries the conversation across the
            # restart, exactly as interrupt() already relies on.
            await self.stop()
        if not self.alive():
            await self.start()
        if not self.alive():
            raise RuntimeError(self.error or "the Claude session is not running")
        if self.state == "busy":
            raise RuntimeError("Claude is still answering — stop it first")

        self._emit({"type": "user", "text": text})
        self._persist()
        payload = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        }) + "\n"
        assert self.proc is not None and self.proc.stdin is not None
        try:
            self.proc.stdin.write(payload.encode())
            await self.proc.stdin.drain()
        except (OSError, ConnectionResetError) as exc:
            self._set_state("error", f"Could not reach the Claude session: {exc}")
            raise RuntimeError(self.error) from exc
        self._busy_since = time.time()
        self._set_state("busy")
        return {"ok": True}

    # -- permissions -----------------------------------------------------

    def _take_permission_request(self, event: dict) -> None:
        """A `can_use_tool` control request: the CLI is asking a person.

        One at a time by construction — the CLI blocks the turn on the
        answer — so a second request while one is pending simply replaces
        it (the first has by then been cancelled or answered).
        """
        request = event.get("request") or {}
        request_id = str(event.get("request_id") or "")
        if not request_id:
            return
        args = request.get("input") if isinstance(request.get("input"), dict) \
            else {}
        self._drop_pending_permission()
        # The raw input is kept aside for the allow answer: the CLI
        # validates `updatedInput` against the tool's schema, so the clipped
        # display copy below must never be what goes back.
        self._pending_input = args
        tool = request.get("tool_name") or "tool"
        # AskUserQuestion is a question wearing a permission request's
        # clothes: render the questions, not a JSON blob with an Allow
        # button that would answer them with nothing. A malformed one falls
        # through to the ordinary card, which at least fails loudly.
        questions = question_spec(args) if tool == QUESTION_TOOL else None
        self.pending_permission = {
            "id": request_id,
            "tool": tool,
            "kind": "question" if questions else "permission",
            "questions": questions or [],
            "summary": "" if questions else tool_summary(tool, args),
            "input": "" if questions else _clip(
                json.dumps(args, ensure_ascii=False, indent=2),
                MAX_RESULT_CHARS),
        }
        # Live-only: the answered question's tool result is the transcript.
        self._emit({"type": "permission", **self.pending_permission},
                   keep=False)
        self._permission_timer = asyncio.create_task(
            self._permission_expiry(request_id))

    async def _permission_expiry(self, request_id: str) -> None:
        await asyncio.sleep(PERMISSION_TIMEOUT)
        if self.pending_permission \
                and self.pending_permission.get("id") == request_id:
            try:
                await self.respond_permission(request_id, False, timed_out=True)
            except (ValueError, RuntimeError):
                # Answered or died in the same instant — either way the
                # question is no longer waiting.
                pass

    async def respond_permission(self, request_id: str, allow: bool,
                                 timed_out: bool = False,
                                 answers: dict | None = None) -> dict:
        """Answer the pending approval, on the wire the CLI asked on.

        An allow hands back the tool's own input untouched; a deny carries
        a sentence the model reads, phrased so the eventual tool_result
        matches ``_DENIED_RE`` and renders amber rather than as a crash.

        A question card is the same wire with one addition: the person's
        ``answers`` (question text → answer string, multi-select
        comma-separated) go back inside ``updatedInput``, which is where the
        CLI's own permission component puts them. Allowing a question with
        no answers is refused here rather than sent — that is the exact
        empty answer sheet this card exists to prevent.
        """
        pending = self.pending_permission
        if not pending or pending.get("id") != request_id:
            raise ValueError("that request is no longer waiting")
        if not self.alive():
            self._drop_pending_permission()
            raise RuntimeError("the Claude session is not running")
        is_question = pending.get("kind") == "question"
        if allow and is_question:
            clean = {str(k): str(v) for k, v in (answers or {}).items()
                     if str(k).strip() and str(v).strip()}
            if not clean:
                raise ValueError("answer the questions first")
            answer: dict = {"behavior": "allow",
                            "updatedInput": {**self._pending_input,
                                             "answers": clean}}
        elif allow:
            answer = {"behavior": "allow",
                      "updatedInput": self._pending_input}
        elif is_question:
            who = ("Nobody was there to answer"
                   if timed_out else "The person watching the chat")
            answer = {"behavior": "deny", "message":
                      f"{who} declined to answer the questions — carry on "
                      "with your best judgement instead of asking again."}
        else:
            who = ("Nobody answered the approval request in time"
                   if timed_out else "The person watching the chat declined")
            answer = {"behavior": "deny", "message":
                      f"{who} — Claude requested permissions to use "
                      f"{pending.get('tool') or 'this tool'} and it was "
                      "not granted."}
        payload = json.dumps({
            "type": "control_response",
            "response": {"subtype": "success", "request_id": request_id,
                         "response": answer},
        }) + "\n"
        try:
            assert self.proc is not None and self.proc.stdin is not None
            self.proc.stdin.write(payload.encode())
            await self.proc.stdin.drain()
        except (OSError, ConnectionResetError, AssertionError) as exc:
            self._drop_pending_permission()
            raise RuntimeError(f"could not reach the Claude session: {exc}") \
                from exc
        self._drop_pending_permission(answered=True, allowed=allow)
        return {"ok": True, "id": request_id, "allow": allow}

    def _refuse_control(self, event: dict) -> None:
        """Decline a control request this panel does not implement.

        The error goes back on the wire so the CLI can fail that one
        feature and carry on with the turn — the alternative is a request
        that never resolves, which from the chat looks like Claude thinking
        forever. Best effort: if the pipe is gone the process is too, and
        the read loop is about to notice.
        """
        request_id = event.get("request_id")
        if not request_id or self.proc is None or self.proc.stdin is None:
            return
        subtype = str((event.get("request") or {}).get("subtype") or "unknown")
        try:
            self.proc.stdin.write((json.dumps({
                "type": "control_response",
                "response": {"subtype": "error", "request_id": request_id,
                             "error": "the brAIn chat does not support "
                                      f"'{subtype}' requests"},
            }) + "\n").encode())
        except (OSError, ConnectionResetError):
            # The pipe is gone, so the process is too — the read loop is
            # about to notice and set the state; nothing to add here.
            pass

    def _drop_pending_permission(self, answered: bool = False,
                                 allowed: bool = False) -> None:
        """Clear the card everywhere a viewer might still be holding it."""
        timer, self._permission_timer = self._permission_timer, None
        if timer is not None:
            try:
                if timer is not asyncio.current_task():
                    timer.cancel()
            except RuntimeError:
                # No running loop (a synchronous caller in a test): the
                # timer never started ticking anywhere it could fire.
                timer.cancel()
        pending, self.pending_permission = self.pending_permission, None
        self._pending_input = {}
        if pending:
            self._emit({"type": "permission_done", "id": pending.get("id"),
                        "answered": answered, "allow": allowed}, keep=False)

    async def interrupt(self) -> dict:
        """Politely, then not.

        The control request is what a current CLI answers; older ones ignore
        it silently, which is indistinguishable from "still thinking". So the
        grace period is short and the fallback is unconditional — and because
        the CLI persists the conversation itself, respawning with --resume
        picks it back up where the last completed turn left it.
        """
        if not self.alive():
            return {"ok": True, "method": "none"}
        try:
            assert self.proc is not None and self.proc.stdin is not None
            self.proc.stdin.write((json.dumps({
                "type": "control_request",
                "request_id": f"int-{int(time.time() * 1000)}",
                "request": {"subtype": "interrupt"},
            }) + "\n").encode())
            await self.proc.stdin.drain()
        except (OSError, ConnectionResetError, AssertionError):
            # The pipe is already closed, so the interrupt cannot be delivered —
            # which is what the kill-and-resume below exists for.
            pass
        deadline = time.time() + INTERRUPT_GRACE
        while time.time() < deadline:
            if self.state != "busy":
                return {"ok": True, "method": "interrupt"}
            await asyncio.sleep(0.2)
        await self.stop()
        self._emit({"type": "notice", "text": "Stopped."})
        await self.start()
        return {"ok": True, "method": "restart"}

    async def stop(self) -> None:
        proc, self.proc = self.proc, None
        # A question the killed process asked can never be answered now.
        self._drop_pending_permission()
        if self._reader:
            self._reader.cancel()
            self._reader = None
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except (OSError, ProcessLookupError):
                # The process ended between the check and the kill. That is the
                # outcome being asked for.
                pass
        self._busy_since = 0.0
        self._set_state("idle")

    async def handoff(self) -> dict:
        """Release this conversation so the classic terminal can take it up.

        Claude Code stores the conversation itself and resumes it by id, so
        "continue in the terminal" is just `claude --resume <id>` in the same
        project directory. Two things have to be true first, and this does
        both: the id has to be known to the person typing it, and *we* have
        to stop holding the session open.
        """
        session_id = self.session_id
        cwd = self.info.get("cwd") or WORK_DIR
        await self.stop()
        opened = _open_in_terminal(session_id) if session_id else False
        return {
            "ok": True,
            "session_id": session_id,
            "cwd": cwd,
            "opened": opened,
            "command": f"claude --resume {session_id}" if session_id else "claude",
        }

    async def resume(self, session_id: str, replay: list[dict]) -> dict:
        """Take up an existing conversation — including one from the terminal.

        This is what makes the two faces interchangeable rather than merely
        adjacent. Claude Code holds the conversation and resumes it by id;
        ``replay`` is its stored transcript rendered into our event shapes,
        so the pane shows what was said instead of an empty box promising
        that Claude remembers.
        """
        if not session_id:
            raise ValueError("no conversation given")
        await self.stop()
        self.session_id = session_id
        self.info = {}
        self.context = {}
        self.events = []
        self._seq = 0
        # Live viewers repaint from here: clear first, then the history.
        self._emit({"type": "cleared"}, keep=False)
        for event in replay:
            self._emit(dict(event))
        if not replay:
            self._emit({"type": "notice", "text":
                        "Resumed. Claude has this conversation's history — "
                        "this pane starts from here."})
        self._persist()
        await self.start()
        # start() may have discovered the CLI no longer holds this
        # conversation and opened a fresh session instead. Saying so is the
        # difference between "carrying on" and a pane that only looks like
        # it is.
        return {"ok": True, "session_id": self.session_id,
                "resumed": not self.resume_fell_back, "events": len(replay)}

    async def set_model(self, model: str) -> dict:
        """Point the session at a different model, keeping the conversation.

        The model is an argv flag, so a live process keeps the one it was
        started with — changing it means a restart. The conversation
        survives because the CLI persisted it and the respawn carries
        ``--resume``; the same trick interrupt() already relies on. Refused
        mid-answer, because a restart now would lose the answer being
        written.
        """
        model = (model or "").strip()
        if self.state == "busy":
            raise RuntimeError("Claude is still answering — stop it first")
        self.model = model
        # The label rides back on every answer, because the meta line is the
        # only confirmation a pick landed and the event that would refresh
        # it (init → info) does not arrive until the NEXT message — a
        # restarted `--resume` process says nothing until it is spoken to.
        # Waiting for it is how the picker looked like it did nothing.
        label = pretty_model(model)
        if not self.alive():
            # Nothing running: the next spawn simply takes the new flag.
            return {"ok": True, "model": model, "model_label": label,
                    "restarted": False}
        if model == self._spawned_model:
            # Compared against what the process actually runs, never against
            # `self.model` — the server refreshes that from settings on every
            # request, so a ⚙ edit made it agree with a pick the live process
            # had never seen, and the picker answered "already that model"
            # about a session still running the old one.
            return {"ok": True, "model": model, "model_label": label,
                    "restarted": False}
        await self.stop()
        await self.start()
        return {"ok": True, "model": model, "model_label": label,
                "restarted": True}

    async def reset(self) -> dict:
        """Start a genuinely new conversation.

        Drops the resume id as well as the transcript — keeping the id would
        make "New chat" mean "same conversation, blank screen", which is the
        one thing it must not mean.
        """
        await self.stop()
        self.session_id = None
        self.events = []
        self.info = {}
        self.context = {}
        self._seq = 0
        self._persist()
        self._emit({"type": "cleared"}, keep=False)
        await self.start()
        return {"ok": True}


# ---------------------------------------------------------------------------
# Normalising the CLI's stream into something a browser can render
# ---------------------------------------------------------------------------

def _normalise(event: dict) -> list[dict]:
    """Turn one stream-json event into zero or more transcript events.

    Everything that knows the CLI's wire shape is here (the control channel
    — permission requests and their answers — is the one exception, handled
    in the read loop because it is state, not transcript). The panel only
    ever sees: text, text_delta, thinking, thinking_delta, tool,
    tool_result, result, notice.
    """
    etype = event.get("type")

    if etype == "stream_event":
        delta = (event.get("event") or {}).get("delta") or {}
        if delta.get("type") == "text_delta" and delta.get("text"):
            # Not kept: the assistant event that follows carries the whole
            # block, so keeping deltas too would double every answer in the
            # transcript a reload repaints.
            return [{"type": "text_delta", "text": delta["text"], "_keep": False}]
        if delta.get("type") == "thinking_delta" and delta.get("thinking"):
            # Same contract as text deltas — live-only, sealed by the
            # assistant event's whole thinking block. Dropping these was
            # most of "the chat doesn't show thinking": the block only
            # arrives when the message closes, so a long think was minutes
            # of dots followed by reasoning delivered after its conclusion.
            return [{"type": "thinking_delta", "text": delta["thinking"],
                     "_keep": False}]
        return []

    if etype == "assistant":
        out = []
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                out.append({"type": "text", "text": _clip(block["text"], MAX_RESULT_CHARS * 4)})
            elif btype == "thinking" and block.get("thinking"):
                out.append({"type": "thinking",
                            "text": _clip(block["thinking"], MAX_RESULT_CHARS)})
            elif btype == "tool_use":
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
                out.append({
                    "type": "tool",
                    "id": block.get("id") or "",
                    "name": block.get("name") or "tool",
                    "summary": tool_summary(block.get("name") or "", args),
                    "input": _clip(json.dumps(args, ensure_ascii=False, indent=2),
                                   MAX_RESULT_CHARS),
                })
        return out

    if etype == "user":
        # A "user" event coming *from* the CLI is a tool result being fed
        # back, not something the person typed.
        out = []
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            content = block.get("content")
            if isinstance(content, list):
                text = "\n".join(
                    part.get("text", "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text")
            else:
                text = content if isinstance(content, str) else ""
            failed = bool(block.get("is_error"))
            out.append({
                "type": "tool_result",
                "id": block.get("tool_use_id") or "",
                "ok": not failed,
                "denied": failed and bool(_DENIED_RE.search(text)),
                "text": _clip(text, MAX_RESULT_CHARS),
            })
        return out

    if etype == "result":
        if event.get("is_error"):
            return [{"type": "notice", "level": "error",
                     "text": _error_text(event)}]
        return [{
            "type": "result",
            "duration_ms": event.get("duration_ms"),
            "cost_usd": event.get("total_cost_usd"),
            "turns": event.get("num_turns"),
            "_keep": False,
        }]

    return []


def _session_info(event: dict) -> dict:
    """The four facts about a session that the panel has a use for.

    ``cwd`` matters more than it looks: Claude Code files conversations by
    working directory (``~/.claude/projects/<escaped-cwd>/``), and
    ``claude --resume`` only lists the ones belonging to the directory you
    are standing in. If this and the terminal's cwd ever diverge, the chat's
    conversations become unreachable from the terminal — so it is shown
    rather than assumed.

    ``api_key_source`` is the CLI's own answer to "is anyone being billed
    per token". On a subscription it is "none", and a dollar figure would be
    a number that looks like money and isn't.
    """
    return {
        "model": event.get("model") or "",
        "model_label": pretty_model(event.get("model") or ""),
        "cwd": event.get("cwd") or "",
        "version": event.get("claude_code_version") or "",
        "api_key_source": event.get("apiKeySource") or "none",
    }


def _error_text(event: dict) -> str:
    subtype = event.get("subtype") or ""
    if subtype == "error_max_turns":
        return ("Claude reached this session's turn limit. Your next message "
                "restarts the session and the conversation carries on.")
    result = event.get("result")
    if isinstance(result, str) and result.strip():
        return _clip(result.strip(), 1000)
    return subtype or "The turn ended with an error."


# ---------------------------------------------------------------------------
# Handing a conversation to the classic terminal
# ---------------------------------------------------------------------------

HANDOFF_FILE = os.environ.get("BRAIN_TERMINAL_HANDOFF",
                              "/data/terminal-handoff.json")
TMUX_SESSION = os.environ.get("BRAIN_TMUX_SESSION", "claude")
# The `claude` user run.sh creates (UID 1000), which is who the terminal —
# and so the other end of the handoff — runs as.
CLAUDE_UID = int(os.environ.get("BRAIN_CLAUDE_UID", "1000"))
CLAUDE_GID = int(os.environ.get("BRAIN_CLAUDE_GID", "1000"))
TERMINAL_START = os.environ.get("BRAIN_TERMINAL_START",
                                "/usr/local/bin/brain-terminal-start")


def _open_in_terminal(session_id: str) -> bool:
    """Leave the conversation where the terminal will pick it up, and — if
    the terminal is already running — open it there now.

    The file is the contract and always written: ``brain-terminal-start``
    reads it on launch, so even a terminal that has never been opened comes
    up inside the conversation. The tmux window is the nicety on top, for
    when the terminal is already attached and waiting; a new window rather
    than keystrokes into whatever happens to be in front, and the existing
    session is left alone in its own window.

    Returns whether the window was opened. Everything here is best effort:
    the file alone is enough to be correct, just not instant.
    """
    payload = json.dumps({"session_id": session_id, "ts": int(time.time())})
    try:
        path = Path(HANDOFF_FILE)
        atomic_write.write_text(path, payload, mode=0o600)
        # The terminal runs as the claude user and this file is written by
        # the panel, which is root — so hand it over rather than opening it
        # up. 0o666 did the job by making it world-writable, which is a
        # wider grant than the one user that needs it, and removing it was
        # never the file's permission to give: unlinking is governed by the
        # directory, which the claude user already owns.
        try:
            os.chown(path, CLAUDE_UID, CLAUDE_GID)
            os.chmod(path, 0o600)
        except OSError:
            # Best effort: an unreadable handoff file costs the terminal its
            # `--resume`, and the session id is still in the transcript.
            pass
    except OSError:
        return False

    argv = _tmux_argv() + [
        "new-window", "-t", TMUX_SESSION, "-c", WORK_DIR, TERMINAL_START]
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=10)
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _tmux_argv() -> list[str]:
    """tmux, as the user whose server it is.

    The terminal's tmux server belongs to the `claude` user; the panel is
    root. Without the drop, root talks to its own (empty) server and the
    window opens where nobody is looking.
    """
    tmux = shutil.which("tmux") or "tmux"
    if os.geteuid() == 0 and shutil.which("su-exec"):
        return ["su-exec", "claude", tmux]
    return [tmux]


# One session per add-on, created lazily so importing this module (which the
# tests do) never spawns anything.
_session: ChatSession | None = None


def session() -> ChatSession:
    global _session
    if _session is None:
        _session = ChatSession()
    return _session
