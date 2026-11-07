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


RENDER_PRELUDE = f"""
globalThis.window = {{ dispatchEvent() {{}}, addEventListener() {{}} }};
globalThis.Event = class {{ constructor(t) {{ this.type = t; }} }};
const C = await import({json.dumps((FRONTEND / "cards.js").as_uri())});
const H = await import({json.dumps((FRONTEND / "history.js").as_uri())});
const U = await import({json.dumps((FRONTEND / "util.js").as_uri())});
const settle = () => new Promise((r) => setTimeout(r, 20));
const house = (states, entities = {{}}) => ({{ states, entities, config: {{ unit_system: {{ temperature: '°F' }} }},
  callWS: async (m) => {{
    if (m.type !== 'recorder/statistics_during_period') return [];
    const id = m.statistic_ids[0]; const v = parseFloat((states[id] || {{}}).state);
    const t0 = Date.parse(m.start_time);
    return {{ [id]: Array.from({{ length: 12 }}, (_, i) => ({{ start: t0 + i * 7200000, mean: v, min: v, max: v }})) }};
  }} }});
// The pieces of rendered markup a person reads: each element with a class
// that holds a value, as its class and its text.
const document_ = (html) => {{
  const out = []; const re = /<div class="(ovenvi[^"]*)">([\s\S]*?)<svg/g; let m;
  while ((m = re.exec(html))) out.push({{ cls: m[1], text: m[2].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() }});
  return out;
}};
const text_ = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
"""


def run_render(body: str):
    script = RENDER_PRELUDE + textwrap.dedent(body)
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
    """Only a sentence that ASSERTS a current state is checked, and each kind
    of claim by its own entities: "locked"/"unlocked" by locks, "open"/
    "closed" by door, window and garage contacts and covers."""

    def check(self, text, list_):
        return run_node(HOUSE + f"console.log(JSON.stringify(U.checkDoorClaims({json.dumps(text)}, hass([{list_}]))));")

    LOCKED_FRONT = "st('lock.front', 'locked', { friendly_name: 'Front Door Lock' })"
    GARAGE_CLOSED = "st('cover.garage', 'closed', { friendly_name: 'Garage Door', device_class: 'garage' })"
    GARAGE_OPEN = "st('cover.garage', 'open', { friendly_name: 'Garage Door', device_class: 'garage' })"

    # ---- #719 and #734 as reported
    def test_an_unlocked_claim_about_a_locked_lock_is_dropped(self):
        got = self.check("The back door lock is still unlocked.",
                         "st('lock.back_door', 'locked', { friendly_name: 'Back Door Lock' })")
        self.assertEqual(got, "")

    def test_an_unlocked_claim_about_an_unlocked_lock_stands(self):
        got = self.check("The back door lock is still unlocked.",
                         "st('lock.back_door', 'unlocked', { friendly_name: 'Back Door Lock' })")
        self.assertEqual(got, "The back door lock is still unlocked.")

    def test_close_the_garage_is_dropped_when_it_is_closed(self):
        self.assertEqual(self.check("Close the garage before bed.", self.GARAGE_CLOSED), "")

    def test_close_the_garage_stands_when_it_is_open(self):
        self.assertEqual(self.check("Close the garage before bed.", self.GARAGE_OPEN), "Close the garage before bed.")

    def test_left_open_and_still_open_are_current_claims(self):
        self.assertEqual(self.check("The garage door was left open.", self.GARAGE_CLOSED), "")
        self.assertEqual(self.check("The garage is still open.", self.GARAGE_CLOSED), "")
        self.assertEqual(self.check("The garage door was left open.", self.GARAGE_OPEN), "The garage door was left open.")

    def test_only_the_stale_sentence_goes(self):
        got = self.check("It is warm out. The garage is open. Laundry is done.", self.GARAGE_CLOSED)
        self.assertEqual(got, "It is warm out. Laundry is done.")

    # ---- the reviewer's sentences: a lock noun is not a state claim
    def test_a_battery_sentence_about_a_locked_lock_stands(self):
        self.assertEqual(self.check("The front door lock battery is low.", self.LOCKED_FRONT),
                         "The front door lock battery is low.")

    def test_an_offline_sentence_about_a_locked_lock_stands(self):
        self.assertEqual(self.check("The front door lock is offline.", self.LOCKED_FRONT),
                         "The front door lock is offline.")
        self.assertEqual(self.check("The front door lock is jammed.", self.LOCKED_FRONT),
                         "The front door lock is jammed.")

    def test_a_past_unlock_that_ends_locked_stands(self):
        self.assertEqual(self.check("The front door was unlocked at 3 pm, now locked.", self.LOCKED_FRONT),
                         "The front door was unlocked at 3 pm, now locked.")
        self.assertEqual(self.check("The front door was unlocked at 3 pm and is now locked.", self.LOCKED_FRONT),
                         "The front door was unlocked at 3 pm and is now locked.")
        self.assertEqual(self.check("The front door was unlocked at 3 pm.", self.LOCKED_FRONT),
                         "The front door was unlocked at 3 pm.")
        self.assertEqual(self.check("The garage was left open at 3 pm, now closed.", self.GARAGE_CLOSED),
                         "The garage was left open at 3 pm, now closed.")

    def test_a_past_sentence_that_ends_in_a_false_reassurance_goes(self):
        got = self.check("The front door was unlocked at 3 pm, now locked.",
                         "st('lock.front', 'unlocked', { friendly_name: 'Front Door Lock' })")
        self.assertEqual(got, "")

    def test_all_doors_are_locked_goes_while_one_is_unlocked(self):
        house = "st('lock.front', 'locked', { friendly_name: 'Front Door Lock' }), st('lock.back', 'unlocked', { friendly_name: 'Back Door Lock' })"
        self.assertEqual(self.check("All doors are locked.", house), "")
        self.assertEqual(self.check("Every door is locked.", house), "")
        self.assertEqual(self.check("The house is locked up.", house), "")
        both = "st('lock.front', 'locked', { friendly_name: 'Front Door Lock' }), st('lock.back', 'locked', { friendly_name: 'Back Door Lock' })"
        self.assertEqual(self.check("All doors are locked.", both), "All doors are locked.")

    def test_everything_is_shut_goes_while_a_window_is_open(self):
        house = ("st('binary_sensor.bed_window', 'on', { friendly_name: 'Bedroom Window', device_class: 'window' }),"
                 + self.GARAGE_CLOSED)
        self.assertEqual(self.check("Everything is shut.", house), "")
        self.assertEqual(self.check("Nothing is open.", house), "")
        self.assertEqual(self.check("All windows are closed.", house), "")
        self.assertEqual(self.check("The house is secure.", house), "")
        # A claim about the garage only is not overruled by the window.
        self.assertEqual(self.check("The garage is closed.", house), "The garage is closed.")

    def test_a_locked_claim_about_an_unlocked_lock_is_dropped(self):
        got = self.check("The front door is locked.",
                         "st('lock.front', 'unlocked', { friendly_name: 'Front Door Lock' })")
        self.assertEqual(got, "")

    # ---- locks and openings are two facts
    def test_a_contact_that_is_open_is_not_overruled_by_a_locked_lock_of_the_same_name(self):
        got = self.check("The front door is open.",
                         "st('lock.front', 'locked', { friendly_name: 'Front Door Lock' }),"
                         "st('binary_sensor.front', 'on', { friendly_name: 'Front Door', device_class: 'door' })")
        self.assertEqual(got, "The front door is open.")

    def test_an_open_claim_beside_only_a_locked_lock_named_front_door_stands(self):
        # Nothing in the house says whether the door is open: it is kept.
        got = self.check("The front door is open.", "st('lock.front', 'locked', { friendly_name: 'Front Door' })")
        self.assertEqual(got, "The front door is open.")

    def test_open_is_judged_by_contacts_only_not_by_locks(self):
        got = self.check("The front door is open.",
                         "st('lock.front', 'locked', { friendly_name: 'Front Door' }),"
                         "st('binary_sensor.entry', 'on', { friendly_name: 'Front Entry', device_class: 'door' })")
        self.assertEqual(got, "The front door is open.")
        got = self.check("The main door is open.",
                         "st('lock.main', 'locked', { friendly_name: 'Main Door' }),"
                         "st('binary_sensor.entrance', 'on', { friendly_name: 'Main Entrance Door', device_class: 'door' })")
        self.assertEqual(got, "The main door is open.")

    def test_unlocked_is_judged_by_locks_only_not_by_contacts(self):
        got = self.check("The front door is still unlocked.",
                         "st('lock.front', 'locked', { friendly_name: 'Front Door Lock' }),"
                         "st('binary_sensor.front', 'on', { friendly_name: 'Front Door', device_class: 'door' })")
        self.assertEqual(got, "")

    def test_a_window_claim_is_not_judged_by_a_door_of_the_same_room(self):
        got = self.check("The front window is open.",
                         "st('binary_sensor.front', 'off', { friendly_name: 'Front Door', device_class: 'door' })")
        self.assertEqual(got, "The front window is open.")

    # ---- a sentence with two claims loses only the false one
    def test_a_true_warning_beside_a_false_one_stays(self):
        house = ("st('binary_sensor.bed_window', 'off', { friendly_name: 'Bedroom Window', device_class: 'window' }),"
                 "st('lock.side', 'unlocked', { friendly_name: 'Side Door Lock' })")
        self.assertEqual(self.check("The bedroom window is open and the side door is unlocked.", house),
                         "The side door is unlocked.")
        self.assertEqual(self.check("The bedroom window is open.", house), "")
        self.assertEqual(self.check("Water was found in the basement and the garage is open.", self.GARAGE_CLOSED),
                         "Water was found in the basement.")

    def test_a_continuation_goes_with_its_claim(self):
        self.assertEqual(self.check("The garage is open and it should be closed.", self.GARAGE_CLOSED), "")

    def test_front_and_back_is_one_subject(self):
        house = ("st('binary_sensor.front', 'on', { friendly_name: 'Front Door', device_class: 'door' }),"
                 "st('binary_sensor.back', 'off', { friendly_name: 'Back Door', device_class: 'door' })")
        self.assertEqual(self.check("The front and back doors are open.", house), "The front and back doors are open.")

    def test_a_decimal_does_not_split_a_sentence(self):
        self.assertEqual(self.check("It is 62.6° out and the garage is open.", self.GARAGE_OPEN),
                         "It is 62.6° out and the garage is open.")
        self.assertEqual(self.check("It is 62.6° out and the garage is open.", self.GARAGE_CLOSED), "It is 62.6° out.")
        self.assertEqual(self.check("It is 62.6° out. The garage is open.", self.GARAGE_CLOSED), "It is 62.6° out.")

    def test_an_ambiguous_match_is_kept(self):
        got = self.check("The garage is open.",
                         "st('cover.g1', 'closed', { friendly_name: 'Left Garage Door', device_class: 'garage' }),"
                         "st('cover.g2', 'open', { friendly_name: 'Right Garage Door', device_class: 'garage' })")
        self.assertEqual(got, "The garage is open.")

    def test_an_unavailable_lock_proves_nothing(self):
        self.assertEqual(self.check("The front door is unlocked.",
                                    "st('lock.front', 'unavailable', { friendly_name: 'Front Door Lock' })"),
                         "The front door is unlocked.")

    def test_requests_and_questions_are_not_claims(self):
        self.assertEqual(self.check("Make sure the back door is locked.",
                                    "st('lock.back', 'unlocked', { friendly_name: 'Back Door Lock' })"),
                         "Make sure the back door is locked.")
        self.assertEqual(self.check("Is the garage open?", self.GARAGE_CLOSED), "Is the garage open?")

    def test_what_it_cannot_judge_is_kept(self):
        self.assertEqual(self.check("Close the garage before bed.", "st('sensor.x', '3')"), "Close the garage before bed.")
        self.assertEqual(self.check("The dishwasher is open to inspection.", "st('lock.a', 'locked')"),
                         "The dishwasher is open to inspection.")

    def test_the_story_runs_the_check_at_display_time(self):
        text = (FRONTEND / "morph-panel.js").read_text(encoding="utf-8")
        self.assertRegex(text, r"checkDoorClaims\(sit\.sentence")
        self.assertRegex(text, r"checkDoorClaims\(c\.claim")

    def test_the_away_line_does_not_say_everything_is_locked_over_an_unlocked_lock(self):
        text = (FRONTEND / "morph-panel.js").read_text(encoding="utf-8")
        self.assertIn("unlockedClauses()", text)


class TestAnOldOutdoorReadingSaysSo(unittest.TestCase):
    """#688: the weather card said 57° while the outdoor chip said 62.6°.

    Home Assistant's frontend states carry only `last_changed` and
    `last_updated` (no `last_reported`), and a steady reading's
    `last_updated` is as old as a dead one's. So the chip is marked only when
    two things the panel has disagree: it differs from the weather entity by
    more than a degree AND its value has not changed for half an hour. It
    then says what is measured: the value has not changed since a time."""

    def age(self, value, minutes, weather="57", name="Outdoor Temperature", eid="sensor.outdoor_temperature"):
        w = "" if weather is None else (
            f"['weather.home', {{ entity_id: 'weather.home', state: 'sunny', attributes: {{ temperature: {weather} }}, "
            "last_changed: t, last_updated: t }],")
        return run_node(f"""
            const now = Date.parse('2026-11-07T12:00:00Z');
            const t = new Date(now - {minutes} * 60000).toISOString();
            const states = Object.fromEntries([{w}
              ['{eid}', {{ entity_id: '{eid}', state: '{value}', attributes: {{ friendly_name: '{name}', device_class: 'temperature', unit_of_measurement: '°F' }}, last_changed: t, last_updated: t }}]]);
            const s = U.outdoorStale({{ states }}, '{eid}', now);
            console.log(JSON.stringify(s));
        """)

    def test_an_old_chip_that_disagrees_with_the_weather_is_marked(self):
        got = self.age("62.6", 55)
        self.assertTrue(got.startswith("unchanged since "), got)

    def test_a_fresh_chip_is_not_marked(self):
        self.assertEqual(self.age("62.6", 5), "")
        self.assertEqual(self.age("62.6", 29), "")

    def test_an_old_chip_that_agrees_is_not_marked(self):
        self.assertEqual(self.age("57.4", 55), "")

    def test_without_a_weather_entity_nothing_is_marked(self):
        self.assertEqual(self.age("62.6", 300, weather=None), "")

    def test_an_indoor_reading_is_not_compared_with_the_weather(self):
        self.assertEqual(self.age("70.1", 300, name="Kitchen Temperature", eid="sensor.kitchen_temperature"), "")

    def test_there_is_no_last_reported_in_the_frontend_and_it_is_not_read(self):
        self.assertNotIn("last_reported", (FRONTEND / "util.js").read_text(encoding="utf-8"))

    def test_the_chips_and_tiles_use_it(self):
        for name in ("history.js", "cards.js"):
            self.assertIn("outdoorStale(", (FRONTEND / name).read_text(encoding="utf-8"), name)

    def readings_chips(self, outdoor_minutes):
        return run_render(f"""
            const now = Date.now();
            const old = new Date(now - {outdoor_minutes} * 60000).toISOString(); const fresh = new Date(now - 60000).toISOString();
            const T = (id, v, name, t) => [id, {{ entity_id: id, state: String(v), attributes: {{ friendly_name: name, device_class: 'temperature', unit_of_measurement: '°F' }}, last_changed: t, last_updated: t }}];
            const states = Object.fromEntries([
              ['weather.home', {{ entity_id: 'weather.home', state: 'sunny', attributes: {{ temperature: 57, temperature_unit: '°F' }}, last_changed: fresh, last_updated: fresh }}],
              T('sensor.kitchen_temperature', 70.1, 'Kitchen Temperature', fresh), T('sensor.bed_temperature', 69.2, 'Bedroom Temperature', fresh),
              T('sensor.office_temperature', 70.6, 'Office Temperature', fresh), T('sensor.den_temperature', 71.0, 'Den Temperature', fresh),
              T('sensor.outdoor_temperature', 62.6, 'Outdoor Temperature', old)]);
            const hass = house(states);
            const card = {{ type: 'readings', entities: Object.keys(states).filter((e) => e.startsWith('sensor.')) }};
            const draw = () => H.readings(hass, card, H, () => 'var(--teal)', {{ name: 'Temperature' }});
            draw(); await settle(); const html = draw();
            const t = document_(html); const chip = t.find((x) => /Outdoor/.test(x.text));
            console.log(JSON.stringify(chip || null));
        """)

    def test_the_readings_chip_is_dimmed_and_says_so(self):
        chip = self.readings_chips(55)
        self.assertIsNotNone(chip)
        self.assertIn("stale", chip["cls"])
        self.assertIn("unchanged since", chip["text"])

    def test_a_live_readings_chip_is_not(self):
        chip = self.readings_chips(2)
        self.assertIsNotNone(chip)
        self.assertNotIn("stale", chip["cls"])
        self.assertNotIn("unchanged", chip["text"])


class TestTheMinecraftTile(unittest.TestCase):
    """The real ids: the device is "BRUH Minecraft Server" and entities have names."""

    P = "bruh_minecraft_server"

    def status(self, list_, eid, entities="{}"):
        return run_node(HOUSE + f"const h = hass([{list_}]); h.entities = {entities};"
                        f"console.log(JSON.stringify(U.minecraftStatus(h, {json.dumps(eid)})));")

    ONLINE = "st('binary_sensor.bruh_minecraft_server_online', 'on')"
    EID = "binary_sensor.bruh_minecraft_server_online"

    def test_online_and_empty(self):
        got = self.status(self.ONLINE + ", st('sensor.bruh_minecraft_server_players_online', '0', { players: [] })", self.EID)
        self.assertEqual(got, "Online · nobody playing")

    def test_players_by_name_from_the_players_sensor_too(self):
        got = self.status(self.ONLINE + ", st('sensor.bruh_minecraft_server_players_online', '2', { players: ['Ana', 'Ben'] })",
                          "sensor.bruh_minecraft_server_players_online")
        self.assertEqual(got, "2 playing: Ana, Ben")

    def test_one_player_and_a_tps(self):
        got = self.status(self.ONLINE + ", st('sensor.bruh_minecraft_server_players_online', '1', { players: ['Cy'] }), "
                          "st('sensor.bruh_minecraft_server_tps_1m', '19.98')", self.EID)
        self.assertEqual(got, "1 playing: Cy · 20 TPS")

    def test_offline_when_it_does_not_answer(self):
        self.assertEqual(self.status("st('binary_sensor.bruh_minecraft_server_online', 'off'), "
                                     "st('sensor.bruh_minecraft_server_players_online', '0')", self.EID), "Offline")
        self.assertEqual(self.status("st('binary_sensor.bruh_minecraft_server_online', 'unavailable')", self.EID), "Offline")

    def test_a_renamed_device_is_found_through_the_registry(self):
        ents = json.dumps({
            "binary_sensor.mc_online": {"platform": "bruh_minecraft", "device_id": "d1"},
            "sensor.mc_players_online": {"platform": "bruh_minecraft", "device_id": "d1"},
            "sensor.mc_tps_1m": {"platform": "bruh_minecraft", "device_id": "d1"},
            "binary_sensor.other_online": {"platform": "bruh_minecraft", "device_id": "d2"},
        })
        got = self.status("st('binary_sensor.mc_online', 'on'), st('binary_sensor.other_online', 'off'), "
                          "st('sensor.mc_players_online', '2', { players: ['Di', 'Ed'] }), st('sensor.mc_tps_1m', '20')",
                          "binary_sensor.mc_online", ents)
        self.assertEqual(got, "2 playing: Di, Ed · 20 TPS")

    def test_other_entities_of_the_server_keep_their_own_value(self):
        both = self.ONLINE + ", st('sensor.bruh_minecraft_server_version', '1.21'), st('sensor.bruh_minecraft_server_last_backup', 'x')"
        for eid in ("sensor.bruh_minecraft_server_version", "sensor.bruh_minecraft_server_last_backup",
                    "button.bruh_minecraft_server_save_world"):
            self.assertIsNone(self.status(both, eid), eid)

    def test_another_entity_is_not_a_server(self):
        self.assertIsNone(self.status("st('sensor.kitchen_online', '20')", "sensor.kitchen_online"))
        self.assertIsNone(self.status("st('binary_sensor.router_online', 'on')", "binary_sensor.router_online",
                                      json.dumps({"binary_sensor.router_online": {"platform": "ping"}})))

    def test_the_entity_card_uses_it_and_buttons_stay_buttons(self):
        self.assertIn("minecraftStatus(", (FRONTEND / "cards.js").read_text(encoding="utf-8"))
        with MorphEnv() as env:
            self.assertEqual(env.store.guess_type("button.bruh_minecraft_server_save_world"), "button")
            self.assertEqual(env.store.guess_type("sensor.bruh_minecraft_server_version"), "sensor")


class TestTheMinecraftTileThroughTheCardsItGets(unittest.TestCase):
    """#686: `store.guess_type` gives `binary_sensor` a `list` card and
    `sensor` a `sensor` card, so the status is drawn by those faces, not
    only by `entity`'s. Each face is rendered here as the panel draws it."""

    SERVER = """
        const now = new Date().toISOString();
        const S = (id, state, attributes = {}) => [id, { entity_id: id, state, attributes, last_changed: now, last_updated: now }];
        const mk = (online, players, names) => Object.fromEntries([
          S('binary_sensor.bruh_minecraft_server_online', online, { device_class: 'connectivity', friendly_name: 'BRUH Minecraft Server Online' }),
          S('sensor.bruh_minecraft_server_players_online', players, { friendly_name: 'BRUH Minecraft Server Players online', players: names, unit_of_measurement: 'players' }),
          S('sensor.bruh_minecraft_server_version', '1.21.4', { friendly_name: 'BRUH Minecraft Server Version' }),
          S('sensor.bruh_minecraft_server_last_backup', '2026-11-07T10:00:00+00:00', { friendly_name: 'BRUH Minecraft Server Last backup', device_class: 'timestamp' }),
          S('button.bruh_minecraft_server_save_world', 'unknown', { friendly_name: 'BRUH Minecraft Server Save world' }),
        ]);
        const face = (states, type, eid) => {
          const hass = house(states); const card = type === 'list' ? { type, entities: [eid] } : { type, entity: eid };
          return C.TYPES[type].face({ hass, card, st: states[eid], name: 'Server', sec: { title: 'BRUH Minecraft' }, accent: 'var(--teal)' });
        };
    """

    def face(self, online, players, names, type_, eid):
        return run_render(self.SERVER + f"""
            const html = face(mk({json.dumps(online)}, {json.dumps(players)}, {json.dumps(names)}), {json.dumps(type_)}, {json.dumps(eid)});
            console.log(JSON.stringify(text_(html)));
        """)

    ON = "binary_sensor.bruh_minecraft_server_online"
    PL = "sensor.bruh_minecraft_server_players_online"

    def test_the_online_sensor_in_its_list_card(self):
        self.assertIn("Online · nobody playing", self.face("on", "0", [], "list", self.ON))
        self.assertIn("2 playing: Person 1, Lev", self.face("on", "2", ["Person 1", "Lev"], "list", self.ON))
        self.assertIn("Offline", self.face("off", "0", [], "list", self.ON))

    def test_the_online_sensor_is_not_an_alarm(self):
        html = run_render(self.SERVER + f"""
            console.log(JSON.stringify(face(mk('on', '0', []), 'list', {json.dumps(self.ON)})));
        """)
        self.assertNotIn("--rose", html)

    def test_the_players_sensor_in_its_sensor_card(self):
        self.assertIn("Online · nobody playing", self.face("on", "0", [], "sensor", self.PL))
        self.assertIn("2 playing: Person 1, Lev", self.face("on", "2", ["Person 1", "Lev"], "sensor", self.PL))
        self.assertIn("Offline", self.face("off", "0", [], "sensor", self.PL))

    def test_the_entity_card_too(self):
        self.assertIn("2 playing: Person 1, Lev", self.face("on", "2", ["Person 1", "Lev"], "entity", self.ON))

    def test_the_version_and_backup_keep_their_own_value(self):
        self.assertIn("1.21.4", self.face("on", "2", ["A"], "sensor", "sensor.bruh_minecraft_server_version"))
        self.assertNotIn("playing", self.face("on", "2", ["A"], "sensor", "sensor.bruh_minecraft_server_version"))
        self.assertNotIn("playing", self.face("on", "2", ["A"], "sensor", "sensor.bruh_minecraft_server_last_backup"))

    def test_the_save_button_stays_a_button(self):
        got = run_render(self.SERVER + """
            const states = mk('on', '0', []); const eid = 'button.bruh_minecraft_server_save_world';
            const ctx = { hass: house(states), card: { type: 'button', entity: eid }, st: states[eid], name: 'Save world', sec: { title: 'BRUH Minecraft' }, accent: 'var(--teal)' };
            const tap = C.TYPES.button.tap(ctx);
            console.log(JSON.stringify({ tap: !!tap, text: text_(C.TYPES.button.face(ctx)) }));
        """)
        self.assertTrue(got["tap"])
        self.assertNotIn("playing", got["text"])

