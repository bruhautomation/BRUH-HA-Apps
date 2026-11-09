"""Morph, the house walkthrough of 2026-11-07/08: tiles that drew what was not so.

  * #764: a freezer whose thermostat had stopped answering showed its last
    temperature, its target and controls under an "unavailable" badge, as if
    live. Every card that shows a figure greys it for an entity that is
    `unavailable` or `unknown` and says when it was last seen
    (`util.lastSeen`), and a sensor tile's name wraps rather than being cut.
  * #757/#766: a chart of rooms drew no lines although every room had a
    reading. Statistics exist only for a sensor with a `state_class` and never
    for a thermostat, so `history.readings` reads such a room from its
    recorded history (a thermostat's `current_temperature`), and says in
    words when there is nothing to draw.
  * #787: a soil probe that fell straight from 47% to 0 read as bone-dry
    soil. A moisture reading that lands on exactly 0 straight from 10 or more
    is a probe to check (`util.fellToZero`, `util.probeOffline`); soil that
    dried to 0 over hours still reads 0%.

The browser half is the "tiles" block of tests/manual/measure-morph.mjs.
"""
import json
import re
import subprocess
import textwrap
import unittest

from morph_env import FRONTEND

PRELUDE = f"""
globalThis.window = {{ dispatchEvent() {{}}, addEventListener() {{}} }};
globalThis.Event = class {{ constructor(t) {{ this.type = t; }} }};
const C = await import({json.dumps((FRONTEND / "cards.js").as_uri())});
const H = await import({json.dumps((FRONTEND / "history.js").as_uri())});
const U = await import({json.dumps((FRONTEND / "util.js").as_uri())});
const settle = () => new Promise((r) => setTimeout(r, 20));
const hour = 3600000;
const st = (id, state, attributes = {{}}, agoH = 1) => [id, {{ entity_id: id, state, attributes, last_changed: new Date(Date.now() - agoH * hour).toISOString() }}];
// A house whose recorder answers like Home Assistant's: statistics only for
// a sensor with a state_class, history as compressed rows ({{s, a, lu}}).
const house = (list, entities = {{}}) => {{
  const states = Object.fromEntries(list);
  return {{ states, entities, config: {{ unit_system: {{ temperature: '°F' }} }},
    callWS: async (m) => {{
      if (m.type === 'recorder/statistics_during_period') {{
        const id = m.statistic_ids[0]; const s = states[id];
        if (!s || !s.attributes.state_class) return {{}};
        const v = parseFloat(s.state); const t0 = Date.parse(m.start_time);
        return {{ [id]: Array.from({{ length: 24 }}, (_, i) => ({{ start: t0 + i * hour, mean: isFinite(v) ? v : 50 }})) }};
      }}
      if (m.type === 'history/history_during_period') {{
        const id = m.entity_ids[0]; const s = states[id]; const t0 = Date.parse(m.start_time) / 1000;
        if (!s) return {{}};
        const climate = id.startsWith('climate.');
        return {{ [id]: Array.from({{ length: 24 }}, (_, i) => climate
          ? {{ s: s.state, lu: t0 + i * 3600, a: {{ current_temperature: 70 + (i % 3), temperature: 72 }} }}
          : {{ s: String(60 + (i % 4)), lu: t0 + i * 3600 }}) }};
      }}
      return [];
    }} }};
}};
const text = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim();
const face = (type, hass, card, name) => C.TYPES[type].face({{ hass, card, st: hass.states[card.entity], name: name || 'Tile', accent: 'var(--teal)', sec: {{ title: '' }}, H: {{}} }});
"""


def run(body: str):
    script = PRELUDE + textwrap.dedent(body)
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=30, cwd=str(FRONTEND))
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


class TestSomethingThatStoppedAnsweringShowsNoLiveFigure(unittest.TestCase):
    def test_last_seen_is_said_only_for_unavailable_and_unknown(self):
        got = run("""
            const H1 = house([st('sensor.a', 'unavailable', {}, 0.5), st('sensor.b', 'unknown', {}, 30), st('sensor.c', '4')]);
            console.log(JSON.stringify(['sensor.a', 'sensor.b', 'sensor.c'].map((e) => U.lastSeen(H1.states[e]))));
        """)
        self.assertRegex(got[0], r"^last seen \S")
        self.assertRegex(got[1], r"^last seen [A-Z][a-z]{2} \d")
        self.assertEqual(got[2], "")

    def test_an_unavailable_thermostat_shows_its_last_temperature_greyed_and_no_target(self):
        got = run("""
            const h = house([st('climate.chest_freezer', 'unavailable', { current_temperature: 52, temperature: 52, min_temp: -10, max_temp: 60 }, 26)]);
            console.log(JSON.stringify(face('climate', h, { entity: 'climate.chest_freezer' }, 'Chest Freezer')));
        """)
        self.assertIn('class="big gone"', got)
        self.assertNotIn('data-act="tgt"', got)
        self.assertNotIn("target", got)
        self.assertRegex(text_of(got), r"Unavailable · last seen")

    def test_every_figure_card_says_last_seen(self):
        # A second example of each kind that shows a figure: a sensor, a
        # runtime with a unit, an energy meter and a weather entity.
        got = run("""
            const h = house([st('sensor.probe', 'unknown', { device_class: 'temperature', unit_of_measurement: '°F' }, 3),
              st('sensor.runtime', 'unavailable', { unit_of_measurement: 'min' }, 3),
              st('sensor.energy', 'unavailable', { device_class: 'energy', unit_of_measurement: 'kWh', state_class: 'total_increasing' }, 3),
              st('weather.home', 'unavailable', {}, 3)]);
            console.log(JSON.stringify([face('sensor', h, { entity: 'sensor.probe' }), face('entity', h, { entity: 'sensor.runtime', type: 'entity' }),
              face('meter', h, { entity: 'sensor.energy' }), face('weather', h, { entity: 'weather.home' })].map(text)));
        """)
        for words in got:
            self.assertIn("last seen", words)
            self.assertNotRegex(words, r"\bunavailable\b|\bunknown\b|NaN")

    def test_a_sensor_title_wraps_and_is_never_cut(self):
        got = run("""
            const h = house([st('sensor.t', '41.2', { device_class: 'temperature', unit_of_measurement: '°F' })]);
            console.log(JSON.stringify(face('sensor', h, { entity: 'sensor.t' }, 'Garage Freezer Temperature Probe')));
        """)
        self.assertIn('class="ttl"', got)
        self.assertNotIn("text-overflow:ellipsis", got)


class TestAChartOfRoomsDrawsEveryRoom(unittest.TestCase):
    def test_rooms_without_statistics_are_read_from_their_history(self):
        got = run("""
            const h = house([st('climate.downstairs', 'cool', { current_temperature: 71, temperature: 72 }),
              st('sensor.den_temperature', '68.7', { device_class: 'temperature', unit_of_measurement: '°F' }),
              st('sensor.kitchen_temperature', '72.4', { device_class: 'temperature', unit_of_measurement: '°F', state_class: 'measurement' })]);
            const card = { id: 'c', entities: ['climate.downstairs', 'sensor.den_temperature', 'sensor.kitchen_temperature'] };
            const draw = () => H.readings(h, card, {}, () => 'var(--teal)', { name: 'Spaces' });
            draw(); await settle(); draw(); await settle(); draw(); await settle();
            const html = draw();
            const lines = [...html.matchAll(/<polyline points="([^"]*)"/g)].map((m) => m[1].trim().split(/\\s+/).length);
            console.log(JSON.stringify({ lines, text: text(html) }));
        """)
        self.assertEqual(len([n for n in got["lines"] if n > 1]), 3, got)
        self.assertNotIn("NaN", got["text"])
        self.assertIn("71", got["text"])

    def test_no_history_at_all_is_said_in_words(self):
        got = run("""
            const h = house([st('sensor.shed_temperature', '57.3', { device_class: 'temperature', unit_of_measurement: '°F' })]);
            h.callWS = async () => ({});
            const card = { id: 'e', entities: ['sensor.shed_temperature'] };
            const draw = () => H.readings(h, card, {}, () => 'var(--teal)', { name: 'Shed' });
            draw(); await settle(); draw(); await settle();
            console.log(JSON.stringify(draw()));
        """)
        self.assertIn("No history for these rooms", got)
        self.assertNotIn("<polyline", got)


class TestLastAttributesOfSomethingGoneAreNotLive(unittest.TestCase):
    # #764: an unavailable entity keeps its last attributes (a thermostat's
    # current_temperature, a player's track), and they are not live.
    def test_no_live_figure_and_no_line_to_now(self):
        got = run("""
            const h = house([st('climate.a', 'unavailable', { current_temperature: 71, temperature: 72, friendly_name: 'Upstairs' }, 4),
              st('sensor.den_temperature', '68.7', { device_class: 'temperature', unit_of_measurement: '°F', state_class: 'measurement' })]);
            const ws = h.callWS;
            h.callWS = async (m) => {
              if (m.type === 'history/history_during_period' && m.entity_ids[0] === 'climate.a') {
                const t0 = Date.parse(m.start_time) / 1000;
                return { 'climate.a': Array.from({ length: 24 }, (_, i) => ({ s: i < 20 ? 'cool' : 'unavailable', lu: t0 + i * 3600, a: { current_temperature: i < 20 ? 66 + (i % 3) : 71, temperature: 72 } })) };
              }
              return ws(m);
            };
            const card = { id: 'g', entities: ['climate.a', 'sensor.den_temperature'] };
            const draw = () => H.readings(h, card, {}, () => 'var(--teal)', { name: 'Spaces' });
            draw(); await settle(); draw(); await settle(); draw(); await settle();
            const html = draw();
            const spans = [...html.matchAll(/<polyline points="([^"]*)"/g)].map((m) => m[1].trim().split(/\\s+/).map((p) => parseFloat(p.split(',')[0])));
            const labels = [...html.matchAll(/<button type="button" class="ovlab"[^>]*data-v="([^"]*)"[^>]*>(.*?)<\\/button>/g)].map((m) => [m[1], text(m[2])]);
            console.log(JSON.stringify({ ends: spans.map((xs) => Math.max(...xs)), labels }));
        """)
        labels = dict(got["labels"])
        self.assertIn("climate.a", labels, got)
        self.assertNotRegex(labels["climate.a"], r"\d", got)
        self.assertEqual(len(got["ends"]), 2, got)
        # The thermostat's line (the first) stops at the last hour it
        # answered (19 of 24, x=475 of 600) rather than running on to now.
        self.assertLess(got["ends"][0], 500, got)
        self.assertGreater(got["ends"][1], 500, got)
        self.assertRegex(labels["sensor.den_temperature"], r"68\.7", got)

    def test_an_unavailable_player_shows_no_track(self):
        got = run("""
            const h = house([st('media_player.den', 'unavailable', { media_title: 'Old Song', media_artist: 'Old Band', media_duration: 200, media_position: 50 }, 2)]);
            console.log(JSON.stringify(text(face('media', h, { entity: 'media_player.den' }, 'Den'))));
        """)
        self.assertNotIn("Old Song", got)
        self.assertNotIn("Old Band", got)
        self.assertIn("last seen", got)


class TestADeadProbeIsNotDrySoil(unittest.TestCase):
    def fell(self, pts):
        return run(f"console.log(JSON.stringify(U.fellToZero({json.dumps(pts)})));")

    def test_a_cliff_to_zero_is_a_dead_probe(self):
        m = 300000
        self.assertTrue(self.fell([[0, 47], [m, 47], [2 * m, 0], [3 * m, 0]]))
        # The fall split across a five-minute mean: still a fall.
        self.assertTrue(self.fell([[0, 47], [m, 47], [2 * m, 6], [3 * m, 0]]))

    def test_soil_that_dried_to_zero_is_zero(self):
        m = 300000
        pts = [[i * m, max(0.0, 47 - i * 0.5)] for i in range(120)]
        self.assertEqual(pts[-1][1], 0)
        self.assertFalse(self.fell(pts))
        self.assertFalse(self.fell([[0, 0], [m, 0]]))
        self.assertFalse(self.fell([[0, 47], [m, 30]]))

    def test_the_probe_is_named_with_its_battery(self):
        got = run("""
            const h = house([st('sensor.garden_soil_moisture', '0', { device_class: 'moisture', unit_of_measurement: '%' }),
              st('sensor.garden_soil_battery', '1.6', { device_class: 'voltage', unit_of_measurement: 'V' }),
              st('sensor.lawn_moisture', '0', { unit_of_measurement: '%', friendly_name: 'Lawn soil', battery_level: 7 }),
              st('binary_sensor.laundry_leak', 'off', { device_class: 'moisture' })],
              { 'sensor.garden_soil_moisture': { device_id: 'd1' }, 'sensor.garden_soil_battery': { device_id: 'd1' } });
            const cliff = [[0, 40], [300000, 0]];
            console.log(JSON.stringify([U.probeOffline(h, 'sensor.garden_soil_moisture', cliff), U.probeOffline(h, 'sensor.lawn_moisture', cliff),
              U.probeOffline(h, 'binary_sensor.laundry_leak', cliff), U.isMoisture(h.states['binary_sensor.laundry_leak'])]));
        """)
        self.assertEqual(got[0], "Sensor offline · check the probe · battery 1.6 V")
        self.assertEqual(got[1], "Sensor offline · check the probe · battery 7%")
        self.assertEqual(got[2], "")
        self.assertFalse(got[3])


def text_of(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


if __name__ == "__main__":
    unittest.main()
