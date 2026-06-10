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
    return [json.loads(line) for line in lines]


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
        assert prompt.startswith("You are Dave.")
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


def test_pool_script_compiles_and_has_main():
    assert POOL_PATH.exists()
    source = POOL_PATH.read_text()
    compile(source, str(POOL_PATH), "exec")
    assert 'if __name__ == "__main__":' in source
