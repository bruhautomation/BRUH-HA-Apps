"""A Core that speaks the WebSocket handshake and records what it was asked.

Shared by the maintainer tests (tidy, upgrades, the SRE pass, the access
steward), because the code under test reads Core's frames through
`ha_data._ws_calls`, and a fake that handed back hand-written dicts at the
helper would prove only that the fake matches the code that mocked it —
`test_ha_ws_results`' reason, written down once so four files do not each
grow their own copy of the handshake.

`answers` maps a command type to either a `{"success", "result"}` frame
body or a callable taking the command and returning one; an unknown type
is answered `success: false`, which is how Core answers a command it does
not have (ZHA not installed, an older Core).
"""
from __future__ import annotations

from typing import Any, Callable


class FakeCore:
    def __init__(self, answers: dict[str, Any] | None = None):
        self.answers: dict[str, Any] = dict(answers or {})
        self.asked: list[dict] = []
        self.server = None
        self.client = None
        self.url = ""

    async def start(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "auth_required"})
            async for msg in ws:
                data = msg.json()
                if data.get("type") == "auth":
                    await ws.send_json({"type": "auth_ok"})
                    continue
                self.asked.append(data)
                reply = self.answers.get(data.get("type"))
                if callable(reply):
                    reply = reply(data)
                if reply is None:
                    reply = {"success": False,
                             "error": {"code": "unknown_command",
                                       "message": "Unknown command."}}
                await ws.send_json({"id": data["id"], "type": "result", **reply})
            return ws

        app = web.Application()
        app.router.add_get("/websocket", handler)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.url = str(self.server.make_url("/websocket"))
        return self

    async def close(self):
        if self.client is not None:
            await self.client.close()

    def types(self) -> list[str]:
        return [a.get("type") for a in self.asked]


def ok(result: Any) -> dict:
    return {"success": True, "result": result}


def refused(message: str = "Unauthorized") -> dict:
    return {"success": False, "error": {"code": "unauthorized",
                                        "message": message}}


Answer = Callable[[dict], dict]
