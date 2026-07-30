"""Tests for the 3.3.0 memory & learning system.

Covers the cross-cutting memory contract end to end:
  - the remember_fact MCP tool writes a valid inbox JSONL record
  - the `brain memory` CLI's add/answer subcommands produce contract JSONL
  - the consolidator --once (driven by a fake claude) merges the
    inbox into memory.md + voice.md, archives inbox files, and sweeps
    the external /share inbox
  - the worker pool's get_memory cap/fallback, the system-prompt splice
    and its BRAIN_MEMORY_INJECTION gate, the transcript heuristic, and
    the reflection pass writing inbox facts
  - the integration's _append_memory_fact / _append_question_answer
    helpers (extracted from __init__.py, which can't be imported without
    homeassistant installed)

Contract (shared with bruh-insights):
  inbox/<epoch>-<source>.jsonl, one fact per line:
      {"ts": <epoch int>, "source": "<assist|terminal|insights|service>",
       "fact": "<str>", "confidence": "<high|medium|low>"}
  questions.jsonl: question records {"id","q","asked_by","ts"} and answer
      records {"q","a","source","ts"}
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON = REPO_ROOT / "brain"
POOL_PATH = ADDON / "integrations" / "assist-worker-pool.py"
MCP_SERVER_DIR = ADDON / "ha-mcp-server"
HA_MEMORY = ADDON / "scripts" / "brain-memory.sh"
CONSOLIDATOR = ADDON / "scripts" / "brain-memory-consolidate.sh"
SHARE_LOGIN = ADDON / "scripts" / "ha-share-login.sh"
INTEGRATION_INIT = ADDON / "custom_components" / "brain" / "__init__.py"
FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"

VALID_SOURCES = {"assist", "terminal", "insights", "service"}


def assert_contract_line(line: str, expect_source=None, expect_fact=None):
    """One inbox JSONL line must match the cross-add-on contract."""
    record = json.loads(line)
    assert set(record) == {"ts", "source", "fact", "confidence"}
    assert isinstance(record["ts"], int)
    assert record["source"] in VALID_SOURCES
    assert isinstance(record["fact"], str) and record["fact"]
    assert record["confidence"] in ("high", "medium", "low")
    if expect_source is not None:
        assert record["source"] == expect_source
    if expect_fact is not None:
        assert record["fact"] == expect_fact
    return record


def inbox_lines(memory_dir: Path) -> list[str]:
    lines: list[str] = []
    inbox = memory_dir / "inbox"
    if inbox.is_dir():
        for f in sorted(inbox.glob("*.jsonl")):
            lines.extend(
                l for l in f.read_text().splitlines() if l.strip()
            )
    return lines


# ---------------------------------------------------------------------------
# remember_fact MCP tool
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp(monkeypatch, tmp_path):
    sys.path.insert(0, str(MCP_SERVER_DIR))
    import ha_mcp_server

    monkeypatch.setattr(ha_mcp_server, "MEMORY_DIR", str(tmp_path / "memory"))
    return ha_mcp_server


def test_remember_fact_writes_contract_line(mcp, tmp_path):
    result = mcp.remember_fact("We call the office lamp 'the beacon'")
    assert result.get("status") == "remembered"
    lines = inbox_lines(tmp_path / "memory")
    assert len(lines) == 1
    record = assert_contract_line(
        lines[0],
        expect_source="assist",
        expect_fact="We call the office lamp 'the beacon'",
    )
    assert record["confidence"] == "high"
    # File naming: <epoch>-assist.jsonl
    (path,) = (tmp_path / "memory" / "inbox").glob("*.jsonl")
    assert path.name.endswith("-assist.jsonl")
    assert path.name.split("-")[0].isdigit()


def test_remember_fact_confidence_and_validation(mcp, tmp_path):
    assert "error" in mcp.remember_fact("")
    assert "error" in mcp.remember_fact("   ")
    result = mcp.remember_fact("Porch light stays on at night", confidence="low")
    assert result["confidence"] == "low"
    # Unknown confidence coerces to the schema default
    result = mcp.remember_fact("Another fact", confidence="certain")
    assert result["confidence"] == "high"


def test_remember_fact_registered_in_tool_registry(mcp):
    schema_names = {t["name"] for t in mcp.TOOLS}
    assert "remember_fact" in schema_names
    assert "remember_fact" in mcp.TOOL_IMPLEMENTATIONS
    schema = next(t for t in mcp.TOOLS if t["name"] == "remember_fact")
    assert schema["inputSchema"]["required"] == ["fact"]
    assert schema["inputSchema"]["properties"]["confidence"]["enum"] == [
        "high", "medium", "low",
    ]


def test_remember_fact_via_dispatcher(mcp, tmp_path):
    result = mcp.handle_tool_call(
        "remember_fact", {"fact": "Dog gets fed at 7 and 17"}
    )
    assert result.get("status") == "remembered"
    assert "error" in mcp.handle_tool_call("remember_fact", {})


# ---------------------------------------------------------------------------
# brain memory CLI
# ---------------------------------------------------------------------------


def run_ha_memory(memory_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, BRAIN_MEMORY_DIR=str(memory_dir))
    return subprocess.run(
        ["bash", str(HA_MEMORY), *args],
        env=env, capture_output=True, text=True, check=False,
    )


def test_ha_memory_add_writes_contract_line(tmp_path):
    memory_dir = tmp_path / "memory"
    result = run_ha_memory(memory_dir, "add", "Guests sleep in the loft")
    assert result.returncode == 0, result.stderr
    lines = inbox_lines(memory_dir)
    assert len(lines) == 1
    record = assert_contract_line(
        lines[0], expect_source="terminal", expect_fact="Guests sleep in the loft"
    )
    assert record["confidence"] == "high"


def test_ha_memory_add_requires_fact(tmp_path):
    result = run_ha_memory(tmp_path / "memory", "add")
    assert result.returncode != 0


def test_ha_memory_clear_requires_confirm_and_keeps_backup(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "memory.md").write_text("# Home Memory\n\n## Preferences\n- x\n")

    result = run_ha_memory(memory_dir, "clear")
    assert result.returncode != 0
    assert "- x" in (memory_dir / "memory.md").read_text()

    result = run_ha_memory(memory_dir, "clear", "--confirm")
    assert result.returncode == 0, result.stderr
    assert "- x" not in (memory_dir / "memory.md").read_text()
    assert "## Preferences" in (memory_dir / "memory.md").read_text()
    assert "- x" in (memory_dir / "memory.md.bak").read_text()


# ---------------------------------------------------------------------------
# Consolidator (--once, fake claude)
# ---------------------------------------------------------------------------

FAKE_MERGED_MEMORY = """# Home Memory

## Preferences
- Movie nights: lights to 20%

## Entity nicknames
- 'the beacon' = light.office_lamp

## Household patterns

## Device notes
"""

FAKE_VOICE = """- 'the beacon' = light.office_lamp
- Movie nights: lights to 20%
"""


def write_fake_consolidation_claude(tmp_path: Path, body: str) -> Path:
    """A stand-in claude binary printing a canned consolidation answer."""
    script = tmp_path / "fake_consolidate_claude.sh"
    script.write_text("#!/bin/bash\ncat > /dev/null\ncat << 'OUT'\n" + body + "OUT\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def run_consolidator(memory_dir: Path, fake_claude: Path, **extra_env):
    env = dict(
        os.environ,
        BRAIN_MEMORY_DIR=str(memory_dir),
        BRAIN_CLAUDE_BIN=str(fake_claude),
        BRAIN_SHARE_INBOX=str(memory_dir.parent / "share-inbox"),
    )
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(CONSOLIDATOR), "--once"],
        env=env, capture_output=True, text=True, check=False,
    )


def seed_inbox(memory_dir: Path) -> None:
    inbox = memory_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": int(time.time()), "source": "assist",
        "fact": "We call the office lamp 'the beacon'", "confidence": "high",
    }
    (inbox / f"{int(time.time())}-assist.jsonl").write_text(
        json.dumps(record) + "\n"
    )


def test_consolidate_once_merges_and_archives(tmp_path):
    memory_dir = tmp_path / "memory"
    seed_inbox(memory_dir)
    (memory_dir / "memory.md").write_text("# Home Memory\n\n## Preferences\n")

    fake = write_fake_consolidation_claude(
        tmp_path, FAKE_MERGED_MEMORY + "-----VOICE-----\n" + FAKE_VOICE
    )
    result = run_consolidator(memory_dir, fake)
    assert result.returncode == 0, result.stdout + result.stderr

    memory = (memory_dir / "memory.md").read_text()
    assert "'the beacon' = light.office_lamp" in memory
    assert "## Preferences" in memory
    voice = (memory_dir / "voice.md").read_text()
    assert "'the beacon'" in voice
    assert len(voice.encode()) <= 2048

    # Inbox archived (not deleted, not left pending)
    assert inbox_lines(memory_dir) == []
    processed = list((memory_dir / "inbox" / "processed").glob("*.jsonl"))
    assert len(processed) == 1


def test_consolidate_once_sweeps_share_inbox(tmp_path):
    memory_dir = tmp_path / "memory"
    share_inbox = tmp_path / "share-inbox"
    share_inbox.mkdir(parents=True)
    record = {
        "ts": int(time.time()), "source": "insights",
        "fact": "Solar production peaks at 13:00", "confidence": "medium",
    }
    external = share_inbox / f"{int(time.time())}-insights.jsonl"
    external.write_text(json.dumps(record) + "\n")

    fake = write_fake_consolidation_claude(
        tmp_path, FAKE_MERGED_MEMORY + "-----VOICE-----\n" + FAKE_VOICE
    )
    result = run_consolidator(memory_dir, fake)
    assert result.returncode == 0, result.stdout + result.stderr
    # External file was moved out of /share and processed
    assert not external.exists()
    processed = list((memory_dir / "inbox" / "processed").glob("*insights*"))
    assert len(processed) == 1


def test_consolidate_failure_leaves_files_untouched(tmp_path):
    memory_dir = tmp_path / "memory"
    seed_inbox(memory_dir)
    original = "# Home Memory\n\n## Preferences\n- keep me\n"
    (memory_dir / "memory.md").write_text(original)

    # Output missing the separator -> parse failure -> nothing changes
    fake = write_fake_consolidation_claude(tmp_path, "garbage output\n")
    result = run_consolidator(memory_dir, fake)
    assert result.returncode != 0
    assert (memory_dir / "memory.md").read_text() == original
    assert not (memory_dir / "voice.md").exists()
    assert len(inbox_lines(memory_dir)) == 1  # still pending

    # Oversized voice.md is also rejected
    fake = write_fake_consolidation_claude(
        tmp_path, FAKE_MERGED_MEMORY + "-----VOICE-----\n" + "x" * 4000 + "\n"
    )
    result = run_consolidator(memory_dir, fake)
    assert result.returncode != 0
    assert (memory_dir / "memory.md").read_text() == original


def test_consolidate_empty_inbox_is_a_noop(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True)
    fake = write_fake_consolidation_claude(tmp_path, "should never run\n")
    result = run_consolidator(memory_dir, fake)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (memory_dir / "voice.md").exists()


def test_a_successful_pass_stamps_the_marker(tmp_path):
    """The marker's mtime is how the panel tells a queued discovery from a
    filed one, so a pass that files facts has to move it."""
    memory_dir = tmp_path / "memory"
    seed_inbox(memory_dir)
    fake = write_fake_consolidation_claude(
        tmp_path, FAKE_MERGED_MEMORY + "-----VOICE-----\n" + FAKE_VOICE)
    assert run_consolidator(memory_dir, fake).returncode == 0
    assert (memory_dir / ".last_consolidated").exists()


def test_a_failed_pass_does_not_stamp_the_marker(tmp_path):
    """…and a pass that keeps the facts must NOT move it, or the panel would
    fold away discoveries that are still queued."""
    memory_dir = tmp_path / "memory"
    seed_inbox(memory_dir)
    fake = write_fake_consolidation_claude(tmp_path, "garbage output\n")
    assert run_consolidator(memory_dir, fake).returncode != 0
    assert not (memory_dir / ".last_consolidated").exists()


def test_a_held_lock_exits_busy_rather_than_claiming_success(tmp_path):
    """Skipping because someone else holds the lock used to exit 0, which let
    the panel report facts as filed while they sat in the queue untouched."""
    if shutil.which("flock") is None:
        pytest.skip("no flock in this image")
    memory_dir = tmp_path / "memory"
    seed_inbox(memory_dir)
    fake = write_fake_consolidation_claude(
        tmp_path, FAKE_MERGED_MEMORY + "-----VOICE-----\n" + FAKE_VOICE)
    memory_dir.mkdir(parents=True, exist_ok=True)
    lock = memory_dir / ".consolidate.lock"
    lock.touch()
    holder = subprocess.Popen(["flock", str(lock), "sleep", "10"])
    try:
        # wait for the holder to actually own it before racing it
        deadline = time.time() + 5
        while time.time() < deadline:
            probe = subprocess.run(["flock", "-n", str(lock), "true"], check=False)
            if probe.returncode != 0:
                break
            time.sleep(0.05)
        result = run_consolidator(memory_dir, fake, BRAIN_MEMORY_LOCK_WAIT="1")
    finally:
        holder.kill()
        holder.wait()
    assert result.returncode == 75, result.stdout + result.stderr
    assert "already running" in result.stdout + result.stderr
    assert len(inbox_lines(memory_dir)) == 1  # still pending


# ---------------------------------------------------------------------------
# Worker pool: get_memory, prompt splice, reflection
# ---------------------------------------------------------------------------


def load_pool_module(tmp_path: Path, monkeypatch, **extra_env):
    """Import a fresh pool module with env pointed at tmp dirs (mirrors
    tests/test_assist_worker_pool.py's loader, which isn't importable)."""
    shared = tmp_path / "shared"
    monkeypatch.setenv("BRAIN_SHARED_DIR", str(shared))
    monkeypatch.setenv("BRAIN_ASSIST_WORKDIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_CLAUDE_BIN", f"{sys.executable} {FAKE_CLAUDE}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "argv.log"))
    monkeypatch.setenv("BRAIN_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("FAKE_MODE", raising=False)
    for key, value in extra_env.items():
        monkeypatch.setenv(key, value)

    spec = importlib.util.spec_from_file_location(
        f"assist_pool_{uuid.uuid4().hex}", POOL_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    for d in (mod.REQUESTS_DIR, mod.RESPONSES_DIR, mod.SESSIONS_DIR,
              mod.CACHE_DIR, mod.LOG_DIR):
        os.makedirs(d, exist_ok=True)
    return mod


def test_get_memory_prefers_voice_and_caps_at_2kb(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "memory.md").write_text("## Full memory file\n")
    (memory_dir / "voice.md").write_text(
        "- nickname line\n" + ("- filler entry\n" * 400)
    )
    mod.refresh_memory()
    memory = mod.get_memory()
    assert memory.startswith("- nickname line")
    assert len(memory) <= 2048
    assert "## Full memory file" not in memory
    # Cap cuts on a line boundary
    assert not memory or memory.endswith("\n")


def test_get_memory_falls_back_to_memory_md(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "memory.md").write_text("## Preferences\n- lights at 20%\n")
    mod.refresh_memory()
    assert "- lights at 20%" in mod.get_memory()

    # No files at all -> empty, not an error
    mod2 = load_pool_module(tmp_path / "empty", monkeypatch)
    assert mod2.get_memory() == ""


def test_memory_spliced_into_system_prompt(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "voice.md").write_text("- 'the beacon' = light.office_lamp\n")
    mod.refresh_memory()
    prompt = mod.build_system_prompt("")
    assert "Known about this household (learned):" in prompt
    assert "'the beacon' = light.office_lamp" in prompt
    # Memory rides after the tool/area instructions, near the end
    assert prompt.index("Known about this household") > prompt.index("MCP tools")


def test_memory_injection_env_gate(tmp_path, monkeypatch):
    mod = load_pool_module(
        tmp_path, monkeypatch, BRAIN_MEMORY_INJECTION="false"
    )
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(exist_ok=True)
    (memory_dir / "voice.md").write_text("- secret nickname\n")
    mod.refresh_memory()
    prompt = mod.build_system_prompt("")
    assert "Known about this household" not in prompt
    assert "secret nickname" not in prompt


def test_operational_prompt_mentions_remember_fact(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    assert "remember_fact" in mod.OPERATIONAL_PROMPT


def test_transcript_recording_is_bounded(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)

    class FakeWorker:
        transcript: list = []

    worker = FakeWorker()
    worker.transcript = []
    for i in range(20):
        mod._record_exchange(worker, f"user {i} " + "x" * 700, "resp " + "y" * 700)
    assert len(worker.transcript) <= mod.TRANSCRIPT_MAX_EXCHANGES
    assert sum(len(u) + len(a) for u, a in worker.transcript) <= mod.TRANSCRIPT_MAX_BYTES
    # Newest exchanges are the ones kept
    assert worker.transcript[-1][0].startswith("user 19")


def test_transcript_worth_reflecting_heuristic(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    assert not mod._transcript_worth_reflecting([])
    assert not mod._transcript_worth_reflecting([("turn on the lights", "done")])
    assert mod._transcript_worth_reflecting(
        [("hi", "hello"), ("turn on lights", "done")]
    )
    assert mod._transcript_worth_reflecting(
        [("actually we call that lamp the beacon", "noted")]
    )
    assert mod._transcript_worth_reflecting(
        [("never lock the side door automatically", "ok")]
    )


def test_reflection_writes_contract_facts(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    fake = tmp_path / "fake_reflect_claude.sh"
    fake.write_text(
        "#!/bin/bash\ncat > /dev/null\n"
        'echo \'{"fact": "Beacon = light.office_lamp", "confidence": "high"}\'\n'
        'echo \'not json at all\'\n'
        'echo \'{"fact": "", "confidence": "high"}\'\n'
        'echo \'{"fact": "Movie nights dim to 20%", "confidence": "certain"}\'\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("BRAIN_CLAUDE_BIN", str(fake))

    mod.reflect_on_transcript([
        ("actually we call the office lamp the beacon", "Noted!"),
    ])
    lines = inbox_lines(tmp_path / "memory")
    assert len(lines) == 2
    first = assert_contract_line(lines[0], expect_source="assist")
    assert first["fact"] == "Beacon = light.office_lamp"
    assert first["confidence"] == "high"
    second = assert_contract_line(lines[1])
    assert second["confidence"] == "medium"  # invalid value coerced


def test_reflection_none_and_failure_write_nothing(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)

    fake = tmp_path / "fake_none_claude.sh"
    fake.write_text("#!/bin/bash\ncat > /dev/null\necho NONE\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("BRAIN_CLAUDE_BIN", str(fake))
    mod.reflect_on_transcript([("hi", "hello"), ("bye", "bye")])
    assert inbox_lines(tmp_path / "memory") == []

    # Non-zero exit (e.g. not authenticated) is swallowed, nothing stored
    fail = tmp_path / "fail_claude.sh"
    fail.write_text("#!/bin/bash\nexit 1\n")
    fail.chmod(fail.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("BRAIN_CLAUDE_BIN", str(fail))
    mod.reflect_on_transcript([("hi", "hello"), ("bye", "bye")])
    assert inbox_lines(tmp_path / "memory") == []


def test_maybe_reflect_respects_learning_gate(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch, BRAIN_ASSIST_LEARNING="false")
    called = []
    monkeypatch.setattr(
        mod.threading, "Thread",
        lambda *a, **k: called.append(k) or _NeverStartThread(),
    )

    class FakeWorker:
        pass

    worker = FakeWorker()
    worker.transcript = [("hi", "hello"), ("actually call it the den", "ok")]
    mod.maybe_reflect(worker)
    assert called == []


class _NeverStartThread:
    def start(self):
        pass


def test_drop_worker_triggers_reflection(tmp_path, monkeypatch):
    """A reaped/dropped worker with a meaningful transcript is reflected."""
    mod = load_pool_module(tmp_path, monkeypatch)
    reflected: list = []
    monkeypatch.setattr(
        mod, "reflect_on_transcript", lambda transcript: reflected.append(transcript)
    )
    pool = mod.Pool()
    try:
        req = {
            "id": uuid.uuid4().hex,
            "conversation_id": "convR",
            "text": "actually, we call the office lamp the beacon",
            "type": "conversation",
            "ts": time.time(),
            "timeout": 120,
            "conversation_history": [],
        }
        pool.handle(req)
        worker = pool.workers["convR"]
        assert worker.transcript, "successful exchange must be recorded"
        pool._drop_worker("convR", worker)
        deadline = time.time() + 5
        while not reflected and time.time() < deadline:
            time.sleep(0.05)
        assert reflected and "beacon" in reflected[0][0][0]
    finally:
        for w in list(pool.workers.values()):
            w.kill()
        if pool.spare is not None:
            pool.spare.kill()


# ---------------------------------------------------------------------------
# Integration helpers (extracted from __init__.py — HA isn't importable here)
# ---------------------------------------------------------------------------


def load_integration_helpers():
    """Exec just the pure memory helpers from the real __init__.py source."""
    source = INTEGRATION_INIT.read_text()
    tree = ast.parse(source)
    wanted = {
        "_sanitize_source", "_append_memory_fact",
        "_append_question_answer", "_read_text_capped",
    }
    nodes = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef,)) and n.name in wanted
    ]
    assert {n.name for n in nodes} == wanted, "helper functions missing from __init__.py"
    namespace = {
        "os": os, "json": json, "time": time,
        "MEMORY_INBOX_DIR": "inbox", "QUESTIONS_FILE": "questions.jsonl",
    }
    exec(  # noqa: S102 — executing our own source under test
        compile(ast.Module(body=nodes, type_ignores=[]), str(INTEGRATION_INIT), "exec"),
        namespace,
    )
    return namespace


def test_integration_add_memory_helper(tmp_path):
    helpers = load_integration_helpers()
    memory_dir = tmp_path / "memory"
    path = helpers["_append_memory_fact"](
        str(memory_dir), "  Solar peaks at 13:00  ", "service", "medium"
    )
    assert Path(path).parent == memory_dir / "inbox"
    lines = inbox_lines(memory_dir)
    assert len(lines) == 1
    record = assert_contract_line(
        lines[0], expect_source="service", expect_fact="Solar peaks at 13:00"
    )
    assert record["confidence"] == "medium"

    # Bad confidence coerces, hostile source is sanitized for the filename
    helpers["_append_memory_fact"](
        str(memory_dir), "another", "../../etc", "bogus"
    )
    files = sorted((memory_dir / "inbox").glob("*.jsonl"))
    assert all("/" not in f.name.replace(str(memory_dir), "") for f in files)
    last = assert_contract_line(inbox_lines(memory_dir)[-1])
    assert last["confidence"] == "medium"
    assert "/" not in last["source"] and ".." not in last["source"]


def test_integration_answer_question_helper(tmp_path):
    helpers = load_integration_helpers()
    memory_dir = tmp_path / "memory"
    helpers["_append_question_answer"](
        str(memory_dir), "Holiday thermostat schedule?", "Like weekends", "service"
    )
    answers = [
        json.loads(l)
        for l in (memory_dir / "questions.jsonl").read_text().splitlines()
    ]
    assert len(answers) == 1
    assert answers[0]["q"] == "Holiday thermostat schedule?"
    assert answers[0]["a"] == "Like weekends"
    assert answers[0]["source"] == "service"
    assert isinstance(answers[0]["ts"], int)

    record = assert_contract_line(inbox_lines(memory_dir)[0])
    assert record["fact"] == "Q: Holiday thermostat schedule? → A: Like weekends"
    assert record["confidence"] == "high"


def test_read_text_capped(tmp_path):
    helpers = load_integration_helpers()
    path = tmp_path / "memory.md"
    path.write_text("x" * 5000)
    assert helpers["_read_text_capped"](str(path), 2048) == "x" * 2048
    assert helpers["_read_text_capped"](str(tmp_path / "missing"), 100) == ""


def test_integration_registers_memory_services():
    """Source-level checks matching test_integration_python.py's style."""
    content = INTEGRATION_INIT.read_text()
    assert '"add_memory"' in content
    assert '"answer_question"' in content
    assert "ADD_MEMORY_SCHEMA" in content
    assert "ANSWER_QUESTION_SCHEMA" in content
    # Memory context feeds insight runs
    assert "Known about this home:" in content
    assert "Previous report" in content


# ---------------------------------------------------------------------------
# ha-share-login (token mode + status/revoke; no interactive OAuth here)
# ---------------------------------------------------------------------------


def run_share_login(auth_dir: Path, *args: str):
    env = dict(os.environ, BRAIN_AUTH_DIR=str(auth_dir))
    return subprocess.run(
        ["bash", str(SHARE_LOGIN), *args],
        env=env, capture_output=True, text=True, check=False,
    )


def test_share_login_token_mode_writes_contract_file(tmp_path):
    auth_dir = tmp_path / "secrets"
    token = "sk-ant-oat01-" + "a" * 40
    result = run_share_login(auth_dir, "--token", token)
    assert result.returncode == 0, result.stderr

    auth_file = auth_dir / "claude_auth.json"
    data = json.loads(auth_file.read_text())
    assert data["type"] == "oauth_token"
    assert data["value"] == token
    assert isinstance(data["saved_at"], int)
    assert stat.S_IMODE(auth_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(auth_dir.stat().st_mode) == 0o700

    # The stored token must match the regex bruh-insights uses to detect it
    import re
    insights_re = re.compile(r"sk-ant-oat\d{2}-[A-Za-z0-9_\-]{20,}")
    assert insights_re.fullmatch(data["value"])


def test_share_login_rejects_bad_token(tmp_path):
    result = run_share_login(tmp_path / "secrets", "--token", "not-a-token")
    assert result.returncode != 0
    assert not (tmp_path / "secrets" / "claude_auth.json").exists()


def test_share_login_status_and_revoke(tmp_path):
    auth_dir = tmp_path / "secrets"
    result = run_share_login(auth_dir, "--status")
    assert result.returncode == 0
    assert "not set up" in result.stdout

    token = "sk-ant-oat01-" + "b" * 40
    run_share_login(auth_dir, "--token", token)
    result = run_share_login(auth_dir, "--status")
    assert "ACTIVE" in result.stdout

    result = run_share_login(auth_dir, "--revoke")
    assert result.returncode == 0
    assert not (auth_dir / "claude_auth.json").exists()


# ---------------------------------------------------------------------------
# run.sh / config plumbing (source-level, matching test_shell_scripts style)
# ---------------------------------------------------------------------------


def test_run_sh_plumbs_memory_options():
    content = (ADDON / "run.sh").read_text()
    for var in ("BRAIN_ASSIST_LEARNING", "BRAIN_MEMORY_INJECTION", "BRAIN_MEMORY_MAX_KB"):
        assert f"export {var}=" in content, f"run.sh missing export of {var}"
    assert "start_memory_consolidator" in content
    assert "/config/.brain/secrets" in content
    assert "/config/.brain/memory/inbox" in content
    # Installed alongside the other CLI tools
    assert "ha-share-login" in content
    assert "brain memory" in content


def test_config_yaml_has_memory_options():
    import yaml

    config = yaml.safe_load((ADDON / "config.yaml").read_text())
    assert config["options"]["learning"] is True
    assert config["options"]["memory_injection"] is True
    assert config["options"]["memory_max_kb"] == 8
    assert config["schema"]["learning"] == "bool?"
    assert config["schema"]["memory_injection"] == "bool?"
    assert config["schema"]["memory_max_kb"] == "int(1,64)?"


def test_context_gen_preserves_user_notes_and_memory():
    content = (ADDON / "scripts" / "ha-context-gen.sh").read_text()
    assert "bruh:user-notes:start" in content
    assert "bruh:user-notes:end" in content
    assert "Learned Home Knowledge" in content
    assert "brain memory" in content
    assert "ha login" in content
    # The generated CLAUDE.md is what Claude reads to learn its own tooling,
    # so a retired command documented here is one it will actually try to run.
    for retired in ("ha-share-login", "ha-reload", "ha-backup", "ha-entity",
                    "ha-yaml-check", "ha-selftest"):
        assert retired not in content, f"CLAUDE.md still teaches {retired}"
