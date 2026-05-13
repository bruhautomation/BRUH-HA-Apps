"""Unit tests for the chat-server's ClaudeSession + WS dispatcher.

We test the ClaudeSession lifecycle against a *fake* claude-code subprocess
(a tiny shell script that produces a known NDJSON stream) so we exercise the
real pipe / line-buffering behaviour without depending on the real binary.

The WS-side dispatcher (`_dispatch_client_message`) is tested directly
against a stub ClaudeSession so we can verify message routing without
spawning subprocesses for every assertion.

`CLAUDE_BIN` is read at module-import time from `BRUH_CLAUDE_BIN`. We patch
the module-level attribute per test rather than reloading the module, so
tests stay independent.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "bruh-claude-terminal" / "chat-server"


def _load(module_name: str):
    path = SERVER_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"chat_server.{module_name}", path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Both modules live in /opt/chat-server at runtime; app.py does
    # `from claude_session import ClaudeSession` which resolves via sys.path.
    # We mirror that here so app.py can import claude_session under test.
    sys.modules[f"chat_server.{module_name}"] = mod
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def claude_session_mod():
    return _load("claude_session")


@pytest.fixture(scope="module")
def app_mod(claude_session_mod):
    # Load app.py after claude_session so `from claude_session import ...`
    # resolves to our module instance.
    return _load("app")


def _write_fake_bin(path: Path, script: str) -> Path:
    path.write_text(script)
    path.chmod(0o755)
    return path


@pytest.fixture
def use_fake_bin(claude_session_mod, monkeypatch):
    """Helper: install a fake claude binary for the duration of a test."""

    def _install(script: str, tmp_path: Path, name: str = "fake-claude") -> Path:
        bin_path = _write_fake_bin(tmp_path / name, script)
        monkeypatch.setattr(claude_session_mod, "CLAUDE_BIN", str(bin_path))
        return bin_path

    return _install


def test_session_emits_events_in_order(claude_session_mod, use_fake_bin, tmp_path):
    use_fake_bin(
        "#!/bin/sh\n"
        "echo '{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"abc\"}'\n"
        "echo '{\"type\":\"assistant\",\"message\":{\"role\":\"assistant\","
        "\"content\":[{\"type\":\"text\",\"text\":\"hi\"}]}}'\n"
        "echo '{\"type\":\"result\",\"duration_ms\":1}'\n"
        "cat >/dev/null\n",
        tmp_path,
    )

    async def run():
        sess = claude_session_mod.ClaudeSession(cwd=str(tmp_path))
        await sess.start()
        collected = []
        async for ev in sess.events():
            collected.append(ev)
            if ev.get("type") == "result":
                break
        await sess.close()
        return collected

    events = asyncio.run(run())
    types = [e.get("type") for e in events]
    assert "system" in types
    assert "assistant" in types
    assert types[-1] == "result"
    assistant = next(e for e in events if e.get("type") == "assistant")
    assert assistant["message"]["content"][0]["text"] == "hi"


def test_session_send_user_message_writes_ndjson(claude_session_mod, use_fake_bin, tmp_path):
    """Verify stdin gets one newline-terminated JSON object per user message."""
    use_fake_bin(
        "#!/bin/sh\n"
        # Echo stdin back to stdout so the parent can parse what we wrote.
        "while IFS= read -r line; do echo \"$line\"; done\n",
        tmp_path,
        name="echo-claude",
    )

    async def run():
        sess = claude_session_mod.ClaudeSession(cwd=str(tmp_path))
        await sess.start()
        await sess.send_user_message("hello")
        # Pull directly off the queue since `events()` returns an async
        # iterator that closes on _eof; we want to inspect mid-stream.
        ev = await asyncio.wait_for(sess._events.get(), timeout=2)
        await sess.close()
        return ev

    ev = asyncio.run(run())
    assert ev["type"] == "user"
    assert ev["content"] == "hello"


def test_session_surfaces_non_json_lines_as_raw(claude_session_mod, use_fake_bin, tmp_path):
    """Non-JSON output should be surfaced as `type: raw` rather than dropped.

    Important because if claude-code ever logs to stdout (warning, crash trace,
    etc.) we want the UI to see it, not silently lose it.
    """
    use_fake_bin(
        "#!/bin/sh\n"
        "echo 'not json at all'\n"
        "cat >/dev/null\n",
        tmp_path,
    )

    async def run():
        sess = claude_session_mod.ClaudeSession(cwd=str(tmp_path))
        await sess.start()
        ev = await asyncio.wait_for(sess._events.get(), timeout=2)
        await sess.close()
        return ev

    ev = asyncio.run(run())
    assert ev["type"] == "raw"
    assert ev["line"] == "not json at all"


def test_send_user_message_requires_running_session(claude_session_mod):
    """Sending before start() should raise so callers don't silently lose
    messages."""
    sess = claude_session_mod.ClaudeSession()

    async def run():
        with pytest.raises(RuntimeError):
            await sess.send_user_message("hi")

    asyncio.run(run())


def test_session_id_propagates_to_subprocess_args(claude_session_mod, use_fake_bin, tmp_path):
    """The provided session_id should appear in argv (so claude can resume),
    and the streaming-mode flags should all be present."""
    argv_file = tmp_path / "argv.txt"
    use_fake_bin(
        "#!/bin/sh\n"
        f"echo \"$@\" > {argv_file}\n"
        "cat >/dev/null\n",
        tmp_path,
        name="record-claude",
    )

    async def run():
        sess = claude_session_mod.ClaudeSession(
            session_id="11111111-2222-3333-4444-555555555555",
            cwd=str(tmp_path),
        )
        await sess.start()
        # Wait for the script to write argv before tearing down.
        for _ in range(30):
            if argv_file.exists():
                break
            await asyncio.sleep(0.05)
        await sess.close()

    asyncio.run(run())
    argv = argv_file.read_text()
    assert "--session-id" in argv
    assert "11111111-2222-3333-4444-555555555555" in argv
    assert "--output-format" in argv and "stream-json" in argv
    assert "--input-format" in argv
    assert "--include-partial-messages" in argv
    assert "--replay-user-messages" in argv


def test_dispatcher_routes_user_message(app_mod):
    """`_dispatch_client_message` should call send_user_message on type=user
    and interrupt() on type=interrupt, and silently ignore unknown types."""
    class Stub:
        def __init__(self):
            self.sent = []
            self.interrupted = 0

        async def send_user_message(self, content):
            self.sent.append(content)

        def interrupt(self):
            self.interrupted += 1

    stub = Stub()
    asyncio.run(app_mod._dispatch_client_message(stub, {"type": "user", "content": "hi"}))
    assert stub.sent == ["hi"]
    asyncio.run(app_mod._dispatch_client_message(stub, {"type": "interrupt"}))
    assert stub.interrupted == 1
    asyncio.run(app_mod._dispatch_client_message(stub, {"type": "wat"}))
    assert stub.sent == ["hi"]
    assert stub.interrupted == 1


def test_dispatcher_flattens_rich_user_content(app_mod):
    """A rich user content array (block-style) should be flattened to text
    so the existing stream-json input shape ({"type":"user","content":"..."})
    remains the only thing claude-code sees."""
    class Stub:
        def __init__(self):
            self.sent = []

        async def send_user_message(self, content):
            self.sent.append(content)

        def interrupt(self):
            pass

    stub = Stub()
    asyncio.run(app_mod._dispatch_client_message(stub, {
        "type": "user",
        "content": [
            {"type": "text", "text": "part 1 "},
            {"type": "text", "text": "part 2"},
            {"type": "image"},  # non-text blocks dropped
        ],
    }))
    assert stub.sent == ["part 1 part 2"]


# --------------------------------------------------------------------------
# Asset URL rewrite — see app.py rewrite_asset_urls docstring for the why.
# These tests use a snippet of the actual HTML Astro emits so a regression
# in the SPA build output (new attribute name, different asset dir) shows
# up here instead of as a black page in production.
# --------------------------------------------------------------------------

REAL_ASTRO_HTML_FRAGMENT = (
    '<link rel="stylesheet" href="/assets/index.B8spJlff.css">'
    '<astro-island uid="J2juE" '
    'component-url="/assets/Chat.RyoiKyJC.js" '
    'component-export="Chat" '
    'renderer-url="/assets/client.CGBE-6eU.js" '
    'props="{}" ssr client="load">'
    '</astro-island>'
)


def test_rewrite_asset_urls_injects_ingress_prefix(app_mod):
    out = app_mod.rewrite_asset_urls(
        REAL_ASTRO_HTML_FRAGMENT,
        "/api/hassio_ingress/abc123",
    )
    assert 'href="/api/hassio_ingress/abc123/assets/index.B8spJlff.css"' in out
    assert 'component-url="/api/hassio_ingress/abc123/assets/Chat.RyoiKyJC.js"' in out
    assert 'renderer-url="/api/hassio_ingress/abc123/assets/client.CGBE-6eU.js"' in out


def test_rewrite_asset_urls_handles_trailing_slash_on_prefix(app_mod):
    """HA usually sends X-Ingress-Path without trailing slash, but in case
    that ever changes we shouldn't double up the separator."""
    out = app_mod.rewrite_asset_urls(
        REAL_ASTRO_HTML_FRAGMENT,
        "/api/hassio_ingress/abc123/",
    )
    assert "//assets/" not in out
    assert 'href="/api/hassio_ingress/abc123/assets/index.B8spJlff.css"' in out


def test_rewrite_asset_urls_empty_prefix_is_noop(app_mod):
    """Direct-port access (no ingress in front) gets no X-Ingress-Path
    header — the absolute URLs already work because they resolve to the
    same FastAPI mount. Don't touch them."""
    out = app_mod.rewrite_asset_urls(REAL_ASTRO_HTML_FRAGMENT, "")
    assert out == REAL_ASTRO_HTML_FRAGMENT


def test_rewrite_asset_urls_handles_both_quote_styles(app_mod):
    """HTML can technically come back with single-quoted attributes (e.g. if
    a future Astro version flips minification). Cover both."""
    src = "<link href='/assets/foo.css'>"
    out = app_mod.rewrite_asset_urls(src, "/api/hassio_ingress/T")
    assert out == "<link href='/api/hassio_ingress/T/assets/foo.css'>"


def test_rewrite_asset_urls_leaves_unrelated_paths_alone(app_mod):
    """Don't rewrite anchor hrefs, API URLs, or other absolute paths that
    aren't actual SPA assets."""
    src = '<a href="/something/else">link</a> <img src="/img/foo.png">'
    out = app_mod.rewrite_asset_urls(src, "/api/hassio_ingress/T")
    assert out == src
