"""Morph 1.0: the page brAIn and Morph share (docs/design/morph-vision.md).

The salience engine is pure, so it is driven under node exactly as the
panel imports it; the service halves (a card's pin, a floor's heading, a
habit's weight, a suggestion filed as one of brAIn's cases, a conversation
handed to brAIn) are driven against a scratch /config through MorphEnv.
`tests/manual/measure-morph.mjs` drives the same behaviour in a browser.
"""
import json
import shutil
import subprocess
import textwrap
import unittest

from morph_env import FRONTEND, MorphEnv

HAS_NODE = shutil.which("node") is not None
SAL = json.dumps((FRONTEND / "salience.js").as_uri())


def run_node(body: str):
    r = subprocess.run(["node", "--input-type=module", "-e", textwrap.dedent(body)],
                       capture_output=True, text=True, timeout=30, cwd=str(FRONTEND))
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


def house(alarm="disarmed", lock="locked", lock_age_h=4, warm=False):
    """A states map: a front door lock, a thermostat reading far off its
    normal when ``warm``, an alarm and one person at home."""
    return f"""
        const now = Date.now();
        const ago = (h) => new Date(now - h * 3600000).toISOString();
        const states = {{
          'alarm_control_panel.house': {{ entity_id: 'alarm_control_panel.house', state: {json.dumps(alarm)}, attributes: {{}}, last_changed: ago(1) }},
          'lock.front_door': {{ entity_id: 'lock.front_door', state: {json.dumps(lock)}, attributes: {{ friendly_name: 'Front Door' }}, last_changed: ago({lock_age_h}) }},
          'sensor.kitchen_temperature': {{ entity_id: 'sensor.kitchen_temperature', state: {json.dumps('80' if warm else '71.5')}, attributes: {{ unit_of_measurement: '°F', device_class: 'temperature' }}, last_changed: ago(0.2) }},
          'person.ben': {{ entity_id: 'person.ben', state: 'home', attributes: {{}}, last_changed: ago(5) }},
        }};
        const feed = {{ v: 1, at: now / 1000, stale_after_s: 7200, normal: {{ 'sensor.kitchen_temperature': {{ now: [71.5, 0.2, 40], next: [71.5, 0.2, 40], unit: '°F' }} }}, doors: {{}}, habits: [], rhythm: {{}} }};
        const items = [
          {{ id: 'c_lock', sec: 's_entry', entities: ['lock.front_door'] }},
          {{ id: 'c_lock_twin', sec: 's_security', entities: ['lock.front_door'] }},
          {{ id: 'c_temp', sec: 's_kitchen', entities: ['sensor.kitchen_temperature'] }},
        ];
    """


@unittest.skipUnless(HAS_NODE, "node is needed to drive the panel's modules")
class TestTheNightPageIsTheOneThingWrong(unittest.TestCase):
    """§11: armed for the night with the front door unlocked, the page holds
    exactly that door — not a warm kitchen, not the door's twin card."""

    def compute(self, **kw):
        return run_node(f"""
            const S = await import({SAL});
            {house(**kw)}
            const r = S.compute(items, {{ now, states, feed, nowMax: 3 }}, null);
            console.log(JSON.stringify({{ period: r.period, now: r.now, lock: r.items.c_lock.band, twin: r.items.c_lock_twin.twin || false, temp: r.items.c_temp.band }}));
        """)

    def test_armed_night_is_the_night_period(self):
        self.assertEqual(self.compute(alarm="armed_night")["period"], "night")

    def test_an_unlocked_door_at_night_is_the_only_card_lifted(self):
        r = self.compute(alarm="armed_night", lock="unlocked", warm=True)
        self.assertEqual(r["now"], ["c_lock"])
        self.assertTrue(r["twin"], "the door's second card is not lifted beside it")
        self.assertNotEqual(r["temp"], "now", "a warm kitchen is lifted into the night page")

    def test_by_day_a_reading_far_off_its_normal_may_lead(self):
        r = self.compute(warm=True)
        self.assertEqual(r["period"], "day")
        self.assertIn(r["temp"], ("now", "lead"))

    def test_a_locked_house_at_night_lifts_nothing(self):
        self.assertEqual(self.compute(alarm="armed_night")["now"], [])


@unittest.skipUnless(HAS_NODE, "node is needed to drive the panel's modules")
class TestThePageMovesOnlyAtAQuietMoment(unittest.TestCase):

    def test_bands_hold_on_the_way_down(self):
        r = run_node(f"""
            const S = await import({SAL});
            const B = S.BANDS;
            const mid = (B.now.enter + B.now.leave) / 2;
            console.log(JSON.stringify([S.bandFor(mid, 'now'), S.bandFor(mid, 'lead'), S.bandFor(0, 'now')]));
        """)
        self.assertEqual(r, ["now", "lead", "folded"])

    def test_hands_on_the_page_hold_a_rearrangement(self):
        r = run_node(f"""
            const S = await import({SAL});
            const now = 1e9;
            const calm = {{ lastTouch: 0, lastScroll: 0, lastArrange: 0 }};
            console.log(JSON.stringify([
              S.quietMoment(calm, now, false),
              S.quietMoment({{ ...calm, pointerDown: true }}, now, false),
              S.quietMoment({{ ...calm, open: true }}, now, false),
              S.quietMoment({{ ...calm, lastTouch: now - 500 }}, now, false),
              S.quietMoment({{ ...calm, lastArrange: now - 2000 }}, now, false),
              S.quietMoment({{ ...calm, pointerDown: true }}, now, true),
            ]));
        """)
        self.assertEqual(r, [True, False, False, False, False, True])


class TestTheDashboardKeepsWhatAPersonSaid(unittest.TestCase):

    DOC = {"title": "Home", "floors": [{"id": "f_g", "title": "Ground", "heading": False, "sections": [{
        "id": "s_k", "title": "Kitchen", "groups": [{"cards": [
            {"id": "c_a", "entity": "light.a", "pin": True},
            {"id": "c_b", "entity": "light.b", "pin": "active"},
            {"id": "c_c", "entity": "light.c", "pin": "sometimes"}]}]}]}]}

    def test_a_pin_and_a_heading_survive_a_round_trip(self):
        with MorphEnv() as env:
            d, _ = env.store.normalize(json.loads(json.dumps(self.DOC)))
            fl = d["floors"][0]
            cards = {c["id"]: c for c in fl["sections"][0]["groups"][0]["cards"]}
            self.assertIs(fl.get("heading"), False)
            self.assertIs(cards["c_a"].get("pin"), True)
            self.assertEqual(cards["c_b"].get("pin"), "active")
            self.assertNotIn("pin", cards["c_c"], "a pin word Morph does not know was kept")
            again, _ = env.store.normalize(json.loads(json.dumps(d)))
            self.assertEqual(again, d)


class TestAPredictionNobodyUsesFades(unittest.TestCase):

    def test_ignored_halves_and_used_restores(self):
        with MorphEnv() as env:
            env.settings.habit("light.master_cans", False)
            env.settings.habit("light.master_cans", False)
            self.assertAlmostEqual(env.settings.load()["habit_weights"]["light.master_cans"], 0.25)
            env.settings.habit("light.master_cans", True)
            self.assertNotIn("light.master_cans", env.settings.load().get("habit_weights") or {})


class TestASuggestionIsOneOfBrainsCases(unittest.TestCase):
    """Morph keeps no list of its own: an open suggestion is filed as a
    `morph_case` request on brAIn's queue, and brAIn's published ending is
    what starts (or refuses) the Tell."""

    def setUp(self):
        self.env = MorphEnv()
        self.env.__enter__()
        self.env.brain_shared.mkdir(parents=True, exist_ok=True)
        L = self.env.learning
        data = L._load()
        data["items"].append({"id": "g1c", "key": "k1", "title": "Move the porch light into Entry",
                              "why": "you open it from there", "status": "open", "kind": "dashboard"})
        L._save(data)

    def tearDown(self):
        self.env.__exit__(None, None, None)

    def requests(self):
        d = self.env.brain_shared / "finding-requests"
        return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.is_dir() else []

    def test_an_open_suggestion_is_filed_once(self):
        L = self.env.learning
        L.sync_brain()
        L.sync_brain()
        reqs = [r for r in self.requests() if r["kind"] == "morph_case"]
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["action"], "file")
        self.assertEqual(reqs[0]["key"], "g1c")
        self.assertTrue(reqs[0]["claim"])

    def test_an_accepted_ending_starts_one_tell(self):
        L = self.env.learning
        L.sync_brain()
        (self.env.brain_shared / "morph").mkdir(exist_ok=True)
        (self.env.brain_shared / "morph" / "cases.json").write_text(json.dumps(
            {"ended_morph": [{"key": "g1c", "how": "accepted", "note": "", "at": 100}]}))
        started = []
        L.sync_brain(lambda it: started.append(it["id"]) or "morph-t1")
        L.sync_brain(lambda it: started.append(it["id"]) or "morph-t2")
        self.assertEqual(started, ["g1c"])

    def test_a_declined_ending_is_remembered_and_never_filed_again(self):
        L = self.env.learning
        L.sync_brain()
        (self.env.brain_shared / "morph").mkdir(exist_ok=True)
        (self.env.brain_shared / "morph" / "cases.json").write_text(json.dumps(
            {"ended_morph": [{"key": "g1c", "how": "declined", "note": "the porch is fine", "at": 100}]}))
        L.sync_brain()
        item = next(x for x in L._load()["items"] if x["id"] == "g1c")
        self.assertEqual(item["status"], "declined")
        self.assertEqual(len([r for r in self.requests() if r.get("action") == "file"]), 1)


class TestAConversationIsBrainsChat(unittest.TestCase):

    def test_the_task_asks_for_a_conversation_and_resumes_its_session(self):
        with MorphEnv() as env:
            (env.brain_shared / "tasks").mkdir(parents=True)
            env.brain.submit("conv-1", "hello", kind="conversation", session_id="abcd1234-ef")
            task = json.loads((env.brain_shared / "tasks" / "conv-1.json").read_text())
            self.assertEqual(task["kind"], "conversation")
            self.assertEqual(task["session_id"], "abcd1234-ef")

    def test_a_session_id_off_the_wire_is_checked(self):
        with MorphEnv() as env:
            self.assertIsNone(env.converse.SESSION.match("../../etc"))
            self.assertIsNotNone(env.converse.SESSION.match("0f3c2a1e-77aa-4bcd-9e10-1234567890ab"))


if __name__ == "__main__":
    unittest.main()
