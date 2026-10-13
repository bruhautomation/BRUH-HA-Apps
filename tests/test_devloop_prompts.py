#!/usr/bin/env python3
"""What the Claude streams of the development loop are asked, and how
their answers are read.

The claims, each driven through the real builders and readers:

  * every Claude stream asks for `done_when` and an `impact` estimate, and
    the run is handed a JSON schema that requires both, so the CLI refuses
    a reply without them rather than the house filing it;
  * a reply on a CLI without the schema is still read from its text, and a
    row missing `done_when` is filed without that line rather than lost;
  * a reply that cannot be read is LOGGED and COUNTED in the stream's
    status, never read as "the run found nothing";
  * what the developer closed as declined, not brAIn's or a duplicate
    comes home with the first line of the closing comment, and the next
    gaps, ideas and design run is shown it, bounded;
  * the reasons people typed when they marked a finding Wrong reach the
    gaps prompt, which has always said it reads them;
  * the design topic is cut once, in whole lines.

GitHub is `test_devloop`'s loopback fake, so the closing comment is read
over a real request.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import devloop  # noqa: E402
import devloop.github  # noqa: E402
import devloop.streams  # noqa: E402
import devloop.upstream  # noqa: E402

from test_devloop import TOKEN, FakeGitHub, diagnostics  # noqa: E402

github = devloop.github
streams = devloop.streams
upstream = devloop.upstream

CLAUDE = ("gaps", "ideas", "design", "look")


def _row(**extra) -> dict:
    row = {"title": "dev.frozen and fixed tariffs",
           "what": "dev.frozen files a tariff sensor as stuck",
           "why": "It has read 0.28 for three weeks."}
    row.update(extra)
    return row


def _valid(schema: dict, reply: dict) -> bool:
    """The parts of JSON Schema `reply_schema` uses, checked by hand: the
    CLI does the real validation, and a dependency for this would be a
    dependency for one test."""
    if not isinstance(reply.get("rows"), list):
        return False
    rows_schema = schema["properties"]["rows"]
    if len(reply["rows"]) > rows_schema["maxItems"]:
        return False
    item = rows_schema["items"]
    kinds = {"string": str, "boolean": bool}
    for r in reply["rows"]:
        if any(k not in r for k in item["required"]):
            return False
        for k, spec in item["properties"].items():
            if k in r and not isinstance(r[k], kinds[spec["type"]]):
                return False
    return True


class TestEveryStreamAsksForATestAndAnImpact(unittest.TestCase):
    def test_every_system_prompt_asks_for_both(self):
        for stream in CLAUDE:
            system = streams.analyst_system(stream)
            self.assertIn('"done_when"', system, stream)
            self.assertIn('"impact"', system, stream)

    def test_the_schema_requires_both_and_holds_the_cap(self):
        for stream in CLAUDE:
            schema = streams.reply_schema(stream)
            item = schema["properties"]["rows"]["items"]
            self.assertIn("done_when", item["required"], stream)
            self.assertIn("impact", item["required"], stream)
            self.assertEqual(schema["properties"]["rows"]["maxItems"],
                             streams.row_cap(stream))
            full = {"rows": [_row(done_when="a test drives it", impact="3 Wrongs",
                                  **({"ui": False} if "ui" in item["properties"]
                                     else {}))]}
            self.assertTrue(_valid(schema, full), stream)
            self.assertFalse(_valid(schema, {"rows": [_row(impact="3")]}), stream)
            self.assertFalse(_valid(schema, {"rows": [_row(done_when="x")]}), stream)
        # `ui` is a screen label, asked only where a row can be about one.
        self.assertIn("ui", streams.reply_schema("design")["properties"]["rows"]
                      ["items"]["required"])
        self.assertNotIn("ui", streams.reply_schema("gaps")["properties"]["rows"]
                         ["items"]["properties"])
        # The schema is JSON the CLI can be handed on its argv.
        json.dumps(streams.reply_schema("gaps"))

    def test_no_example_seeds_a_screen(self):
        """The example reply said `"ui": true`, which a run copies."""
        for stream in ("design", "look"):
            self.assertNotIn('"ui": true', streams.analyst_system(stream))


class TestTheReplyIsRead(unittest.TestCase):
    def test_the_validated_object_wins_over_the_text(self):
        data = {"rows": [_row(done_when="a test drives it", impact="3 findings")]}
        rows, problem = streams.reply_rows(
            {"ok": True, "data": data, "text": "Sure! Here you go."}, "gaps")
        self.assertEqual(problem, "")
        self.assertEqual(rows[0]["where"], "Gap: dev.frozen and fixed tariffs")
        self.assertIn("**Done when:** a test drives it", rows[0]["body"])
        self.assertIn("**Estimated impact:** 3 findings", rows[0]["body"])

    def test_text_is_the_fallback(self):
        text = "```json\n" + json.dumps({"rows": [_row(done_when="d")]}) + "\n```"
        rows, problem = streams.reply_rows({"ok": True, "text": text}, "ideas")
        self.assertEqual((len(rows), problem), (1, ""))
        self.assertTrue(rows[0]["where"].startswith("Idea: "))

    def test_a_row_missing_done_when_is_filed_without_that_line(self):
        rows, problem = streams.parse_reply(json.dumps({"rows": [_row()]}), "gaps")
        self.assertEqual(problem, "")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("Done when", rows[0]["body"])
        self.assertNotIn("Estimated impact", rows[0]["body"])
        self.assertIn("0.28", rows[0]["body"])

    def test_an_empty_list_is_an_answer_and_garbage_is_not(self):
        self.assertEqual(streams.parse_reply('{"rows": []}', "gaps"), ([], ""))
        for reply in ("I looked and it all seems fine.", '{"rows": [',
                      '{"answer": "none"}', "[1, 2]"):
            rows, problem = streams.parse_reply(reply, "gaps")
            self.assertEqual(rows, [], reply)
            self.assertTrue(problem, reply)

    def test_the_old_guarantees_hold(self):
        many = {"rows": [_row(title=f"t{i}", done_when="d") for i in range(20)]
                + [{"title": "", "what": "w"}]}
        for stream in CLAUDE:
            self.assertEqual(len(streams.parse_rows(many, stream)),
                             streams.row_cap(stream))
        self.assertEqual(streams.parse_rows({"rows": [{"title": "t"}]}, "gaps"), [])
        long = streams.parse_rows({"rows": [_row(title="x" * 500, what="y" * 900)]},
                                  "gaps")[0]
        self.assertLessEqual(len(long["where"]), len("Gap: ") + 120)
        self.assertLessEqual(len(long["what"]), 300)


class TestRejectedReasonsBlock(unittest.TestCase):
    def test_bounded_newest_first_and_only_noise(self):
        rows = [{"stream": "gaps", "verdict": "declined", "at": i,
                 "where": f"Gap: part {i}", "what": "w" * 20,
                 "reason": "needs a new option"}
                for i in range(50)]
        rows.append({"stream": "gaps", "verdict": "fixed", "at": 99,
                     "where": "Gap: fixed one", "what": "x"})
        block = streams.rejected_block(rows)
        lines = block.splitlines()
        self.assertEqual(len(lines), streams.MAX_REJECTED)
        self.assertTrue(lines[0].startswith("- Gap: part 49:"))
        self.assertNotIn("fixed one", block)
        self.assertIn("closed as declined: needs a new option", lines[0])
        # Long rows meet the character budget first, in whole lines, each
        # field clipped on its own.
        long = [dict(r, what="w " * 300, reason="r " * 400) for r in rows]
        block = streams.rejected_block(long)
        self.assertLessEqual(len(block), streams.REJECTED_CHARS)
        for line in block.splitlines():
            self.assertTrue(line.startswith("- Gap: part "))
            self.assertLess(len(line), 120 + 200 + 200 + 60)

    def test_it_sits_beside_already_reported_and_not_in_a_look(self):
        block = "- Gap: Cameras: no image analysis — closed as declined: needs a dependency"
        for stream in ("gaps", "ideas", "design"):
            prompt = streams.analyst_prompt(stream, "FAULTS: none", "ctx",
                                            "- Gap: A: b", block)
            self.assertIn("CLOSED BY THE DEVELOPER", prompt)
            self.assertIn("needs a dependency", prompt)
            # ALREADY REPORTED stays last: nothing may cut it.
            self.assertTrue(prompt.endswith("- Gap: A: b"))
            self.assertIn("CLOSED BY THE DEVELOPER", streams.analyst_system(stream))
        prompt = streams.analyst_prompt("look", "FAULTS: none", "too crowded",
                                        "", block)
        self.assertNotIn("CLOSED BY THE DEVELOPER", prompt)


class TestWrongReasonsReachTheGapsPrompt(unittest.TestCase):
    def test_the_reasons_people_typed_are_in_the_context_bounded(self):
        settled = [{"kind": "ignored", "source": "check:dev.frozen",
                    "source_title": "Sensors frozen on one value", "ts": i,
                    "text": "sensor.rate has not moved",
                    "note": f"it is a fixed tariff {i} " + "z" * 400}
                   for i in range(30)]
        settled.append({"kind": "fixed", "source": "check:x", "ts": 99,
                        "text": "t", "note": "I replaced the battery"})
        settled.append({"kind": "ignored", "source": "check:y", "ts": 98,
                        "text": "t", "note": "   "})
        ctx = streams.context_block({}, [], [], settled)
        self.assertIn("WHAT PEOPLE SAID WHEN THEY MARKED A FINDING WRONG", ctx)
        said = [ln for ln in ctx.splitlines() if "they said:" in ln]
        self.assertEqual(len(said), streams.MAX_WRONG_REASONS)
        self.assertIn("fixed tariff 29", said[0])
        self.assertIn("Sensors frozen on one value", said[0])
        self.assertNotIn("replaced the battery", ctx)
        for line in said:
            self.assertLessEqual(len(line), 160 + streams.WRONG_REASON_CHARS + 120)
        prompt = streams.analyst_prompt("gaps", ctx)
        self.assertIn("fixed tariff 29", prompt)
        self.assertIn("reasons people gave", prompt)

    def test_no_reasons_no_heading(self):
        self.assertNotIn("MARKED A FINDING WRONG", streams.context_block({}, [], [], []))


class TestTheDesignTopicIsCutOnce(unittest.TestCase):
    def test_whole_lines_and_no_second_cut(self):
        findings = [{"text": f"finding {i} " + "w" * 250, "detail": "d" * 250,
                     "fix": "f" * 250} for i in range(40)]
        ctx = streams.design_context([], findings)
        self.assertLessEqual(len(ctx), streams.DESIGN_CHARS)
        self.assertTrue(ctx.splitlines()[-1].endswith(" | "),
                        "the last finding is whole, its empty triage column included")
        prompt = streams.analyst_prompt("design", "", ctx)
        self.assertIn(ctx, prompt)
        system = streams.analyst_system("design")
        self.assertIn("Never re-file anything under ALREADY REPORTED", system)
        self.assertIn("not the owner speaking", system)


class VerdictCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (devloop.DATA_DIR, devloop.TOKEN_FILE, github.API,
                     dict(upstream.STATE))
        devloop.DATA_DIR = base / "devloop"
        devloop.TOKEN_FILE = base / "secrets" / "devloop_github_token"
        self.gh = FakeGitHub()
        github.API = self.gh.url
        upstream.STATE.update(last_sweep=0.0, last_send=0.0, error="", running=False)
        devloop.save_settings({"enabled": True, "repo": "me/reports", "review": False})
        devloop.save_token(TOKEN)

    def tearDown(self):
        (devloop.DATA_DIR, devloop.TOKEN_FILE, github.API, state) = self._old
        upstream.STATE.clear()
        upstream.STATE.update(state)
        self.gh.close()
        self.tmp.cleanup()

    def _file(self, stream, title, t):
        upstream.ingest(stream, [{"where": f"Gap: {title}", "what": "it should",
                                  "detail": "", "body": "why"}], diagnostics(), now=t)
        upstream.send_due(now=t)
        return len(self.gh.issues)


class TestTheClosingReasonComesHome(VerdictCase):
    def test_the_first_line_of_the_closing_comment_is_kept(self):
        t = time.time()
        n = self._file("gaps", "the brief", t)
        closing = ("> **Declined:** it needs a new add-on option.\n\n"
                   "More text the house does not need.")
        self.gh.comments.append((n, closing))
        self.gh.judge(n, "devloop:declined")
        upstream.send_due(now=t + upstream.VERDICT_INTERVAL_S + 1)
        rows = upstream.rejected()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "Declined: it needs a new add-on option.")
        self.assertEqual(rows[0]["where"], "Gap: the brief")
        block = streams.rejected_block(rows)
        self.assertIn("Gap: the brief: it should — closed as declined", block)
        self.assertNotIn("More text", block)

    def test_an_unreadable_comment_is_asked_again_then_the_label_stands(self):
        t = time.time()
        n = self._file("ideas", "a widget", t)
        self.gh.judge(n, "devloop:not-brain")
        self.gh.comments_forbidden = True
        for i in range(1, upstream.REASON_TRIES):
            upstream.send_due(now=t + i * (upstream.VERDICT_INTERVAL_S + 1))
            self.assertNotIn("reason", upstream.rejected()[0])
        upstream.send_due(now=t + upstream.REASON_TRIES
                          * (upstream.VERDICT_INTERVAL_S + 1))
        self.assertEqual(upstream.rejected()[0]["reason"], "labelled not_brain")

    def test_reasons_are_read_a_few_a_pass_and_once(self):
        t = time.time()
        # Letters, not digits: the fingerprint folds digits, and "part 1"
        # and "part 2" would be one report.
        filed = [self._file("gaps", f"part {chr(97 + i)}", t + i)
                 for i in range(upstream.REASONS_PER_PASS + 3)]
        for n in filed:
            self.gh.comments.append((n, f"Duplicate of #{n - 1}."))
            self.gh.judge(n, "devloop:duplicate")
        later = t + 2 * upstream.VERDICT_INTERVAL_S

        def comment_reads():
            return sum(1 for m, p in self.gh.requests
                       if m == "GET" and p.split("?")[0].endswith("/comments"))

        upstream.send_due(now=later)
        self.assertEqual(comment_reads(), upstream.REASONS_PER_PASS)
        upstream.send_due(now=later + upstream.VERDICT_INTERVAL_S + 1)
        self.assertEqual(comment_reads(), upstream.REASONS_PER_PASS + 3)
        upstream.send_due(now=later + 2 * (upstream.VERDICT_INTERVAL_S + 1))
        self.assertEqual(comment_reads(), upstream.REASONS_PER_PASS + 3)
        self.assertEqual(len(upstream.rejected()), upstream.REASONS_PER_PASS + 3)

    def test_a_fixed_report_is_not_a_rejection(self):
        t = time.time()
        n = self._file("gaps", "the brief", t)
        self.gh.judge(n, "devloop:fixed")
        upstream.send_due(now=t + upstream.VERDICT_INTERVAL_S + 1)
        self.assertEqual(upstream.rejected(), [])


class TestAnUnreadableReplyIsCounted(VerdictCase):
    """Driven through the server's own stream pass, with the run itself
    stood in for: what is asserted is what the panel does with the answer."""

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        self.sent: list[dict] = []
        self.answer: dict = {}
        srv = self.server
        self._saved = (srv._claude, srv._record_usage, srv.engine.get_auth,
                       srv.findings_store._load_settled, srv.findings_store.scorecard)

        async def fake_claude(fn, prompt, system, *args, **kwargs):
            self.sent.append({"prompt": prompt, "system": system, **kwargs})
            return dict(self.answer)

        srv._claude = fake_claude
        srv._record_usage = lambda result, source: {}
        srv.engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        srv.findings_store._load_settled = lambda: [
            {"kind": "ignored", "source": "check:dev.frozen", "ts": 1,
             "text": "sensor.rate has not moved", "note": "it is a fixed tariff"}]
        srv.findings_store.scorecard = lambda: []

    def tearDown(self):
        srv = self.server
        (srv._claude, srv._record_usage, srv.engine.get_auth,
         srv.findings_store._load_settled, srv.findings_store.scorecard) = self._saved
        super().tearDown()

    def _run(self, stream="gaps"):
        return asyncio.run(self.server._devloop_stream(stream, {}, pressed=True))

    def test_garbage_is_logged_counted_and_files_nothing(self):
        self.answer = {"ok": True, "text": "I had a look and everything is fine."}
        with self.assertLogs("brain", level="WARNING") as logs:
            out = self._run()
        self.assertEqual(out, {"rows": 0})
        self.assertTrue(any("could not be read" in m for m in logs.output))
        seen = upstream.status()["unreadable"]["gaps"]
        self.assertEqual(seen["count"], 1)
        self.assertIn("no JSON object", seen["why"])
        self._run()
        self.assertEqual(upstream.status()["unreadable"]["gaps"]["count"], 2)

    def test_an_empty_list_is_not_counted(self):
        self.answer = {"ok": True, "text": "", "data": {"rows": []}}
        self.assertEqual(self._run(), {"rows": 0})
        self.assertNotIn("gaps", upstream.status()["unreadable"])

    def test_the_run_gets_the_schema_the_reasons_and_files_the_data(self):
        self.answer = {"ok": True, "text": "ignored prose", "data": {"rows": [
            _row(done_when="a monetary sensor is never reported", impact="3 Wrongs")]}}
        out = self._run()
        self.assertEqual(out.get("added"), 1)
        sent = self.sent[0]
        self.assertEqual(sent["schema"], streams.reply_schema("gaps"))
        self.assertIn("it is a fixed tariff", sent["prompt"])
        body = [e for e in upstream._load()["items"].values()][0]["body"]
        self.assertIn("**Done when:** a monetary sensor", body)


if __name__ == "__main__":
    unittest.main()
