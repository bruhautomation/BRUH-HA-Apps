"""A case reads the same in Morph's feed as on brAIn's Needs you (#452).

"wherever I'm looking at things (HA issues, morph feed, brain insights), it
feels like the same surface." For one house the cases are built the way
brAIn builds them — `answers.answers` for the presses, `answers.chip` for
the chip, `morph_bridge.case_row` for the row cases.json carries — and drawn
by Morph's own `caseFace` under node. Each card must wear brAIn's chip word,
brAIn's title with names in place of ids, and brAIn's labels for every press
Morph can carry back, in brAIn's order; and Morph's own words name the
assistant by the household's name.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from morph_env import FRONTEND

ROOT = Path(__file__).resolve().parent.parent
BRAIN_PANEL = ROOT / "brain" / "panel"
HAS_NODE = shutil.which("node") is not None
CASES_JS = json.dumps((FRONTEND / "cases.js").as_uri())

NAMES = {"light.hall_lamp": "Hall lamp", "sensor.loft_battery": "Loft sensor",
         "binary_sensor.shed_door": "Shed door"}

# Presses Morph can carry back to brAIn's queue (finding_requests.MORPH_ACTIONS).
MORPH_CAN = {"Fix", "Apply", "Add to To Do", "Dismiss", "Snooze", "Doesn't apply"}


def _brain():
    saved = {n: sys.modules.pop(n) for n in ("answers", "morph_bridge", "atomic_write") if n in sys.modules}
    sys.path.insert(0, str(BRAIN_PANEL))
    try:
        import answers  # noqa: PLC0415
        import morph_bridge  # noqa: PLC0415
        return answers, morph_bridge
    finally:
        sys.path.remove(str(BRAIN_PANEL))
        for n in ("answers", "morph_bridge", "atomic_write"):
            sys.modules.pop(n, None)
        sys.modules.update(saved)


CASES = [
    {"id": "f:101", "kind": "problem", "claim": "light.hall_lamp has not answered since Tuesday.",
     "detail": "It dropped off the network twice this week.", "severity": "warning",
     "source": "check:dev.unavailable", "fixable": True, "status": "open",
     "origin": {"store": "findings"}, "entity_id": "light.hall_lamp", "fix": "Reload its integration."},
    {"id": "f:102", "kind": "problem", "claim": "sensor.loft_battery is at 6%.", "detail": "",
     "severity": "serious", "source": "check:dev.battery_low", "fixable": False, "status": "open",
     "origin": {"store": "findings"}, "entity_id": "sensor.loft_battery"},
    {"id": "f:103", "kind": "problem", "claim": "Twelve devices have no room.", "detail": "",
     "severity": "info", "source": "check:reg.no_area", "fixable": True, "status": "open",
     "origin": {"store": "findings"}},
    {"id": "f:104", "kind": "problem", "claim": "binary_sensor.shed_door was left open overnight.",
     "detail": "", "severity": "serious", "source": "resident", "fixable": True, "status": "acting",
     "finding_status": "planned", "origin": {"store": "findings"},
     "plan": {"steps": ["Close it at 23:00"], "risk": "None.", "can_fix": True, "ops": [{"op": "reload"}]}},
    {"id": "h:105", "kind": "question", "claim": "Does the porch light run on a timer?", "detail": "",
     "severity": "info", "source": "curiosity", "fixable": False, "status": "open",
     "origin": {"store": "hypotheses"}},
]


def _rows():
    answers, bridge = _brain()
    out = []
    for case in CASES:
        urgent = case["id"] == "f:102"
        brain_presses = [a["label"] for a in answers.answers(case)]
        row = bridge.case_row(case, todo_text="", thread=[], ask="", urgent=urgent,
                              answers=bridge.morph_answers(answers.answers(case)),
                              finding_status=str(case.get("finding_status") or ""))
        out.append({"row": row, "chip": answers.CHIP_WORDS[answers.chip(case, urgent)],
                    "presses": brain_presses,
                    "title": re.sub(r"\b[a-z_]+\.[a-z0-9_]+\b", lambda m: NAMES.get(m.group(0), m.group(0)),
                                    case["claim"])})
    return out


def _draw(rows, who="Wren"):
    body = f"""
        import {{ caseFace }} from {CASES_JS};
        const names = {json.dumps(NAMES)};
        const rows = {json.dumps([r["row"] for r in rows])};
        console.log(JSON.stringify(rows.map((c) => caseFace(c, {{ admin: true, who: {json.dumps(who)}, name: (id) => names[id] || '' }}))));
    """
    r = subprocess.run(["node", "--input-type=module", "-e", textwrap.dedent(body)],
                       capture_output=True, text=True, timeout=30, cwd=str(FRONTEND))
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


@unittest.skipUnless(HAS_NODE, "node is needed to draw Morph's cards")
class TestTheSameCaseReadsTheSame(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = _rows()
        cls.faces = _draw(cls.rows)

    def test_the_chip_is_brains_word(self):
        for r, face in zip(self.rows, self.faces):
            m = re.search(r'<span class="casechip"[^>]*>(.*?)</span>', face, re.S)
            self.assertIsNotNone(m, f"{r['row']['id']} wears no chip")
            self.assertEqual(r["chip"], _text(m.group(1)), r["row"]["id"])

    def test_the_title_names_things_the_way_brain_does(self):
        for r, face in zip(self.rows, self.faces):
            m = re.search(r'<p class="claim">(.*?)</p>', face, re.S)
            self.assertEqual(r["title"], _text(m.group(1)), r["row"]["id"])

    def test_every_press_morph_can_carry_has_brains_label_and_order(self):
        for r, face in zip(self.rows, self.faces):
            got = [_text(b) for b in re.findall(r'<button[^>]*data-act="case"[^>]*>(.*?)</button>', face, re.S)]
            want = [p for p in r["presses"] if p in MORPH_CAN]
            self.assertEqual(want, got, r["row"]["id"])

    def test_the_body_is_brains_detail(self):
        face = self.faces[0]
        self.assertIn("It dropped off the network twice this week.", _text(face))

    def test_the_household_name_is_the_assistants(self):
        planning = dict(self.rows[0]["row"], status="planning", answers=[])
        face = _draw([{"row": planning}], who="Wren")[0]
        self.assertIn("Wren is working out a plan", _text(face))
        self.assertNotIn("brAIn", _text(face))
        self.assertIn('aria-label="Reply to Wren about this"', face)

    def test_without_a_name_it_is_brain(self):
        planning = dict(self.rows[0]["row"], status="planning", answers=[])
        face = _draw([{"row": planning}], who="")[0]
        self.assertIn("brAIn is working out a plan", _text(face))


if __name__ == "__main__":
    unittest.main()


class TestTheServiceNamesTheAssistantToo(unittest.TestCase):
    """The steps a Tell or a conversation shows are Morph's words as well."""

    def test_the_household_name_is_read_from_brains_personality(self):
        from morph_env import MorphEnv
        with MorphEnv() as env:
            self.assertEqual("brAIn", env.brain.who())
            env.brain_shared.mkdir(parents=True, exist_ok=True)
            (env.brain_shared / "personality.json").write_text(json.dumps({"name": "  Wren \n", "persona": "x"}))
            self.assertEqual("Wren", env.brain.who())
            (env.brain_shared / "personality.json").write_text("{not json")
            self.assertEqual("brAIn", env.brain.who())

    def test_a_conversations_steps_use_it(self):
        import asyncio
        import importlib
        from morph_env import MorphEnv
        from test_morph_loops import FakeBrain, fast
        with MorphEnv() as env:
            env.brain_on()
            fast(env)
            (env.brain_shared / "personality.json").write_text(json.dumps({"name": "Wren"}))
            fake = FakeBrain(env, lambda task: {"result": "It is on."})
            fake.start()
            try:
                morphd = importlib.import_module("morphd")

                async def go():
                    st = await morphd.handle("converse", {"text": "Is the porch light on?"})
                    for _ in range(300):
                        cur = env.tell.read_state(st["id"]) or {}
                        if cur.get("phase") in ("done", "failed"):
                            return cur
                        await asyncio.sleep(0.02)
                    return cur
                cur = asyncio.run(go())
            finally:
                fake.stop.set()
        steps = " ".join(s["t"] for s in cur.get("steps") or [])
        self.assertIn("Handed to Wren", steps)
        self.assertNotIn("brAIn", steps)
