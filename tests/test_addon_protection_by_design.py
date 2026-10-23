#!/usr/bin/env python3
"""`sec.addon_unprotected`: an add-on that needs Protection mode off by
design is not a problem, and an answer about one add-on is about that one.

Report 377: the check filed ONE row for every unprotected add-on, under
the text "Some add-ons run with Protection mode switched off", and on the
reporting house the add-on it named was BRUH Task Manager — whose process
view needs `host_pid`, which the Supervisor grants only with Protection
mode off, and whose own panel says so before the owner turns it off. And
because the row was one text for all add-ons, a Wrong about it settled
that text and would have hidden a DIFFERENT add-on turned unprotected
later, while the detail naming it was rewritten every pass.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
import findings_store  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

CHECK = "sec.addon_unprotected"


def fire(rows: list[dict]) -> list[dict]:
    snap = house()
    snap["supervisor"] = {**snap["supervisor"], "addons": rows}
    result = checks.run_all(snap, NOW, only=[CHECK])
    return [f for f in result["findings"] if f["source"] == f"check:{CHECK}"]


TASK_MANAGER = {"slug": "a0d7b954_bruh-task-manager",
                "name": "BRUH Task Manager", "installed": True,
                "protected": False, "host_pid": True}
PORTAINER = {"slug": "a0d7b954_portainer", "name": "Portainer",
             "installed": True, "protected": False}
FTP = {"slug": "core_ftp", "name": "FTP", "installed": True,
       "protected": False}


class TestOffOnPurposeIsNotAProblem(unittest.TestCase):
    def test_task_manager_with_protection_off_files_nothing(self):
        self.assertEqual(fire([TASK_MANAGER]), [])

    def test_whatever_repository_it_was_installed_from(self):
        """The hash in front of the slug differs per install; a local
        build is `local_`, and a row whose /info did not carry host_pid is
        still the add-on as it ships."""
        for slug in ("local_bruh-task-manager", "5c53de3b_bruh-task-manager",
                     "bruh-task-manager"):
            row = {**TASK_MANAGER, "slug": slug}
            row.pop("host_pid")
            self.assertEqual(fire([row]), [], slug)

    def test_another_add_on_beside_it_still_files(self):
        found = fire([TASK_MANAGER, PORTAINER])
        self.assertEqual(len(found), 1)
        self.assertIn("Portainer", found[0]["text"])
        self.assertNotIn("Task Manager", found[0]["text"] + found[0]["detail"])

    def test_a_stranger_sharing_the_slug_tail_is_not_excused(self):
        """Ours by the slug's tail AND the name — a stranger's add-on that
        happens to end in the same slug is not."""
        found = fire([{**TASK_MANAGER, "name": "Something Else"}])
        self.assertEqual(len(found), 1)

    def test_a_manifest_without_the_need_is_not_excused(self):
        found = fire([{**TASK_MANAGER, "host_pid": False}])
        self.assertEqual(len(found), 1)
        self.assertIn("BRUH Task Manager", found[0]["text"])


class TestOneAnswerIsAboutOneAddOn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = Path(self.tmp.name) / "findings.json"
        findings_store.INBOX_DIR = Path(self.tmp.name) / "inbox"
        findings_store.SETTLED_FILE = Path(self.tmp.name) / "settled.json"
        findings_store.STATE_FILE = (
            Path(self.tmp.name) / "config" / ".brain" / "findings_state.json")

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def test_each_add_on_is_its_own_row_with_a_stable_text(self):
        first = fire([PORTAINER, FTP])
        self.assertEqual(len(first), 2)
        self.assertEqual(len({f["text"] for f in first}), 2)
        # The text does not move with the rest of the house.
        again = fire([PORTAINER])
        self.assertIn(again[0]["text"], {f["text"] for f in first})

    def test_a_wrong_about_one_does_not_hide_another_later(self):
        created = findings_store.add_many(fire([PORTAINER]))
        self.assertEqual(len(created), 1)
        findings_store.settle_and_clear(created[0]["ts"], "ignored",
                                        "I run Portainer unprotected on purpose")
        # The same add-on again: settled, nothing new.
        self.assertEqual(findings_store.add_many(fire([PORTAINER])), [])
        # A different add-on switched off later is news.
        later = findings_store.add_many(fire([PORTAINER, FTP]))
        self.assertEqual(len(later), 1)
        self.assertIn("FTP", later[0]["text"])


if __name__ == "__main__":
    unittest.main()
