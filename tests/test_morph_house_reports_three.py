"""A third batch of house reports about Morph, each driven end to end.

* Suggestions could not be closed: their ids were a millisecond stamp plus
  one character, so several made in one pass shared an id, and an answer to
  one changed whichever came first.
* Salience crashed on a room whose area id is a name every JavaScript object
  already has ("constructor").
* A copy of Morph's code that threw while drawing one room left a blank page.
* Night dimmed the whole page to 40 % with no way to turn it off.
* A room's header marks could not be turned off.
* Two media players in one room were both named "Mini".
* "Kitchen - Bread Stretch" in the Kitchen came out as "- Bread Stretch".
* Usage tracking recorded nothing.
"""
import json
import subprocess
import textwrap
import time
import unittest
from unittest import mock

from morph_env import FRONTEND, MorphEnv


def run_node(body: str):
    script = textwrap.dedent(body)
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=str(FRONTEND))
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


DASH = {"floors": [{"id": "f", "sections": [{"id": "s", "groups": [{"cards": [{"id": "c"}]}]}]}]}


class _Env(unittest.TestCase):

    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)


class TestEverySuggestionHasItsOwnId(_Env):

    def rows(self, n):
        return [{"title": f"Idea number {w}", "change": f"Change {w}"}
                for w in ("alpha", "bravo", "charlie", "delta", "echo")[:n]]

    def test_one_pass_mints_distinct_ids_even_inside_one_millisecond(self):
        L = self.env.learning
        L.add_suggestions(self.rows(3), DASH)
        frozen = time.time()
        with mock.patch.object(L.time, "time", return_value=frozen):
            L.house_card_broken("a.js", "boom")
            L.house_card_broken("b.js", "boom")
        ids = [it["id"] for it in L.all_items()]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_stored_duplicates_are_repaired_on_load(self):
        L = self.env.learning
        items = [{"id": "g1700000000000c", "key": f"k{i}", "title": f"T{i}", "change": "x",
                  "status": "open", "created": 1.0, "filed": 5.0} for i in range(3)]
        items += [{"id": "g17000000000010", "key": f"j{i}", "title": f"J{i}", "change": "x",
                   "status": "open", "created": 1.0} for i in range(2)]
        self.env.paths.write_json(self.env.paths.SUGGESTIONS, {"items": items, "declined": {}})
        ids = [it["id"] for it in L.all_items()]
        self.assertEqual(5, len(set(ids)), ids)
        self.assertEqual(ids, [it["id"] for it in L.all_items()], "the repair is written, so ids are stable")
        # The first keeps its id (and the brAIn case filed under it); the
        # renamed ones are filed again under their new ids.
        data = L._load()
        self.assertEqual("g1700000000000c", data["items"][0]["id"])
        self.assertIn("filed", data["items"][0])
        self.assertNotIn("filed", data["items"][1])

    def test_no_and_not_now_take_it_off_the_page_and_withdraw_the_case(self):
        L = self.env.learning
        self.env.brain_shared.mkdir(parents=True, exist_ok=True)
        L.add_suggestions(self.rows(3), DASH)
        L.sync_brain()
        a, b, c = [it["id"] for it in L.listing()]
        self.assertTrue(L.decide(a, "no")["ok"])
        self.assertTrue(L.decide(b, "not_now")["ok"])
        self.assertEqual([c], [it["id"] for it in L.listing()])
        reqs = self.env.brain_shared / "finding-requests"
        before = {p.name for p in reqs.glob("*.json")}
        L.sync_brain()
        new = [json.loads((reqs / n).read_text()) for n in sorted({p.name for p in reqs.glob("*.json")} - before)]
        self.assertEqual({(a, "withdraw"), (b, "withdraw")}, {(r["key"], r["action"]) for r in new})
        # A snooze that lapses is filed again.
        data = L._load()
        for it in data["items"]:
            if it["id"] == b:
                it["snoozed_until"] = time.time() - 1
        L._save(data)
        before = {p.name for p in reqs.glob("*.json")}
        L.sync_brain()
        new = [json.loads((reqs / n).read_text()) for n in sorted({p.name for p in reqs.glob("*.json")} - before)]
        self.assertEqual([(b, "file")], [(r["key"], r["action"]) for r in new])

    def test_a_broken_card_suggestion_closes_when_the_card_loads(self):
        env = self.env
        env.paths.CARDS_DIR.mkdir(parents=True, exist_ok=True)
        (env.paths.CARDS_DIR / "pets.js").write_text("syntax error(")
        # The shape the panel sends now: the cause in the message, the
        # file's name in front of the detail (util.cardFailure).
        rows = [{"kind": "card", "card_type": "custom", "ts": time.time(),
                 "message": "Card code failed to load: Unexpected token",
                 "detail": "pets.js: SyntaxError: Unexpected token"}]
        env.paths.ERRORS.write_text("".join(json.dumps(r) + "\n" for r in rows))
        env.devloop.ingest_errors()
        self.assertEqual([], env.devloop.rows(), "the house's own card is the house's to fix")
        sug = env.learning.listing()
        self.assertEqual(["Fix the card code pets.js"], [s["title"] for s in sug])
        self.assertEqual("pets.js", sug[0]["card_file"])
        env.paths.ERRORS.write_text(json.dumps({"kind": "loaded", "ts": time.time() + 1,
                                                "message": "pets.js"}) + "\n")
        env.devloop.ingest_errors()
        self.assertEqual([], env.learning.listing())
        self.assertEqual("done", env.learning.all_items()[0]["status"])
        self.assertEqual([], env.devloop.rows(), "a clean load is not a fault")

    def test_the_panel_says_when_a_card_with_a_suggestion_loads(self):
        src = (FRONTEND / "morph-panel.js").read_text()
        self.assertIn("this.report('loaded'", src)
        ws = (FRONTEND.parent / "websocket.py").read_text()
        self.assertIn('"loaded"', ws)


if __name__ == "__main__":
    unittest.main()


PANEL_PRELUDE = """
globalThis.window = globalThis;
globalThis.HTMLElement = class {};
let Panel = null;
globalThis.customElements = { define(n, c) { if (n === 'morph-panel') Panel = c; }, get() { return null; } };
globalThis.localStorage = { getItem() { return null; }, setItem() {} };
await import(%s);
"""


def panel_node(body: str):
    return run_node(PANEL_PRELUDE % json.dumps((FRONTEND / "morph-panel.js").as_uri()) + textwrap.dedent(body))


class TestARoomNamedLikeAnObjectKey(unittest.TestCase):

    def test_area_entities_is_always_a_list(self):
        got = panel_node("""
            const hass = { entities: {
                'light.a': { entity_id: 'light.a', area_id: 'constructor' },
                'light.b': { entity_id: 'light.b', area_id: 'kitchen' },
                'light.c': { entity_id: 'light.c', device_id: 'd1' },
              }, devices: { d1: { area_id: 'toString' } } };
            const self = { hass };
            const out = Object.create(null);
            for (const area of ['constructor', 'toString', 'valueOf', '__proto__', 'hasOwnProperty', 'kitchen', 'nowhere', 42]) {
              const got = Panel.prototype.areaEntities.call(self, { area });
              out[String(area)] = Array.isArray(got) ? got : 'not a list: ' + typeof got;
            }
            console.log(JSON.stringify(out));
        """)
        self.assertEqual({"constructor": ["light.a"], "toString": ["light.c"], "valueOf": [],
                          "__proto__": [], "hasOwnProperty": [], "kitchen": ["light.b"],
                          "nowhere": [], "42": []}, got)
