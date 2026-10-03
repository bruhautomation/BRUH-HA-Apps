"""An accepted automation is the entity Core REGISTERED, not a guessed slug.

Every accept used to verify — and every one-off used to disarm — a guessed
`automation.<slug of the alias>`. A slug can be taken: Remove spliced the
entry out of `automations.yaml` and left its entity-registry entry, which
Core keeps as a restored orphan holding that very id. The same sentence
accepted again was registered as `…_2`, verification passed on the orphan,
the one-off's disarm switched the orphan off, and the real one kept firing
for ever while `dev.restored` filed a finding about brAIn's own leftover.

Driven against the real panel, a real `/config` and two real aiohttp
servers standing in for Core — the REST half the accept path already used,
and a WebSocket that answers the entity registry the way Core does — so
the claim "the id comes off the registry by the config id" is proved by
the registry being asked, not by a stub of the function that asks it.

Mutations each test catches:

  verify the guess           drop the registry read -> the orphan's id is
                             what the accept reports and the intent arms
  remove leaves the entry    drop `_drop_registry_entry` -> nothing is
                             removed from the registry on Remove or undo
  remove by guessed id       key the removal on the stored entity id ->
                             the orphan (somebody else's id) is removed
  unregistered is accepted   treat "readable, not there" as "could not
                             look" -> an accept Core never registered is
                             reported as running
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

from test_proposal_accept import AcceptCase  # noqa: E402

SLUG = "automation.turn_the_hall_lamp_on_at_18_40_on_weekdays"
REGISTERED = SLUG + "_2"


class RegistryCase(AcceptCase):
    """`AcceptCase`, plus a WebSocket Core that answers the registry.

    The registry holds a restored orphan of an earlier accept under the
    plain slug, and registers every `brain_*` automation in the file
    under `_2` — exactly what Core does when the slug is taken.
    """

    registers = True

    async def asyncSetUp(self):
        await super().asyncSetUp()
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        self.removed: list[str] = []
        self.registry_reads = 0
        # Core's registry outlives the file: an entry, once registered, is
        # kept (as a restored orphan) until somebody removes it — which is
        # the whole reason Remove has to delete it.
        self.registered: dict[str, str] = {"brain_old_one": SLUG}
        test = self

        def registry() -> list[dict]:
            import yaml

            if test.registers:
                for entry in yaml.safe_load(test.automations()) or []:
                    cid = str(entry.get("id") or "")
                    if cid.startswith("brain_") and cid not in test.registered:
                        test.registered[cid] = REGISTERED
            return [{"platform": "automation", "unique_id": cid,
                     "entity_id": eid}
                    for cid, eid in test.registered.items()
                    if eid not in test.removed]

        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "auth_required"})
            async for msg in ws:
                data = msg.json()
                kind = data.get("type")
                if kind == "auth":
                    await ws.send_json({"type": "auth_ok"})
                    continue
                if kind == "config/entity_registry/list":
                    test.registry_reads += 1
                    reply = {"success": True, "result": registry()}
                elif kind == "config/entity_registry/remove":
                    test.removed.append(data.get("entity_id"))
                    reply = {"success": True, "result": None}
                else:
                    reply = {"success": False,
                             "error": {"message": f"no {kind}"}}
                await ws.send_json({"id": data["id"], "type": "result",
                                    **reply})
            return ws

        app = web.Application()
        app.router.add_get("/websocket", handler)
        self.ws_server = TestServer(app)
        await self.ws_server.start_server()
        self.addAsyncCleanup(self.ws_server.close)
        self._old_ws = self.ha_data.CORE_WS
        self.ha_data.CORE_WS = str(self.ws_server.make_url("/websocket"))
        self.addCleanup(setattr, self.ha_data, "CORE_WS", self._old_ws)
        # The orphan answers Core's state API, which is the whole trap: a
        # guessed id "exists". The real one appears once it is loaded.
        self.live.add(SLUG)
        self.live.add(REGISTERED)


class TestTheAcceptReadsTheRegistry(RegistryCase):

    async def test_the_entity_is_the_one_core_registered(self):
        row = self.offer()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 200, out)
        self.assertGreater(self.registry_reads, 0)
        self.assertEqual(out.get("entity_id"), REGISTERED)
        self.assertNotEqual(out.get("entity_id"), SLUG)

    async def test_written_but_never_registered_is_put_back(self):
        """Readable and absent is an answer — the automation did not load —
        where an unreadable registry is not one (the old guess stands)."""
        self.registers = False
        before = self.automations()
        row = self.offer()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409, out)
        self.assertIn("never registered", out.get("error", ""))
        self.assertEqual(self.automations(), before)


class TestRemovingTakesTheRegistryEntryWithIt(RegistryCase):

    async def _armed(self) -> dict:
        row = self.offer()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 200, out)
        import yaml

        written = [e for e in yaml.safe_load(self.automations())
                   if str(e.get("id") or "").startswith("brain_")][0]
        # A row armed BEFORE the registry was read back carries the guess:
        # Remove must still find the right registry entry, by config id.
        armed = self.intents.arm({"ts": 42, "title": row["title"]},
                                 {"automation_id": written["id"],
                                  "entity_id": SLUG})
        self.assertIsNotNone(armed)
        return armed

    async def test_remove_drops_the_entry_core_registered_and_only_it(self):
        armed = await self._armed()
        self.live.discard(REGISTERED)        # the reload takes it away
        resp = await self.client.post(f"/api/intent/{armed['ts']}/remove",
                                      json={})
        self.assertEqual(resp.status, 200, await resp.text())
        self.assertEqual(self.removed, [REGISTERED])
        self.assertNotIn(SLUG, self.removed)

    async def test_undoing_an_accept_drops_the_entry_too(self):
        row = self.offer()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 200, out)
        self.live.discard(REGISTERED)
        undone = await (await self.client.post(
            f"/api/undo/{out['undo']}")).json()
        self.assertTrue(undone.get("reverted"), undone)
        self.assertEqual(self.removed, [REGISTERED])


class TestTheSelfDisarmIsTheOneTemplateAllowed(unittest.TestCase):
    """`{{ this.entity_id }}` can reach exactly one entity — the automation
    running it — so it passes the protected list where every other
    template is still refused."""

    def setUp(self):
        import automation_writer
        self.writer = automation_writer

    def config(self, target: str, service: str = "automation.turn_off"):
        return {"trigger": [{"platform": "time", "at": "07:00:00"}],
                "action": [{"service": "light.turn_off",
                            "target": {"entity_id": "light.porch"}},
                           {"service": service,
                            "target": {"entity_id": target}}]}

    def test_the_disarm_passes(self):
        import intents
        self.assertIsNone(self.writer._protected_refusal(
            self.config(intents.SELF_TARGET), ["lock.*"]))
        self.assertIsNone(self.writer._protected_refusal(
            self.config("{{this.entity_id}}"), ["lock.*"]))

    def test_any_other_template_is_still_refused(self):
        for target, service in (
                ("{{ trigger.entity_id }}", "automation.turn_off"),
                ("{{ this.entity_id }}", "lock.unlock"),
                ("{{ this.entity_id }} ", "light.turn_on")):
            with self.subTest(target=target, service=service):
                self.assertIsNotNone(self.writer._protected_refusal(
                    self.config(target, service), ["lock.*"]))


if __name__ == "__main__":
    unittest.main()
