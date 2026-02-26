"""File-based bridge for communicating with the BRUH Claude Terminal add-on.

The add-on and this integration share /config/.bruh_claude/ for IPC:
  - requests/   : conversation requests  (integration -> add-on)
  - responses/  : conversation responses  (add-on -> integration)
  - tasks/      : automation task requests (integration -> add-on)
  - task_results/: automation task results (add-on -> integration)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_TIMEOUT,
    REQUESTS_DIR,
    RESPONSES_DIR,
    SHARED_DIR,
    TASK_RESULTS_DIR,
    TASKS_DIR,
)

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = 0.5  # seconds


class ClaudeBridge:
    """Handles file-based communication with the Claude Terminal add-on."""

    def __init__(self, hass: HomeAssistant, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._hass = hass
        self._timeout = timeout
        self._base = hass.config.path(SHARED_DIR)

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
    def available(self) -> bool:
        """Return True if the shared directory exists (add-on is running)."""
        return os.path.isdir(self._base)

    async def async_send_conversation(
        self, text: str, conversation_id: str | None = None, timeout: int | None = None
    ) -> str:
        """Send a conversation request and wait for the response."""
        req_id = conversation_id or uuid.uuid4().hex
        timeout = timeout or self._timeout

        request = {
            "id": req_id,
            "text": text,
            "type": "conversation",
        }

        req_file = os.path.join(self.requests_dir, f"{req_id}.json")
        resp_file = os.path.join(self.responses_dir, f"{req_id}.json")

        # Write request file
        await self._hass.async_add_executor_job(
            self._write_json, req_file, request
        )

        _LOGGER.debug("Conversation request %s written", req_id)

        # Poll for response
        response_text = await self._poll_for_response(resp_file, timeout)
        return response_text

    async def async_send_task(
        self,
        prompt: str,
        notify: bool = False,
        notify_entity: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """Send an automation task and wait for the result."""
        task_id = uuid.uuid4().hex
        timeout = timeout or self._timeout

        task = {
            "id": task_id,
            "prompt": prompt,
            "notify": notify,
        }
        if notify_entity:
            task["notify_entity"] = notify_entity

        task_file = os.path.join(self.tasks_dir, f"{task_id}.json")
        result_file = os.path.join(self.task_results_dir, f"{task_id}.json")

        await self._hass.async_add_executor_job(
            self._write_json, task_file, task
        )

        _LOGGER.debug("Task %s written", task_id)

        result_text = await self._poll_for_response(result_file, timeout)
        return result_text

    async def _poll_for_response(self, path: str, timeout: int) -> str:
        """Poll for a response file, return its content or raise TimeoutError."""
        elapsed = 0.0
        while elapsed < timeout:
            result = await self._hass.async_add_executor_job(
                self._read_and_remove, path
            )
            if result is not None:
                return result
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

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
        except (json.JSONDecodeError, OSError) as exc:
            _LOGGER.warning("Failed to read response %s: %s", path, exc)
            return None
