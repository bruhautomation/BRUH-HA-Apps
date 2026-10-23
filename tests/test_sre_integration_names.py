#!/usr/bin/env python3
"""A log-error finding names the integration as Home Assistant shows it.

#340: "Errors in the log from the bambu_lab integration" — the overnight
check titled the integration by its domain, which is a key in a registry
and not what anybody sees in Settings. The collector reads the config
entries, the digest carries each integration's name as the house sees it
(its entry's title, or the domain spelled as words), the title names the
affected device when the record knows it, and no title, detail or fix the
pass files carries an underscore-separated integration domain — including
a title it reuses from an earlier night.
"""

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import ha_data  # noqa: E402
import sre  # noqa: E402
from fake_core_ws import FakeCore, ok  # noqa: E402

NOW = 1_800_000_000.0
SLUG = re.compile(r"\bbambu_lab\b")


def collected(devices=(), entities=(), entries=None):
    return {
        "available": {"log": True, "zha": True, "registry": True,
                      "states": True, "config_entries": entries is not None},
        "errors": {},
        "log": [{"name": "custom_components.bambu_lab.pybambu.client",
                 "message": ["MQTT connection to the printer dropped"],
                 "level": "ERROR", "source": ["pybambu/client.py", 88],
                 "timestamp": NOW - 600, "count": 9}],
        "zha": [], "entities": list(entities), "devices": list(devices),
        "areas": {}, "states": {}, "automations": [],
        "config_entries": entries or [],
    }


def one_cause(dig, **cause):
    rid = next(r["id"] for r in dig["records"] if r["kind"] == "log")
    base = {"title": "Errors in the log from the bambu_lab integration",
            "detail": "The bambu_lab integration lost its connection nine "
                      "times overnight.",
            "fix": "Reload the bambu_lab integration.",
            "severity": "warning", "records": [rid]}
    base.update(cause)
    return sre.parse_causes({"causes": [base]}, dig)["causes"]


class TestTheIntegrationIsNamedAsTheHouseSeesIt(unittest.TestCase):
    def test_the_entry_title_names_it(self):
        dig = sre.digest(collected(entries=[
            {"entry_id": "e1", "domain": "bambu_lab", "title": "Bambu Lab"}]),
            NOW)
        self.assertEqual(dig["integration_names"]["bambu_lab"], "Bambu Lab")
        [cause] = one_cause(dig)
        for field in ("title", "detail", "fix"):
            self.assertIsNone(SLUG.search(cause[field]), cause[field])
        self.assertIn("Bambu Lab", cause["title"])

    def test_without_an_entry_the_domain_is_spelled_as_words(self):
        dig = sre.digest(collected(), NOW)
        self.assertEqual(dig["integration_names"]["bambu_lab"], "Bambu Lab")

    def test_the_plain_title_names_the_device_when_the_record_does(self):
        dig = sre.digest(collected(
            devices=[{"id": "dev-p1s", "name": "P1S printer"}],
            entries=[]), NOW)
        rec = next(r for r in dig["records"] if r["kind"] == "log")
        rec["devices"] = ["dev-p1s"]
        self.assertEqual(
            sre._plain_title(rec, dig),
            "Errors in the log from the Bambu Lab integration about P1S printer")
        rec["devices"] = []
        self.assertEqual(sre._plain_title(rec, dig),
                         "Errors in the log from the Bambu Lab integration")

    def test_no_row_the_pass_files_carries_the_slug(self):
        dig = sre.digest(collected(), NOW)
        causes = one_cause(dig)
        state = {"anchors": {causes[0]["anchor"]: {
            "text": "Errors in the log from the bambu_lab integration",
            "at": 1, "entity": ""}}}
        rows = sre.rows(causes, dig, state, NOW)
        for row in rows:
            for field in ("text", "claim", "detail", "fix"):
                self.assertIsNone(SLUG.search(row[field]), row[field])


class TestNoCheckTitlesAnIntegrationByItsDomain(unittest.TestCase):
    """The same rule over every check's title: `dev.restored` named its
    integration by the domain ('gone_integration') in the text."""

    def test_no_title_the_sweep_files_carries_a_domain(self):
        import io

        import test_check_fix_nonempty as fixes
        from test_finding_text_plain import (SNAKE_RE, SWEEP_MODULES,
                                             _Capture, domains_of)
        holder = fixes.TestEveryRowSaysWhatToDo()
        holder.setUp()
        try:
            with _Capture() as cap:
                suite = unittest.defaultTestLoader.loadTestsFromNames(
                    SWEEP_MODULES + fixes.EXTRA_MODULES)
                unittest.TextTestRunner(stream=io.StringIO(),
                                        verbosity=0).run(suite)
        finally:
            holder.tearDown()
        bad = sorted({f"{cid}: {row.get('text')!r}"
                      for cid, row, snap in cap.rows
                      for w in SNAKE_RE.findall(str(row.get("text") or ""))
                      if w in domains_of(snap)})
        self.assertEqual(bad, [], "\n".join(bad))


class TestTheCollectorReadsTheEntries(unittest.IsolatedAsyncioTestCase):
    async def test_config_entries_are_read(self):
        core = await FakeCore({
            "system_log/list": ok([]),
            "zha/devices": ok([]),
            "config/entity_registry/list": ok([]),
            "config/device_registry/list": ok([]),
            "config/area_registry/list": ok([]),
            "config_entries/get": ok([{"entry_id": "e1", "domain": "bambu_lab",
                                       "title": "Bambu Lab"}]),
        }).start()
        old_ws, old_api = ha_data.CORE_WS, ha_data.CORE_API
        ha_data.CORE_WS = core.url
        ha_data.CORE_API = "http://127.0.0.1:9/api"
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                got = await sre.collect(session)
        finally:
            ha_data.CORE_WS, ha_data.CORE_API = old_ws, old_api
            await core.close()
        self.assertTrue(got["available"]["config_entries"])
        self.assertEqual(got["config_entries"][0]["title"], "Bambu Lab")


if __name__ == "__main__":
    unittest.main()
