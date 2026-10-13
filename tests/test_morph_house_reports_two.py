"""What a second batch of house reports about Morph found, driven end to end.

* A readings card threw ``(rows || []).map is not a function``: the
  thermostat history behind the target band came back as ``{error}`` (a
  fetch that failed), and ``climateTargets`` mapped over it as a list.
* A custom card "failed to load" on a fetch that a moment later would have
  worked: one dropped request over the cloud link is not a fault in the
  card, so a fetch failure is tried once more before it is reported — and a
  card whose code THREW is not, because running it twice runs it twice.
* A section's title row carries Morph's mark, so a change to a whole room
  can be asked for without going through Edit.
* A card type that the served copy of cards.js adds (a house's own change to
  Morph) is drawn by that copy, not wrapped as a Lovelace card nobody can
  draw.
"""
import json
import shutil
import subprocess
import textwrap
import unittest

from morph_env import FRONTEND, MorphEnv

HAS_NODE = shutil.which("node") is not None


def run_node(body: str):
    script = textwrap.dedent(body)
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=30, cwd=str(FRONTEND))
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TestAReadingsCardSurvivesAFailedThermostatHistory(unittest.TestCase):

    def test_an_error_answer_draws_the_chart_without_a_band(self):
        got = run_node(f"""
            const H = await import({json.dumps((FRONTEND / 'history.js').as_uri())});
            const now = Date.now();
            const hass = {{
              states: {{
                'sensor.kitchen_temperature': {{ entity_id: 'sensor.kitchen_temperature', state: '21', attributes: {{ unit_of_measurement: '°C', device_class: 'temperature', friendly_name: 'Kitchen temperature' }} }},
                'climate.hall': {{ entity_id: 'climate.hall', state: 'heat', attributes: {{ temperature: 20 }} }},
              }},
              callWS: async (msg) => {{
                if (msg.type === 'history/history_during_period') throw new Error('history is down');
                return {{ 'sensor.kitchen_temperature': [{{ start: now - 3600000, mean: 20.5 }}, {{ start: now - 1800000, mean: 21 }}] }};
              }},
            }};
            const card = {{ type: 'readings', entities: ['sensor.kitchen_temperature'] }};
            const draw = () => H.readings(hass, card, {{}}, () => 'var(--amber)', {{ name: 'Temperatures' }});
            // The readings are fetched first, the thermostat's history only
            // once they have landed, so three passes reach the band.
            let html = '';
            for (let i = 0; i < 3; i++) {{ html = draw(); await new Promise((r) => setTimeout(r, 20)); }}
            console.log(JSON.stringify({{ chart: html.includes('data-chart'), band: html.includes('<polygon') }}));
        """)
        self.assertEqual({"chart": True, "band": False}, got)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TestACardFileIsFetchedTwiceBeforeItIsAFault(unittest.TestCase):

    def run_retry(self, errors):
        return run_node(f"""
            const U = await import({json.dumps((FRONTEND / 'util.js').as_uri())});
            const errors = {json.dumps(errors)};
            const asked = [];
            const load = (url) => {{ asked.push(url); const e = errors.shift(); return e ? Promise.reject(new TypeError(e)) : Promise.resolve('ok'); }};
            let out;
            try {{ out = await U.importWithRetry('/morph_cards/x.js?v=1', {{ load, delay: 0 }}); }}
            catch (e) {{ out = 'threw: ' + e.message; }}
            console.log(JSON.stringify({{ out, asked }}));
        """)

    def test_a_dropped_fetch_is_tried_again_on_a_fresh_url(self):
        got = self.run_retry(["Failed to fetch dynamically imported module: /morph_cards/x.js?v=1"])
        self.assertEqual("ok", got["out"])
        self.assertEqual(2, len(got["asked"]))
        self.assertNotEqual(got["asked"][0], got["asked"][1], "a failed module fetch may be cached by its URL")

    def test_safari_and_firefox_spellings_are_fetch_failures_too(self):
        for word in ("Importing a module script failed.", "error loading dynamically imported module"):
            self.assertEqual("ok", self.run_retry([word])["out"], word)

    def test_two_failures_are_reported(self):
        got = self.run_retry(["Failed to fetch dynamically imported module: a", "Failed to fetch dynamically imported module: b"])
        self.assertTrue(got["out"].startswith("threw: Failed to fetch"), got)
        self.assertEqual(2, len(got["asked"]))

    def test_code_that_threw_is_not_run_again(self):
        got = self.run_retry(["x is not defined"])
        self.assertEqual("threw: x is not defined", got["out"])
        self.assertEqual(1, len(got["asked"]))

    def test_the_panel_loads_card_files_through_it(self):
        src = (FRONTEND / "morph-panel.js").read_text()
        start = src.index("  loadModules(mods) {")
        body = src[start:src.index("\n  }\n", start)]
        self.assertIn("importWithRetry(", body)
        self.assertNotIn(" import(`", body)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TestASectionTitleCarriesTheMark(unittest.TestCase):

    def head(self, admin, edit):
        return run_node(f"""
            globalThis.HTMLElement = class {{}};
            let C; globalThis.customElements = {{ get: () => false, define: (n, c) => {{ C = c; }} }};
            await import({json.dumps((FRONTEND / 'morph-panel.js').as_uri())});
            const p = Object.create(C.prototype);
            p.s = {{ edit: {json.dumps(edit)}, secEdit: null, tell: null }};
            p.data = {{ admin: {json.dumps(admin)} }};
            Object.defineProperty(p, 'hass', {{ value: {{ states: {{}} }} }});
            p.dash = {{ floors: [] }};
            p.sectionEntities = () => [];
            p.asleepSince = () => null;
            p.presence = () => null;
            console.log(JSON.stringify(p.secHeadHtml({{ id: 's_kitchen', title: 'Kitchen', groups: [] }})));
        """)

    def test_an_admin_outside_edit_can_tell_brain_about_the_room(self):
        html = self.head(True, False)
        self.assertIn('data-act="tell-sec"', html)
        self.assertIn('data-v="s_kitchen"', html)
        self.assertIn("data-snap-skip", html)
        self.assertIn("Kitchen", html)

    def test_not_for_a_non_admin_and_not_in_edit(self):
        self.assertNotIn('tell-sec', self.head(False, False))
        self.assertNotIn('tell-sec', self.head(True, True))

    def test_the_press_is_handled_and_does_not_close_its_own_box(self):
        src = (FRONTEND / "morph-panel.js").read_text()
        self.assertIn("case 'tell-sec':", src)
        start = src.index("  outside(e) {")
        body = src[start:src.index("\n  }\n", start)]
        self.assertIn("tell-sec", body)


class TestACardTypeTheServedCopyAdds(unittest.TestCase):

    CARDS = (
        "export const TYPES = { light, light_group: lightGroup, cover, lovelace };\n"
        "TYPES.cover_group = lightGroup;\n"
        "TYPES['blind_strip'] = cover;\n"
    )

    def doc(self):
        return {"floors": [{"title": "Home", "sections": [{"title": "Room", "groups": [{"cards": [
            {"type": "cover_group", "entities": ["cover.left", "cover.right"]},
            {"type": "tile", "entity": "light.desk"},
        ]}]}]}]}

    def test_a_type_an_active_copy_defines_is_kept(self):
        with MorphEnv() as env:
            d = env.morphcode.code_dir()
            d.mkdir(parents=True, exist_ok=True)
            (d / "cards.js").write_text(self.CARDS)
            self.assertEqual({"cover_group", "blind_strip"}, set(env.morphcode.card_types()) - set(env.store.MORPH_TYPES))
            dash, problems = env.store.normalize(self.doc())
            cards = dash["floors"][0]["sections"][0]["groups"][0]["cards"]
            self.assertEqual("cover_group", cards[0]["type"])
            self.assertEqual(["cover.left", "cover.right"], cards[0]["entities"])
            self.assertEqual("lovelace", cards[1]["type"], "a real Lovelace card is still passed through")

    def test_without_a_copy_it_is_a_lovelace_card_as_before(self):
        with MorphEnv() as env:
            dash, _ = env.store.normalize(self.doc())
            cards = dash["floors"][0]["sections"][0]["groups"][0]["cards"]
            self.assertEqual("lovelace", cards[0]["type"])

    def test_a_paused_copy_is_not_served_so_its_types_do_not_count(self):
        with MorphEnv() as env:
            d = env.morphcode.code_dir()
            d.mkdir(parents=True, exist_ok=True)
            (d / "cards.js").write_text(self.CARDS)
            env.morphcode.status = lambda: [{"name": "cards.js", "status": "paused"}]
            self.assertEqual([], [t for t in env.morphcode.card_types() if t not in env.store.MORPH_TYPES])
            dash, _ = env.store.normalize(self.doc())
            self.assertEqual("lovelace", dash["floors"][0]["sections"][0]["groups"][0]["cards"][0]["type"])


if __name__ == "__main__":
    unittest.main()
