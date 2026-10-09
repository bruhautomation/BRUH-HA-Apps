#!/usr/bin/env python3
"""The voice pool keeps the contract every other Claude run keeps.

Voice is the highest-traffic Claude path in a house and it was the one
outside the add-on's own accounting: no journal row, so nothing counted a
turn and nothing reported a failed one; no usage nudge, so its spend
reached the figure only on the tracker's half-hour heartbeat; an agent set
to Default ran on whatever the CLI defaulted to rather than the plan's
voice tier; and a turn that had already reached a tool and then died was
silently run AGAIN as a one-shot — which is how a light gets toggled twice.

Driven through the real pool against the fake CLI (tests/fake_claude.py),
the same arrangement tests/test_assist_worker_pool.py uses.
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
import queue
import sys
import threading
import time
import types
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POOL_PATH = REPO_ROOT / "brain" / "integrations" / "assist-worker-pool.py"
PANEL_DIR = REPO_ROOT / "brain" / "panel"
FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"


def load_pool_module(tmp_path: Path, monkeypatch, **extra_env):
    monkeypatch.setenv("BRAIN_SHARED_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("BRAIN_ASSIST_WORKDIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_CLAUDE_BIN", f"{sys.executable} {FAKE_CLAUDE}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "argv.log"))
    monkeypatch.setenv("FAKE_HELP_LOG", str(tmp_path / "help.log"))
    monkeypatch.setenv("BRAIN_RUN_SOURCES", str(tmp_path / "run-sources.jsonl"))
    monkeypatch.setenv("BRAIN_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("BRAIN_ENV_FILE", str(tmp_path / "brain_env"))
    monkeypatch.setenv("BRAIN_JOURNAL_FILE", str(tmp_path / "journal.jsonl"))
    monkeypatch.setenv("BRAIN_USAGE_NUDGE", str(tmp_path / "usage-nudge"))
    for name in ("SUPERVISOR_TOKEN", "FAKE_MODE", "FAKE_HELP",
                 "BRAIN_MODEL_VOICE", "BRAIN_EFFORT_VOICE"):
        monkeypatch.delenv(name, raising=False)
    for key, value in extra_env.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location(
        f"assist_pool_{uuid.uuid4().hex}", POOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    for d in (mod.REQUESTS_DIR, mod.RESPONSES_DIR, mod.SESSIONS_DIR,
              mod.CACHE_DIR, mod.LOG_DIR):
        os.makedirs(d, exist_ok=True)
    return mod


def record_journal(mod) -> list:
    rows: list = []
    mod.journal_turn = lambda *a, **kw: rows.append((a, kw))
    return rows


def shutdown(pool) -> None:
    for worker in list(pool.workers.values()):
        worker.kill()
    if pool.spare is not None:
        pool.spare.kill()


def drop_spare(pool) -> None:
    with pool.lock:
        spare, pool.spare = pool.spare, None
    if spare is not None:
        spare.kill()


def request(text, conv="convA", **extra) -> dict:
    req = {"id": uuid.uuid4().hex, "conversation_id": conv, "text": text,
           "type": "conversation", "ts": time.time(), "timeout": 60,
           "conversation_history": []}
    req.update(extra)
    return req


def spawns(tmp_path: Path) -> list[list[str]]:
    try:
        lines = (tmp_path / "argv.log").read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        if line.startswith("["):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def env_lines(tmp_path: Path, name: str) -> list[str]:
    return [line for line in (tmp_path / "argv.log").read_text().splitlines()
            if line.startswith(f"ENV {name}=")]


# ---------------------------------------------------------------------------
# A turn that reached a tool is not run again
# ---------------------------------------------------------------------------


def test_a_turn_that_called_a_tool_and_died_is_not_run_again(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch, FAKE_MODE="tool_then_crash")
    rows = record_journal(mod)
    pool = mod.Pool()
    try:
        drop_spare(pool)
        text, error = pool.process_full(request("toggle the hall light"))
        assert error == "partial"
        assert text == mod.PARTIAL_MESSAGE
        # Only the stream worker ever ran: no one-shot re-sent the command.
        assert spawns(tmp_path), "the worker never spawned"
        assert all("--input-format" in argv for argv in spawns(tmp_path)), \
            "a turn that had touched the house was run a second time"
        assert "convA" not in pool.workers, "the worker that died is kept"
        assert pool.stats["failures"] == 1
        assert pool.stats["by_error"] == {"partial": 1}
        assert rows[-1][0][0] == "partial"
    finally:
        shutdown(pool)


def test_a_turn_that_died_before_touching_anything_still_falls_back(tmp_path, monkeypatch):
    """The fallback stays for the case it was written for."""
    mod = load_pool_module(tmp_path, monkeypatch, FAKE_MODE="crash")
    record_journal(mod)
    pool = mod.Pool()
    try:
        drop_spare(pool)
        text, error = pool.process_full(request("what's the weather?"))
        assert error == ""
        assert "ONESHOT" in text
        assert any("--input-format" not in argv for argv in spawns(tmp_path))
        assert pool.stats["fallbacks"] == 1
    finally:
        shutdown(pool)


# ---------------------------------------------------------------------------
# Several API messages in one turn are separated
# ---------------------------------------------------------------------------


def _bare_worker(mod, events):
    """A Worker with no process, reading a scripted event stream."""
    worker = object.__new__(mod.Worker)
    worker.proc = types.SimpleNamespace(stdin=io.StringIO())
    worker._events = queue.Queue()
    for event in events:
        worker._events.put(event)
    return worker


def _delta(text):
    return {"type": "stream_event", "event": {
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": text}}}


def test_streamed_text_from_two_api_messages_is_two_paragraphs(tmp_path, monkeypatch):
    """"I'll check." then the answer, glued, was one run-on message in
    the chat log that differed from what was spoken."""
    mod = load_pool_module(tmp_path, monkeypatch)
    start = {"type": "stream_event", "event": {"type": "message_start"}}
    tool = {"type": "stream_event", "event": {
        "type": "content_block_start",
        "content_block": {"type": "tool_use", "name": "get_entity_state"}}}
    worker = _bare_worker(mod, [
        start, _delta("I'll check."), tool, start,
        _delta("The lights are off."),
        {"type": "result", "is_error": False,
         "result": "I'll check.The lights are off."},
    ])
    chunks: list[str] = []
    answer = worker.ask("are the lights off?", time.time() + 5,
                        delta_cb=chunks.append)
    assert "".join(chunks) == "I'll check.\n\nThe lights are off."
    assert worker.acted is True
    assert answer == "I'll check.The lights are off."


# The stream the real CLI writes for a turn that says what it is about to
# do, calls the tool, gets its result and closes with a message carrying no
# text: the result event is a SUCCESS whose `result` (the closing message's
# text) is empty.
def _quiet_turn():
    return [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Turning it off."},
            {"type": "tool_use", "id": "t1", "name": "control_light",
             "input": {}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        {"type": "assistant", "message": {"content": []}},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": "", "session_id": "s1"},
    ]


def test_a_turn_that_acted_and_closed_quietly_answers(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    worker = _bare_worker(mod, _quiet_turn())
    answer = worker.ask("turn off the hall light", time.time() + 5)
    assert worker.acted is True
    assert answer == "Turning it off."
    # …and one that said nothing at all before or after the tool.
    silent = _bare_worker(mod, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "control_light",
             "input": {}}]}},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": ""}])
    assert silent.ask("lights off", time.time() + 5) == mod.QUIET_DONE_MESSAGE
    # A turn that ended in an ERROR after a tool is still not an answer.
    broke = _bare_worker(mod, [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Turning it off."},
            {"type": "tool_use", "id": "t1", "name": "control_light",
             "input": {}}]}},
        {"type": "result", "subtype": "error_during_execution",
         "is_error": True, "result": ""}])
    assert broke.ask("lights off", time.time() + 5) is None
    assert broke.acted is True


def test_a_completed_turn_is_never_journaled_partial(tmp_path, monkeypatch):
    """A turn the CLI closed `success` after a tool call was answered with
    PARTIAL_MESSAGE, journaled `error`/`partial` and its worker dropped —
    the voice run a house's journal carried once in a day of six."""
    mod = load_pool_module(tmp_path, monkeypatch)
    rows = record_journal(mod)
    pool = mod.Pool()
    worker = _bare_worker(mod, _quiet_turn())
    worker.lock = threading.Lock()
    worker.partial = False
    worker.session_id = "s1"
    worker.model = "default"
    worker.created = time.time()
    worker.transcript = []
    worker.people = set()
    worker.profile = None
    worker.kill = lambda: None
    worker.alive = lambda: True
    worker.saw_eof = False
    worker.died = lambda *a, **k: False
    pool._take_worker = lambda conv, profile: (worker, "warm")
    pool.workers["convA"] = worker
    try:
        drop_spare(pool)
        text, error = pool.process_full(request("turn off the hall light"))
        assert error == "", f"a completed turn was reported as {error!r}"
        assert text == "Turning it off."
        assert pool.stats["failures"] == 0
        assert rows[-1][0][0] == ""
        assert pool.workers.get("convA") is worker, \
            "a worker that answered was dropped"
    finally:
        pool.workers.clear()
        shutdown(pool)


def test_the_coarse_path_separates_whole_messages_too(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    worker = _bare_worker(mod, [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "I'll check."},
            {"type": "tool_use", "name": "get_entity_state", "input": {}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "off"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "They are off."}]}},
        {"type": "result", "is_error": False, "result": "They are off."},
    ])
    chunks: list[str] = []
    worker.ask("q", time.time() + 5, delta_cb=chunks.append)
    assert "".join(chunks) == "I'll check.\n\nThey are off."
    assert worker.acted is True


def test_a_turn_that_only_talked_did_not_act(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    worker = _bare_worker(mod, [
        _delta("Hello."), {"type": "result", "is_error": False,
                           "result": "Hello."}])
    worker.ask("hi", time.time() + 5, delta_cb=lambda _c: None)
    assert worker.acted is False


# ---------------------------------------------------------------------------
# The plan's voice tier, its depth, and the flags a CLI may not know
# ---------------------------------------------------------------------------


def _plan(tmp_path, **values):
    (tmp_path / "brain_env").write_text("".join(
        f"export {k}={v}\n" for k, v in values.items()))


def test_an_agent_set_to_default_runs_on_the_plans_voice_tier(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch,
                           FAKE_HELP="--effort,--system-prompt-snapshot")
    record_journal(mod)
    _plan(tmp_path, BRAIN_MODEL_VOICE="voice-tier-x", BRAIN_EFFORT_VOICE="low")
    pool = mod.Pool()
    try:
        drop_spare(pool)
        pool.process_full(request("lights off", model="default"))
        argv = [a for a in spawns(tmp_path) if "--input-format" in a][-1]
        assert argv[argv.index("--model") + 1] == "voice-tier-x"
        assert argv[argv.index("--effort") + 1] == "low"
    finally:
        shutdown(pool)


def test_a_model_the_agent_chose_takes_no_planned_depth(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch,
                           FAKE_HELP="--effort,--system-prompt-snapshot")
    record_journal(mod)
    _plan(tmp_path, BRAIN_MODEL_VOICE="voice-tier-x", BRAIN_EFFORT_VOICE="low")
    pool = mod.Pool()
    try:
        drop_spare(pool)
        pool.process_full(request("lights off", model="chosen-model"))
        argv = [a for a in spawns(tmp_path) if "--input-format" in a][-1]
        assert argv[argv.index("--model") + 1] == "chosen-model"
        assert "--effort" not in argv
    finally:
        shutdown(pool)


def test_a_cli_that_does_not_list_a_flag_is_not_sent_it(tmp_path, monkeypatch):
    """An unknown flag ends the run unspoken."""
    mod = load_pool_module(tmp_path, monkeypatch)       # FAKE_HELP: none
    record_journal(mod)
    _plan(tmp_path, BRAIN_MODEL_VOICE="voice-tier-x", BRAIN_EFFORT_VOICE="low")
    pool = mod.Pool()
    try:
        drop_spare(pool)
        text, error = pool.process_full(request("lights off"))
        assert error == ""
        argv = [a for a in spawns(tmp_path) if "--input-format" in a][-1]
        assert "--effort" not in argv
    finally:
        shutdown(pool)
    # And the CLI was asked once, not per spawn.
    assert (tmp_path / "help.log").read_text().count("help") <= 1


def test_a_resumed_conversation_answers_under_this_turns_prompt(tmp_path, monkeypatch):
    """`--system-prompt-snapshot off`: without it a resumed session keeps
    the system prompt its first turn recorded — yesterday's area map."""
    mod = load_pool_module(tmp_path, monkeypatch,
                           FAKE_HELP="--effort,--system-prompt-snapshot")
    record_journal(mod)
    pool = mod.Pool()
    try:
        drop_spare(pool)
        pool.process_full(request("lights off", conv="convR"))
        # The worker goes; the session id stays, so the next turn resumes.
        pool._drop_worker("convR", pool.workers["convR"])
        drop_spare(pool)
        pool.process_full(request("and the hall", conv="convR"))
        # Found by what they ARE, never by position: the pool re-warms a
        # spare on a background thread after every turn, so a fresh spawn
        # can land in the log after the resumed one, and "the last stream
        # spawn" was sometimes the spare.
        stream = [a for a in spawns(tmp_path) if "--input-format" in a]
        resumed = [a for a in stream if "--resume" in a]
        assert len(resumed) == 1, resumed
        second = resumed[0]
        assert second[second.index("--system-prompt-snapshot") + 1] == "off"
        # A fresh session has no recorded prompt to keep, so no fresh
        # spawn (the first turn's worker or any spare) carries the flag.
        assert all("--system-prompt-snapshot" not in a
                   for a in stream if "--resume" not in a)
    finally:
        shutdown(pool)


def test_every_voice_spawn_tells_its_mcp_server_it_is_voice(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch, FAKE_MODE="crash")
    record_journal(mod)
    pool = mod.Pool()
    try:
        drop_spare(pool)
        pool.process_full(request("hi"))    # a stream spawn, then a one-shot
    finally:
        shutdown(pool)
    channels = env_lines(tmp_path, "BRAIN_CHANNEL")
    assert len(channels) >= 2
    assert set(channels) == {"ENV BRAIN_CHANNEL=voice"}


# ---------------------------------------------------------------------------
# The journal, the nudge and /health
# ---------------------------------------------------------------------------


def test_a_turn_is_journaled_and_nudges_the_usage_tracker(tmp_path, monkeypatch):
    """Driven through the REAL journal_turn into the panel's real journal,
    redirected to this test's files."""
    mod = load_pool_module(tmp_path, monkeypatch)
    if str(PANEL_DIR) not in sys.path:
        sys.path.insert(0, str(PANEL_DIR))
    journal = importlib.import_module("journal")
    usage_store = importlib.import_module("usage_store")
    monkeypatch.setattr(journal, "JOURNAL_FILE", str(tmp_path / "journal.jsonl"))
    monkeypatch.setattr(usage_store, "NUDGE_FILE", str(tmp_path / "usage-nudge"))
    pool = mod.Pool()
    try:
        drop_spare(pool)
        pool.process_full(request("lights off"))
        deadline = time.time() + 10
        while time.time() < deadline and not (tmp_path / "journal.jsonl").is_file():
            time.sleep(0.05)
        # The row lands from a thread; give it its moment.
        rows = []
        while time.time() < deadline:
            rows = [json.loads(line) for line in
                    (tmp_path / "journal.jsonl").read_text().splitlines()
                    if line.strip()]
            if rows and (tmp_path / "usage-nudge").exists():
                break
            time.sleep(0.05)
    finally:
        shutdown(pool)
    assert rows[-1]["source"] == "voice"
    assert rows[-1]["outcome"] == "ok"
    assert rows[-1]["run_id"]
    assert (tmp_path / "usage-nudge").exists(), "a finished turn did not nudge"


def test_a_failed_turn_is_counted_and_health_says_so(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch, FAKE_MODE="autherror")
    rows = record_journal(mod)
    pool = mod.Pool()
    try:
        drop_spare(pool)
        _text, error = pool.process_full(request("hi"))
        assert error == "auth"
        status = json.loads(Path(mod.POOL_STATUS_FILE).read_text())
        assert status["counts"]["turns"] == 1
        assert status["counts"]["failures"] == 1
        assert status["counts"]["by_error"] == {"auth": 1}
        assert rows[-1][0][0] == "auth"
    finally:
        shutdown(pool)


def test_the_response_file_carries_the_failure_beside_the_sentence(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch, FAKE_MODE="autherror")
    record_journal(mod)
    pool = mod.Pool()
    try:
        drop_spare(pool)
        req = request("hi")
        pool.handle(req)
        body = json.loads(Path(mod.RESPONSES_DIR, f"{req['id']}.json").read_text())
        assert body["error"] == "auth"
        assert "Sign in again" in body["text"]
    finally:
        shutdown(pool)


# ---------------------------------------------------------------------------
# A preference stated by voice belongs to the person who stated it
# ---------------------------------------------------------------------------


def _inbox(tmp_path: Path) -> list[dict]:
    out = []
    inbox = tmp_path / "memory" / "inbox"
    for path in sorted(inbox.glob("*.jsonl")) if inbox.is_dir() else []:
        out += [json.loads(line) for line in path.read_text().splitlines()
                if line.strip()]
    return out


def test_a_fact_the_model_says_is_the_speakers_is_filed_under_them(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch, FAKE_ONESHOT_TEXT="\n".join([
        json.dumps({"fact": "Prefers the bedroom at 19 degrees",
                    "confidence": "high", "about": "speaker"}),
        json.dumps({"fact": "The office lamp is called the beacon",
                    "confidence": "high", "about": "house"}),
    ]))
    mod.reflect_on_transcript([("keep my bedroom at 19", "Done.")], person="ben")
    facts = _inbox(tmp_path)
    assert [f.get("subject") for f in facts] == ["person:ben", None]
    assert facts[0]["person"] == "ben"
    assert "person" not in facts[1]
    # Never the literal the voice path used to be read as.
    assert all(f.get("subject") != "person:me" for f in facts)


def test_with_no_known_speaker_nothing_is_owned(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch, FAKE_ONESHOT_TEXT=json.dumps(
        {"fact": "Prefers the bedroom at 19 degrees", "about": "speaker"}))
    mod.reflect_on_transcript([("keep my bedroom at 19", "Done.")])
    facts = _inbox(tmp_path)
    assert len(facts) == 1 and "subject" not in facts[0]


def test_two_voices_in_one_conversation_belong_to_nobody(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    seen: list = []
    done = threading.Event()

    def fake_reflect(transcript, **kw):
        seen.append(kw)
        done.set()
    mod.reflect_on_transcript = fake_reflect
    worth = [("actually, we call the office lamp the beacon", "Noted.")]

    for people, expect in (({"ben"}, {"person": "ben"}),
                           ({"ben", "ana"}, {}),
                           ({"ben", None}, {}),
                           ({None}, {})):
        done.clear()
        seen.clear()
        worker = types.SimpleNamespace(transcript=list(worth), people=people)
        mod.maybe_reflect(worker)
        assert done.wait(5)
        assert seen == [expect], people


def test_a_spoken_turn_carries_the_speaker_to_the_worker(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    record_journal(mod)
    pool = mod.Pool()
    try:
        drop_spare(pool)
        pool.process_full(request("keep my bedroom at 19", context={
            "person": "person.ben", "speaker": "Ben"}))
        assert pool.workers["convA"].people == {"ben"}
    finally:
        shutdown(pool)
