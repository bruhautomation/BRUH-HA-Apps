#!/usr/bin/env python3
"""Settling a finding from inside the conversation about it.

Discussing a finding is how you work out what to actually do about it, and
the answer had nowhere to go: the strip above the composer carries the four
endings every finding has, while the useful answer is the specific one the
conversation just reached. Claude offers those as buttons by calling the MCP
server's ``offer_resolutions``; the panel reads the CALL off the stream it is
already reading and draws them.

So there are four claims worth holding, and they are in four different
places:

* **the parse** — which calls are offers, and which options survive one
  (pure, in ``chat_session``);
* **the stream** — that a real turn's real tool call becomes the card and
  not a tool chip, driven against the fake CLI, because reading it off the
  stream is the whole mechanism;
* **the press** — that each verb lands the ending the button promised,
  through the same route the tab's own buttons use;
* **what it may NOT do** — no house-touching verb, and one vocabulary from
  the tool schema through to the panel's own table.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
MCP_DIR = BASE_DIR / "brain" / "ha-mcp-server"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"

sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(MCP_DIR))

import findings_store  # noqa: E402

# The panel harness, imported rather than copied: a second setUp that has to
# stay in step with the first is the drift this repo keeps writing down.
from test_todo_list import PanelCase  # noqa: E402

TOOL = "mcp__home-assistant__offer_resolutions"


def call(options):
    """One assistant event carrying an offer_resolutions call."""
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_res", "name": TOOL,
         "input": {"options": options}},
    ]}}


class TestReadingTheOffer(unittest.TestCase):
    """`resolution_offer`: pure over the wire shape."""

    @classmethod
    def setUpClass(cls):
        cls.chat = importlib.import_module("chat_session")

    def test_the_prefixed_mcp_name_is_an_offer(self):
        # It arrives namespaced by the MCP server it came from, which is not
        # the name the tool is registered under.
        got = self.chat.resolution_offer(
            TOOL, {"options": [{"label": "Replaced it", "kind": "done"}]})
        self.assertEqual(got, [{"label": "Replaced it", "verb": "done"}])

    def test_an_ordinary_tool_call_is_not_an_offer(self):
        self.assertIsNone(self.chat.resolution_offer(
            "Bash", {"options": [{"label": "x", "kind": "done"}]}))

    def test_an_option_whose_kind_is_not_an_ending_is_dropped(self):
        got = self.chat.resolution_offer(TOOL, {"options": [
            {"label": "keep", "kind": "done"},
            {"label": "drop", "kind": "escalate"},
        ]})
        self.assertEqual([o["label"] for o in got], ["keep"])

    def test_fix_is_not_offerable(self):
        """The one verb that sends Claude at the house is not on the list.

        Not an oversight and not a ranking: a resolution records a DECISION,
        so the worst a mis-tap can do is settle a finding — which the toast's
        Undo takes back whole. "Fix it" stays on the strip, pressed
        deliberately, and it does not end a finding anyway.
        """
        self.assertNotIn("fix", self.chat.RESOLUTION_VERBS)
        self.assertIsNone(self.chat.resolution_offer(
            TOOL, {"options": [{"label": "Let brAIn do it", "kind": "fix"}]}))

    def test_an_offer_with_nothing_usable_in_it_is_not_an_offer(self):
        """So the tool chip stays, and the error is visible.

        A card with no buttons is a card that cannot say what went wrong. An
        unreadable call falls through to the ordinary chip, where the MCP
        server's own refusal is on screen and Claude can correct it.
        """
        for args in ({"options": []}, {"options": "three"}, {}, None,
                     {"options": [{"label": "", "kind": "done"}]},
                     {"options": [{"label": "x"}]}):
            self.assertIsNone(self.chat.resolution_offer(TOOL, args), args)

    def test_the_count_and_the_label_are_both_capped(self):
        got = self.chat.resolution_offer(TOOL, {"options": [
            {"label": f"option {n} " + "y" * 200, "kind": "done"}
            for n in range(9)
        ]})
        self.assertEqual(len(got), self.chat.MAX_RESOLUTIONS)
        for option in got:
            self.assertLessEqual(len(option["label"]),
                                 self.chat.MAX_RESOLUTION_LABEL)


class TestWhatTheStreamCarries(unittest.TestCase):
    """`_normalise`: one call in, one card out."""

    @classmethod
    def setUpClass(cls):
        cls.chat = importlib.import_module("chat_session")

    def test_the_call_becomes_the_card_and_not_a_tool_chip(self):
        out = self.chat._normalise(
            call([{"label": "Replaced it", "kind": "done"}]))
        self.assertEqual([e["type"] for e in out], ["resolutions"])
        self.assertEqual(out[0]["options"],
                         [{"label": "Replaced it", "verb": "done"}])

    def test_a_malformed_call_stays_a_tool_chip(self):
        out = self.chat._normalise(call([{"label": "x", "kind": "nope"}]))
        self.assertEqual([e["type"] for e in out], ["tool"])

    def test_the_model_is_never_asked_which_finding_it_is(self):
        """The subject is the session's, stamped in the read loop.

        A model retyping a timestamp is a model that can name the wrong
        finding, so it is not asked for one: the parse cannot produce a
        subject at all.
        """
        out = self.chat._normalise(
            call([{"label": "Replaced it", "kind": "done"}]))
        self.assertNotIn("finding_ts", out[0])
        schema = next(t for t in importlib.import_module("ha_mcp_server").TOOLS
                      if t["name"] == "offer_resolutions")
        self.assertEqual(list(schema["inputSchema"]["properties"]), ["options"])

    def test_the_text_beside_it_still_arrives(self):
        # The card is the last thing in a turn, not the only thing: the
        # reasoning above it is what makes the buttons make sense.
        event = call([{"label": "Replaced it", "kind": "done"}])
        event["message"]["content"].insert(
            0, {"type": "text", "text": "The cell is at 5%."})
        out = self.chat._normalise(event)
        self.assertEqual([e["type"] for e in out], ["text", "resolutions"])


class TestARealTurnOffersThem(unittest.IsolatedAsyncioTestCase):
    """Against the fake CLI, because reading the stream IS the mechanism."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BRAIN_CHAT_TRANSCRIPT"] = os.path.join(self.tmp.name, "t.json")
        os.environ["BRAIN_CHAT_TRANSCRIPT_DIR"] = os.path.join(
            self.tmp.name, "chat")
        os.environ["BRAIN_SETTINGS_FILE"] = os.path.join(
            self.tmp.name, "settings.json")
        os.environ["BRAIN_CHAT_WORKDIR"] = self.tmp.name
        os.environ["BRAIN_CLAUDE_BIN"] = str(FAKE)
        os.environ["FAKE_CHAT_MODE"] = "resolutions"
        os.environ.pop("FAKE_CHAT_LOG", None)
        os.environ.pop("FAKE_CHAT_RESOLUTIONS", None)
        importlib.reload(importlib.import_module("engine"))
        self.mod = importlib.reload(importlib.import_module("chat_session"))
        self.session = self.mod.ChatSession()

    async def asyncTearDown(self):
        await self.session.stop()
        for key in ("FAKE_CHAT_MODE", "FAKE_CHAT_RESOLUTIONS"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    async def _offer(self, timeout=10.0):
        """The resolutions event from one turn."""
        queue = self.session.subscribe()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            await asyncio.sleep(0.05)
            await self.session.send("what is wrong with the garage sensor")
            while loop.time() < deadline:
                event = await asyncio.wait_for(
                    queue.get(), max(0.1, deadline - loop.time()))
                if event.get("type") == "resolutions":
                    return event
        except asyncio.TimeoutError:
            # Swallowed on purpose: running out of time IS "no offer
            # arrived", and the raise below says that in words. Letting the
            # TimeoutError out instead would report the wait rather than the
            # thing the test is about.
            pass
        finally:
            self.session.unsubscribe(queue)
        raise AssertionError("no resolutions event arrived")

    async def test_a_real_call_arrives_as_the_card_with_its_subject_on_it(self):
        await self.session.start()
        self.session.finding_ts = 1720000000
        event = await self._offer()
        self.assertEqual(event["finding_ts"], 1720000000)
        self.assertEqual([o["verb"] for o in event["options"]],
                         ["done", "todo", "wrong"])
        # And the labels are the model's own words, which is what a person
        # reads on the button and what the press records.
        self.assertEqual(event["options"][0]["label"], "Replaced the CR2032")

    async def test_the_card_is_in_the_transcript_a_reload_repaints(self):
        await self.session.start()
        self.session.finding_ts = 1720000000
        await self._offer()
        kept = [e for e in self.session.events if e["type"] == "resolutions"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["finding_ts"], 1720000000)

    async def test_a_new_conversation_is_about_nothing_yet(self):
        """`reset` drops the subject, so a later offer settles nothing.

        The Discuss route sets it AFTER the reset. A subject that survived
        one would attach this conversation's buttons to the last one's
        finding.
        """
        await self.session.start()
        self.session.finding_ts = 1720000000
        await self.session.reset()
        self.assertEqual(self.session.finding_ts, 0)
        event = await self._offer()
        self.assertEqual(event["finding_ts"], 0)


class TestPressingOne(PanelCase):
    """Each verb lands the ending its button promised."""

    def press(self, row, verb, label, extra=None):
        async def body(client):
            res = await client.post(
                f"/api/finding/{row['ts']}/{verb}",
                json={"note": label, **(extra or {})})
            self.assertEqual(res.status, 200, await res.text())
            return await res.json()

        return self.drive(body)

    def test_done_writes_the_label_into_memory(self):
        row = self.file_finding()
        payload = self.press(row, "done", "Replaced the CR2032")
        self.assertEqual(payload["findings"], [])
        self.assertTrue(any("Replaced the CR2032" in line
                            for line in self.queued_memory()),
                        self.queued_memory())
        # And the report is settled, so the next checks pass cannot re-file
        # it — the half of an ending that is not on screen.
        self.assertTrue(findings_store.is_known(row["text"]))
        self.assertTrue(payload["undo"])

    def test_wrong_writes_the_label_as_the_correction(self):
        row = self.file_finding()
        self.press(row, "wrong", "That cupboard is never opened")
        self.assertTrue(any("never opened" in line
                            for line in self.queued_memory()),
                        self.queued_memory())
        self.assertTrue(findings_store.is_known(row["text"]))

    def test_todo_carries_the_label_as_the_step_and_writes_no_memory_line(self):
        """The remedy is the instruction; the finding is still the subject.

        `fix` off the wire beats the producer's own, because "replace the
        CR2032 behind the garage sensor" is what the conversation worked out
        and "Re-pair it" is what the check could say without looking. And
        nothing goes into memory yet: putting something on a list says
        nothing true about the house.
        """
        row = self.file_finding()
        payload = self.press(row, "todo", "Replace the CR2032",
                             {"fix": "Replace the CR2032"})
        item = payload["added"]
        self.assertEqual(item["fix"], "Replace the CR2032")
        self.assertEqual(item["text"], row["text"])
        self.assertEqual(self.queued_memory(), [])
        self.assertTrue(findings_store.is_known(row["text"]))

    def test_the_item_still_takes_the_producers_fix_when_none_is_sent(self):
        # The override is an addition, not a replacement of the old
        # behaviour: every other door into this route sends no `fix`.
        row = self.file_finding()
        payload = self.press(row, "todo", "")
        self.assertEqual(payload["added"]["fix"], "Re-pair it")

    def test_a_press_on_a_finding_that_has_gone_is_a_404(self):
        # What the card's own paint prevents, asserted at the route: the
        # transcript replays the buttons after a reload, and by then it may
        # have been settled on the tab or from a phone.
        row = self.file_finding()
        self.press(row, "done", "Replaced it")

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/done",
                                    json={"note": "again"})
            return res.status

        self.assertEqual(self.drive(body), 404)


class TestOneVocabulary(unittest.TestCase):
    """The verbs are one list, and it is published in four places."""

    @classmethod
    def setUpClass(cls):
        cls.chat = importlib.import_module("chat_session")
        cls.mcp = importlib.import_module("ha_mcp_server")
        cls.app_js = (PANEL_DIR / "app.js").read_text()
        cls.engine = importlib.import_module("engine")

    def test_the_tool_the_schema_the_parser_and_the_panel_agree(self):
        schema = next(t for t in self.mcp.TOOLS
                      if t["name"] == "offer_resolutions")
        enum = schema["inputSchema"]["properties"]["options"]["items"][
            "properties"]["kind"]["enum"]
        # What the panel's own table offers, read out of the panel.
        block = re.search(r"const RESOLUTION_KINDS = \{(.*?)\n\};",
                          self.app_js, re.S).group(1)
        panel = re.findall(r"^  (\w+): \{", block, re.M)
        self.assertEqual(sorted(self.mcp.RESOLUTION_KINDS),
                         sorted(self.chat.RESOLUTION_VERBS))
        self.assertEqual(sorted(enum), sorted(self.chat.RESOLUTION_VERBS))
        self.assertEqual(sorted(panel), sorted(self.chat.RESOLUTION_VERBS))

    def test_every_verb_is_one_the_findings_api_already_takes(self):
        """No new endings: these are the ones the tab's buttons press.

        A resolution is a pre-filled ending, which is why nothing about the
        lifecycle changes — one implementation, whichever surface it was
        given on.
        """
        server = importlib.import_module("server")
        for verb in self.chat.RESOLUTION_VERBS:
            self.assertIn(verb, server.FINDING_VERBS, verb)

    def test_an_unattended_run_may_not_offer_resolutions_to_nobody(self):
        self.assertIn(f"{self.engine.MCP}offer_resolutions",
                      self.engine.ANALYST_DENIED)
        self.assertNotIn(f"{self.engine.MCP}offer_resolutions",
                         self.engine.ANALYST_TOOLS)

    def test_the_tool_refuses_a_bad_call_rather_than_offering_nothing(self):
        for bad in (None, [], "three", [{"label": "x"}],
                    [{"label": "x", "kind": "fix"}],
                    [{"label": "", "kind": "done"}],
                    [{"label": f"o{n}", "kind": "done"} for n in range(9)]):
            answer = self.mcp.offer_resolutions(bad)
            self.assertIn("error", answer, bad)
        good = self.mcp.offer_resolutions(
            [{"label": "Replaced it", "kind": "done"}])
        self.assertEqual(good["status"], "offered")

    def test_the_tool_changes_nothing(self):
        """Its whole effect is that the panel saw the call go past.

        Written down as a test because the day somebody gives it a side
        effect is the day a model settles a finding without a press.
        """
        source = (MCP_DIR / "ha_mcp_server.py").read_text()
        body = source.split("def offer_resolutions(", 1)[1].split(
            "\n# ======", 1)[0].split("\nTOOLS = ", 1)[0]
        for forbidden in ("open(", "requests.", "_api(", "call_service",
                          "urlopen", "os.remove", "subprocess"):
            self.assertNotIn(forbidden, body, forbidden)


if __name__ == "__main__":
    unittest.main()
