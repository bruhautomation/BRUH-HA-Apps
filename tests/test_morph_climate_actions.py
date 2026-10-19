"""A thermostat's own routines are buttons on Morph's climate card.

A house asked for its "drop humidity" scripts on the climate card, and the
only way to get them was for brAIn to copy Morph's own cards.js into the
house and patch it — a copy that pauses on every Morph update. The card
reads ``options.actions`` now (cards.js, driven under node).
"""
import json
import shutil
import subprocess
import textwrap
import unittest

from morph_env import FRONTEND


def run_node(body: str):
    r = subprocess.run(["node", "--input-type=module", "-e", textwrap.dedent(body)],
                       capture_output=True, text=True, timeout=30, cwd=str(FRONTEND))
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestClimateActions(unittest.TestCase):
    def face(self, actions, script_state="off"):
        return run_node(f"""
            const C = await import({json.dumps((FRONTEND / 'cards.js').as_uri())});
            const hass = {{ config: {{ unit_system: {{ temperature: '°F' }} }}, states: {{
              'climate.down': {{ entity_id: 'climate.down', state: 'cool', attributes: {{ current_temperature: 73, temperature: 72, friendly_name: 'Down' }} }},
              'script.drop_humidity': {{ entity_id: 'script.drop_humidity', state: {json.dumps(script_state)}, attributes: {{ friendly_name: 'Drop humidity' }} }},
              'light.x': {{ entity_id: 'light.x', state: 'on', attributes: {{}} }},
            }} }};
            const card = {{ type: 'climate', entity: 'climate.down', options: {{ actions: {json.dumps(actions)} }} }};
            const ctx = {{ hass, card, st: hass.states['climate.down'], name: 'Down', accent: 'var(--sky)' }};
            console.log(JSON.stringify(C.TYPES.climate.face(ctx)));
        """)

    def test_a_script_is_a_button_that_runs_it(self):
        html = self.face(["script.drop_humidity"])
        self.assertIn('data-service="turn_on"', html)
        self.assertIn("Drop humidity", html)
        self.assertIn('aria-pressed="false"', html)

    def test_a_running_script_reads_as_pressed_with_its_own_label(self):
        html = self.face([{"entity": "script.drop_humidity", "label": "Dry it out"}], "on")
        self.assertIn("Dry it out · running", html)
        self.assertIn('aria-pressed="true"', html)

    def test_anything_but_a_routine_is_left_off(self):
        html = self.face(["light.x", "script.missing", 5])
        self.assertNotIn('data-act="svc"', html)

    def test_no_actions_is_the_card_as_before(self):
        self.assertNotIn('data-act="svc"', self.face(None))


if __name__ == "__main__":
    unittest.main()
