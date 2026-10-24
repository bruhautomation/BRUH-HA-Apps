#!/usr/bin/env python3
"""A finding's prose names things the way a person sees them.

A real house's cards told the homeowner to "run brain.delete_orphaned_devices
(it is a dry run unless you tell it otherwise)", listed devices with their
MAC address in brackets, and named a helper as "(input_select.guest_mode)".
Every one of those is developer vocabulary: an entity id is a key in a
registry, a MAC is a hardware address, and `brain.*` is a service a person
reaches through Developer tools if they know it exists. The card's own
`prettyText` swaps known ids for names, but an id the house no longer has
(a dead reference, a restored leftover) has no name to swap in.

So the rule: a check's ``detail`` and ``fix`` carry no entity id, no MAC
and no `brain.*` service name. An entity is named with
``House.label`` — its friendly name, or for one the house has no name for,
the id read aloud ("the scene “before movie”"). The id itself goes in the
row's ``evidence``, which the card keeps under its closed Details.

``text`` is held to a narrower rule, on purpose: it is the store's dedupe
key, so rewording it files a duplicate of every row already on a house and
re-raises every settled one. It already uses the house's name for an
entity; the lint only fails a ``text`` that shows an id the house HAS a
name for, which is a check choosing the id over the name. A fixture entity
with no friendly name anywhere is named by its id in ``text`` (for example
`dev.frozen`'s "sensor.stuck_5 has read exactly the same value…") and that
is the honest fallback, not a finding.

The sweep is the evidence: every check function in the catalog is wrapped,
the check test modules that already plant each defect are run, and every
row any of them produced is linted. A check the sweep never saw is not
covered, so the three named in the report are asserted to have produced
rows, and the orphan device with a MAC in its name is planted here.

Exception, documented rather than linted away: ``reg.hardware_name`` may
show a MAC, because the name the person sees in every picker IS the
hardware id and that is the finding. No fixture plants one in a name it
reports, so the exception is never exercised by the sweep; it is named so
a future one does not read as a regression.
"""

import functools
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

import checks  # noqa: E402
import findings_store  # noqa: E402
_util = checks._util
from test_house_checks import NOW, core_run, house  # noqa: E402

registry = checks.registry
devices = checks.devices

# An entity id, restricted to the domains Home Assistant has, so "3.5",
# "e.g." and "automations.yaml" are not ids.
DOMAINS = _util._CORE_DOMAINS
ID_RE = re.compile(r"(?<![\w.])([a-z_]+)\.([a-z0-9_]+)(?![\w])")
MAC_RE = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)
SERVICE_RE = re.compile(r"\bbrain\.[a-z_]+")
# Template code: a person reads what a rule does, never its Jinja.
TEMPLATE_RE = re.compile(r"\{\{|\{%")
# Home Assistant's internals a person never reads (a house's report): a
# trace's step path, a raw state token where the frontend shows a word, a
# MAC or an IP address, a protocol name, and "1 hours".
TRACE_RE = re.compile(r"\b(?:actions?|sequence|choose|then|else|default|"
                      r"conditions?|triggers?|parallel|repeat)/\d+\b")
RAW_STATES = ("not_home", "heat_cool", "fan_only", "armed_away",
              "armed_home", "armed_night", "armed_vacation",
              "armed_custom_bypass", "below_horizon", "above_horizon")
RAW_STATE_RE = re.compile(r"\b(?:" + "|".join(RAW_STATES) + r")\b")
QUOTED_RAW_RE = re.compile(r"[“\"'](?:finish|" + "|".join(RAW_STATES)
                           + r")[”\"']")
IP_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d]|\.\d)")
PROTOCOL_RE = re.compile(r"\b(?:ARP|ICMP|mDNS|DHCP|SSDP|UDP|TCP|MQTT)\b")
ONE_PLURAL_RE = re.compile(r"\b1 (?:hours|minutes|days|seconds|weeks)\b")


def internals(prose: str) -> list[str]:
    """The raw internals in one piece of prose."""
    found = []
    for rx in (TRACE_RE, RAW_STATE_RE, QUOTED_RAW_RE, IP_RE, PROTOCOL_RE,
               ONE_PLURAL_RE):
        found += [m.group(0) for m in rx.finditer(prose or "")]
    return found


# A snake_case word outside an entity id. It fails the lint only when it is
# an integration's domain: the house's own (its registry platforms and
# config entries) or one of the commonly reported ones below. A setting a
# person types into their configuration (`purge_keep_days`) is not one.
SNAKE_RE = re.compile(r"(?<![\w.])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?!\w|\.\w)")
KNOWN_DOMAINS = frozenset({
    "homekit_controller", "yalexs_ble", "history_stats", "zwave_js",
    "mobile_app", "switch_as_x", "min_max", "utility_meter",
    "google_assistant", "music_assistant",
    "alexa_media", "unifi_protect", "tplink_omada", "ring_doorbell",
    "xiaomi_miio", "tuya_local", "local_tuya", "bluetooth_le_tracker",
})


def domains_of(snap) -> set[str]:
    """The integration domains a snapshot names: its entities' platforms
    and its config entries' domains."""
    out = set(KNOWN_DOMAINS)
    if isinstance(snap, dict):
        for row in snap.get("entities") or []:
            if isinstance(row, dict) and row.get("platform"):
                out.add(str(row["platform"]))
        for row in snap.get("config_entries") or []:
            if isinstance(row, dict) and row.get("domain"):
                out.add(str(row["domain"]))
    return out

# The check modules that plant each defect. Pure over a snapshot: none of
# them stands up a server or writes a store, so running them here is cheap.
SWEEP_MODULES = (
    "test_house_checks",
    "test_checks_field_reports",
    "test_checks_house_reports",
    "test_checks_seven_house_reports",
    "test_checks_wrong_in_the_field",
    "test_finding_area_sentence",
    "test_job_status_chore",
    "test_not_a_house_reading",
    "test_never_fired_safety",
    "test_battery_rechargeable",
)

# A MAC is allowed here and nowhere else (module docstring).
MAC_ALLOWED = {"reg.hardware_name"}


def ids_in(text: str) -> list[str]:
    return [m.group(0) for m in ID_RE.finditer(text) if m.group(1) in DOMAINS]


def problems(check_id: str, row: dict, snap: dict | None) -> list[str]:
    """What is wrong with one row's prose, as sentences naming the field."""
    out = []
    for field in ("text", "detail", "fix"):
        prose = str(row.get(field) or "")
        found = []
        ids = ids_in(prose)
        if field == "text":
            known = _util.House(snap) if isinstance(snap, dict) else None
            ids = [e for e in ids
                   if known is not None and known.name(e) != e]
        found += ids
        if check_id not in MAC_ALLOWED:
            found += [m.group(0) for m in MAC_RE.finditer(prose)]
        found += SERVICE_RE.findall(prose)
        found += internals(prose)
        if field in ("detail", "fix"):
            found += TEMPLATE_RE.findall(prose)
            slugs = domains_of(snap)
            found += [w for w in SNAKE_RE.findall(prose) if w in slugs]
        if found:
            out.append(f"{check_id} {field}: {found} in {prose!r}")
    return out


class _Capture:
    """Wrap every check's run function and keep what it returned."""

    def __init__(self):
        self.rows: list[tuple[str, dict, dict | None]] = []
        self._undo: list = []

    def __enter__(self):
        for c in checks.CHECKS:
            fn = c["run"]
            wrapped = self._wrap(c["id"], fn)
            self._undo.append((c, "run", fn, None))
            c["run"] = wrapped
            mod = sys.modules.get(fn.__module__)
            if mod is not None and getattr(mod, fn.__name__, None) is fn:
                self._undo.append((None, fn.__name__, fn, mod))
                setattr(mod, fn.__name__, wrapped)
        return self

    def __exit__(self, *exc):
        for holder, key, fn, mod in reversed(self._undo):
            if mod is not None:
                setattr(mod, key, fn)
            else:
                holder[key] = fn
        return False

    def _wrap(self, check_id, fn):
        @functools.wraps(fn)
        def run(*args, **kwargs):
            out = fn(*args, **kwargs)
            snap = args[0] if args else kwargs.get("snap")
            for row in out or []:
                if isinstance(row, dict):
                    self.rows.append((check_id, row, snap))
            return out
        return run


class TestEveryCheckWritesPlainProse(unittest.TestCase):
    def test_no_id_mac_or_service_in_what_a_person_reads(self):
        with _Capture() as cap:
            suite = unittest.defaultTestLoader.loadTestsFromNames(
                SWEEP_MODULES)
            result = unittest.TextTestRunner(
                stream=io.StringIO(), verbosity=0).run(suite)
        # The sweep is only evidence if the houses it ran were the houses
        # those tests meant to build.
        self.assertTrue(result.wasSuccessful(),
                        [str(t) for t, _ in result.failures + result.errors])
        seen = {cid for cid, _r, _s in cap.rows}
        for wanted in ("auto.dead_ref", "auto.trigger_unavailable",
                       "auto.conflict", "reg.unused_helper",
                       "reg.orphan_device", "dev.restored",
                       "reg.hardware_name", "org.dashboard_dead_ref",
                       "sys.history_incomplete", "dev.unavailable"):
            self.assertIn(wanted, seen, "the sweep never produced a row "
                          f"from {wanted}, so it proves nothing about it")
        bad = sorted({p for cid, row, snap in cap.rows
                      for p in problems(cid, row, snap)})
        self.assertEqual(bad, [], "\n".join(bad))


class TestTheReportedRows(unittest.TestCase):
    def test_an_orphan_device_is_named_without_its_mac(self):
        snap = house()
        snap["devices"].append({"id": "dev-a", "name":
                                "Lounge speaker (AA:BB:CC:DD:EE:0F)"})
        snap["devices"].append({"id": "dev-b", "name": "aa:bb:cc:dd:ee:10"})
        found = registry.orphan_device(snap, NOW)
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(problems("reg.orphan_device", row, snap), [])
        self.assertIn("Lounge speaker", row["detail"])
        self.assertIn("1 named only by a hardware address", row["detail"])
        self.assertIn("Settings > Devices & services > Devices", row["fix"])

    def test_one_device_named_only_by_its_address_is_still_reported(self):
        snap = house()
        snap["devices"].append({"id": "dev-b", "name": "AA:BB:CC:DD:EE:10"})
        row = registry.orphan_device(snap, NOW)[0]
        self.assertEqual(problems("reg.orphan_device", row, snap), [])
        self.assertTrue(row["detail"].startswith("One, named only"))

    def test_an_unused_helper_is_named_and_its_id_is_evidence(self):
        snap = house()
        snap["states"]["input_select.guest_mode"] = {
            "state": "off", "attributes": {"friendly_name": "Guest mode"},
            "last_changed": "2026-01-01T00:00:00+00:00"}
        snap["entities"].append({"entity_id": "input_select.guest_mode",
                                 "platform": "input_select",
                                 "created_at": NOW - 400 * 86400})
        row = registry.unused_helper(snap, NOW)[0]
        self.assertEqual(problems("reg.unused_helper", row, snap), [])
        self.assertIn("Guest mode", row["detail"])
        self.assertIn("input_select.guest_mode",
                      [e["entity"] for e in row["evidence"]])

    def test_an_entity_the_house_has_no_name_for_is_read_aloud(self):
        self.assertEqual(_util.spoken_id("scene.before_movie"),
                         "the scene “before movie”")
        self.assertEqual(_util.House(house()).label("light.kitchen"),
                         _util.House(house()).name("light.kitchen"))

    def test_the_lint_catches_what_the_house_reported(self):
        """The three sentences from the report, as the lint reads them."""
        for prose in ("run brain.delete_orphaned_devices (it is a dry run)",
                      "Old speaker (aa:bb:cc:dd:ee:ff)",
                      "1 helper: Guest mode (input_select.guest_mode)"):
            self.assertTrue(problems("x", {"fix": prose}, None), prose)
        for prose in ("3.5 degrees", "edit automations.yaml", "e.g. this"):
            self.assertFalse(problems("x", {"fix": prose}, None), prose)

    def test_the_lint_catches_template_code_and_integration_slugs(self):
        for prose in ("It runs at {{ today_at('07:00') }}.",
                      "{% if is_state('sun.sun', 'below_horizon') %}",
                      "Reload the homekit_controller integration.",
                      "The yalexs_ble lock dropped off.",
                      "It is a history_stats helper."):
            self.assertTrue(problems("x", {"detail": prose}, None), prose)
            self.assertTrue(problems("x", {"fix": prose}, None), prose)
        self.assertFalse(problems(
            "x", {"fix": "Lower purge_keep_days in configuration.yaml."},
            None))
        snap = {"entities": [{"entity_id": "sensor.a",
                              "platform": "my_custom_thing"}]}
        self.assertTrue(problems("x", {"detail": "From my_custom_thing."},
                                 snap))

    def test_a_down_helper_is_named_in_plain_words(self):
        snap = house()
        snap["states"]["sensor.water_meter"] = {
            "state": "unavailable",
            "attributes": {"friendly_name": "Water this month"},
            "last_changed": "2026-01-01T00:00:00+00:00"}
        snap["entities"].append({"entity_id": "sensor.water_meter",
                                 "platform": "utility_meter"})
        rows = [r for r in devices.unavailable(snap, NOW)
                if r.get("entity_id") == "sensor.water_meter"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(problems("dev.unavailable", rows[0], snap), [])
        self.assertIn("utility meter helper", rows[0]["fix"])

    def test_a_failed_entry_with_no_title_is_named_in_plain_words(self):
        snap = house(config_entries=[
            {"entry_id": "a1", "domain": "homekit_controller", "title": "",
             "state": "setup_error", "source": "user", "reason": "Gone"}])
        [row] = checks.system.entry_failed(snap, NOW)
        self.assertEqual(problems("sys.entry_failed", row, snap), [])


class TestRawInternalsAreNotShown(unittest.TestCase):
    """What a real house's findings read: a trace's step path, `not_home`,
    an ARP lookup at an IP address, a status's own word "finish" and
    "1 hours". Each is named the way Home Assistant's frontend says it."""

    def test_the_lint_catches_what_the_house_reported(self):
        for prose in ("at step action/0/choose/1/sequence/0: Failed to send " +
                      "request",
                      "The phone goes not_home at 05:20.",
                      "none answers ARP from 192.168.1.40 ('host is " +
                      "unreachable')",
                      "went from running to “finish” 1 hours ago"):
            self.assertTrue(problems("x", {"detail": prose}, None), prose)
        for prose in ("It finished at 14:10.", "Nobody was home at 05:20.",
                      "Version 2026.10.1 is waiting.",
                      "when it tried to turn on Kitchen"):
            self.assertFalse(problems("x", {"detail": prose}, None), prose)

    def test_a_failed_step_is_named_by_what_it_does(self):
        snap = house()
        snap["automations"][0]["actions"] = [
            {"choose": [
                {"conditions": [], "sequence": [{"delay": "00:00:05"}]},
                {"conditions": [], "sequence": [
                    {"action": "light.turn_on",
                     "target": {"entity_id": "light.kitchen"}}]}]}]
        snap["traces"]["automation.morning-1"] = [
            core_run("1", "error", 30, error="Failed to send request",
                     last_step="action/0/choose/1/sequence/0")]
        [row] = checks.automations.trace_error(snap, NOW)
        self.assertEqual(problems("auto.trace_error", row, snap), [])
        self.assertIn("when it tried to turn on Kitchen", row["detail"])
        self.assertNotIn("/", row["detail"])

    def test_a_step_it_cannot_find_is_left_out_rather_than_quoted(self):
        snap = house()
        snap["traces"]["automation.morning-1"] = [
            core_run("1", "error", 30, error="boom",
                     last_step="action/7/sequence/2")]
        [row] = checks.automations.trace_error(snap, NOW)
        self.assertNotIn("action/7", row["detail"])
        self.assertIn("boom", row["detail"])

    def test_states_are_the_words_the_frontend_shows(self):
        for raw, shown in (("finish", "finished"), ("not_home", "away"),
                           ("heat_cool", "heat/cool"), ("idle", "idle"),
                           ("fan_only", "fan only")):
            self.assertEqual(_util.state_words(raw), shown)

    def test_durations_are_counted_in_words(self):
        import numfmt
        for minutes, said in ((1, "1 minute ago"), (5, "5 minutes ago"),
                              (60, "1 hour ago"), (95, "1 hour ago"),
                              (150, "2 hours ago")):
            self.assertEqual(numfmt.ago_minutes(minutes), said)


class TestARewordedFixReachesTheRowsAlreadyFiled(unittest.TestCase):
    """`refresh_details` carries a check's new `fix` onto its open rows —
    otherwise every house keeps the old sentence for as long as the row
    lives — and never over a sentence somebody or something else wrote."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        base = Path(self.tmp.name)
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.INBOX_DIR = base / "inbox"
        findings_store.SETTLED_FILE = base / "settled.json"
        findings_store.STATE_FILE = base / "config" / ".brain" / "state.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def _row(self, fix):
        return {"text": "Some devices are left in the registry with no "
                        "entities", "detail": "Old thermostat.",
                "fix": fix, "severity": "info",
                "source": "check:reg.orphan_device"}

    def test_the_rule_written_fix_follows_the_rule(self):
        findings_store.add_many([self._row("run brain.delete_orphaned_devices")])
        findings_store.refresh_details([self._row("Remove them in Settings.")])
        self.assertEqual(findings_store.list_all()[0]["fix"],
                         "Remove them in Settings.")

    def test_a_fix_somebody_else_wrote_is_kept(self):
        findings_store.add_many([self._row("the rule's sentence")])
        items = findings_store._load()
        items[0]["fix"], items[0]["fix_by"] = "the look's sentence", "resident"
        findings_store._write(items)
        findings_store.refresh_details([self._row("Remove them in Settings.")])
        self.assertEqual(findings_store.list_all()[0]["fix"],
                         "the look's sentence")


if __name__ == "__main__":
    unittest.main()
