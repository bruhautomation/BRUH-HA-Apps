#!/usr/bin/env python3
"""A card ends on a verdict, a finding's "what to do" is one action, and
what a person reads carries no template code or integration slug.

Four things a house reported about how brAIn's cards read:

  * An insight card listed figures and never said whether they mattered —
    a "Normal." followed by numbers, an air-conditioning card that compared
    heat and runtime and never said whether the unit was working. The card
    contract now asks for one plain verdict first, each number read against
    this house's own normal.
  * A finding's "what to do" was the rule's generic instruction to go and
    look — or to press Ignore and say why — on a row brAIn's own look had
    already concluded about. Once a look has concluded, the card shows the
    look's sentence and not the rule's errand; and a check's fix is one
    action, never a second one about a button.
  * Template code and integration slugs reached what a person reads. The
    check rows are linted for both (`test_finding_text_plain`), and a
    model-written row has its template spans taken out at the store's door.
  * A card and an open finding about one device reached different
    conclusions. The block that hands a card the live rows tells it to take
    the row's conclusion as its own, or say why it differs.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cases  # noqa: E402
import categories  # noqa: E402
import checks  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
import resident  # noqa: E402
import triage  # noqa: E402

from test_house_checks import NOW, house  # noqa: E402

CONTRACT = categories._CARD_CONTRACT


class TestACardStatesOneVerdict(unittest.TestCase):
    def test_the_contract_asks_for_a_verdict_first(self):
        self.assertIn("opens with ONE plain verdict", CONTRACT)
        for word in ("it is fine", "it needs action", "the one thing to do"):
            self.assertIn(word, CONTRACT)
        for system in (categories.SYSTEM_PROMPT, categories.ANALYST_SYSTEM):
            self.assertIn("opens with ONE plain verdict", system)

    def test_each_number_is_read_against_this_houses_normal(self):
        self.assertIn("this house's own normal", CONTRACT)

    def test_the_schema_says_the_summary_opens_with_it(self):
        summary = categories.CARD_SCHEMA["properties"]["summary"]
        self.assertEqual(summary["type"], "string")
        self.assertIn("verdict", summary.get("description", ""))

    def test_the_contract_stays_under_its_ceiling(self):
        self.assertLess(len(CONTRACT), 9100)


class _Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE,
                     findings_store.DISPLAY_NAMES, findings_store.HOUSE_TZ)
        base = Path(self.tmp.name)
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.INBOX_DIR = base / "inbox"
        findings_store.SETTLED_FILE = base / "settled.json"
        findings_store.STATE_FILE = base / "config" / ".brain" / "state.json"
        findings_store.DISPLAY_NAMES = None
        findings_store.HOUSE_TZ = None

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE,
         findings_store.DISPLAY_NAMES, findings_store.HOUSE_TZ) = self._old
        self.tmp.cleanup()


GENERIC = "Look at what it is measuring for a change brAIn cannot see."
CONCLUDED = "Humidity falls like this every autumn when the heating comes on."


def _row(**over):
    row = {"ts": 1_700_000_000, "text": "Hall humidity is reading far "
           "outside its usual range", "detail": "41% against a usual 58%.",
           "fix": GENERIC, "fix_by": "", "severity": "info",
           "source": "check:base.unusual", "status": "open",
           "entity_id": "sensor.hall_humidity"}
    row.update(over)
    return row


class TestAConcludedLookReplacesTheRulesErrand(_Store):
    def test_a_concluded_look_hides_the_generic_fix_on_the_case(self):
        row = _row(triage={"verdict": "elevated", "reason": CONCLUDED,
                           "at": 1})
        case = cases._from_finding(row, {})
        self.assertEqual(case["fix"], "")
        self.assertEqual(case["triage"]["reason"], CONCLUDED)

    def test_a_row_nothing_concluded_about_keeps_the_rules_fix(self):
        for look in ({}, {"verdict": "untriaged", "reason": triage.UNJUDGED},
                     {"verdict": "untriaged", "reason": triage.RUN_FAILED},
                     {"verdict": "elevated", "reason": _row()["text"]}):
            case = cases._from_finding(_row(triage=look), {})
            self.assertEqual(case["fix"], GENERIC, look)

    def test_a_fix_the_look_wrote_is_shown(self):
        row = _row(fix="Run the bathroom fan longer after showers.",
                   fix_by="resident",
                   triage={"verdict": "elevated", "reason": CONCLUDED, "at": 1})
        self.assertEqual(cases._from_finding(row, {})["fix"], row["fix"])

    def test_the_findings_listing_agrees(self):
        findings_store.add_many([{k: v for k, v in _row().items()
                                  if k not in ("ts", "status")}])
        items = findings_store._load()
        items[0]["triage"] = {"verdict": "elevated", "reason": CONCLUDED,
                              "at": 1}
        items[0]["status"] = "open"
        findings_store._write(items)
        [shown] = findings_store.listing()["findings"]
        self.assertEqual(shown["fix"], "")
        # The stored row is untouched: the rule's sentence is still its own.
        self.assertEqual(findings_store._load()[0]["fix"], GENERIC)


class TestAFixIsOneAction(unittest.TestCase):
    def test_no_check_fix_tells_anybody_to_press_ignore(self):
        import ast
        offenders = []
        for path in (BASE_DIR / "brain" / "panel" / "checks").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(
                        node.value, str):
                    if "press Ignore" in node.value or (
                            "Ignore and" in node.value):
                        offenders.append(f"{path.name}: {node.value!r}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_investigation_writes_one_action_or_says_none_is_needed(self):
        system = resident.INVESTIGATE_SYSTEM
        self.assertIn("ONE action", system)
        self.assertIn("nothing is needed", system)
        self.assertIn("never tell the person to press", system.lower())


class TestTemplateCodeLeavesAtTheDoor(_Store):
    def test_house_words_takes_template_spans_out(self):
        said = house_words.templates(
            "It runs at {{ today_at('07:00') }} and again "
            "{% if is_state('sun.sun', 'above_horizon') %}by day{% endif %}.")
        self.assertNotIn("{{", said)
        self.assertNotIn("{%", said)
        self.assertIn("07:00", said)
        self.assertEqual(house_words.templates("no code here"),
                         "no code here")
        self.assertIn("a template", house_words.templates(
            "The trigger is {{ states('sensor.x') | float > 3 }}."))

    def test_plain_does_it_too(self):
        self.assertNotIn("{{", house_words.plain(
            "Set to {{ now().hour }} by the automation."))

    def test_a_model_written_row_is_stored_without_it(self):
        findings_store.add_many([{
            "text": "The porch light comes on an hour late",
            "detail": "Its trigger is {{ today_at('19:00') }} and sunset "
                      "is at 18:00.",
            "fix": "Change the trigger from {{ today_at('19:00') }} to "
                   "sunset.",
            "severity": "warning", "source": "lighting",
            "entity_id": "light.porch"}])
        [row] = findings_store._load()
        for key in ("detail", "fix"):
            self.assertNotIn("{{", row[key], key)
            self.assertIn("19:00", row[key], key)

    def test_a_checks_row_is_left_as_its_producer_wrote_it(self):
        self.assertFalse(findings_store._model_written("check:x.y"))


class TestACardTakesTheFindingsConclusion(_Store):
    def test_the_block_tells_the_card_not_to_contradict_the_row(self):
        findings_store.add_many([{
            "text": "The garage freezer has run warm for two days",
            "detail": "Averaged -9.5 °C overnight.", "severity": "warning",
            "entity_id": "sensor.garage_freezer", "source": "check:base.unusual"}])
        block = findings_store.prompt_block(("lighting",), figures=True)
        self.assertIn("take that row's conclusion as this card's own", block)
        self.assertIn("say why in one clause", block)


class TestPlainWordsForIntegrations(unittest.TestCase):
    def test_a_failed_entry_is_named_by_its_title(self):
        snap = house(config_entries=[
            {"entry_id": "a1", "domain": "homekit_controller",
             "title": "Front door lock", "state": "setup_retry",
             "source": "user", "reason": "Timeout"},
            {"entry_id": "a2", "domain": "yalexs_ble", "title": "",
             "state": "setup_error", "source": "user", "reason": ""}])
        [row] = checks.system.entry_failed(snap, NOW)
        self.assertIn("Front door lock: Timeout", row["detail"])
        self.assertNotIn("homekit_controller", row["detail"])
        self.assertNotIn("yalexs_ble", row["detail"])
        self.assertIn("yalexs ble", row["detail"])


if __name__ == "__main__":
    unittest.main()
