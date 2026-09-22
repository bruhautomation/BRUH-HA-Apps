#!/usr/bin/env python3
"""Ending a finding from Settings → System → Repairs.

`findings.py` raises one issue per finding that is a decision waiting on
somebody; this is the dialog behind it. The flow writes nothing to the
findings store and could not: the store is the panel's, behind a port
Home Assistant cannot reach. A press drops a *request*, exactly as a tick
in the To-do app does, and the panel applies it through the same
`_end_finding` the Findings tab's buttons use.

So what is driven here is the whole width of that gap — the real
`requests.write_request` into the real `finding_requests.parse` — because
the two processes cannot import each other and a wire format written down
twice with only one side tested is a format that drifts.

`repairs.py` imports voluptuous, the data-entry-flow machinery and the
issue registry, none of it installed here, so it comes in behind stubs
and the table is put back exactly as it was found.
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import finding_requests  # noqa: E402  (the add-on's own reader)


class _Registry(types.ModuleType):
    def __init__(self):
        super().__init__("homeassistant.helpers.issue_registry")
        self.deleted: list[str] = []
        self.IssueSeverity = type(
            "IssueSeverity", (), {"ERROR": "error", "WARNING": "warning"})

    def async_create_issue(self, hass, domain, issue_id, **kwargs):
        pass

    def async_delete_issue(self, hass, domain, issue_id):
        self.deleted.append(issue_id)


class _FlowHandler:
    """The four results a repair flow can hand back, as plain dicts.

    Home Assistant's own base class builds the same shapes; what matters
    to these tests is which one was chosen and what was in it, so a fake
    that records them is the honest stand-in — the flow's behaviour is
    ours, the rendering is core's.
    """

    hass = None

    def async_show_menu(self, **kwargs):
        return {"type": "menu", **kwargs}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "entry", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}


def _import_repairs():
    """Import `brain_cc.repairs` behind stubs, leaving sys.modules as found."""
    saved = dict(sys.modules)
    registry = _Registry()
    try:
        vol = types.ModuleType("voluptuous")
        vol.Schema = lambda spec, **kw: spec
        vol.Optional = lambda key, **kw: f"optional:{key}"
        vol.Required = lambda key, **kw: f"required:{key}"
        sys.modules["voluptuous"] = vol

        for name in ("homeassistant", "homeassistant.helpers",
                     "homeassistant.components"):
            sys.modules[name] = types.ModuleType(name)
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = type("HomeAssistant", (), {})
        sys.modules["homeassistant.core"] = core
        flow = types.ModuleType("homeassistant.data_entry_flow")
        flow.FlowResult = dict
        flow.FlowHandler = _FlowHandler
        sys.modules["homeassistant.data_entry_flow"] = flow
        sys.modules["homeassistant"].data_entry_flow = flow
        repairs_mod = types.ModuleType("homeassistant.components.repairs")
        repairs_mod.RepairsFlow = _FlowHandler
        repairs_mod.ConfirmRepairFlow = type("ConfirmRepairFlow", (_FlowHandler,), {})
        sys.modules["homeassistant.components.repairs"] = repairs_mod
        sys.modules["homeassistant.helpers.issue_registry"] = registry
        sys.modules["homeassistant.helpers"].issue_registry = registry

        pkg = types.ModuleType("brain_cc")
        pkg.__path__ = [str(INTEGRATION_DIR)]
        sys.modules["brain_cc"] = pkg
        for stale in [m for m in sys.modules if m.startswith("brain_cc.")]:
            del sys.modules[stale]
        return importlib.import_module("brain_cc.repairs"), registry
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


repairs, REGISTRY = _import_repairs()


class _Hass:
    def __init__(self, base: str):
        self.config = types.SimpleNamespace(
            path=lambda *parts: os.path.join(base, *parts))
        self.data: dict = {}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class FlowCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hass = _Hass(self.tmp.name)
        REGISTRY.deleted.clear()
        self.dir = Path(self.tmp.name, ".brain", "finding-requests")

    def flow(self, ts: int = 1720, text: str = "Hall sensor is silent"):
        made = repairs.FindingRepairFlow(ts, text)
        made.hass = self.hass
        return made

    def written(self) -> list[dict]:
        """What the panel's own reader makes of what was dropped."""
        old = finding_requests.REQUEST_DIR
        finding_requests.REQUEST_DIR = self.dir
        try:
            return finding_requests.collect()
        finally:
            finding_requests.REQUEST_DIR = old


class TestWhichFlowAnIssueGets(unittest.TestCase):
    def test_a_finding_issue_gets_the_finding_flow(self):
        made = asyncio.run(repairs.async_create_fix_flow(
            None, "finding_1720", {"text": "Hall sensor is silent"}))
        self.assertIsInstance(made, repairs.FindingRepairFlow)

    def test_the_ts_comes_off_the_id_not_out_of_the_data(self):
        """An issue raised by an older build carries no `data` at all, and
        still has to end the right row — the ts is in the id by
        construction, which is the whole reason `issue_id_for` exists."""
        made = asyncio.run(
            repairs.async_create_fix_flow(None, "finding_1720", None))
        self.assertEqual(made._ts, 1720)

    def test_anything_that_is_not_one_of_ours_falls_through(self):
        for issue_id in ("finding_", "finding_x", "finding_1.5", "findings_1"):
            made = asyncio.run(
                repairs.async_create_fix_flow(None, issue_id, None))
            self.assertNotIsInstance(made, repairs.FindingRepairFlow, issue_id)

    def test_the_other_repairs_still_get_their_own_flows(self):
        made = asyncio.run(
            repairs.async_create_fix_flow(None, "restart_required", None))
        self.assertIsInstance(made, repairs.RestartRequiredRepairFlow)


class TestTheThreeEndings(FlowCase):
    """The tab's own verbs and nothing new.

    Anything that starts WORK — a fix run, a regeneration — belongs behind
    the panel where the thing it starts can be watched, which is why
    `requests.ACTIONS` is three words long and this menu is too.
    """

    def test_the_menu_offers_the_classic_three_when_the_row_says_nothing(self):
        """An issue from an older add-on carries no answers; the dialog
        still has to be answerable."""
        got = asyncio.run(self.flow().async_step_init())
        self.assertEqual(got["type"], "menu")
        self.assertEqual(got["menu_options"], list(repairs.DEFAULT_ACTIONS))
        # Every action a request can carry except Reply, which is a turn
        # in the conversation rather than an ending and needs a text box
        # a Repairs menu has no room for: a reply is a phone's button.
        self.assertEqual(set(repairs.FLOW_ACTIONS),
                         set(finding_requests.ACTIONS) - {"reply"})
        self.assertNotIn("reply", repairs.FLOW_ACTIONS)

    def test_the_menu_is_the_cards_own_row_when_the_row_says_which(self):
        """The add-on decides the buttons once (`answers.py`); the dialog
        shows that subset, in the flow's own order, and never a verb it
        has no step for."""
        flow = repairs.FindingRepairFlow(1720, "a", ("wrong", "todo", "bogus"))
        flow.hass = self.hass
        got = asyncio.run(flow.async_step_init())
        self.assertEqual(got["menu_options"], ["todo", "wrong"])
        for option in got["menu_options"]:
            self.assertTrue(hasattr(flow, f"async_step_{option}"), option)
        # The flow built by `async_create_fix_flow` carries what the
        # watcher stamped on the issue.
        built = asyncio.run(repairs.async_create_fix_flow(
            self.hass, "finding_1720", {"ts": 1720, "text": "a",
                                        "answers": ["ack"]}))
        built.hass = self.hass
        self.assertEqual(built.menu(), ["ack"])
        # A change brAIn made is answered with Got it, and the request
        # is the ack the panel's own button writes.
        asyncio.run(built.async_step_ack())
        self.assertEqual(self.written()[-1]["action"], "ack")

    def test_add_to_my_to_do_list_is_the_feeds_own_press(self):
        got = asyncio.run(self.flow(ts=1720).async_step_todo())
        self.assertEqual(got["type"], "entry")
        row = self.written()[-1]
        self.assertEqual((row["ts"], row["action"]), (1720, "todo"))

    def test_ive_fixed_it_writes_the_tabs_own_ending(self):
        got = asyncio.run(self.flow(ts=1720).async_step_fixed())
        self.assertEqual(got["type"], "entry")
        rows = self.written()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ts"], 1720)
        self.assertEqual(rows[0]["action"], "fixed")
        self.assertEqual(rows[0]["via"], "repairs")
        # ...and the panel maps it onto the Findings tab's own verb.
        self.assertEqual(finding_requests.verb_for(rows[0]["action"]), "done")

    def test_remind_me_tomorrow_carries_its_hours(self):
        asyncio.run(self.flow(ts=99).async_step_snooze())
        rows = self.written()
        self.assertEqual(rows[0]["action"], "snooze")
        self.assertEqual(rows[0]["hours"], float(repairs.SNOOZE_HOURS))

    def test_not_a_problem_here_asks_before_it_writes(self):
        made = self.flow()
        first = asyncio.run(made.async_step_wrong())
        self.assertEqual(first["type"], "form")
        self.assertEqual(self.written(), [])

    def test_the_reason_reaches_the_panel_verbatim(self):
        made = self.flow(ts=55)
        asyncio.run(made.async_step_wrong({"note": "that cupboard is never opened"}))
        rows = self.written()
        self.assertEqual(rows[0]["action"], "wrong")
        self.assertEqual(rows[0]["note"], "that cupboard is never opened")

    def test_the_box_is_never_required(self):
        """"Not a problem here" needs no essay, and a mandatory field
        turns a one-press dismissal into a chore and fills up with "no"."""
        made = self.flow(ts=56)
        got = asyncio.run(made.async_step_wrong({"note": ""}))
        self.assertEqual(got["type"], "entry")
        self.assertEqual(self.written()[0]["note"], "")


class TestWhatAPressLeavesBehind(FlowCase):
    def test_the_issue_is_taken_down(self):
        asyncio.run(self.flow(ts=1720).async_step_fixed())
        self.assertEqual(REGISTRY.deleted, ["finding_1720"])

    def test_the_answer_is_remembered_until_the_addon_applies_it(self):
        """The row stays on the mirror until the panel drains the request.

        Without this the next poll of the watcher would raise the issue
        again, which reads as a dialog reappearing the moment it closed.
        """
        asyncio.run(self.flow(ts=1720).async_step_fixed())
        self.assertIn(1720, self.hass.data["brain"]["_findings_answered"])

    def test_a_write_that_failed_leaves_the_issue_where_it_was(self):
        """An entry that vanished over an answer nothing recorded is the
        one ending with no way back."""
        Path(self.tmp.name, ".brain").write_text("not a directory",
                                                 encoding="utf-8")
        got = asyncio.run(self.flow(ts=1720).async_step_fixed())
        self.assertEqual(got["type"], "abort")
        self.assertEqual(got["reason"], "cannot_write")
        self.assertEqual(REGISTRY.deleted, [])
        self.assertEqual(self.hass.data, {})


class TestTheStringsExist(unittest.TestCase):
    """A translation key nothing defines renders as the key itself."""

    @classmethod
    def setUpClass(cls):
        with open(INTEGRATION_DIR / "strings.json", encoding="utf-8") as fh:
            cls.strings = json.load(fh)
        with open(INTEGRATION_DIR / "translations/en.json", encoding="utf-8") as fh:
            cls.en = json.load(fh)

    def test_every_step_the_flow_can_show_has_words(self):
        for blob in (self.strings, self.en):
            issue = blob["issues"]["finding"]
            step = issue["fix_flow"]["step"]
            self.assertIn("init", step)
            self.assertEqual(set(step["init"]["menu_options"]),
                             set(repairs.FLOW_ACTIONS))
            self.assertIn("wrong", step)
            self.assertIn("note", step["wrong"]["data"])
            self.assertIn("cannot_write", issue["fix_flow"]["abort"])

    def test_every_placeholder_the_watcher_stamps_is_used(self):
        """A placeholder with nothing to render into is a `{fix}` on
        somebody's screen."""
        blob = self.strings["issues"]["finding"]
        rendered = json.dumps(blob)
        for field in ("text", "detail", "fix", "source_title"):
            self.assertIn("{" + field + "}", rendered, field)

    def test_the_two_files_say_the_same_thing(self):
        self.assertEqual(self.strings["issues"]["finding"],
                         self.en["issues"]["finding"])


if __name__ == "__main__":
    unittest.main()
