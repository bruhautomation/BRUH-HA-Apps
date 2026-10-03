#!/usr/bin/env python3
"""The access steward — `sec.*` checks, and what they read.

The house-check rules, held for four new rules:

  * silent on the clean fixture (`test_house_checks.house()` carries the
    new keys, healthy), and each one shown FIRING on its planted state;
  * a key the snapshot could not fill skips the check rather than reading
    as a house with nothing to say — and a row WITHOUT `protected` is "I
    could not look", never "unprotected";
  * stable text: the number that moves lives in `detail`.

The collector is driven against a real WebSocket server speaking Core's
handshake (`fake_core_ws`), because what decides "unavailable" is how a
refused command's frame is read, and a fake at the helper cannot show it.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
import ha_data  # noqa: E402
from fake_core_ws import FakeCore, ok, refused  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

security = checks.security
DAY = 86400.0


def fire(check_id: str, snap: dict) -> list[dict]:
    result = checks.run_all(snap, NOW, only=[check_id])
    return [f for f in result["findings"] if f["source"] == f"check:{check_id}"]


class TestSilentOnAHealthyHouse(unittest.TestCase):
    def test_every_sec_check_ran_and_said_nothing(self):
        result = checks.run_all(house(), NOW)
        sec = [c for c in result["ran"] if c.startswith("sec.")]
        self.assertEqual(sorted(sec), sorted(c["id"] for c in security.CHECKS))
        self.assertEqual([f for f in result["findings"]
                          if f["source"].startswith("check:sec.")], [])

    def test_a_partner_with_an_admin_account_is_not_a_finding(self):
        """An ordinary household — that is what the review is for."""
        snap = house(users=[
            {"id": "u1", "name": "Ben", "admin": True, "owner": True,
             "active": True, "system": False, "local_only": False},
            {"id": "u2", "name": "Sam", "admin": True, "owner": False,
             "active": True, "system": False, "local_only": False}])
        self.assertEqual(checks.run_all(snap, NOW)["findings"], [])


class TestALockACloudSpeakerCanOpen(unittest.TestCase):
    def _snap(self, exposure):
        snap = house(exposure=exposure)
        snap["states"]["lock.front_door"] = {
            "state": "locked", "attributes": {"friendly_name": "Front door"}}
        snap["entities"].append({"entity_id": "lock.front_door",
                                 "platform": "zwave_js"})
        return snap

    def test_alexa_on_a_lock_fires(self):
        found = fire("sec.lock_cloud_voice",
                     self._snap({"lock.front_door": {"cloud.alexa": True}}))
        self.assertEqual(len(found), 1)
        self.assertIn("Front door (Alexa)", found[0]["detail"])
        self.assertEqual(found[0]["entity_id"], "lock.front_door")
        self.assertFalse(found[0]["fixable"])

    def test_local_assist_alone_is_not_cloud(self):
        """brAIn's own voice refuses unlock; Core's Assist is local."""
        self.assertEqual(fire("sec.lock_cloud_voice", self._snap(
            {"lock.front_door": {"conversation": True,
                                 "cloud.alexa": False}})), [])

    def test_a_light_on_google_is_not_a_door(self):
        self.assertEqual(fire("sec.lock_cloud_voice", self._snap(
            {"light.kitchen": {"cloud.google_assistant": True}})), [])

    def test_the_text_does_not_move_with_the_count(self):
        one = fire("sec.lock_cloud_voice",
                   self._snap({"lock.front_door": {"cloud.alexa": True}}))
        snap = self._snap({"lock.front_door": {"cloud.alexa": True},
                           "alarm_control_panel.home": {
                               "cloud.google_assistant": True}})
        snap["states"]["alarm_control_panel.home"] = {
            "state": "armed_away", "attributes": {"friendly_name": "Alarm"}}
        two = fire("sec.lock_cloud_voice", snap)
        self.assertEqual(one[0]["text"], two[0]["text"])
        self.assertIn("2:", two[0]["detail"])

    def test_a_correction_excepts_the_lock(self):
        snap = self._snap({"lock.front_door": {"cloud.alexa": True}})
        snap["facts"] = {"lock.front_door": {"sec.lock_cloud_voice"}}
        self.assertEqual(fire("sec.lock_cloud_voice", snap), [])

    def test_an_unread_exposure_list_skips_rather_than_clears(self):
        snap = self._snap({"lock.front_door": {"cloud.alexa": True}})
        snap["available"]["exposure"] = False
        result = checks.run_all(snap, NOW, only=["sec.lock_cloud_voice"])
        self.assertIn("sec.lock_cloud_voice", result["skipped"])
        self.assertNotIn("sec.lock_cloud_voice", result["ran"])


class TestBrainsOwnPosture(unittest.TestCase):
    def test_skip_permissions_on_fires(self):
        found = fire("sec.brain_posture",
                     house(posture={"dangerously_skip_permissions": True}))
        self.assertEqual(len(found), 1)
        self.assertIn("Configuration tab", found[0]["fix"])

    def test_an_option_the_file_did_not_carry_is_not_on(self):
        self.assertEqual(fire("sec.brain_posture", house(posture={})), [])


class TestProtectionModeOff(unittest.TestCase):
    def _addons(self, rows):
        snap = house()
        snap["supervisor"] = {**snap["supervisor"], "addons": rows}
        return snap

    def test_an_explicit_false_fires(self):
        found = fire("sec.addon_unprotected", self._addons([
            {"slug": "portainer", "name": "Portainer", "installed": True,
             "protected": False},
            {"slug": "brain", "name": "brAIn", "installed": True,
             "protected": True}]))
        self.assertEqual(len(found), 1)
        self.assertIn("Portainer", found[0]["detail"])
        self.assertNotIn("brAIn", found[0]["detail"])

    def test_a_row_without_the_key_is_i_could_not_look(self):
        """A frozen corpus house's add-on rows predate the field."""
        self.assertEqual(fire("sec.addon_unprotected", self._addons([
            {"slug": "x", "name": "Something", "installed": True}])), [])


class TestBannedAfterFailedLogins(unittest.TestCase):
    def _iso(self, ago):
        import datetime as dt
        return dt.datetime.fromtimestamp(NOW - ago, tz=dt.timezone.utc).isoformat()

    def test_a_fresh_ban_fires_and_an_old_one_does_not(self):
        found = fire("sec.login_bans", house(ip_bans=[
            {"ip": "203.0.113.7", "banned_at": self._iso(2 * DAY)},
            {"ip": "198.51.100.1", "banned_at": self._iso(40 * DAY)}]))
        self.assertEqual(len(found), 1)
        self.assertIn("203.0.113.7", found[0]["detail"])
        self.assertNotIn("198.51.100.1", found[0]["detail"])

    def test_a_ban_with_no_date_is_history(self):
        self.assertEqual(fire("sec.login_bans", house(ip_bans=[
            {"ip": "203.0.113.7", "banned_at": ""}])), [])

    def test_the_file_reader_tells_absent_from_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ip_bans.yaml")
            self.assertEqual(security.read_ip_bans(path), [])
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("203.0.113.7:\n  banned_at: '2026-09-30T10:00:00+00:00'\n")
            rows = security.read_ip_bans(path)
            self.assertEqual(rows[0]["ip"], "203.0.113.7")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("- just\n- a list\n")
            self.assertIsNone(security.read_ip_bans(path))


class TestTheCollector(unittest.IsolatedAsyncioTestCase):
    """What a refused `config/auth/list` does to the users key, over a
    real socket."""

    async def _collect(self, answers, options=None):
        core = await FakeCore(answers).start()
        self.addAsyncCleanup(core.close)
        old = ha_data.CORE_WS
        ha_data.CORE_WS = core.url
        self.addCleanup(setattr, ha_data, "CORE_WS", old)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        opts = os.path.join(tmp.name, "options.json")
        if options is not None:
            with open(opts, "w", encoding="utf-8") as fh:
                json.dump(options, fh)
        old_o, old_b = security.OPTIONS_FILE, security.IP_BANS_FILE
        security.OPTIONS_FILE = opts
        security.IP_BANS_FILE = os.path.join(tmp.name, "ip_bans.yaml")
        self.addCleanup(setattr, security, "OPTIONS_FILE", old_o)
        self.addCleanup(setattr, security, "IP_BANS_FILE", old_b)
        import aiohttp
        snap = {"available": {}, "errors": {}}

        def mark(key, okay, err=""):
            snap["available"][key] = okay
            if err:
                snap["errors"][key] = err

        async with aiohttp.ClientSession() as session:
            await security.collect(session, snap, mark)
        return snap

    async def test_everything_answered(self):
        snap = await self._collect({
            "config/auth/list": ok([
                {"id": "u1", "name": "Ben", "is_owner": True, "is_active": True,
                 "group_ids": ["system-admin"], "credentials": [
                     {"type": "homeassistant", "secret": "never-copied"}]}]),
            "homeassistant/expose_entity/list": ok(
                {"exposed_entities": {"lock.front": {"cloud.alexa": True}}}),
        }, options={"dangerously_skip_permissions": True, "model": ""})
        self.assertTrue(all(snap["available"][k] for k in security.SNAPSHOT_KEYS))
        self.assertTrue(snap["users"][0]["admin"])
        # Nothing about a credential is carried into the snapshot.
        self.assertNotIn("never-copied", json.dumps(snap))
        self.assertEqual(snap["posture"], {"dangerously_skip_permissions": True})
        self.assertEqual(snap["ip_bans"], [])

    async def test_a_refusal_is_unavailable_not_empty(self):
        snap = await self._collect({
            "config/auth/list": refused(),
            "homeassistant/expose_entity/list": refused("nope")})
        self.assertFalse(snap["available"]["users"])
        self.assertFalse(snap["available"]["exposure"])
        # No options file: posture could not be read.
        self.assertFalse(snap["available"]["posture"])
        self.assertTrue(snap["errors"]["users"])


class TestTheReviewDigest(unittest.TestCase):
    def test_unread_is_said_rather_than_zeroed(self):
        snap = house()
        snap["available"]["users"] = False
        digest = security.review_digest(snap, NOW)
        self.assertEqual(digest["users"], "unread")
        self.assertIsInstance(digest["exposed"], dict)

    def test_it_names_what_cannot_be_seen(self):
        digest = security.review_digest(house(), NOW)
        self.assertIn("long-lived tokens", digest["token_visibility"])
        self.assertEqual(digest["users"]["admins"], ["Ben"])


if __name__ == "__main__":
    unittest.main()
