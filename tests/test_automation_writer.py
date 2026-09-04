"""Accepting a proposal writes an automation, and `brain undo` reverts it.

This is the first thing in the add-on that changes `/config` without a
Claude run and without somebody pressing Fix it, so every test here is
about a guard rather than about the happy path. Real files in a real
temporary directory posing as `/config`, and a real edit journal, because
the whole claim is about bytes on disk.

Each test names the mutation it catches:

  the user's file is untouched   re-serialise the list instead of appending
                                 -> the prefix of the file changes and
                                 somebody's comments and quoting are gone
  snapshot BEFORE the write      move `snapshot()` after `write_text` ->
                                 undo restores the change it was undoing
  the include line               drop the check -> brAIn appends to a file
                                 Core does not read and nothing happens
  a protected entity             drop the check -> the one option that is
                                 supposed to hold everywhere holds in the
                                 MCP server and not here
  an area target                 resolve it / allow it -> a protected
                                 entity is reached through its area
  a duplicate id or alias        drop either -> a config Core refuses to
                                 load, or two rules nobody can tell apart
  a list of maps                 accept anything -> a packages install has
                                 an automation appended to a mapping
  revert is byte-for-byte        rewrite from the parsed YAML -> the undo
                                 leaves a file the person did not write
  the journal line               change a field name -> `brain undo` reads
                                 the index and finds nothing to restore
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

# What a person's automations.yaml looks like: their ordering, their
# comments, their quoting. Every one of those has to survive an append.
EXISTING = '''\
# My automations. Do not reformat.
- id: '1699999999999'
  alias: Porch light at dusk
  description: ""
  trigger:
    - platform: sun
      event: sunset
  condition: []
  action:
    - service: light.turn_on
      target:
        entity_id: light.porch
  mode: single
'''

INCLUDE = "automation: !include automations.yaml\n"


def proposal(entity: str = "light.hall", ts: int = 1_700_000_000_123,
             title: str = "Turn the hall lamp on at 18:40 on weekdays",
             service: str = "light.turn_on") -> dict:
    return {
        "ts": ts,
        "key": "abc123",
        "kind": "automation",
        "title": title,
        "why": "You have done this yourself on 9 of the last 10 weekdays",
        "source": "routine",
        "status": "proposed",
        "config": {
            "trigger": [{"platform": "time", "at": "18:40:00"}],
            "condition": [{"condition": "time",
                           "weekday": ["mon", "tue", "wed", "thu", "fri"]}],
            "action": [{"service": service,
                        "target": {"entity_id": entity}}],
            "mode": "single",
        },
    }


class WriterCase(unittest.TestCase):
    """Each test gets its own /config and its own edit journal."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = root / "config"
        self.config.mkdir()
        self.journal = root / "edits"
        self._env = dict(os.environ)
        os.environ["BRAIN_EDIT_JOURNAL"] = str(self.journal)
        os.environ["BRAIN_CONFIG_DIR"] = str(self.config)
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        self.addCleanup(self._restore_env)
        sys.modules.pop("automation_writer", None)
        self.w = importlib.import_module("automation_writer")

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._env)
        sys.modules.pop("automation_writer", None)

    # -- fixtures ---------------------------------------------------------
    def house(self, automations: str | None = EXISTING,
              configuration: str = INCLUDE) -> None:
        (self.config / "configuration.yaml").write_text(configuration,
                                                        encoding="utf-8")
        if automations is not None:
            (self.config / "automations.yaml").write_text(automations,
                                                          encoding="utf-8")

    def apply(self, row=None, **kw):
        return self.w.apply(row or proposal(), config_dir=str(self.config),
                            **kw)

    def yaml_rows(self):
        import yaml
        return yaml.safe_load(
            (self.config / "automations.yaml").read_text(encoding="utf-8"))

    def index_lines(self):
        return [json.loads(line) for line in
                (self.journal / "index.jsonl").read_text().splitlines()
                if line.strip()]


class TestTheHappyPath(WriterCase):

    def test_it_appends_one_automation_and_says_what_it_wrote(self):
        self.house()
        out = self.apply()
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(out["automation_id"], "brain_1700000000123")
        self.assertEqual(out["entity_id"],
                         "automation.turn_the_hall_lamp_on_at_18_40_on_weekdays")
        rows = self.yaml_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["id"], "brain_1700000000123")
        self.assertEqual(rows[1]["alias"], proposal()["title"])
        self.assertIn("Proposed by brAIn", rows[1]["description"])
        self.assertEqual(rows[1]["action"],
                         proposal()["config"]["action"])
        self.assertEqual(rows[1]["mode"], "single")

    def test_the_user_s_existing_file_is_byte_identical_above_the_block(self):
        """Not "it still parses" — the prefix is unchanged, comments and
        quoting included. A writer that re-serialised the list would pass
        a parse test and hand back a diff nobody asked for."""
        self.house()
        self.apply()
        after = (self.config / "automations.yaml").read_text(encoding="utf-8")
        self.assertTrue(after.startswith(EXISTING),
                        "the file above the appended block changed:\n"
                        + after[:len(EXISTING) + 40])

    def test_a_file_with_no_trailing_newline_does_not_glue_the_block_on(self):
        self.house(EXISTING.rstrip("\n"))
        self.assertTrue(self.apply()["ok"])
        self.assertEqual(len(self.yaml_rows()), 2)

    def test_a_missing_automations_yaml_is_created_because_HA_creates_one(self):
        self.house(automations=None)
        self.assertTrue(self.apply()["ok"])
        self.assertEqual(len(self.yaml_rows()), 1)

    def test_an_empty_automations_yaml_is_a_list_of_none(self):
        self.house("")
        self.assertTrue(self.apply()["ok"])
        self.assertEqual(len(self.yaml_rows()), 1)

    def test_nothing_here_talks_to_the_network(self):
        source = (BASE_DIR / "brain" / "panel"
                  / "automation_writer.py").read_text()
        for forbidden in ("aiohttp", "requests", "http://", "urllib"):
            self.assertNotIn(forbidden, source, forbidden)


class TestTheSnapshotComesFirst(WriterCase):

    def test_the_snapshot_holds_the_file_as_it_was_before_the_write(self):
        """The whole of undo. A snapshot taken after the write records the
        change rather than what it replaced."""
        self.house()
        out = self.apply()
        saved = (self.journal / "snapshots" / out["snapshot"]).read_text()
        self.assertEqual(saved, EXISTING)
        self.assertNotEqual(
            saved, (self.config / "automations.yaml").read_text())

    def test_the_journal_line_is_one_brain_undo_can_read(self):
        self.house()
        out = self.apply()
        lines = self.index_lines()
        self.assertEqual(len(lines), 1)
        entry = lines[0]
        self.assertEqual(set(entry),
                         {"ts", "path", "tool", "snapshot", "existed"})
        self.assertEqual(entry["path"],
                         str(self.config / "automations.yaml"))
        self.assertEqual(entry["tool"], "brain-panel")
        self.assertTrue(entry["existed"])
        self.assertIsInstance(entry["ts"], float)
        self.assertEqual(entry["snapshot"], out["snapshot"])

    def test_the_snapshot_name_is_the_hook_s_own_shape(self):
        """`<int ts>-<sha256(path)[:10]>-<name>`, so both halves of the
        journal are named the same way and a reader cannot tell them
        apart — which is the point."""
        import hashlib
        self.house()
        out = self.apply()
        path = str(self.config / "automations.yaml")
        digest = hashlib.sha256(path.encode()).hexdigest()[:10]
        stamp, got_digest, name = out["snapshot"].split("-", 2)
        self.assertEqual((got_digest, name), (digest, "automations.yaml"))
        self.assertEqual(int(stamp), int(out["journal_ts"]))

    def test_a_file_that_did_not_exist_is_journalled_as_such(self):
        self.house(automations=None)
        out = self.apply()
        self.assertFalse(out["existed"])
        self.assertEqual(out["snapshot"], "")
        self.assertFalse(self.index_lines()[0]["existed"])

    def test_nothing_is_written_when_the_snapshot_cannot_be(self):
        """A change brAIn could not record is a change it cannot take
        back, so it is not made. (The journal directory is a *file* here
        rather than a chmod, because a suite running as root — which the
        add-on's own container does — cannot be stopped by a mode.)"""
        self.house()
        self.journal.write_text("not a directory", encoding="utf-8")
        out = self.apply()
        self.assertFalse(out["ok"])
        self.assertIn("snapshot", out["error"])
        self.assertEqual(
            (self.config / "automations.yaml").read_text(), EXISTING)


class TestTheRefusals(WriterCase):

    def test_no_include_line_is_refused_naming_the_line_looked_for(self):
        self.house(configuration="default_config:\n")
        out = self.apply()
        self.assertFalse(out["ok"])
        self.assertIn("automation: !include automations.yaml", out["error"])
        self.assertFalse((self.config / "automations.yaml")
                         .read_text().endswith("brain_1700000000123\n"))

    def test_a_packages_install_is_refused_rather_than_guessed_at(self):
        self.house(configuration="homeassistant:\n  packages: !include_dir_named pkg\n")
        self.assertFalse(self.apply()["ok"])

    def test_the_include_line_is_read_however_it_is_spaced_or_quoted(self):
        for line in ("automation: !include automations.yaml",
                     "  automation:   !include   'automations.yaml'  ",
                     'automation: !include "automations.yaml"'):
            self.assertTrue(self.w.INCLUDE_RE.search(line + "\n"), line)
        for line in ("automation manual: !include automations.yaml",
                     "automation: !include_dir_merge_list automations/",
                     "# automation: !include automations.yaml"):
            self.assertIsNone(self.w.INCLUDE_RE.search(line + "\n"), line)

    def test_a_protected_entity_is_refused_here_because_the_MCP_cannot_see_it(self):
        self.house()
        out = self.apply(protected=["light.hall"])
        self.assertFalse(out["ok"])
        self.assertIn("light.hall", out["error"])
        self.assertEqual(
            (self.config / "automations.yaml").read_text(), EXISTING)

    def test_the_option_is_read_from_the_environment_the_MCP_reads(self):
        self.house()
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "lock.front, light.hall"
        self.assertFalse(self.apply()["ok"])

    def test_a_domain_wildcard_protects_the_whole_domain(self):
        self.house()
        self.assertFalse(self.apply(protected=["light.*"])["ok"])
        self.assertTrue(self.apply(
            row=proposal(entity="switch.fan", service="switch.turn_on",
                         title="Fan on at 18:40"),
            protected=["light.*"])["ok"])

    def test_an_unprotected_entity_is_written_with_a_list_set(self):
        """The neighbouring fixture: same list, a different entity."""
        self.house()
        self.assertTrue(self.apply(protected=["lock.front"])["ok"])

    def test_an_area_target_is_refused_while_the_list_is_non_empty(self):
        """It cannot be expanded without the registries, and a protected
        entity reached through its area is the bypass."""
        self.house()
        row = proposal()
        row["config"]["action"] = [{"service": "light.turn_on",
                                    "target": {"area_id": "hall"}}]
        self.assertFalse(self.apply(row=row, protected=["light.hall"])["ok"])
        # With no protected entities there is nothing to bypass.
        self.assertTrue(self.apply(row=row)["ok"])

    def test_a_duplicate_id_is_refused(self):
        self.house()
        self.assertTrue(self.apply()["ok"])
        out = self.apply()
        self.assertFalse(out["ok"])
        self.assertIn("accepted before", out["error"])
        self.assertEqual(len(self.yaml_rows()), 2)

    def test_a_duplicate_alias_is_refused_even_under_a_new_id(self):
        self.house()
        self.assertTrue(self.apply()["ok"])
        out = self.apply(row=proposal(ts=1_700_000_999_000))
        self.assertFalse(out["ok"])
        self.assertIn("same", out["error"])
        self.assertEqual(len(self.yaml_rows()), 2)

    def test_an_automations_file_that_is_not_a_list_of_maps_is_refused(self):
        self.house("kitchen:\n  alias: not a list\n")
        out = self.apply()
        self.assertFalse(out["ok"])
        self.assertIn("not a list", out["error"])

    def test_a_list_of_something_that_is_not_an_automation_is_refused(self):
        self.house("- one\n- two\n")
        self.assertFalse(self.apply()["ok"])

    def test_an_unparseable_automations_file_is_refused_not_overwritten(self):
        broken = "- id: '1'\n   alias: bad indent\n  x\n"
        self.house(broken)
        out = self.apply()
        self.assertFalse(out["ok"])
        self.assertEqual(
            (self.config / "automations.yaml").read_text(), broken)

    def test_a_proposal_with_no_trigger_or_no_action_is_refused(self):
        self.house()
        for key in ("trigger", "action"):
            row = proposal()
            row["config"].pop(key)
            out = self.apply(row=row)
            self.assertFalse(out["ok"], key)
            self.assertIn("trigger and an action", out["error"])

    def test_a_proposal_with_no_config_is_refused(self):
        self.house()
        row = proposal()
        row["config"] = None
        self.assertFalse(self.apply(row=row)["ok"])

    def test_a_refusal_never_raises(self):
        """A person is waiting on a press; a traceback is not an answer."""
        self.house(configuration="")
        out = self.apply()
        self.assertIs(out["ok"], False)
        self.assertIsInstance(out["error"], str)


class TestRevert(WriterCase):

    def test_it_restores_the_file_byte_for_byte(self):
        self.house()
        before = (self.config / "automations.yaml").read_text()
        out = self.apply()
        entry = self.index_lines()[0]
        back = self.w.revert(entry, config_dir=str(self.config))
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual(
            (self.config / "automations.yaml").read_text(), before)
        self.assertEqual(before, EXISTING)
        self.assertNotEqual(out["snapshot"], "")

    def test_reverting_a_file_that_did_not_exist_removes_it(self):
        self.house(automations=None)
        self.assertTrue(self.apply()["ok"])
        self.assertTrue((self.config / "automations.yaml").exists())
        back = self.w.revert(self.index_lines()[0],
                             config_dir=str(self.config))
        self.assertTrue(back["ok"])
        self.assertTrue(back["removed"])
        self.assertFalse((self.config / "automations.yaml").exists())

    def test_a_lost_snapshot_is_reported_rather_than_faked(self):
        self.house()
        self.apply()
        entry = self.index_lines()[0]
        (self.journal / "snapshots" / entry["snapshot"]).unlink()
        back = self.w.revert(entry, config_dir=str(self.config))
        self.assertFalse(back["ok"])
        self.assertIn("last block", back["error"])

    def test_it_will_not_write_outside_the_config_folder_it_was_given(self):
        self.house()
        self.apply()
        entry = self.index_lines()[0]
        back = self.w.revert(entry, config_dir=str(self.config / "nope"))
        self.assertFalse(back["ok"])

    def test_an_empty_entry_is_refused(self):
        self.assertFalse(self.w.revert({}, config_dir=str(self.config))["ok"])


class TestBrainUndoCanReadIt(WriterCase):
    """The real shell script, driven against the real journal line.

    The whole reason `apply` writes into the PreToolUse hook's journal
    rather than inventing an undo of its own is that `brain undo` already
    exists — and a wire format written down twice with only one side
    tested is a format that drifts. So this runs `brain-undo.sh` rather
    than asserting a shape it might not read.
    """

    SCRIPT = BASE_DIR / "brain" / "scripts" / "brain-undo.sh"

    def undo(self, *args):
        import subprocess
        env = dict(os.environ, BRAIN_EDIT_JOURNAL=str(self.journal))
        return subprocess.run(["bash", str(self.SCRIPT), *args],
                              capture_output=True, text=True, env=env,
                              check=False)

    def setUp(self):
        super().setUp()
        import shutil
        if shutil.which("jq") is None:      # pragma: no cover
            self.skipTest("brain undo needs jq, which this box has not got")

    def test_the_edit_shows_up_in_the_list_as_a_modified_file(self):
        self.house()
        self.apply()
        out = self.undo()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("automations.yaml", out.stdout)
        self.assertIn("modified", out.stdout)

    def test_brain_undo_1_puts_the_file_back(self):
        self.house()
        self.apply()
        out = self.undo("1")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Restored", out.stdout)
        self.assertEqual(
            (self.config / "automations.yaml").read_text(), EXISTING)

    def test_a_created_file_is_removed_by_the_same_command(self):
        self.house(automations=None)
        self.apply()
        out = self.undo("1")
        self.assertIn("Removed", out.stdout)
        self.assertFalse((self.config / "automations.yaml").exists())


class TestTheOneWriter(unittest.TestCase):

    def test_nothing_else_under_panel_writes_automations_yaml(self):
        """A second writer is a second set of guards to keep true — and
        the one that skipped the snapshot would be invisible until an undo
        somebody needed did not work."""
        offenders = []
        panel = BASE_DIR / "brain" / "panel"
        for path in sorted(panel.rglob("*.py")):
            if path.name == "automation_writer.py":
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.split("\n"), 1):
                if "automations.yaml" not in line:
                    continue
                if any(w in line for w in ("write", "dump", "append",
                                           "atomic_write", "open(")):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [],
                         "automation_writer.py is the only writer:\n"
                         + "\n".join(offenders))

    def test_the_image_ships_the_yaml_this_depends_on(self):
        """Asserted separately from the test requirements: the tests run
        where pip installed pyyaml and the add-on runs where apk did.
        `shadow.py`'s jinja2 is the same lesson."""
        dockerfile = (BASE_DIR / "brain" / "Dockerfile").read_text()
        self.assertIn("py3-yaml", dockerfile)
        reqs = (BASE_DIR / "tests" / "requirements-dev.txt").read_text()
        self.assertIn("pyyaml", reqs)


if __name__ == "__main__":
    unittest.main()
