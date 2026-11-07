"""Morph, the house report of 2026-11-07: three things the page said that were not so.

  * The story said a lock was unlocked while the lock and the Doors card said
    locked, and told the owner to close a garage door that was closed. A
    sentence about a door, lock, garage or window is checked against the
    entity's state NOW, each time the story is drawn (`util.checkDoorClaims`),
    because the sentence was written before the state changed.
  * A chip showing a reading older than half an hour looked like a live one
    (`util.staleAge`): it is dimmed and says how old it is.
  * A tile for the BRUH Minecraft server showed only the word "Server"
    (`util.minecraftStatus`): it reads the Online, Players online and
    Players entities.
"""
import json
import subprocess
import textwrap
import unittest

from morph_env import FRONTEND, MorphEnv

UTIL = json.dumps((FRONTEND / "util.js").as_uri())


def run_node(body: str):
    script = textwrap.dedent(f"import * as U from {UTIL};\n" + textwrap.dedent(body))
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=30, cwd=str(FRONTEND))
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


HOUSE = """
const st = (id, state, attributes = {}) => [id, { entity_id: id, state, attributes }];
const hass = (list) => ({ states: Object.fromEntries(list), entities: {} });
"""


class TestDoorClaimsAreCheckedAgainstNow(unittest.TestCase):

    def check(self, text, list_):
        return run_node(HOUSE + f"console.log(JSON.stringify(U.checkDoorClaims({json.dumps(text)}, hass([{list_}]))));")

    def test_an_unlocked_claim_about_a_locked_lock_is_dropped(self):
        got = self.check("The back door lock is still unlocked.",
                         "st('lock.back_door', 'locked', { friendly_name: 'Back Door Lock' })")
        self.assertEqual(got, "")

    def test_an_unlocked_claim_about_an_unlocked_lock_stands(self):
        got = self.check("The back door lock is still unlocked.",
                         "st('lock.back_door', 'unlocked', { friendly_name: 'Back Door Lock' })")
        self.assertEqual(got, "The back door lock is still unlocked.")

    def test_close_the_garage_is_dropped_when_it_is_closed(self):
        got = self.check("Close the garage before bed.",
                         "st('cover.garage', 'closed', { friendly_name: 'Garage Door', device_class: 'garage' })")
        self.assertEqual(got, "")

    def test_close_the_garage_stands_when_it_is_open(self):
        got = self.check("Close the garage before bed.",
                         "st('cover.garage', 'open', { friendly_name: 'Garage Door', device_class: 'garage' })")
        self.assertEqual(got, "Close the garage before bed.")

    def test_only_the_stale_sentence_goes(self):
        got = self.check("It is warm out. The garage is open. Laundry is done.",
                         "st('cover.garage', 'closed', { friendly_name: 'Garage Door', device_class: 'garage' })")
        self.assertEqual(got, "It is warm out. Laundry is done.")

    def test_a_second_house_a_window_and_a_named_gate(self):
        # Another example: a window contact, and two doors where only one is open.
        got = self.check("The bedroom window is open and the side door is unlocked.",
                         "st('binary_sensor.bed_window', 'off', { friendly_name: 'Bedroom Window', device_class: 'window' }),"
                         "st('lock.side', 'unlocked', { friendly_name: 'Side Door Lock' })")
        self.assertEqual(got, "The bedroom window is open and the side door is unlocked.")  # one named thing is still so
        got = self.check("The bedroom window is open.",
                         "st('binary_sensor.bed_window', 'off', { friendly_name: 'Bedroom Window', device_class: 'window' }),"
                         "st('lock.side', 'unlocked', { friendly_name: 'Side Door Lock' })")
        self.assertEqual(got, "")

    def test_a_contact_that_is_open_is_not_overruled_by_a_locked_lock_of_the_same_name(self):
        got = self.check("The front door is open.",
                         "st('lock.front', 'locked', { friendly_name: 'Front Door Lock' }),"
                         "st('binary_sensor.front', 'on', { friendly_name: 'Front Door', device_class: 'door' })")
        self.assertEqual(got, "The front door is open.")

    def test_a_locked_claim_about_an_unlocked_lock_is_dropped(self):
        got = self.check("The front door is locked.",
                         "st('lock.front', 'unlocked', { friendly_name: 'Front Door Lock' })")
        self.assertEqual(got, "")

    def test_what_it_cannot_judge_is_kept(self):
        self.assertEqual(self.check("Close the garage before bed.", "st('sensor.x', '3')"), "Close the garage before bed.")
        self.assertEqual(self.check("The dishwasher is open to inspection.", "st('lock.a', 'locked')"),
                         "The dishwasher is open to inspection.")

    def test_the_story_runs_the_check_at_display_time(self):
        text = (FRONTEND / "morph-panel.js").read_text(encoding="utf-8")
        self.assertRegex(text, r"checkDoorClaims\(sit\.sentence")
        self.assertRegex(text, r"checkDoorClaims\(c\.claim")


class TestAnOldReadingSaysSo(unittest.TestCase):

    def age(self, minutes):
        return run_node(f"""
            const now = Date.parse('2026-11-07T12:00:00Z');
            const t = new Date(now - {minutes} * 60000).toISOString();
            console.log(JSON.stringify(U.staleAge({{ state: '62.6', last_updated: t, last_reported: t }}, now)));
        """)

    def test_a_fresh_reading_has_no_age(self):
        self.assertEqual(self.age(5), "")
        self.assertEqual(self.age(29), "")

    def test_an_old_reading_says_how_old(self):
        self.assertEqual(self.age(55), "55 min ago")
        self.assertEqual(self.age(180), "3 h ago")

    def test_the_last_report_counts_over_the_last_change(self):
        got = run_node("""
            const now = Date.parse('2026-11-07T12:00:00Z');
            const old = new Date(now - 300 * 60000).toISOString(); const fresh = new Date(now - 60000).toISOString();
            console.log(JSON.stringify(U.staleAge({ state: '60', last_updated: old, last_reported: fresh }, now)));
        """)
        self.assertEqual(got, "")

    def test_the_chips_and_tiles_use_it(self):
        for name in ("history.js", "cards.js"):
            self.assertIn("staleAge(", (FRONTEND / name).read_text(encoding="utf-8"), name)


class TestTheMinecraftTile(unittest.TestCase):

    def status(self, list_, eid="binary_sensor.bruh_minecraft_online"):
        return run_node(HOUSE + f"console.log(JSON.stringify(U.minecraftStatus(hass([{list_}]), {json.dumps(eid)})));")

    ONLINE = "st('binary_sensor.bruh_minecraft_online', 'on')"

    def test_online_and_empty(self):
        got = self.status(self.ONLINE + ", st('sensor.bruh_minecraft_players_online', '0', { players: [] })")
        self.assertEqual(got, "Online · nobody playing")

    def test_players_by_name(self):
        got = self.status(self.ONLINE + ", st('sensor.bruh_minecraft_players_online', '2', { players: ['Ana', 'Ben'] })")
        self.assertEqual(got, "2 playing: Ana, Ben")

    def test_one_player_and_a_tps(self):
        got = self.status(self.ONLINE + ", st('sensor.bruh_minecraft_players_online', '1', { players: ['Cy'] }), "
                          "st('sensor.bruh_minecraft_tps_1m', '19.98')")
        self.assertEqual(got, "1 playing: Cy · 20 TPS")

    def test_offline_when_it_does_not_answer(self):
        self.assertEqual(self.status("st('binary_sensor.bruh_minecraft_online', 'off'), "
                                     "st('sensor.bruh_minecraft_players_online', '0')"), "Offline")
        self.assertEqual(self.status("st('binary_sensor.bruh_minecraft_online', 'unavailable')"), "Offline")

    def test_any_entity_of_the_server_reads_the_same(self):
        got = self.status(self.ONLINE + ", st('sensor.bruh_minecraft_version', '1.21'), "
                          "st('sensor.bruh_minecraft_players_online', '0', { players: [] })",
                          eid="sensor.bruh_minecraft_version")
        self.assertEqual(got, "Online · nobody playing")

    def test_another_entity_is_not_a_server(self):
        self.assertIsNone(self.status("st('sensor.kitchen_temp', '20')", eid="sensor.kitchen_temp"))

    def test_the_entity_card_uses_it_and_new_tiles_start_as_entity_cards(self):
        self.assertIn("minecraftStatus(", (FRONTEND / "cards.js").read_text(encoding="utf-8"))
        with MorphEnv() as env:
            for eid in ("binary_sensor.bruh_minecraft_online", "sensor.bruh_minecraft_players_online",
                        "button.bruh_minecraft_save"):
                self.assertEqual(env.store.guess_type(eid), "entity", eid)
            self.assertEqual(env.store.guess_type("binary_sensor.front_door"), "list")
            self.assertEqual(env.store.guess_type("sensor.kitchen_temp"), "sensor")
