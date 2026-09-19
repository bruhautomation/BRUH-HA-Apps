#!/usr/bin/env python3
"""Stop hook: what the person just taught the terminal, into the memory inbox.

Voice has reflected into memory since the worker pool was written — a
finished Assist conversation gets one cheap Claude pass over its exchanges
and whatever durable fact it carried is queued for the consolidator. The
terminal and the panel chat, where the most knowledgeable person in the
house types the most, taught nothing at all: everything they said about
how the home is wired, what a device is really called, which automation is
deliberately switched off, was said once and thrown away with the
scrollback.

This is that same pass for the two faces a person types into, hung off
Claude Code's own ``Stop`` hook. The CLI pipes one JSON object in on
stdin — ``{session_id, transcript_path, cwd, permission_mode,
hook_event_name: "Stop", stop_hook_active}`` — and reads what the hook
prints; the shape is the CLI bundle's own ``wj()`` plus the ``Stop``
fields, not a remembered one.

Four rules hold it together.

**The hook must never be felt.** A hook runs between a person pressing
enter and the turn ending, so anything that takes a second here is a
second added to every turn in the terminal. It parses, decides in one
bounded ledger read whether this conversation is even a person's, hands
the work to a detached child, prints nothing and exits 0. The extraction —
a transcript read, a Claude turn, an inbox write — happens after the CLI
has long since moved on.

**Only unclaimed conversations.** ``run_sources`` is a contract: every
background face (voice, the consolidator, study, doctor, triage, the
automation listener) mints its own session id and records it *before* the
run, so an id nobody claimed is one a person typed. That is exactly the
set worth extracting from — voice already reflects for itself, and the
"facts" in a machine conversation are the machine's prompt read back.

**Every writer goes through the inbox.** Nothing here touches
``memory.md``; that document has one writer and it is the consolidator. A
``kind: correction`` line is filed under source ``correction``, which is
the word the consolidator already knows means *the homeowner is telling
you brAIn read the house wrong*.

**Nothing raises and nothing blocks.** Every failure is silent and exits
0. A missed fact costs a fact; a hook that throws costs the turn.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Where everything lives. Spelled out here rather than imported: this runs as
# the `claude` user under the CLI, inside somebody's terminal turn, and must
# not need the panel (or anything on sys.path) to start.
# ---------------------------------------------------------------------------

# The same ledger panel/run_sources.py writes and reads, and the same one
# the worker pool appends to by hand for the same reason.
RUN_SOURCES = Path(os.environ.get("BRAIN_RUN_SOURCES", "/data/run-sources.jsonl"))
# Every writer's door into memory. One file per call, appended.
MEMORY_INBOX_DIR = Path(os.environ.get(
    "BRAIN_MEMORY_INBOX_DIR", "/config/.brain/memory/inbox"))
# One marker per conversation: when it was last extracted, and the digest of
# what was extracted. Under /data because it is bookkeeping about our own
# passes, not something a person edits or backs up.
STATE_DIR = Path(os.environ.get(
    "BRAIN_EXTRACT_STATE_DIR", "/data/memory-extract"))
# A conversation the panel chat is holding has a scrollback of its own under
# this directory, named for the session id. That file existing is the one
# signal that tells the chat from the terminal without guessing at a cwd.
CHAT_TRANSCRIPT_DIR = Path(os.environ.get(
    "BRAIN_CHAT_TRANSCRIPT_DIR", "/data/chat"))

# Anything the CLI would be asked for that is not a person's own typing.
# `memory` is this pass's own claim: the extraction is itself a Claude run
# from /config, and unclaimed it would file in the Chats rail as a
# conversation somebody had — dozens of identical machine prompts burying
# the chats this feature exists to learn from.
EXTRACT_SOURCE = "memory"

# The model tier for a cheap one-turn extraction. run.sh writes
# BRAIN_MODEL_MEMORY into /data/.brain_env from panel/model_plan.py's own
# table at boot; `haiku` is the fallback for a process that never saw it,
# and the empty string must fall through to it rather than being sent.
MODEL = os.environ.get("BRAIN_MODEL_MEMORY", "").strip() or "haiku"

# engine.CLAUDE_BIN_CANDIDATES, walked in the same order and for the same
# reason: run.sh installs the CLI under the claude user's home and the image
# symlinks it into root's, neither of which is reliably on PATH.
CLAUDE_HOME = os.environ.get("BRAIN_HOME", "/data/home")
CLAUDE_BIN_CANDIDATES = (
    os.path.join(CLAUDE_HOME, ".local", "bin", "claude"),
    "/root/.local/bin/claude",
    "/usr/local/bin/claude",
)

# The add-on's option file. The terminal's shell sources it, the panel's
# chat process may not, so `learning: false` is read off the file itself
# when the variable did not arrive in the environment.
BRAIN_ENV_FILE = Path(os.environ.get("BRAIN_ENV_FILE", "/data/.brain_env"))
LEARNING_VAR = "BRAIN_ASSIST_LEARNING"

# A turn shorter than this said nothing worth a model call.
MIN_CHARS = 40
# What a single extraction reads. Four kilobytes is the voice pool's own
# transcript budget, and the last exchange of a terminal turn is usually a
# great deal shorter than that.
MAX_TEXT_BYTES = 4096
MAX_MESSAGE_CHARS = 1500
# At most one extraction per conversation per this many seconds. The gate is
# per session rather than global: two people in two tabs are two
# conversations, and a busy one must not silence a quiet one.
MIN_SPACING_S = int(os.environ.get("BRAIN_EXTRACT_SPACING", "120") or 120)
# A one-turn pass over four kilobytes. Same budget voice gives its own.
EXTRACT_TIMEOUT = 60
MAX_FACTS = 3
MAX_FACT_CHARS = 500
MAX_SUBJECT_CHARS = 120
# A transcript is somebody's whole session and can run to megabytes; only
# the tail is ever the last turn.
TRANSCRIPT_TAIL_BYTES = 512 * 1024

# Corrective / preference / intent language. A single exchange carrying
# none of it is small talk or a one-off command; a conversation of two or
# more exchanges is worth a look whatever words are in it (the voice pool's
# own heuristic, and the same trade — a missed fact costs a fact, a pass
# over nothing costs a haiku turn).
KEYWORDS = (
    "actually", "remember", "call it", "we call", "always", "never",
    "prefer", "instead", "from now on", "keep in mind", "note that",
    "no longer", "used to", "in fact", "correction", "wrong", "not a fault",
    "on purpose", "deliberately", "i want", "we want", "make sure",
)

_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,120}")

EXTRACT_PROMPT = (
    "From this conversation between a person and their smart-home "
    "assistant, extract 0-3 durable facts worth remembering about the "
    "HOUSE: how something is wired or configured, what a device or area is "
    "really called, a standing preference, a correction to something the "
    "assistant had wrong, or an intent the person stated.\n\n"
    "Exclude anything transient (current states, one-off commands, what is "
    "on right now), anything secret, and anything about a PERSON rather "
    "than the house — never health, whereabouts, who was home, sleep or "
    "household composition. There is no exception to that.\n\n"
    "Output one JSON object per line and nothing else:\n"
    '{"fact": "...", "confidence": "high|medium|low", '
    '"subject": "<entity id | area:name | person:me | house>", '
    '"kind": "fact|correction|intent"}\n'
    "Use kind \"correction\" when the person is telling the assistant it "
    "read the house wrong, and \"intent\" when they stated something they "
    "mean to do. At most 3 lines. If there is nothing durable, output the "
    "single word NONE."
)


def _log(message: str) -> None:
    """One line, in the child only. The hook's own stderr is read by the CLI
    and is never written to."""
    try:
        sys.stderr.write(f"[brain-memory-extract] {message}\n")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 — logging must never be the failure
        pass


def safe_id(value: str) -> str:
    """A session id, or "" for anything that has no business being one.

    It becomes a filename under the state directory and it arrives from
    outside this process, so it is refused rather than sanitised — the same
    rule chat_session.transcript_path follows, for the same reason.
    """
    text = str(value or "")
    if not _ID_RE.fullmatch(text):
        return ""
    if text in (".", ".."):
        return ""
    return text


# ---------------------------------------------------------------------------
# The ledger: is this conversation anybody's but a person's?
# ---------------------------------------------------------------------------


def claimed(session_id: str) -> bool:
    """True when some face has already claimed this session id.

    Read by hand rather than through panel/run_sources.py: the hook must
    start without the panel on sys.path. The shape is that module's —
    ``{"id", "source", "ts"}``, one JSON object per line, last claim wins —
    and tests/test_memory_extract.py drives the real ``lookup`` over a file
    this writes so the two cannot drift.
    """
    if not session_id:
        return False
    try:
        with RUN_SOURCES.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or session_id not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and entry.get("id") == session_id \
                        and entry.get("source"):
                    return True
    except OSError:
        # No ledger is a house where nothing has claimed anything yet, which
        # is a person's conversation by definition.
        return False
    return False


def claim(session_id: str, source: str = EXTRACT_SOURCE) -> None:
    """Claim a session id for a face, before the run it labels.

    Bookkeeping: a run that cannot be labelled still has to happen.
    """
    if not safe_id(session_id):
        return
    line = json.dumps({"id": session_id, "source": source,
                       "ts": int(time.time())}, separators=(",", ":"))
    try:
        RUN_SOURCES.parent.mkdir(parents=True, exist_ok=True)
        with RUN_SOURCES.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        # The claim is a label on the Chats rail, not the run: a ledger the
        # claude user cannot write costs a row's source, never the extraction.
        pass


# ---------------------------------------------------------------------------
# The transcript: the last exchange, as plain text
# ---------------------------------------------------------------------------


def _block_text(content) -> str:
    """The prose in one message's content, tool traffic dropped.

    A tool call and its result are the turn's machinery, not what anybody
    said, and four kilobytes of them would crowd out the one sentence the
    pass is for.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n".join(parts)


def read_last_turn(path: str) -> tuple[str, int, str]:
    """``(text, exchanges, said)`` for the most recent exchange or two —
    the whole exchange, how many turns it spans, and what the PERSON said
    on its own, which is the half the worth-check judges.

    Claude Code's transcript is JSONL, one object per event, with the
    conversation carried on the ``user``/``assistant`` lines. Reading back
    to the *previous* user line rather than only the last one is what makes
    a follow-up ("no, the other one") legible: on its own it is a fragment,
    and with the turn it corrects in front of it, it is a correction.

    Sidechains are a subagent's conversation, not the person's, and are
    dropped whole.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            if size > TRANSCRIPT_TAIL_BYTES:
                fh.seek(size - TRANSCRIPT_TAIL_BYTES)
                fh.readline()       # the partial line the seek landed in
            lines = fh.readlines()
    except OSError:
        return "", 0, ""

    messages: list[tuple[str, str]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") not in ("user", "assistant"):
            continue
        if entry.get("isSidechain"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _block_text(message.get("content")).strip()
        if not text:
            continue
        messages.append((role, text[:MAX_MESSAGE_CHARS]))

    if not messages:
        return "", 0, ""

    # Walk back to the second-to-last thing the person said, or to the
    # start of what we have.
    user_at = [i for i, (role, _) in enumerate(messages) if role == "user"]
    if not user_at:
        return "", 0, ""
    start = user_at[-2] if len(user_at) >= 2 else user_at[-1]
    slice_ = messages[start:]
    exchanges = sum(1 for role, _ in slice_ if role == "user")

    blob = "\n".join(
        f"{'USER' if role == 'user' else 'ASSISTANT'}: {text}"
        for role, text in slice_)
    if len(blob) > MAX_TEXT_BYTES:
        blob = blob[-MAX_TEXT_BYTES:]
    said = "\n".join(text for role, text in slice_ if role == "user")
    return blob, exchanges, said


def worth_extracting(said: str, exchanges: int) -> bool:
    """Cheap, deterministic, and made in the direction where being wrong is
    cheap: a missed fact costs a fact, a pass over nothing costs one haiku
    turn. Nothing asks a model whether to ask a model.

    Judged on what the PERSON typed and never on the reply: the model
    answers "Noted — I will remember that" to nearly anything, and a
    keyword list read over the whole exchange found "remember" in every
    turn and spent a run on "ok". The voice pool reads its transcript the
    same way (``u.lower() for u, _ in transcript``).
    """
    if len(said.strip()) < MIN_CHARS:
        return False
    if exchanges >= 2:
        return True
    lowered = said.lower()
    return any(keyword in lowered for keyword in KEYWORDS)


# ---------------------------------------------------------------------------
# The rate limit: one marker per conversation
# ---------------------------------------------------------------------------


def _state_path(session_id: str) -> Path | None:
    name = safe_id(session_id)
    if not name:
        return None
    base = os.path.normpath(os.path.abspath(str(STATE_DIR)))
    candidate = os.path.normpath(os.path.join(base, f"{name}.json"))
    if not candidate.startswith(base + os.sep):
        return None
    return Path(candidate)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:32]


def spacing_ok(session_id: str, text: str, now: float | None = None) -> bool:
    """False when this conversation was extracted moments ago, or when the
    last extraction was over this very text.

    The hash matters as much as the clock: a Stop fires on every turn, and
    a turn that ended without the person saying anything new (an
    interrupted answer, a bare "continue") would otherwise buy a second
    identical extraction of the same exchange.
    """
    path = _state_path(session_id)
    if path is None:
        return False
    now = time.time() if now is None else now
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(state, dict):
        return True
    try:
        last = float(state.get("ts") or 0)
    except (TypeError, ValueError):
        last = 0.0
    if now - last < MIN_SPACING_S:
        return False
    return state.get("hash") != _digest(text)


def remember_extraction(session_id: str, text: str) -> None:
    path = _state_path(session_id)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"ts": int(time.time()), "hash": _digest(text)},
            separators=(",", ":")), encoding="utf-8")
    except OSError:
        # Losing the marker costs one extra extraction, never a wrong one.
        pass


# ---------------------------------------------------------------------------
# The extraction itself
# ---------------------------------------------------------------------------


def resolve_claude_cmd() -> list[str]:
    """How to invoke the CLI, walking engine.CLAUDE_BIN_CANDIDATES.

    No su-exec here and no claude-run: this process is already the hook,
    running as whoever the CLI runs as.
    """
    override = os.environ.get("BRAIN_CLAUDE_BIN", "").strip()
    if override:
        return shlex.split(override)
    for candidate in CLAUDE_BIN_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return [candidate]
    return [shutil.which("claude") or "claude"]


def parse_facts(stdout: str) -> list[dict]:
    """The model's reply, read defensively — one bad line is one bad line.

    Every field is narrowed to something the consolidator can read: a
    confidence outside the three words becomes `medium`, a kind outside the
    three becomes `fact`, an absent subject becomes `house`. A verdict
    invented from an unrecognised string reads exactly like a real one.
    """
    facts: list[dict] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line or line.upper() == "NONE":
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        fact = obj.get("fact")
        if not isinstance(fact, str) or not fact.strip():
            continue
        confidence = obj.get("confidence")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"
        kind = obj.get("kind")
        if kind not in ("fact", "correction", "intent"):
            kind = "fact"
        subject = obj.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            subject = "house"
        facts.append({
            "fact": fact.strip()[:MAX_FACT_CHARS],
            "confidence": confidence,
            "kind": kind,
            "subject": subject.strip()[:MAX_SUBJECT_CHARS],
        })
        if len(facts) >= MAX_FACTS:
            break
    return facts


def run_extraction(text: str, workdir: str) -> tuple[list[dict], str]:
    """One capped Claude turn, no tools. Returns ``(facts, run_id)``."""
    cmd = resolve_claude_cmd() + [
        "-p",
        "--disallowedTools", "*",
        "--max-turns", "1",
        "--model", MODEL,
    ]
    run_id = str(uuid.uuid4())
    # Claimed BEFORE the run, because a pass that times out still leaves a
    # transcript and it should still be labelled as the pass it was.
    claim(run_id)
    prompt = EXTRACT_PROMPT + "\n\nConversation:\n" + text
    try:
        proc = subprocess.run(
            cmd + ["--session-id", run_id],
            input=prompt, capture_output=True, text=True,
            timeout=EXTRACT_TIMEOUT, cwd=workdir,
        )
        if proc.returncode != 0 and "session-id" in (proc.stderr or ""):
            # A CLI from before --session-id refuses the flag by name. The
            # label is optional; the run is not.
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                timeout=EXTRACT_TIMEOUT, cwd=workdir,
            )
    except (OSError, subprocess.SubprocessError):
        return [], run_id
    if proc.returncode != 0:
        return [], run_id
    return parse_facts(proc.stdout or ""), run_id


# ---------------------------------------------------------------------------
# The inbox
# ---------------------------------------------------------------------------


def turn_source(session_id: str) -> str:
    """``chat`` or ``terminal`` — never a guess dressed up as a reading.

    The panel chat keeps its own scrollback for each conversation it holds,
    named for the session id; that file existing is the one thing that
    tells the two faces apart from inside a hook. Anything else is the
    terminal, which is the honest answer when we cannot tell: it is the
    face that runs a bare CLI, and a fact filed under the wrong one of two
    words a person types into costs nothing downstream.
    """
    name = safe_id(session_id)
    if name:
        try:
            if (CHAT_TRANSCRIPT_DIR / f"{name}.json").is_file():
                return "chat"
        except OSError:
            # A transcript directory this user may not stat is the terminal's
            # ordinary case; the label falls through to it below.
            pass
    return "terminal"


def file_facts(facts: list[dict], source: str, run_id: str) -> Path | None:
    """One file per call, appended, in the shape every inbox writer uses.

    A correction is filed under the source word the consolidator already
    knows: it is told a correction is not a fact, and to record the
    standing truth the reason implies rather than the report.
    """
    if not facts:
        return None
    now = int(time.time())
    path = MEMORY_INBOX_DIR / f"{now}-{source}.jsonl"
    try:
        MEMORY_INBOX_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for item in facts:
                record = {
                    "ts": now,
                    "source": "correction" if item["kind"] == "correction" else source,
                    "fact": item["fact"],
                    "confidence": item["confidence"],
                    "subject": item["subject"],
                    "run_id": run_id,
                }
                fh.write(json.dumps(record) + "\n")
    except OSError:
        return None
    return path


# ---------------------------------------------------------------------------
# The two halves: the hook, and the child it hands the work to
# ---------------------------------------------------------------------------


def extract(session_id: str, transcript: str, cwd: str) -> int:
    """The detached half. Everything that costs time lives here."""
    text, exchanges, said = read_last_turn(transcript)
    if not worth_extracting(said, exchanges):
        return 0
    if not spacing_ok(session_id, text):
        return 0
    # Stamped before the run, not after: a pass that hangs for its whole
    # timeout must not let the next Stop start a second one over the same
    # exchange.
    remember_extraction(session_id, text)

    workdir = cwd if cwd and os.path.isdir(cwd) else "/config"
    facts, run_id = run_extraction(text, workdir)
    if not facts:
        return 0
    path = file_facts(facts, turn_source(session_id), run_id)
    if path is not None:
        _log(f"queued {len(facts)} candidate fact(s) from a "
             f"{turn_source(session_id)} turn")
    return 0


def _child_stderr():
    """Where the detached child's output goes.

    Devnull, and that is not incidental: the CLI reads the hook process's
    stderr, so a detached child inheriting it would hold that pipe open
    after the hook has exited and the turn would wait on a Claude call it
    was never meant to see. BRAIN_EXTRACT_LOG names a file for anybody
    debugging a house that is not filing anything.
    """
    target = os.environ.get("BRAIN_EXTRACT_LOG", "").strip()
    if target:
        try:
            return open(target, "a", encoding="utf-8")
        except OSError:
            # A log file that will not open costs the child's stderr and
            # nothing else; the hook's own contract is to never fail the turn.
            pass
    return subprocess.DEVNULL


def spawn(session_id: str, transcript: str, cwd: str) -> None:
    """Hand the work to a process the turn does not wait on."""
    stderr = _child_stderr()
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--extract",
             session_id, transcript, cwd],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, ValueError):
        # A child that could not spawn costs one extraction. The hook exits 0
        # regardless, because a hook that throws costs the person's turn.
        pass
    finally:
        if stderr is not subprocess.DEVNULL:
            try:
                stderr.close()
            except OSError:
                # The child holds its own descriptor; ours failing to close
                # leaks one fd in a process about to exit.
                pass


def learning_enabled() -> bool:
    """`learning: false` switches every writer off, and this is one.

    The value is read from the environment first (the terminal's shell
    sourced the env file) and off the env file itself otherwise (the chat's
    process did not); a file that cannot be read is the default, which is
    on — the same answer the consolidator and the study watcher give.
    """
    value = os.environ.get(LEARNING_VAR)
    if value is None:
        try:
            with BRAIN_ENV_FILE.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("export "):
                        line = line[7:]
                    if line.startswith(LEARNING_VAR + "="):
                        value = line.split("=", 1)[1].strip().strip("\"'")
        except OSError:
            value = None
    return (value or "true").strip().lower() != "false"


def hook() -> int:
    """The half the turn waits on. It reads, it decides, it returns."""
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("hook_event_name") not in (None, "Stop"):
        return 0
    if payload.get("stop_hook_active"):
        # The CLI is already inside a stop hook: whatever ends this turn is
        # a continuation of one we have already seen, not a new thing said.
        return 0

    session_id = safe_id(payload.get("session_id") or "")
    transcript = str(payload.get("transcript_path") or "")
    if not session_id or not transcript:
        return 0
    if not learning_enabled():
        return 0
    if claimed(session_id):
        # Voice, the consolidator, a study session, triage, a doctor probe.
        # Their transcripts are a prompt read back, and voice reflects for
        # itself.
        return 0
    spawn(session_id, transcript, str(payload.get("cwd") or ""))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--extract":
        args = argv[2:] + ["", "", ""]
        return extract(args[0], args[1], args[2])
    return hook()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:  # noqa: BLE001 — a hook must never break the turn
        sys.exit(0)
