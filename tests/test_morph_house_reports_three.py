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


class TestNightDimAndRoomMarksAreDashboardKeys(_Env):

    def test_absent_means_the_default_and_no_new_key(self):
        dash, problems = self.env.store.normalize({"title": "Home", "floors": []})
        self.assertEqual([], problems)
        self.assertNotIn("night_dim", dash, "a house that never set it gets no new line in its file")
        self.assertNotIn("room_marks", dash)

    def test_set_keys_are_kept_as_booleans_through_a_round_trip(self):
        S = self.env.store
        dash, _ = S.normalize({"night_dim": True, "room_marks": False, "floors": []})
        self.assertIs(True, dash["night_dim"])
        self.assertIs(False, dash["room_marks"])
        again, _ = S.normalize(S.yaml.safe_load(S.dump(dash)))
        self.assertEqual(dash, again)

    def test_the_guide_brain_reads_names_both(self):
        guide = (FRONTEND.parents[2] / "defaults" / "AGENTS.md").read_text()
        self.assertRegex(guide, r"(?m)^night_dim: false\s+#")
        self.assertRegex(guide, r"(?m)^room_marks: true\s+#")

    def test_the_panel_reads_them_and_the_style_no_longer_dims_by_default(self):
        panel = (FRONTEND / "morph-panel.js").read_text()
        self.assertIn("this.dash.night_dim === true", panel)
        self.assertIn("room_marks === false", panel)
        styles = (FRONTEND / "styles.js").read_text()
        self.assertNotIn("brightness(.4)", styles)
        self.assertIn(".form-night.night-dim", styles)


class TestTheDigestSaysWhatTheUseLogIs(_Env):
    """#361: a digest of 0 events over 0 days read as "nobody used
    anything" whether nothing had been logged, the log could not be read,
    or the household really had not touched the page. The path from a tap
    to the digest is driven end to end in test_morph_usage_and_names; what
    this holds is that the three answers are told apart."""

    def digest(self):
        dash, _ = self.env.store.normalize({"floors": [{"title": "F", "sections": [
            {"id": "s", "title": "Kitchen", "groups": [{"cards": [{"id": "c", "entity": "light.k"}]}]}]}]})
        return self.env.learning.digest(dash)

    def prompt(self, d):
        return self.env.learning.build_prompt(d, "", [], {}, [])

    def test_no_log_at_all_is_not_nobody_using_it(self):
        d = self.digest()
        self.assertEqual("never", d["log"]["state"])
        self.assertIn("Morph has no record of use yet", self.prompt(d))
        self.assertIn("not evidence that nobody", self.prompt(d))

    def test_a_log_that_cannot_be_read_says_so(self):
        self.env.paths.USAGE.mkdir(parents=True)
        d = self.digest()
        self.assertEqual("unreadable", d["log"]["state"])
        self.assertIn("could not be read", self.prompt(d))

    def test_a_log_with_nothing_this_month_is_a_quiet_month(self):
        old = time.time() - 40 * 86400
        self.env.paths.USAGE.write_text(json.dumps({"ts": old, "kind": "toggle", "card": "c"}) + "\n")
        d = self.digest()
        self.assertEqual("quiet", d["log"]["state"])
        self.assertEqual(0, d["events"])
        self.assertIn("nobody used the dashboard", self.prompt(d))

    def test_a_used_dashboard_is_counted(self):
        self.env.paths.USAGE.write_text(json.dumps({"ts": time.time() - 60, "kind": "toggle", "card": "c_c",
                                                    "section": "s_s", "hour": 9}) + "\n")
        d = self.digest()
        self.assertEqual("ok", d["log"]["state"])
        self.assertEqual(1, d["events"])
        self.assertEqual(1, d["cards"][0]["uses"])


class TestNamesInARoom(_Env):
    """#364 and #357 were fixed in the generator in Morph 0.2.1 and are held
    by test_morph_usage_and_names (TestRoomPrefixes,
    TestNamesInASectionDoNotCollide). Two more cases from the same houses:
    a dashboard generated before that release still carries the dangling
    separator, and a separator other than a hyphen."""

    def test_a_card_named_by_an_old_cut_reads_right(self):
        for raw, want in (("- Bread Stretch", "Bread Stretch"), ("– Kettle", "Kettle"),
                          (": Lamp", "Lamp"), ("| Fan", "Fan"), ("Bread - Stretch", "Bread - Stretch"),
                          ("-", "-")):
            dash, _ = self.env.store.normalize({"floors": [{"title": "F", "sections": [{"title": "Kitchen", "groups": [
                {"cards": [{"entity": "script.kitchen_bread_stretch", "name": raw}]}]}]}]})
            card = dash["floors"][0]["sections"][0]["groups"][0]["cards"][0]
            self.assertEqual(want, card["name"], raw)

    def test_every_separator_goes_with_the_room(self):
        G = self.env.generator
        for name in ("Kitchen - Bread Stretch", "Kitchen – Bread Stretch", "Kitchen — Bread Stretch",
                     "Kitchen: Bread Stretch", "Kitchen | Bread Stretch", "Kitchen  -  Bread Stretch"):
            self.assertEqual("Bread Stretch", G._short(name, "Kitchen"), name)

    def test_two_minis_in_one_room_keep_what_tells_them_apart(self):
        G = self.env.generator
        cards = [{"entity": "media_player.kitchen_mini", "name": "Mini"},
                 {"entity": "media_player.kitchen_mini_2", "name": "Mini"}]
        G._distinct(cards, {"media_player.kitchen_mini": "Kitchen Mini",
                            "media_player.kitchen_mini_2": "Kitchen Mini MA"})
        self.assertEqual(["Kitchen Mini", "Kitchen Mini MA"], [c["name"] for c in cards])
