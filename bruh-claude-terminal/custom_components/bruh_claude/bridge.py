"""File-based bridge for communicating with the BRUH Claude Terminal add-on.

The add-on and this integration share /config/.bruh_claude/ for IPC:
  - requests/   : conversation requests  (integration -> add-on)
  - responses/  : conversation responses  (add-on -> integration)
  - tasks/      : automation task requests (integration -> add-on)
  - task_results/: automation task results (add-on -> integration)
  - sessions/   : conversation_id -> Claude session uuid (written by add-on)

Request/response files are named by a per-request unique id (NOT the
conversation_id). Reusing the conversation_id as the filename caused a nasty
bug: a response written after the bridge stopped waiting (timeout, cancelled
voice pipeline) was consumed by the NEXT turn, leaving the conversation
permanently one answer behind.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from homeassistant.core import HomeAssistant

from .const import (
    API_ENDPOINT_FILENAME,
    API_TOKEN_FILENAME,
    DEFAULT_TASK_TIMEOUT,
    DEFAULT_TIMEOUT,
    REQUESTS_DIR,
    RESPONSES_DIR,
    SESSIONS_DIR,
    SHARED_DIR,
    TASK_RESULTS_DIR,
    TASKS_DIR,
)

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = 0.1  # seconds — local stat() is cheap, keep responses snappy


# Maximum number of conversation turns (user+assistant pairs) to retain per
# session. Only used for the fallback history replay (when the add-on can't
# resume the Claude session); keep it small — replayed history is prepended
# as plain text to every request and slows time-to-first-token.
MAX_HISTORY_TURNS = 6

# Cap stored message length so one verbose answer doesn't bloat every
# subsequent request in the fallback replay path.
HISTORY_MSG_MAX_CHARS = 1500

# Evict the oldest conversation histories beyond this many sessions so the
# in-memory map doesn't grow forever (each voice session gets a fresh id).
MAX_TRACKED_CONVERSATIONS = 50


class _StreamBrokenError(RuntimeError):
    """The pool accepted the request but the stream failed afterwards —
    re-sending is NOT safe (the command may already be executing)."""


class ClaudeBridge:
    """Handles file-based communication with the Claude Terminal add-on."""

    def __init__(self, hass: HomeAssistant, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._hass = hass
        self._timeout = timeout
        self._base = hass.config.path(SHARED_DIR)
        # In-memory conversation history keyed by conversation_id
        self._conversation_history: dict[str, list[dict[str, str]]] = {}

    @property
    def requests_dir(self) -> str:
        return os.path.join(self._base, REQUESTS_DIR)

    @property
    def responses_dir(self) -> str:
        return os.path.join(self._base, RESPONSES_DIR)

    @property
    def tasks_dir(self) -> str:
        return os.path.join(self._base, TASKS_DIR)

    @property
    def task_results_dir(self) -> str:
        return os.path.join(self._base, TASK_RESULTS_DIR)

    @property
    def sessions_dir(self) -> str:
        return os.path.join(self._base, SESSIONS_DIR)

    @property
    def available(self) -> bool:
        """Return True if the shared directory exists (add-on is running)."""
        return os.path.isdir(self._base)

    async def async_send_conversation(
        self,
        text: str,
        conversation_id: str | None = None,
        timeout: int | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> str:
        """Send a conversation request and wait for the response."""
        conv_id = conversation_id or uuid.uuid4().hex
        # Unique per request so concurrent/stale files can never collide
        request_id = uuid.uuid4().hex
        timeout = timeout or self._timeout

        # Snapshot the history for this request; the shared list may gain
        # entries from concurrent turns while we await the response.
        history = list(self._conversation_history.get(conv_id, []))

        request: dict = {
            "id": request_id,
            "conversation_id": conv_id,
            "text": text,
            "type": "conversation",
            "ts": time.time(),
            "timeout": timeout,
            "conversation_history": history,
        }
        if system_prompt:
            request["system_prompt"] = system_prompt
        if model:
            request["model"] = model

        req_file = os.path.join(self.requests_dir, f"{request_id}.json")
        resp_file = os.path.join(self.responses_dir, f"{request_id}.json")

        # Write request file
        await self._hass.async_add_executor_job(
            self._write_json, req_file, request
        )

        _LOGGER.debug(
            "Conversation request %s written (conversation=%s, history: %d turns)",
            request_id,
            conv_id,
            len(history) // 2,
        )

        # Poll for response
        response_text = await self._poll_for_response(resp_file, timeout)

        self._append_history(conv_id, text, response_text)

        return response_text

    # ------------------------------------------------------------------
    # HTTP transport (3.0): streaming via the add-on's internal API, with
    # transparent fallback to the file protocol above.
    # ------------------------------------------------------------------

    async def async_api_config(self) -> tuple[str, str] | None:
        """Return (base_url, token) when the add-on publishes its API."""
        return await self._hass.async_add_executor_job(self._read_api_config)

    def _read_api_config(self) -> tuple[str, str] | None:
        try:
            with open(os.path.join(self._base, API_ENDPOINT_FILENAME)) as fh:
                endpoint = json.load(fh)
            with open(os.path.join(self._base, API_TOKEN_FILENAME)) as fh:
                token = fh.read().strip()
            host = endpoint.get("host")
            port = endpoint.get("port")
            if host and port and token:
                return f"http://{host}:{port}", token
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return None

    async def async_api_health(self) -> dict | None:
        """GET /health from the add-on API; None when unreachable."""
        api = await self.async_api_config()
        if not api:
            return None
        base_url, _token = api
        try:
            import aiohttp
            from homeassistant.helpers.aiohttp_client import async_get_clientsession

            session = async_get_clientsession(self._hass)
            async with session.get(
                f"{base_url}/health", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception:  # noqa: BLE001 — any failure means "not healthy via HTTP"
            return None

    async def async_send_conversation_streaming(
        self,
        text: str,
        conversation_id: str | None = None,
        timeout: int | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        delta_listener=None,
    ) -> str:
        """Send a conversation over HTTP/SSE when available (deltas pushed to
        delta_listener as they arrive), else fall back to the file protocol."""
        api = await self.async_api_config()
        if api:
            try:
                return await self._http_conversation(
                    api, text, conversation_id, timeout, system_prompt, model,
                    delta_listener,
                )
            except _StreamBrokenError as exc:
                # The pool ACCEPTED the request before the stream broke — it
                # may already be executing the command, so re-sending could
                # run it twice. Report instead of retrying.
                _LOGGER.warning("Conversation stream broke mid-flight: %s", exc)
                return (
                    "Sorry, the connection to Claude dropped mid-response. "
                    "The command may still have completed — check before retrying."
                )
            except Exception as exc:  # noqa: BLE001 — pre-acceptance: safe to retry
                _LOGGER.warning(
                    "HTTP transport unavailable (%s) — falling back to file IPC", exc
                )
        return await self.async_send_conversation(
            text,
            conversation_id=conversation_id,
            timeout=timeout,
            system_prompt=system_prompt,
            model=model,
        )

    async def _http_conversation(
        self, api, text, conversation_id, timeout, system_prompt, model,
        delta_listener,
    ) -> str:
        import aiohttp
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        base_url, token = api
        conv_id = conversation_id or uuid.uuid4().hex
        timeout = timeout or self._timeout
        request: dict = {
            "id": uuid.uuid4().hex,
            "conversation_id": conv_id,
            "text": text,
            "type": "conversation",
            "ts": time.time(),
            "timeout": timeout,
            "conversation_history": list(self._conversation_history.get(conv_id, [])),
        }
        if system_prompt:
            request["system_prompt"] = system_prompt
        if model:
            request["model"] = model

        session = async_get_clientsession(self._hass)
        result_text: str | None = None
        accepted = False
        try:
            async with session.post(
                f"{base_url}/conversation",
                json=request,
                headers={"X-BRUH-Token": token},
                timeout=aiohttp.ClientTimeout(total=timeout + 10, sock_read=timeout + 10),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"API returned HTTP {resp.status}")
                # 200 means the pool claimed the request and is processing it
                accepted = True
                async for raw_line in resp.content:
                    line = raw_line.decode(errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type")
                    if etype == "delta" and delta_listener is not None:
                        try:
                            delta_listener(event.get("text") or "")
                        except Exception:  # noqa: BLE001 — listener bugs can't kill the turn
                            _LOGGER.exception("delta listener failed")
                    elif etype == "result":
                        result_text = event.get("text") or ""
                        break
                    elif etype == "error":
                        raise RuntimeError(event.get("message") or "stream error")
        except Exception as exc:
            if accepted:
                raise _StreamBrokenError(str(exc)) from exc
            raise

        if result_text is None:
            if accepted:
                raise _StreamBrokenError("stream ended without a result event")
            raise RuntimeError("stream ended without a result event")
        self._append_history(conv_id, text, result_text)
        return result_text

    def _append_history(self, conv_id: str, user_text: str, response: str) -> None:
        """Record an exchange, trimming length and evicting old sessions.

        Mutates the shared list via setdefault so concurrent turns for the
        same conversation don't overwrite each other's exchanges.
        """
        history = self._conversation_history.setdefault(conv_id, [])
        history.append(
            {"role": "user", "content": user_text[:HISTORY_MSG_MAX_CHARS]}
        )
        history.append(
            {"role": "assistant", "content": response[:HISTORY_MSG_MAX_CHARS]}
        )
        # Trim in place to the most recent turns
        if len(history) > MAX_HISTORY_TURNS * 2:
            del history[: len(history) - MAX_HISTORY_TURNS * 2]

        # Evict the oldest conversations (dicts preserve insertion order)
        while len(self._conversation_history) > MAX_TRACKED_CONVERSATIONS:
            oldest = next(iter(self._conversation_history))
            if oldest == conv_id:
                break
            self._conversation_history.pop(oldest, None)

    async def async_clear_conversation(
        self, conversation_id: str | None = None
    ) -> None:
        """Clear the conversation history and Claude session for a session.

        If conversation_id is None, clears ALL sessions. Removes both the
        in-memory history (fallback replay) and the add-on's session mapping
        file so the assist listener starts a fresh Claude session instead of
        resuming the old one.
        """
        if conversation_id:
            self._conversation_history.pop(conversation_id, None)
        else:
            self._conversation_history.clear()

        await self._hass.async_add_executor_job(
            self._remove_session_files, self.sessions_dir, conversation_id
        )
        _LOGGER.info(
            "Cleared conversation history: %s", conversation_id or "ALL"
        )

    async def async_send_task(
        self,
        prompt: str,
        notify: bool = False,
        notify_entity: str | None = None,
        timeout: int | None = None,
        model: str | None = None,
    ) -> str:
        """Send an automation task and wait for the result."""
        task_id = uuid.uuid4().hex
        # Tasks default to a longer window than conversations — the add-on
        # listener allows up to BRUH_AUTOMATION_TIMEOUT (300s default), and
        # waiting less than that orphans results we asked for.
        timeout = timeout or max(self._timeout, DEFAULT_TASK_TIMEOUT)

        task = {
            "id": task_id,
            "prompt": prompt,
            "notify": notify,
            "ts": time.time(),
            "timeout": timeout,
        }
        if notify_entity:
            task["notify_entity"] = notify_entity
        if model and model != "default":
            task["model"] = model

        task_file = os.path.join(self.tasks_dir, f"{task_id}.json")
        result_file = os.path.join(self.task_results_dir, f"{task_id}.json")

        await self._hass.async_add_executor_job(
            self._write_json, task_file, task
        )

        _LOGGER.debug("Task %s written (timeout=%ds)", task_id, timeout)

        result_text = await self._poll_for_response(result_file, timeout)
        return result_text

    async def _poll_for_response(self, path: str, timeout: int) -> str:
        """Poll for a response file, return its content or raise TimeoutError."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = await self._hass.async_add_executor_job(
                self._read_and_remove, path
            )
            if result is not None:
                return result
            await asyncio.sleep(POLL_INTERVAL)

        raise TimeoutError(
            f"No response within {timeout}s for {os.path.basename(path)}"
        )

    # ------------------------------------------------------------------
    # Synchronous filesystem helpers (run via executor)
    # ------------------------------------------------------------------

    @staticmethod
    def _write_json(path: str, data: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)  # atomic on POSIX

    @staticmethod
    def _read_and_remove(path: str) -> str | None:
        """Read a JSON response file if it exists, delete it, return the text."""
        if not os.path.isfile(path):
            return None
        try:
            with open(path) as fh:
                data = json.load(fh)
            os.remove(path)
            return data.get("text", data.get("result", json.dumps(data)))
        except json.JSONDecodeError as exc:
            _LOGGER.warning("Corrupt response file %s: %s", path, exc)
            # Remove corrupt file to avoid infinite retry loop
            try:
                os.remove(path)
            except OSError:
                pass
            return "Error: received corrupt response from Claude Terminal."
        except OSError as exc:
            _LOGGER.warning("Failed to read response %s: %s", path, exc)
            return None

    @staticmethod
    def _remove_session_files(sessions_dir: str, conversation_id: str | None) -> None:
        """Remove the add-on's Claude session mapping file(s)."""
        try:
            if conversation_id:
                os.remove(os.path.join(sessions_dir, conversation_id))
            else:
                for name in os.listdir(sessions_dir):
                    try:
                        os.remove(os.path.join(sessions_dir, name))
                    except OSError:
                        pass
        except OSError:
            pass
