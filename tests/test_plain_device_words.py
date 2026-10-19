#!/usr/bin/env python3
"""A device, camera, login or integration that failed is told in household words.

A real house's cards said a camera's stream "ended with I/O errors and EOF"
from "the gateway at <an address>" and asked whether its "RTSP stream is
still enabled"; a smart plug's said "re-probes, resubscribes and control
calls to <an address> keep timing out"; a light's "failed with a device
communication error"; a login card talked about refreshing a token. Every
one is what brAIn READ (a log line, an integration's exception), not what
the person holding the device needs: which thing, what stopped working,
and one step.

Three halves, each held here:

* the two model-written producers that write those cards — the overnight
  check (`sre.SYSTEM`) and the Resident's investigation
  (`resident.INVESTIGATE_SYSTEM`) — carry the one shared rule
  (`prompt_kit.DEVICE_WORDS`);
* a deterministic pass (`house_words.addresses`, inside
  `house_words.plain`, which `findings_store` runs over every model-written
  row before it is stored) takes an IPv4 address out of what a person
  reads, whatever the model wrote;
* no deterministic check writes an address or a protocol word into its
  `detail` or `fix`, linted over every row the check test modules produce
  (`test_finding_text_plain`'s sweep). One exception, named rather than
  linted away: `sec.login_bans` reports the address Home Assistant banned,
  because that address IS the finding.
"""

import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PANEL_DIR = TESTS_DIR.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(TESTS_DIR))

import findings_store  # noqa: E402
import house_words  # noqa: E402
import prompt_kit  # noqa: E402
import resident  # noqa: E402
import sre  # noqa: E402

IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d]|\.\d)")
# The words a log or a protocol uses and a household does not. Matched as
# whole words, case-folded; "I/O" has no word boundary inside it.
JARGON_RE = re.compile(
    r"\bRTSP\b|\bEOF\b|\bI/O\b|\btokens?\b|\bprob(?:e|es|ing|ed)\b|"
    r"\bre-?probes?\b|\b(?:re)?subscri(?:be|bes|bed|bing|ption)\b",
    re.I)
# The address Home Assistant banned is the finding (module docstring).
IPV4_ALLOWED = {"sec.login_bans"}

# Documentation addresses (RFC 5737), never a real house's.
CAMERA = ("The stream from the gateway at 192.0.2.40 ended with I/O "
          "errors and EOF.")
PLUG = ("Re-probes, resubscribes and control calls to 198.51.100.7 keep "
        "timing out.")


class TestThePromptsCarryTheRule(unittest.TestCase):
    def test_the_rule_names_what_it_forbids(self):
        rule = prompt_kit.DEVICE_WORDS
        for word in ("IP address", "RTSP", "EOF", "I/O", "token", "probe",
                     "subscribe", "resubscribe"):
            self.assertIn(word, rule)
        for half in ("which thing", "what stopped working", "one step",
                     "household words"):
            self.assertIn(half, rule)

    def test_the_overnight_check_carries_it(self):
        self.assertIn(prompt_kit.DEVICE_WORDS, sre.SYSTEM)

    def test_the_resident_investigation_carries_it(self):
        self.assertIn(prompt_kit.DEVICE_WORDS, resident.INVESTIGATE_SYSTEM)
        # A rewrite of a filed row starts from the same contract.
        self.assertIn(prompt_kit.DEVICE_WORDS,
                      resident.INVESTIGATE_SYSTEM + resident.REFINE_SYSTEM)


class TestAnAddressIsTakenOut(unittest.TestCase):
    def test_an_address_after_at_is_dropped(self):
        out = house_words.addresses(CAMERA)
        self.assertEqual(IPV4_RE.findall(out), [], out)
        self.assertIn("from the gateway ended", out)

    def test_an_address_standing_for_the_thing_is_its_address(self):
        out = house_words.addresses(PLUG)
        self.assertEqual(IPV4_RE.findall(out), [], out)
        self.assertIn("calls to its address keep timing out", out)

    def test_an_aside_and_a_port_go_too(self):
        self.assertEqual(
            house_words.addresses("The porch camera (192.0.2.41) dropped."),
            "The porch camera dropped.")
        self.assertEqual(
            house_words.addresses("IP address 192.0.2.42:554 refused it."),
            "its address refused it.")

    def test_a_version_number_is_not_an_address(self):
        for text in ("Updated to 2026.10.1 overnight.",
                     "Firmware 1.2.3.4.5 is installed.",
                     "No address here."):
            self.assertEqual(house_words.addresses(text), text)

    def test_plain_runs_it(self):
        self.assertEqual(IPV4_RE.findall(house_words.plain(PLUG)), [])


class TestAStoredModelRowIsPlain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE,
                     findings_store.DISPLAY_NAMES, findings_store.HOUSE_TZ)
        base = Path(self.tmp.name)
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.INBOX_DIR = base / "inbox"
        findings_store.SETTLED_FILE = base / "settled.json"
        findings_store.STATE_FILE = (
            base / "config" / ".brain" / "findings_state.json")
        findings_store.DISPLAY_NAMES = None
        findings_store.HOUSE_TZ = None

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE,
         findings_store.DISPLAY_NAMES, findings_store.HOUSE_TZ) = self._old
        self.tmp.cleanup()

    def test_an_overnight_cause_loses_its_address(self):
        [row] = findings_store.add_many([{
            "text": "The porch camera keeps dropping its picture",
            "detail": CAMERA, "fix": "Restart the camera at 192.0.2.40.",
            "source": sre.SOURCE, "entity_id": "camera.porch"}])
        for key in ("text", "detail", "fix"):
            self.assertEqual(IPV4_RE.findall(row[key]), [], (key, row[key]))

    def test_a_resident_case_loses_its_address(self):
        row = findings_store.add_case({
            "text": "The office plug stopped answering",
            "claim": "The office plug stopped answering",
            "detail": PLUG, "fix": "Power-cycle the office plug.",
            "entity_id": "switch.office_plug"})
        self.assertIsNotNone(row)
        stored = findings_store.get(row["ts"])
        self.assertEqual(IPV4_RE.findall(stored["detail"]), [],
                         stored["detail"])

    def test_a_checks_text_is_never_rewritten(self):
        # `text` is a check's dedupe key: the pass is for model-written rows.
        text = "Device at 192.0.2.9 is unavailable"
        [row] = findings_store.add_many([{
            "text": text, "source": "check:dev.unavailable",
            "entity_id": "switch.office_plug"}])
        self.assertEqual(row["text"], text)


class TestNoCheckSpeaksProtocol(unittest.TestCase):
    def test_no_address_or_protocol_word_in_a_detail_or_fix(self):
        import test_finding_text_plain as sweep
        with sweep._Capture() as cap:
            suite = unittest.defaultTestLoader.loadTestsFromNames(
                sweep.SWEEP_MODULES)
            result = unittest.TextTestRunner(
                stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(),
                        [str(t) for t, _ in result.failures + result.errors])
        self.assertGreater(len(cap.rows), 20, "the sweep produced no rows")
        bad = []
        for check_id, row, _snap in cap.rows:
            for field in ("detail", "fix"):
                prose = str(row.get(field) or "")
                found = JARGON_RE.findall(prose)
                if check_id not in IPV4_ALLOWED:
                    found += IPV4_RE.findall(prose)
                if found:
                    bad.append(f"{check_id} {field}: {found} in {prose!r}")
        self.assertEqual(sorted(set(bad)), [], "\n".join(sorted(set(bad))))

    def test_the_lint_catches_what_the_house_reported(self):
        for prose in (CAMERA, PLUG,
                      "Check its RTSP stream is still enabled.",
                      "Sign in again to refresh the token."):
            self.assertTrue(JARGON_RE.search(prose) or IPV4_RE.search(prose),
                            prose)


if __name__ == "__main__":
    unittest.main()
