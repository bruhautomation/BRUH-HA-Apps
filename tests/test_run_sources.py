#!/usr/bin/env python3
"""The run-source ledger: who started a conversation.

Claude Code files every conversation under its working directory and
records nothing about which of us asked for it. brAIn drives the same CLI
from /config for voice, automations, study sessions and memory
consolidation, so without this the Chats rail was a person's own chats
buried under machine ones — and "switch back from the terminal" adopted
whichever machine had run last.

The contract under test is deliberately narrow: a background caller claims
its own session id *before* the run, and an id nobody claimed is yours.
That is what keeps the default free of inference — no prompt-text matching
to break the day a prompt is reworded.

Both halves are tested against each other. The shell library is what the
listeners and the consolidator actually use, so a Python-only test would
let the two drift into writing files the other can't read.
"""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
SHELL_LIB = BASE_DIR / "brain" / "scripts" / "brain-run-source.sh"

sys.path.insert(0, str(PANEL))


class RunSourcesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "run-sources.jsonl"
        os.environ["BRAIN_RUN_SOURCES"] = str(self.ledger)
        import run_sources
        self.mod = importlib.reload(run_sources)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_claim_round_trips(self):
        self.assertTrue(self.mod.record("abc", "memory"))
        self.assertEqual(self.mod.lookup(["abc"]), {"abc": "memory"})

    def test_an_id_nobody_claimed_is_simply_absent(self):
        """Which is what makes "yours" the default rather than a guess."""
        self.mod.record("abc", "memory")
        self.assertEqual(self.mod.lookup(["nobody-claimed-this"]), {})

    def test_a_source_we_do_not_know_is_refused(self):
        """Written and then silently ignored on the way out would be a row
        the rail can neither label nor filter."""
        self.assertFalse(self.mod.record("abc", "wat"))
        self.assertEqual(self.mod.lookup(["abc"]), {})

    def test_an_id_that_is_not_an_id_is_refused(self):
        for bad in ("", "../../etc/passwd", "a b", "x" * 200):
            self.assertFalse(self.mod.record(bad, "voice"), bad)

    def test_a_resumed_session_keeps_its_latest_claim(self):
        self.mod.record("abc", "voice")
        self.mod.record("abc", "study")
        self.assertEqual(self.mod.lookup(["abc"]), {"abc": "study"})

    def test_a_missing_ledger_is_empty_not_an_error(self):
        self.assertEqual(self.mod.lookup(["abc"]), {})

    def test_a_corrupt_line_does_not_take_the_rest_with_it(self):
        self.mod.record("good-one", "voice")
        with self.ledger.open("a", encoding="utf-8") as fh:
            fh.write("{not json\n\n")
        self.mod.record("other-one", "memory")
        self.assertEqual(self.mod.lookup(["good-one", "other-one"]),
                         {"good-one": "voice", "other-one": "memory"})

    def test_an_unwritable_ledger_never_raises(self):
        """This is bookkeeping about a run. It must never be the reason the
        run doesn't happen."""
        self.mod.LEDGER = Path("/proc/nope/run-sources.jsonl")
        self.assertFalse(self.mod.record("abc", "voice"))
        self.assertEqual(self.mod.lookup(["abc"]), {})

    def test_the_ledger_is_capped_newest_first(self):
        """An index, not a queue: it is capped rather than drained, because
        a session whose transcript the CLI pruned has nothing left to
        label."""
        self.mod.MAX_ENTRIES = 20
        self.mod.PRUNE_SLACK = 5
        for n in range(60):
            self.mod.record(f"s{n}", "voice")
        entries = [json.loads(line)
                   for line in self.ledger.read_text().splitlines() if line]
        self.assertLessEqual(len(entries), 25)
        self.assertEqual(entries[-1]["id"], "s59")
        # the newest are what survive
        self.assertEqual(self.mod.lookup(["s59"]), {"s59": "voice"})


class ShellHalfCase(unittest.TestCase):
    """The library the listeners and the consolidator actually source.

    Tested against the Python reader rather than against itself: the two
    halves only work if they agree on the file, and nothing else would
    catch them drifting apart.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "run-sources.jsonl"
        os.environ["BRAIN_RUN_SOURCES"] = str(self.ledger)
        import run_sources
        self.mod = importlib.reload(run_sources)

    def tearDown(self):
        self.tmp.cleanup()

    def _sh(self, body):
        return subprocess.run(
            ["bash", "-c", f'set -u\nBRAIN_RUN_SOURCES="{self.ledger}"\n'
                           f'source "{SHELL_LIB}"\n{body}'],
            capture_output=True, text=True, check=False)

    def test_a_minted_id_is_a_uuid_the_panel_can_read_back(self):
        out = self._sh('brain_new_session memory')
        self.assertEqual(out.returncode, 0, out.stderr)
        session_id = out.stdout.strip()
        self.assertRegex(session_id, r"^[0-9a-f-]{36}$")
        self.assertEqual(self.mod.lookup([session_id]), {session_id: "memory"})

    def test_claiming_an_id_we_already_have_works(self):
        """Voice mints its own ids — that is how a follow-up turn resumes
        the same conversation — so it claims rather than mints."""
        out = self._sh('brain_claim_session "known-id" voice')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.mod.lookup(["known-id"]), {"known-id": "voice"})

    def test_an_unknown_source_writes_nothing(self):
        self._sh('brain_claim_session "abc" nonsense')
        self.assertEqual(self.mod.lookup(["abc"]), {})

    def test_both_halves_agree_on_the_known_sources(self):
        """A source Python knows and bash refuses is a caller that silently
        stops labelling itself."""
        for source in self.mod.SOURCES:
            self._sh(f'brain_claim_session "id-{source}" {source}')
            self.assertEqual(self.mod.lookup([f"id-{source}"]),
                             {f"id-{source}": source}, source)

    def test_a_failure_is_silent_and_never_fails_the_caller(self):
        out = subprocess.run(
            ["bash", "-c",
             f'set -eu\nBRAIN_RUN_SOURCES="/proc/nope/x.jsonl"\n'
             f'source "{SHELL_LIB}"\nbrain_claim_session abc voice\necho survived'],
            capture_output=True, text=True, check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("survived", out.stdout)


class ListingCase(unittest.TestCase):
    """What the rail ends up rendering."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name
        os.environ["BRAIN_RUN_SOURCES"] = str(
            Path(self.tmp.name) / "run-sources.jsonl")
        import run_sources
        self.sources = importlib.reload(run_sources)
        import conversations
        self.mod = importlib.reload(conversations)
        self.cwd = "/config"
        self.project = Path(self.tmp.name) / "projects" / "-config"
        self.project.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, session_id, text, age_s=0):
        path = self.project / f"{session_id}.jsonl"
        path.write_text(json.dumps({
            "type": "user", "cwd": self.cwd,
            "message": {"role": "user", "content": text}}) + "\n" + "x" * 300)
        if age_s:
            when = time.time() - age_s
            os.utime(path, (when, when))

    def test_every_row_carries_a_source(self):
        self._write("mine", "why is the porch light on")
        self._write("theirs", "You maintain a small long-term memory file")
        self.sources.record("theirs", "memory")
        rows = {r["id"]: r["source"] for r in self.mod.listing(self.cwd)}
        self.assertEqual(rows, {"mine": "you", "theirs": "memory"})

    def test_filtering_happens_before_the_limit(self):
        """Otherwise a page of 30 spent on voice turns hands back four of
        yours and calls it a listing."""
        for n in range(50):
            self._write(f"v{n}", f"voice {n}", age_s=n)
            self.sources.record(f"v{n}", "voice")
        self._write("mine", "the one I actually had", age_s=9999)
        rows = self.mod.listing(self.cwd, limit=30, sources=("you",))
        self.assertEqual([r["id"] for r in rows], ["mine"])

    def test_a_filtered_listing_stays_bounded(self):
        """The guard that stops a directory of ten thousand voice sessions
        turning one listing into ten thousand title reads."""
        self.mod.MAX_FILTER_SCAN = 10
        for n in range(40):
            self._write(f"v{n}", f"voice {n}", age_s=n)
            self.sources.record(f"v{n}", "voice")
        self.assertEqual(self.mod.listing(self.cwd, sources=("you",)), [])

    def test_counting_sources_does_not_read_every_transcript(self):
        """A count needs the id and nothing else. listing() reads up to 400
        lines of every transcript looking for a title, and paying that to
        draw a number on a chip is how a filter row becomes the most
        expensive thing on the tab."""
        for n in range(5):
            self._write(f"v{n}", "voice turn", age_s=n)
            self.sources.record(f"v{n}", "voice")
        self._write("mine", "mine", age_s=99)
        # Opened and never used: not something you can resume, so not
        # something to count either.
        (self.project / "stub.jsonl").write_text("{}\n")

        reads = []
        original = self.mod.title_of
        self.mod.title_of = lambda path: reads.append(path) or original(path)
        try:
            counts = self.mod.source_counts(self.cwd)
        finally:
            self.mod.title_of = original
        self.assertEqual(counts, {"voice": 5, "you": 1})
        self.assertEqual(reads, [])

    def test_an_unfiltered_listing_is_unchanged(self):
        self._write("a", "one")
        self._write("b", "two")
        self.assertEqual(len(self.mod.listing(self.cwd)), 2)


if __name__ == "__main__":
    unittest.main()
