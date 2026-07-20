"""Tests for integrations/assist-worker-pool.py (Assist fast mode).

The pool is exercised against tests/fake_claude.py — a stub that speaks the
same stream-json shape the real CLI does and embeds its PID in every answer,
so process reuse (the whole point of the pool) is directly observable.

The module reads its configuration from the environment at import time, so
each test imports a fresh copy via importlib with env pointed at tmp_path.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
POOL_PATH = (
    REPO_ROOT / "bruh-claude-terminal" / "integrations" / "assist-worker-pool.py"
)
FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"


def load_pool_module(tmp_path: Path, monkeypatch, **extra_env):
    shared = tmp_path / "shared"
    monkeypatch.setenv("BRUH_SHARED_DIR", str(shared))
    monkeypatch.setenv("BRUH_ASSIST_WORKDIR", str(tmp_path))
    monkeypatch.setenv("BRUH_CLAUDE_BIN", f"{sys.executable} {FAKE_CLAUDE}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "argv.log"))
    # No token -> area-map refresh is skipped; prompts use the no-map branch.
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


def shutdown(pool) -> None:
    for worker in list(pool.workers.values()):
        worker.kill()
    if pool.spare is not None:
        pool.spare.kill()


def make_request(text="turn on the lab lights", conv="convA", **extra) -> dict:
    req = {
        "id": uuid.uuid4().hex,
        "conversation_id": conv,
        "text": text,
        "type": "conversation",
        "ts": time.time(),
        "timeout": 120,
        "conversation_history": [],
    }
    req.update(extra)
    return req


def read_response(mod, req_id: str) -> str:
    path = os.path.join(mod.RESPONSES_DIR, f"{req_id}.json")
    with open(path) as fh:
        return json.load(fh)["text"]


def fake_pid(response: str) -> str:
    assert response.startswith("OK["), response
    return response[3:response.index("]")]


def argv_log(tmp_path: Path) -> list[list[str]]:
    try:
        lines = (tmp_path / "argv.log").read_text().splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if not line.startswith("ENV ")]


def test_cold_then_warm_reuses_process(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        r1 = make_request("first")
        pool.handle(r1)
        resp1 = read_response(mod, r1["id"])
        pid1 = fake_pid(resp1)
        assert "first" in resp1

        # Session id persisted for cross-restart resume
        with open(os.path.join(mod.SESSIONS_DIR, "convA")) as fh:
            assert len(fh.read()) == 36

        r2 = make_request("second")
        pool.handle(r2)
        resp2 = read_response(mod, r2["id"])
        assert fake_pid(resp2) == pid1, "follow-up must reuse the live worker"
    finally:
        shutdown(pool)


def test_new_conversation_adopts_prewarmed_spare(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        r1 = make_request("warm me up", conv="convA")
        pool.handle(r1)

        # The first request triggers an async spare spawn — wait for it.
        deadline = time.time() + 5
        while pool.spare is None and time.time() < deadline:
            time.sleep(0.05)
        assert pool.spare is not None, "spare was never pre-warmed"
        spare_pid = str(pool.spare.proc.pid)

        r2 = make_request("new conversation", conv="convB")
        pool.handle(r2)
        resp2 = read_response(mod, r2["id"])
        assert fake_pid(resp2) == spare_pid, "new conv should adopt the spare"
        assert "convB" in pool.workers
    finally:
        shutdown(pool)


def test_worker_crash_falls_back_to_oneshot(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_MODE", "crash")
    pool = mod.Pool()
    try:
        req = make_request("please survive", timeout=40)
        pool.handle(req)
        # In crash mode the stream worker dies, but the one-shot fallback
        # also runs in crash mode... which only crashes in stream mode.
        resp = read_response(mod, req["id"])
        assert resp.startswith("ONESHOT:")
        assert "please survive" in resp
        assert "convA" not in pool.workers, "crashed worker must be dropped"
    finally:
        shutdown(pool)


def test_auth_error_recycles_pool_and_gives_guidance(tmp_path, monkeypatch):
    """An expired OAuth login must not leak the raw CLI error to the voice
    channel: the pool replaces it with an actionable /login instruction and
    drops its workers so post-relogin requests spawn fresh processes."""
    mod = load_pool_module(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_MODE", "autherror")
    pool = mod.Pool()
    try:
        req = make_request("what's going on at home?", timeout=40)
        pool.handle(req)
        resp = read_response(mod, req["id"])
        assert "OAuth session expired" not in resp
        assert "/login" in resp and "BRUH Terminal" in resp
        assert "convA" not in pool.workers, "broken worker must be dropped"
    finally:
        shutdown(pool)


def test_auth_error_regex_matches_cli_phrasings(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    for text in (
        "Failed to authenticate: OAuth session expired and could not be refreshed",
        "OAuth token refresh failed: authentication_error",
        "Not logged in. Please run /login",
        "Invalid API key · Fix external API key",
    ):
        assert mod.AUTH_ERROR_RE.search(text), text
    # ordinary answers that merely mention logins/refreshing must not trip it
    for text in (
        "ONESHOT: turn on the lights",
        "The Netflix account is not logged in on the living room TV.",
        "The sensor data could not be refreshed, so I used the last reading.",
    ):
        assert not mod.AUTH_ERROR_RE.search(text), text


def test_hang_produces_timeout_message(tmp_path, monkeypatch):
    mod = load_pool_module(
        tmp_path, monkeypatch, BRUH_ASSIST_LIMIT_FLOOR="3"
    )
    monkeypatch.setenv("FAKE_MODE", "hang")
    pool = mod.Pool()
    try:
        req = make_request("are you there?", timeout=4)
        start = time.time()
        pool.handle(req)
        elapsed = time.time() - start
        resp = read_response(mod, req["id"])
        assert "timed out" in resp
        assert elapsed < 15, f"timeout path took {elapsed:.0f}s"
    finally:
        shutdown(pool)


def test_cold_start_replays_history(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        req = make_request(
            "and now?",
            conversation_history=[
                {"role": "user", "content": "turn on the lights"},
                {"role": "assistant", "content": "done"},
            ],
        )
        pool.handle(req)
        resp = read_response(mod, req["id"])
        assert "Previous conversation:" in resp
        assert "USER: turn on the lights" in resp
        assert "and now?" in resp
    finally:
        shutdown(pool)


def test_cold_start_resumes_stored_session(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    sid = "facefeed-dead-beef-aaaa-000011112222"
    with open(os.path.join(mod.SESSIONS_DIR, "convA"), "w") as fh:
        fh.write(sid)
    pool = mod.Pool()
    try:
        req = make_request(
            "continue please",
            conversation_history=[{"role": "user", "content": "old turn"}],
        )
        pool.handle(req)
        resp = read_response(mod, req["id"])
        # Resumed sessions must NOT replay history (context lives server-side)
        assert "Previous conversation" not in resp
        spawns = argv_log(tmp_path)
        assert any(
            "--resume" in a and a[a.index("--resume") + 1] == sid
            for a in spawns
        ), "worker was not spawned with --resume <stored session>"
    finally:
        shutdown(pool)


def test_area_map_lands_in_system_prompt(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    with open(mod.AREA_MAP_FILE, "w") as fh:
        fh.write("Lab: light.lab_main, fan.lab\nWeather: weather.home\n")
    pool = mod.Pool()
    try:
        req = make_request("turn on the lab fan")
        pool.handle(req)
        spawns = argv_log(tmp_path)
        prompts = [
            a[a.index("--system-prompt") + 1]
            for a in spawns if "--system-prompt" in a
        ]
        assert prompts, "no worker spawned with a system prompt"
        assert "light.lab_main" in prompts[-1]
        assert "weather.home" in prompts[-1]
        assert "never call get_areas" in prompts[-1]
    finally:
        shutdown(pool)


def test_custom_prompt_and_model_flag(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        req = make_request(
            "hello", system_prompt="You are Dave.", model="haiku"
        )
        pool.handle(req)
        spawns = argv_log(tmp_path)
        last = spawns[-1]
        assert "--model" in last and last[last.index("--model") + 1] == "haiku"
        prompt = last[last.index("--system-prompt") + 1]
        assert prompt.startswith("PERSONALITY")
        assert "You are Dave." in prompt
    finally:
        shutdown(pool)


def test_claim_request_discards_stale(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    req = make_request("too old")
    req["ts"] = time.time() - 500
    path = os.path.join(mod.REQUESTS_DIR, "stale.json")
    with open(path, "w") as fh:
        json.dump(req, fh)
    assert mod.claim_request(path) is None
    assert not os.path.exists(path)


def test_claim_request_race_and_garbage(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    missing = os.path.join(mod.REQUESTS_DIR, "gone.json")
    assert mod.claim_request(missing) is None

    garbage = os.path.join(mod.REQUESTS_DIR, "bad.json")
    with open(garbage, "w") as fh:
        fh.write("{not json")
    assert mod.claim_request(garbage) is None
    assert not os.path.exists(garbage)


def test_reap_kills_idle_and_caps_pool(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        for i in range(3):
            req = make_request(f"hi {i}", conv=f"conv{i}")
            pool.handle(req)
        assert len(pool.workers) >= 1
        # Make every worker look idle beyond the reap window
        for worker in pool.workers.values():
            worker.last_used -= mod.WORKER_IDLE_REAP + 1
        pool.reap()
        assert pool.workers == {}
    finally:
        shutdown(pool)


def test_no_map_prompt_without_area_cache(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        req = make_request("anything")
        pool.handle(req)
        spawns = argv_log(tmp_path)
        prompt = spawns[-1][spawns[-1].index("--system-prompt") + 1]
        assert "call get_areas to resolve the room" in prompt
    finally:
        shutdown(pool)


def test_truncate_at_line(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    text = "Weather: weather.home\nLab: light.lab_one, light.lab_two\nKitchen: light.kitchen\n"
    # No-op under the cap
    assert mod._truncate_at_line(text, 1000) == text
    # Over the cap: cut lands on a line boundary, never mid-entity
    cut = mod._truncate_at_line(text, len("Weather: weather.home\nLab: light."))
    assert cut == "Weather: weather.home\n"
    assert mod._truncate_at_line("oneline-no-newline", 5) == ""


def test_prewarm_spare_uses_last_profile(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    with open(mod.LAST_PROFILE_FILE, "w") as fh:
        json.dump({"system_prompt": "You are Dave.", "model": "haiku"}, fh)

    pool = mod.Pool()
    try:
        mod.prewarm_spare(pool)
        deadline = time.time() + 5
        while pool.spare is None and time.time() < deadline:
            time.sleep(0.05)
        assert pool.spare is not None, "prewarm never produced a spare"
        assert pool.spare.profile[0].startswith("PERSONALITY")
        assert "You are Dave." in pool.spare.profile[0]
        assert pool.spare.profile[1] == "haiku"
        spare_pid = str(pool.spare.proc.pid)

        # The first request with the same agent profile adopts it directly.
        req = make_request("hello", system_prompt="You are Dave.", model="haiku")
        pool.handle(req)
        resp = read_response(mod, req["id"])
        assert fake_pid(resp) == spare_pid, "first request should adopt prewarmed spare"
    finally:
        shutdown(pool)


def test_handle_persists_last_profile(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        pool.handle(make_request("hi", system_prompt="Butler mode.", model="sonnet"))
        with open(mod.LAST_PROFILE_FILE) as fh:
            data = json.load(fh)
        assert data == {"system_prompt": "Butler mode.", "model": "sonnet", "denied": ""}
    finally:
        shutdown(pool)


def test_pool_script_compiles_and_has_main():
    assert POOL_PATH.exists()
    source = POOL_PATH.read_text()
    compile(source, str(POOL_PATH), "exec")
    assert 'if __name__ == "__main__":' in source


def test_clear_conversation_resets_warm_worker(tmp_path, monkeypatch):
    """Deleting the session mapping (bruh_claude.clear_conversation) must
    reset a live warm worker too — otherwise the old context survives."""
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        r1 = make_request("remember me", conv="convClear")
        pool.handle(r1)
        pid1 = fake_pid(read_response(mod, r1["id"]))
        session_file = os.path.join(mod.SESSIONS_DIR, "convClear")
        assert os.path.isfile(session_file)

        # Same conversation, mapping intact -> warm reuse
        r2 = make_request("still me", conv="convClear")
        pool.handle(r2)
        assert fake_pid(read_response(mod, r2["id"])) == pid1

        # Integration clears the conversation -> mapping file removed
        os.remove(session_file)
        r3 = make_request("who am i", conv="convClear")
        pool.handle(r3)
        assert fake_pid(read_response(mod, r3["id"])) != pid1, \
            "cleared conversation must not reuse the old worker"
    finally:
        shutdown(pool)


def test_local_time_stamp_and_timezone_prompt(tmp_path, monkeypatch):
    """With HA's timezone cached, the system prompt names it and every
    message carries a local-time stamp; without it, nothing is added."""
    mod = load_pool_module(tmp_path, monkeypatch)
    with open(mod.TIMEZONE_FILE, "w") as fh:
        fh.write("America/Chicago")
    pool = mod.Pool()
    try:
        req = make_request("what time is it")
        pool.handle(req)
        resp = read_response(mod, req["id"])
        assert "(Local time: " in resp
        assert "America/Chicago" in resp

        spawns = argv_log(tmp_path)
        prompt = spawns[-1][spawns[-1].index("--system-prompt") + 1]
        assert "timezone is America/Chicago" in prompt
        assert "never UTC" in prompt
    finally:
        shutdown(pool)

    # No timezone known -> clean messages (also keeps other tests stable)
    mod2 = load_pool_module(tmp_path / "no_tz", monkeypatch)
    pool2 = mod2.Pool()
    try:
        req = make_request("plain")
        pool2.handle(req)
        assert "(Local time:" not in read_response(mod2, req["id"])
    finally:
        shutdown(pool2)


def test_prompt_layering_personality_owns_identity(tmp_path, monkeypatch):
    """With a personality: it leads with explicit precedence, and the
    operational block carries no competing identity or brevity rule.
    Without one: the default identity + brevity apply."""
    mod = load_pool_module(tmp_path, monkeypatch)

    with_persona = mod.build_system_prompt("You are Dave, a sardonic butler.")
    assert with_persona.startswith("PERSONALITY")
    assert "takes precedence" in with_persona
    assert "You are Dave, a sardonic butler." in with_persona
    # the old identity/brevity must NOT fight the personality
    assert "You are a helpful, efficient Home Assistant voice assistant" not in with_persona
    assert "1-2 short sentences" not in with_persona
    # personality comes before the operational block
    assert with_persona.index("You are Dave") < with_persona.index("Use your MCP tools")
    # capabilities always present
    assert "get_weather_forecast" in with_persona

    no_persona = mod.build_system_prompt("")
    assert no_persona.startswith("You are a helpful, efficient Home Assistant voice assistant")
    assert "1-2 short sentences" in no_persona
    assert "PERSONALITY" not in no_persona
    assert "Use your MCP tools" in no_persona


def _env_lines(tmp_path):
    return [l for l in (tmp_path / "argv.log").read_text().splitlines()
            if l.startswith("ENV BRUH_DENIED_SERVICES=")]


def test_normalize_denied_stable_sorted_dedup(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    assert mod.normalize_denied(["lock.unlock", "Lock.Unlock", " alarm.* "]) == "alarm.*,lock.unlock"
    assert mod.normalize_denied("b.x,a.y") == "a.y,b.x"
    assert mod.normalize_denied(None) == ""


def test_denied_services_reach_worker_env(tmp_path, monkeypatch):
    """The agent's deny-list must be passed to the claude subprocess env
    (where the MCP server inherits and enforces it)."""
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        req = make_request("lock it", denied_services=["lock.unlock", "alarm_control_panel.*"])
        pool.handle(req)
        envs = _env_lines(tmp_path)
        assert envs, "no env line captured"
        # normalized: sorted + comma-joined
        assert envs[-1] == "ENV BRUH_DENIED_SERVICES=alarm_control_panel.*,lock.unlock"
        # and the deny-list is part of the worker profile (so agents separate)
        conv = "convA"
        assert pool.workers[conv].profile[2] == "alarm_control_panel.*,lock.unlock"
    finally:
        shutdown(pool)


def test_no_denied_services_empty_env(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        pool.handle(make_request("hi"))
        envs = _env_lines(tmp_path)
        assert envs and envs[-1] == "ENV BRUH_DENIED_SERVICES="
    finally:
        shutdown(pool)
