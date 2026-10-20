#!/usr/bin/env python3
"""The other BRUH add-ons, watched from outside and filed through the loop.

The claims, each driven:
  * an installed BRUH add-on is recognised by its slug however the
    Supervisor prefixes it, and nothing else is;
  * a log's errors are distinct by what they say, not by when: a traceback
    is its exception line, a clock is not part of a fault, a WARNING is not
    an error;
  * every row names its add-on first, carries its version, and is labelled
    for the directory its fix belongs in;
  * a fix to another add-on is waited for in THAT add-on's release, never
    brAIn's — "Fixed in GardenRX 0.1.1" is not "here" because brAIn is 2.x;
  * an add-on this pass could not look at is never told "not seen since";
  * the chat's report becomes one look row about the add-on it names.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from test_devloop import NAMES, DevloopCase, diagnostics, upstream  # noqa: E402

import devloop.siblings as siblings  # noqa: E402
import devloop.verify as verify  # noqa: E402

HOUR = 3600

GARDEN_LOG = """\
s6-rc: info: service legacy-services successfully started
2026-10-19 21:04:11.120 INFO gateway listening on 8099
2026-10-19 21:05:02.991 ERROR [db] SqliteError: no such column: harvest.weight_g
2026-10-19 21:05:09.004 WARNING slow response from Next
2026-10-19 21:06:02.112 ERROR [db] SqliteError: no such column: harvest.weight_g
Traceback (most recent call last):
  File "/opt/bridge.py", line 40, in poll
    data = fetch()
  File "/opt/bridge.py", line 12, in fetch
    raise ConnectionError("gateway refused 0x7f3a9c11d2")
ConnectionError: gateway refused 0x7f3a9c11d2
"""


def observation(name="GardenRX", *, state="started", boot="auto",
                log=GARDEN_LOG, system_log=None, outbox=None, version="0.1.0"):
    spec = siblings.spec_by_name(name)
    return {"spec": spec, "slug": f"a0d7b954_{spec['key']}",
            "info": {"state": state, "boot": boot, "version": version},
            "log": log, "log_error": "", "system_log": system_log,
            "outbox": outbox}


class TestWhichAddonIsWhich(unittest.TestCase):
    def test_a_repository_slug_is_recognised(self):
        self.assertEqual(siblings.spec_for("a0d7b954_gardenrx", "GardenRX")["name"],
                         "GardenRX")
        self.assertEqual(siblings.spec_for("local_bruh-print")["name"], "BRUH Print")
        self.assertEqual(siblings.spec_for("a0d7b954_bruh_minecraft_server",
                                           "BRUH Minecraft")["dir"],
                         "bruh-minecraft-server/")

    def test_a_stranger_is_not_ours(self):
        self.assertIsNone(siblings.spec_for("core_mosquitto", "Mosquitto broker"))
        # Same slug tail, somebody else's add-on: the name says so.
        self.assertIsNone(siblings.spec_for("5c53de3b_bright", "Bright Lights Pro"))

    def test_brain_itself_is_not_a_sibling(self):
        self.assertNotIn("brAIn", siblings.PRODUCTS)


class TestTheLogIsReadForWhatItSays(unittest.TestCase):
    def test_errors_are_folded_by_what_they_say(self):
        errors = siblings.log_errors(GARDEN_LOG)
        sigs = [e["signature"] for e in errors]
        # Twice, at two clocks: one error.
        self.assertEqual(errors[0]["count"], 2)
        self.assertEqual(sigs[0], "[db] SqliteError: no such column: harvest.weight_g")
        # The traceback is its exception line, its hex folded.
        self.assertIn("ConnectionError: gateway refused <hex>", sigs)
        self.assertEqual(len(errors), 2, sigs)

    def test_a_warning_is_not_an_error(self):
        self.assertEqual(siblings.log_errors(
            "2026-10-19 10:00:00 WARNING disk is slow\nINFO ok\n"), [])

    def test_the_context_is_the_last_occurrence(self):
        err = siblings.log_errors(GARDEN_LOG)[1]
        self.assertIn('File "/opt/bridge.py", line 12', err["context"])


class TestTheRows(unittest.TestCase):
    def test_every_row_names_its_addon_and_version(self):
        rows = siblings.rows({"addons": [observation()]})
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["where"].startswith("GardenRX · "), row["where"])
            self.assertEqual(row["product"], "GardenRX")
            self.assertEqual(row["product_version"], "0.1.0")
            self.assertIn("gardenrx/", row["body"])

    def test_a_stopped_addon_set_to_boot_is_a_row(self):
        rows = siblings.rows({"addons": [observation(state="stopped")]})
        self.assertIn("GardenRX · Add-on", [r["where"] for r in rows])
        manual = siblings.rows({"addons": [observation(state="stopped", boot="manual",
                                                       log="")]})
        self.assertEqual(manual, [])

    def test_the_integrations_errors_are_its_own(self):
        log = [
            {"name": "custom_components.gardenrx.sensor", "level": "ERROR",
             "message": ["Error fetching gardenrx data: 401"], "count": 4,
             "exception": "Traceback ...\nUpdateFailed: 401", "source": []},
            {"name": "custom_components.bruh_print.sensor", "level": "ERROR",
             "message": ["printer gone"], "count": 1, "source": []},
            {"name": "custom_components.gardenrx", "level": "WARNING",
             "message": ["slow"], "count": 9, "source": []},
        ]
        rows = siblings.rows({"addons": [observation(log="", system_log=log)]})
        self.assertEqual([r["what"] for r in rows],
                         ["Home Assistant logged: Error fetching gardenrx data: 401"])
        self.assertIn("UpdateFailed", rows[0]["body"])

    def test_an_outbox_row_must_name_its_addon(self):
        outbox_dir = Path(self.tmp_dir())
        (outbox_dir / "bruh-print.json").write_text(
            '{"rows": [{"where": "BRUH Print · Card", "what": "card threw"},'
            ' {"where": "Somebody else", "what": "not ours"}]}', encoding="utf-8")
        rows = siblings.read_outbox(siblings.spec_by_name("BRUH Print"), outbox_dir)
        self.assertEqual([r["what"] for r in rows], ["card threw"])
        self.assertIsNone(siblings.read_outbox(siblings.spec_by_name("BRight"), outbox_dir))

    def tmp_dir(self):
        import tempfile
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return d.name


class TestCollect(unittest.TestCase):
    def test_what_could_not_be_read_is_unread(self):
        def get(path, text=False):
            if path == "/addons":
                return {"addons": [
                    {"slug": "a0d7b954_gardenrx", "name": "GardenRX"},
                    {"slug": "a0d7b954_bright", "name": "BRight"},
                    {"slug": "core_mosquitto", "name": "Mosquitto broker"}]}
            if path == "/addons/a0d7b954_bright/info":
                raise OSError("500")
            if path.endswith("/info"):
                return {"state": "started", "boot": "auto", "version": "0.1.0"}
            return "ERROR boom\n"
        out = siblings.collect([], get=get)
        self.assertEqual([o["spec"]["name"] for o in out["addons"]], ["GardenRX"])
        self.assertIn("BRight", out["unread"])         # info refused
        self.assertIn("BRUH Print", out["unread"])     # not installed
        self.assertNotIn("GardenRX", out["unread"])
        self.assertEqual(siblings.products(out), {"GardenRX": "0.1.0"})

    def test_a_supervisor_that_does_not_answer_is_an_error(self):
        def get(path, text=False):
            raise OSError("down")
        out = siblings.collect([], get=get)
        self.assertTrue(out["error"])
        self.assertEqual(set(out["unread"]), set(siblings.PRODUCTS))


class TestTheFixIsWaitedForInItsOwnRelease(DevloopCase):
    def file_garden(self, now, version="0.1.0"):
        rows = siblings.rows({"addons": [observation(version=version)]})
        upstream.ingest("siblings", rows, diagnostics(version="2.18.0"), NAMES,
                        now=now, products={"GardenRX": version})
        upstream.send_due(now=now)
        return rows

    def test_it_is_filed_labelled_for_its_directory(self):
        self.switch_on()
        self.file_garden(time.time())
        self.assertTrue(self.gh.issues)
        for issue in self.gh.issues:
            labels = [x["name"] for x in issue["labels"]]
            self.assertIn("devloop:gardenrx", labels)
            self.assertIn("devloop:siblings", labels)
            self.assertTrue(issue["title"].startswith("[GardenRX · "), issue["title"])
            self.assertIn("| GardenRX | 0.1.0 |", issue["body"])

    def test_fixed_in_gardenrx_is_read_against_gardenrx(self):
        self.switch_on()
        t = time.time() - 3 * 24 * HOUR
        self.file_garden(t)
        self.gh.judge(1, "devloop:fixed")
        self.gh.comments.append(
            (1, "Fixed in GardenRX 0.1.1 (https://github.test/pr/9)."))
        upstream.send_due(now=t + upstream.VERDICT_INTERVAL_S + 1)
        entry = next(e for e in upstream._load()["items"].values() if e.get("issue") == 1)
        self.assertEqual(entry["fixed_in"], "0.1.1")
        self.assertEqual(entry["product"], "GardenRX")
        # brAIn is 2.18.0, far past 0.1.1 — and the house still waits,
        # because GardenRX is 0.1.0.
        waiting = upstream.awaiting_update()
        self.assertEqual([(w["issue"], w["product"]) for w in waiting], [(1, "GardenRX")])
        # Once GardenRX 0.1.1 is installed, it is no longer waited for.
        upstream.ingest("siblings", [], diagnostics(version="2.18.0"), NAMES,
                        now=t + 2 * HOUR, products={"GardenRX": "0.1.1"})
        self.assertEqual(upstream.awaiting_update(), [])

    def test_the_follow_up_names_the_addon(self):
        self.switch_on()
        t = time.time() - 4 * 24 * HOUR
        self.file_garden(t)
        # Gone for days, with the add-on looked at: "Not seen since", in
        # GardenRX's release.
        upstream.ingest("siblings", [], diagnostics(version="2.18.0"), NAMES,
                        now=t + 3 * 24 * HOUR, products={"GardenRX": "0.1.0"})
        upstream.send_due(now=t + 3 * 24 * HOUR)
        said = [text for _, text in self.gh.comments]
        self.assertTrue(any("(GardenRX 0.1.0)" in s for s in said), said)
        self.assertFalse(any("brAIn" in s for s in said), said)

    def test_an_addon_not_looked_at_is_never_said_to_have_stopped(self):
        self.switch_on()
        t = time.time() - 4 * 24 * HOUR
        self.file_garden(t)
        upstream.ingest("siblings", [], diagnostics(version="2.18.0"), NAMES,
                        now=t + 3 * 24 * HOUR, unread=("GardenRX",))
        upstream.send_due(now=t + 3 * 24 * HOUR)
        self.assertEqual(self.gh.comments, [])

    def test_the_owner_is_asked_in_the_addons_own_release(self):
        items = {"x": {"fp": "x" * 16, "verdict": "fixed", "stream": "look",
                       "fixed_in": "0.1.1", "product": "GardenRX", "what": "y"}}
        self.assertEqual(verify.due(items, "2.18.0", {}, set(), {"GardenRX": "0.1.0"}), [])
        due = verify.due(items, "2.18.0", {}, set(), {"GardenRX": "0.1.1"})
        self.assertEqual(len(due), 1)
        self.assertIn("GardenRX 0.1.1 was meant", verify.question_row(due[0])["claim"])

    def test_a_brain_report_is_unchanged(self):
        entry = {"fixed_in": "2.18.0"}
        self.assertEqual(upstream.product_of(entry), "brAIn")
        self.assertEqual(upstream.running_for(entry, "2.18.0", {"GardenRX": "0.1.0"}),
                         "2.18.0")


class TestTheLookKnowsTheAddons(unittest.TestCase):
    def test_a_look_about_another_addon_is_filed_for_it(self):
        import devloop.streams as streams
        rows, problem = streams.parse_reply(
            {"rows": [{"title": "Harvest page fails", "what": "The harvest page errors.",
                       "why": "", "done_when": "It loads.", "impact": "daily",
                       "ui": True, "addon": "GardenRX"}]}, "look", "garden harvest broken")
        self.assertEqual(problem, "")
        self.assertTrue(rows[0]["where"].startswith("GardenRX · Fix: "))
        self.assertEqual(rows[0]["product"], "GardenRX")

    def test_a_verbatim_request_naming_one_addon_is_its(self):
        import devloop.streams as streams
        row = streams.verbatim_rows("BRUH Print labels come out blank")[0]
        self.assertEqual(row["product"], "BRUH Print")
        self.assertNotIn("product", streams.verbatim_rows("the brief is long")[0])


class TestTheChatsReport(unittest.TestCase):
    def setUp(self):
        import server  # noqa: PLC0415
        self.server = server

    def test_a_report_about_bambu_is_bambus(self):
        row, why = self.server.report_row({
            "addon": "BRUH Bambu Studio", "title": "Slice fails on plate 2",
            "what": "Slicing a two-plate 3MF fails.",
            "evidence": "ERROR slicer exited 1\n```inner```",
            "asked": "fix the slicer"})
        self.assertEqual(why, "")
        self.assertTrue(row["where"].startswith("BRUH Bambu Studio · Fix: "))
        self.assertEqual(row["product"], "BRUH Bambu Studio")
        self.assertIn("> fix the slicer", row["body"])
        self.assertEqual(row["body"].count("```"), 2)

    def test_an_unknown_addon_is_refused(self):
        row, why = self.server.report_row({"addon": "Mosquitto", "title": "t", "what": "w"})
        self.assertIsNone(row)
        self.assertIn("GardenRX", why)

    def test_brain_is_the_default(self):
        row, _ = self.server.report_row({"title": "t", "what": "w"})
        self.assertNotIn("product", row)


if __name__ == "__main__":
    unittest.main()
