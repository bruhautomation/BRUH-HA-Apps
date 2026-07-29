"""Tests for the worker pool's 3.0 HTTP frontend and the integration's
HTTP transport — including a genuine end-to-end loop in CI:

    bridge (aiohttp, stubbed hass) -> pool HTTP server -> fake claude -> SSE back
"""

from __future__ import annotations

import asyncio
import http.client
import importlib.util
import json
import os
import sys
import time
import types
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
POOL_PATH = (
    REPO_ROOT / "brain" / "integrations" / "assist-worker-pool.py"
)
BRIDGE_DIR = (
    REPO_ROOT / "brain" / "custom_components" / "brain"
)
FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"


def load_pool_module(tmp_path: Path, monkeypatch, **extra_env):
    shared = tmp_path / "shared"
    monkeypatch.setenv("BRAIN_SHARED_DIR", str(shared))
    monkeypatch.setenv("BRAIN_ASSIST_WORKDIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_CLAUDE_BIN", f"{sys.executable} {FAKE_CLAUDE}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "argv.log"))
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


def make_request(text="hello", conv="convA", **extra) -> dict:
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


def start_server(mod, pool, port):
    mod.API_PORT = port
    mod.start_http_server(pool)
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/health")
            conn.getresponse().read()
            conn.close()
            return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("server never came up")


def read_sse(resp) -> list[dict]:
    events = []
    buffer = b""
    while True:
        chunk = resp.read(1)
        if not chunk:
            break
        buffer += chunk
        while b"\n\n" in buffer:
            raw, buffer = buffer.split(b"\n\n", 1)
            line = raw.decode().strip()
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        if events and events[-1].get("type") in ("result", "error"):
            return events
    return events


def test_health_and_auth(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        start_server(mod, pool, 18741)
        # Unauthenticated /health: liveness only, no operational telemetry.
        conn = http.client.HTTPConnection("127.0.0.1", 18741, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        health = json.loads(resp.read())
        assert health == {"status": "ok"}
        conn.close()

        # token + endpoint published for the integration
        assert os.path.isfile(mod.API_TOKEN_FILE)
        endpoint = json.load(open(mod.API_ENDPOINT_FILE))
        assert endpoint["port"] == 18741

        # With the token, /health returns the full telemetry.
        token = open(mod.API_TOKEN_FILE).read().strip()
        conn = http.client.HTTPConnection("127.0.0.1", 18741, timeout=5)
        conn.request("GET", "/health", headers={"X-BRUH-Token": token})
        resp = conn.getresponse()
        assert resp.status == 200
        health = json.loads(resp.read())
        assert health["status"] == "ok"
        assert "workers" in health and "tool_access" in health
        conn.close()

        # conversation without/with-bad token -> 401
        conn = http.client.HTTPConnection("127.0.0.1", 18741, timeout=5)
        conn.request("POST", "/conversation", body=json.dumps(make_request()),
                     headers={"X-BRUH-Token": "wrong"})
        assert conn.getresponse().status == 401
        conn.close()
    finally:
        shutdown(pool)


def test_conversation_sse_streams_deltas(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        start_server(mod, pool, 18742)
        token = open(mod.API_TOKEN_FILE).read().strip()
        conn = http.client.HTTPConnection("127.0.0.1", 18742, timeout=30)
        conn.request(
            "POST", "/conversation",
            body=json.dumps(make_request("stream me")),
            headers={"X-BRUH-Token": token, "Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/event-stream"
        events = read_sse(resp)
        conn.close()

        deltas = [e["text"] for e in events if e["type"] == "delta"]
        results = [e for e in events if e["type"] == "result"]
        assert len(results) == 1
        assert "stream me" in results[0]["text"]
        # fake_claude splits the result into 2 token deltas
        assert len(deltas) >= 2
        assert "".join(deltas) == results[0]["text"]
    finally:
        shutdown(pool)


def test_process_delta_cb_direct(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        chunks: list[str] = []
        response = pool.process(make_request("direct"), delta_cb=chunks.append)
        assert "direct" in response
        assert "".join(chunks) == response
    finally:
        shutdown(pool)


def test_mcp_only_scoping_adds_settings_flag(tmp_path, monkeypatch):
    mod = load_pool_module(
        tmp_path, monkeypatch, BRAIN_ASSIST_TOOL_ACCESS="mcp_only"
    )
    with open(mod.ASSIST_SETTINGS_FILE, "w") as fh:
        json.dump({"permissions": {"deny": ["Bash"]}}, fh)
    pool = mod.Pool()
    try:
        pool.handle(make_request("scoped"))
        spawns = [json.loads(line) for line in
                  (tmp_path / "argv.log").read_text().splitlines()
                  if not line.startswith("ENV ")]
        argv = spawns[-1]
        assert "--settings" in argv
        assert argv[argv.index("--settings") + 1] == mod.ASSIST_SETTINGS_FILE
    finally:
        shutdown(pool)


def test_full_access_skips_settings_flag(tmp_path, monkeypatch):
    mod = load_pool_module(
        tmp_path, monkeypatch, BRAIN_ASSIST_TOOL_ACCESS="full"
    )
    with open(mod.ASSIST_SETTINGS_FILE, "w") as fh:
        json.dump({"permissions": {"deny": ["Bash"]}}, fh)
    pool = mod.Pool()
    try:
        pool.handle(make_request("unscoped"))
        spawns = [json.loads(line) for line in
                  (tmp_path / "argv.log").read_text().splitlines()
                  if not line.startswith("ENV ")]
        assert "--settings" not in spawns[-1]
    finally:
        shutdown(pool)


def test_pool_status_heartbeat(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        pool.handle(make_request("beat"))
        status = json.load(open(mod.POOL_STATUS_FILE))
        assert status["status"] == "ok"
        assert status["last_request"]["duration_s"] >= 0
    finally:
        shutdown(pool)


# ---------------------------------------------------------------------------
# End-to-end: the actual integration bridge over HTTP against the live pool
# ---------------------------------------------------------------------------


def load_bridge(tmp_path: Path):
    """Import the real bridge.py with homeassistant stubbed out."""
    ha = types.ModuleType("homeassistant")
    ha_core = types.ModuleType("homeassistant.core")
    ha_core.HomeAssistant = type("HomeAssistant", (), {})
    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_aiohttp = types.ModuleType("homeassistant.helpers.aiohttp_client")
    import aiohttp

    def async_get_clientsession(hass):
        return hass.aiohttp_session

    ha_aiohttp.async_get_clientsession = async_get_clientsession
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.aiohttp_client"] = ha_aiohttp

    pkg_dir = tmp_path / "bridgepkg"
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")
    for name in ("bridge.py", "const.py"):
        (pkg_dir / name).write_text((BRIDGE_DIR / name).read_text())
    sys.path.insert(0, str(tmp_path))
    pkg_name = f"bridgepkg"
    if pkg_name in sys.modules:
        for mod_name in list(sys.modules):
            if mod_name.startswith(pkg_name):
                del sys.modules[mod_name]
    import importlib
    return importlib.import_module(f"{pkg_name}.bridge")


def test_bridge_streams_over_http_end_to_end(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    pool = mod.Pool()
    try:
        start_server(mod, pool, 18743)
        # Point the endpoint file at localhost (container hostname isn't
        # resolvable in CI)
        endpoint = json.load(open(mod.API_ENDPOINT_FILE))
        endpoint["host"] = "127.0.0.1"
        json.dump(endpoint, open(mod.API_ENDPOINT_FILE, "w"))

        bridge_mod = load_bridge(tmp_path)
        import aiohttp

        class FakeConfig:
            def path(self, *parts):
                return os.path.join(str(tmp_path / "shared"), *parts[1:]) \
                    if parts and parts[0] == ".brain" \
                    else os.path.join(str(tmp_path), *parts)

        class FakeHass:
            config = FakeConfig()

            async def async_add_executor_job(self, fn, *args):
                return fn(*args)

        async def main():
            hass = FakeHass()
            hass.aiohttp_session = aiohttp.ClientSession()
            try:
                bridge = bridge_mod.ClaudeBridge(hass, timeout=60)

                # health over HTTP
                health = await bridge.async_api_health()
                assert health and health["status"] == "ok"

                deltas: list[str] = []
                text = await bridge.async_send_conversation_streaming(
                    "end to end", conversation_id="convE2E",
                    delta_listener=deltas.append,
                )
                assert "end to end" in text
                assert "".join(deltas) == text
                # history recorded on the HTTP path too
                assert len(bridge._conversation_history["convE2E"]) == 2
            finally:
                await hass.aiohttp_session.close()

        asyncio.new_event_loop().run_until_complete(main())
    finally:
        shutdown(pool)


def test_bridge_falls_back_to_files_when_api_down(tmp_path, monkeypatch):
    mod = load_pool_module(tmp_path, monkeypatch)
    # endpoint file points at a dead port
    os.makedirs(os.path.dirname(mod.API_ENDPOINT_FILE), exist_ok=True)
    json.dump({"host": "127.0.0.1", "port": 1, "ts": time.time()},
              open(mod.API_ENDPOINT_FILE, "w"))
    with open(mod.API_TOKEN_FILE, "w") as fh:
        fh.write("x" * 32)

    bridge_mod = load_bridge(tmp_path)
    import aiohttp

    class FakeConfig:
        def path(self, *parts):
            return os.path.join(str(tmp_path / "shared"), *parts[1:]) \
                if parts and parts[0] == ".brain" \
                else os.path.join(str(tmp_path), *parts)

    class FakeHass:
        config = FakeConfig()

        async def async_add_executor_job(self, fn, *args):
            return fn(*args)

    async def main():
        hass = FakeHass()
        hass.aiohttp_session = aiohttp.ClientSession()
        try:
            bridge = bridge_mod.ClaudeBridge(hass, timeout=5)
            assert await bridge.async_api_health() is None

            async def fake_file_responder():
                for _ in range(100):
                    files = [f for f in os.listdir(bridge.requests_dir)
                             if f.endswith(".json")]
                    if files:
                        p = os.path.join(bridge.requests_dir, files[0])
                        req = json.load(open(p))
                        os.remove(p)
                        out = os.path.join(bridge.responses_dir,
                                           req["id"] + ".json")
                        os.makedirs(bridge.responses_dir, exist_ok=True)
                        json.dump({"id": req["id"], "text": "via files"},
                                  open(out, "w"))
                        return
                    await asyncio.sleep(0.02)

            os.makedirs(bridge.requests_dir, exist_ok=True)
            responder = asyncio.ensure_future(fake_file_responder())
            text = await bridge.async_send_conversation_streaming(
                "fallback please", conversation_id="convFB"
            )
            await responder
            assert text == "via files"
        finally:
            await hass.aiohttp_session.close()

    asyncio.new_event_loop().run_until_complete(main())


def test_bridge_does_not_resend_after_accepted_stream_break(tmp_path, monkeypatch):
    """Once the pool accepts a request (200), a broken stream must NOT fall
    back to a file re-send — the command may already be executing."""
    import socket
    import threading

    mod = load_pool_module(tmp_path, monkeypatch)
    os.makedirs(os.path.dirname(mod.API_ENDPOINT_FILE), exist_ok=True)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def broken_server():
        conn, _addr = server.accept()
        conn.recv(65536)  # read the request
        conn.sendall(
            b"HTTP/1.0 200 OK\r\nContent-Type: text/event-stream\r\n\r\n"
            b'data: {"type": "delta", "text": "half a rep"}\n\n'
        )
        conn.close()  # die mid-stream, before the result event

    threading.Thread(target=broken_server, daemon=True).start()

    json.dump({"host": "127.0.0.1", "port": port, "ts": time.time()},
              open(mod.API_ENDPOINT_FILE, "w"))
    with open(mod.API_TOKEN_FILE, "w") as fh:
        fh.write("t" * 32)

    bridge_mod = load_bridge(tmp_path)
    import aiohttp

    class FakeConfig:
        def path(self, *parts):
            return os.path.join(str(tmp_path / "shared"), *parts[1:]) \
                if parts and parts[0] == ".brain" \
                else os.path.join(str(tmp_path), *parts)

    class FakeHass:
        config = FakeConfig()

        async def async_add_executor_job(self, fn, *args):
            return fn(*args)

    async def main():
        hass = FakeHass()
        hass.aiohttp_session = aiohttp.ClientSession()
        try:
            bridge = bridge_mod.ClaudeBridge(hass, timeout=10)
            deltas = []
            text = await bridge.async_send_conversation_streaming(
                "toggle the lights", conversation_id="convBRK",
                delta_listener=deltas.append,
            )
            # Apology, not a retry
            assert "dropped mid-response" in text
            # And crucially: nothing was re-sent over the file protocol
            req_files = [f for f in os.listdir(bridge.requests_dir)
                         if f.endswith(".json")] \
                if os.path.isdir(bridge.requests_dir) else []
            assert req_files == [], "stream break must not re-send via files"
        finally:
            await hass.aiohttp_session.close()
            server.close()

    asyncio.new_event_loop().run_until_complete(main())


def test_runsh_voice_deny_list_blocks_all_file_access():
    """The mcp_only deny-list must block shell, web, AND file reads —
    voice gets HA data exclusively via MCP; Read/Glob/Grep would only
    enable reading /config secrets aloud."""
    run_sh = (REPO_ROOT / "brain" / "run.sh").read_text()
    start = run_sh.index("assist_settings.json << 'SCOPE'")
    deny_block = run_sh[start:run_sh.index("SCOPE", start + 40)]
    for tool in ("Bash", "Read", "Glob", "Grep", "Write", "Edit",
                 "WebFetch", "WebSearch", "Agent"):
        assert f'"{tool}"' in deny_block, f"voice deny-list missing {tool}"
