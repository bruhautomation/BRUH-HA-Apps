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
from checks import _util  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

registry = checks.registry
devices = checks.devices

# An entity id, restricted to the domains Home Assistant has, so "3.5",
# "e.g." and "automations.yaml" are not ids.
DOMAINS = _util._CORE_DOMAINS
ID_RE = re.compile(r"(?<![\w.])([a-z_]+)\.([a-z0-9_]+)(?![\w])")
MAC_RE = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)
SERVICE_RE = re.compile(r"\bbrain\.[a-z_]+")

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
