"""Talking to the GardenRX add-on.

The add-on's port is on Home Assistant's internal network and not published,
so Core reaches it by the add-on's hostname, which the Supervisor's discovery
message carries. Every call carries the token the add-on wrote to /config.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT_S


class GardenRxError(Exception):
    """The add-on could not be reached, or refused — the message says which."""


class GardenRxClient:
    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, token_file: Path) -> None:
        self._session = session
        self._base = f"http://{host}:{port}"
        self._token_file = token_file
        self._token: str | None = None
        self._token_mtime: float | None = None

    def _read_token(self) -> str:
        try:
            st = self._token_file.stat()
        except OSError as err:
            raise GardenRxError(
                f"No GardenRX token at {self._token_file}. Start the GardenRX add-on; it writes one."
            ) from err
        if self._token is None or self._token_mtime != st.st_mtime:
            self._token = self._token_file.read_text(encoding="utf-8").strip()
            self._token_mtime = st.st_mtime
        return self._token

    async def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        token = await asyncio.get_running_loop().run_in_executor(None, self._read_token)
        try:
            async with self._session.request(
                method,
                self._base + path,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S),
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    body = None
                if resp.status == 401:
                    raise GardenRxError(
                        "The GardenRX add-on refused the token. Restart the add-on, then reload this integration."
                    )
                if resp.status >= 400:
                    message = body.get("error") if isinstance(body, dict) else None
                    raise GardenRxError(message or f"The GardenRX add-on answered HTTP {resp.status}.")
                return body
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GardenRxError(f"The GardenRX add-on is not answering at {self._base}: {err}") from err

    async def summary(self) -> dict:
        body = await self._request("GET", "/api/ha/summary")
        if not isinstance(body, dict):
            raise GardenRxError("The GardenRX add-on sent a summary this integration could not read.")
        return body

    async def action(self, action: str, data: dict) -> dict:
        body = await self._request("POST", "/api/ha/action", {"action": action, "data": data})
        if not isinstance(body, dict) or not body.get("ok"):
            message = body.get("error") if isinstance(body, dict) else None
            raise GardenRxError(message or "The GardenRX add-on did not say what happened.")
        return body
