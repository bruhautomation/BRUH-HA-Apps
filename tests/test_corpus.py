#!/usr/bin/env python3
"""The corpus, and the half of the replay that costs nothing.

Two jobs.

**Every entry is valid.** `tests/corpus/schema.json` is the document a
contributor and a reviewer read, and nothing in this repository validates
against it with a JSON Schema library — `jsonschema` is not in
`tests/requirements-dev.txt`, and taking a dependency so that two files
agree about a shape is a poor trade. So the validator here is structural
and small, and a test asserts that what it requires and what the schema
document says are the *same* lists: a schema nothing enforces is a comment,
and a validator that has drifted from the published schema is worse than
either.

**Every `checks` entry scores exactly as it is labelled.** This is the test
that fails when a floor moves. A check gaining a condition goes quiet on a
house that used to prove it; a check losing one starts firing on the clean
fixture, whose whole label is *nothing fires here*. Either way this names
the house, which is the thing a unit test on a hand-built dict cannot do
— the corpus houses are frozen and their expectations are arithmetic.

It runs in ordinary CI because it asks no model. The other half of the
replay does, and lives behind a nightly workflow and a token budget.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CORPUS = BASE_DIR / "tests" / "corpus"
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(CORPUS))

import capture  # noqa: E402
import replay  # noqa: E402
import score as scorer  # noqa: E402
import scoring  # noqa: E402

# What the structural validator requires. Asserted against schema.json's
# own `required` lists below, so the two cannot drift.
REQUIRED = ("schema", "kind", "id", "captured_at", "labels")
KINDS = ("checks", "analyst")
VERBS = ("done", "wrong", "got_it")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,127}")
CHECK_RE = re.compile(r"[a-z]+\.[a-z_]+")


def validate(entry: dict) -> list[str]:
    """Every reason this is not a corpus entry. Empty means it is one."""
    bad: list[str] = []
    if not isinstance(entry, dict):
        return ["an entry is a JSON object"]
    for key in REQUIRED:
        if key not in entry:
            bad.append(f"missing {key}")
    if entry.get("schema") != capture.SCHEMA:
        bad.append(f"schema must be {capture.SCHEMA}")
    kind = entry.get("kind")
    if kind not in KINDS:
        bad.append(f"kind must be one of {', '.join(KINDS)}")
    if not isinstance(entry.get("id"), str) \
            or not ID_RE.fullmatch(entry.get("id") or ""):
        bad.append("id must be a filename-safe string")
    if not isinstance(entry.get("captured_at"), int):
        bad.append("captured_at must be epoch seconds")
    labels = entry.get("labels")
    if not isinstance(labels, list):
        bad.append("labels must be a list")
        labels = []

    if kind == "checks":
        snap = entry.get("snapshot")
        if not isinstance(snap, dict):
            bad.append("a checks entry carries a snapshot")
        else:
            if not isinstance(snap.get("now"), (int, float)):
                bad.append("the snapshot needs a `now` — every timestamp in "
                           "it is relative to that, and grading against the "
                           "wall clock would score the same entry "
                           "differently every day")
            if not isinstance(snap.get("available"), dict):
                bad.append("the snapshot needs `available`, or a check that "
                           "could not look reads as one that found nothing")
        for i, label in enumerate(labels):
            if not isinstance(label, dict):
                bad.append(f"label {i} is not an object")
                continue
            if not CHECK_RE.fullmatch(str(label.get("check") or "")):
                bad.append(f"label {i}: `check` must be a check id")
    elif kind == "analyst":
        if not isinstance(entry.get("bundle"), dict):
            bad.append("an analyst entry carries the bundle it was sent")
        if not labels:
            bad.append("an analyst entry with no labels cannot be scored — "
                       "the endings ARE the ground truth")
        for i, label in enumerate(labels):
            if not isinstance(label, dict):
                bad.append(f"label {i} is not an object")
                continue
            if not str(label.get("finding_key") or "").strip():
                bad.append(f"label {i}: needs the finding key it answers")
            if label.get("verb") not in VERBS:
                bad.append(f"label {i}: verb must be one of "
                           f"{', '.join(VERBS)}")
    return bad


class TestTheValidatorMatchesThePublishedSchema(unittest.TestCase):
    """A schema nothing enforces is a comment; a validator that has drifted
    from the schema is worse, because both look right on their own."""

    def setUp(self):
        self.schema = json.loads(
            (CORPUS / "schema.json").read_text(encoding="utf-8"))

    def test_the_top_level_required_keys_are_the_same_list(self):
        self.assertEqual(sorted(self.schema["required"]), sorted(REQUIRED))

    def test_the_two_kinds_are_the_same_two(self):
        self.assertEqual(sorted(self.schema["properties"]["kind"]["enum"]),
                         sorted(KINDS))
        # And capture's own list, because a capture file IS an analyst
        # entry with its labels filled in later.
        self.assertEqual(sorted(capture.KINDS), sorted(KINDS))

    def test_the_ending_words_are_the_same_three(self):
        analyst = self.schema["properties"]["labels"]["items"]["oneOf"][1]
        self.assertEqual(sorted(analyst["properties"]["verb"]["enum"]),
                         sorted(VERBS))
        # And the panel's verbs, which are what write them.
        import server
        labels = {spec["label"] for spec in server.FINDING_VERBS.values()
                  if spec.get("label")}
        self.assertEqual(sorted(labels), sorted(VERBS))

    def test_the_schema_version_is_the_one_capture_writes(self):
        self.assertEqual(self.schema["properties"]["schema"]["const"],
                         capture.SCHEMA)

    def test_the_schema_says_out_loud_that_nothing_validates_against_it(self):
        """Because it does not, and a schema people believe is enforced is
        worse than one they know is a document."""
        self.assertIn("NOTHING IN THIS REPOSITORY VALIDATES IT",
                      self.schema["$comment"])


class TestTheValidatorRefusesWhatItShould(unittest.TestCase):
    """Driven against mutations, because a validator nothing has ever seen
    reject anything is a validator that returns [] for everything."""

    GOOD_CHECKS = {
        "schema": capture.SCHEMA, "kind": "checks", "id": "x", "labels": [],
        "captured_at": 1_800_000_000,
        "snapshot": {"now": 1_800_000_000.0, "available": {"states": True}},
    }
    GOOD_ANALYST = {
        "schema": capture.SCHEMA, "kind": "analyst", "id": "y",
        "captured_at": 1_800_000_000, "bundle": {"domains": {}},
        "labels": [{"finding_key": "a dead battery", "verb": "done"}],
    }

    def test_the_good_ones_are_good(self):
        self.assertEqual(validate(self.GOOD_CHECKS), [])
        self.assertEqual(validate(self.GOOD_ANALYST), [])

    def test_a_checks_entry_with_no_now_is_refused(self):
        bad = {**self.GOOD_CHECKS,
               "snapshot": {"available": {"states": True}}}
        self.assertTrue(any("now" in why for why in validate(bad)))

    def test_a_checks_entry_with_no_available_map_is_refused(self):
        bad = {**self.GOOD_CHECKS, "snapshot": {"now": 1.0}}
        self.assertTrue(any("available" in why for why in validate(bad)))

    def test_an_analyst_entry_with_no_labels_is_refused(self):
        bad = {**self.GOOD_ANALYST, "labels": []}
        self.assertTrue(any("cannot be scored" in why for why in validate(bad)))

    def test_an_ending_word_nobody_writes_is_refused(self):
        bad = {**self.GOOD_ANALYST,
               "labels": [{"finding_key": "k", "verb": "maybe"}]}
        self.assertTrue(any("verb" in why for why in validate(bad)))

    def test_an_id_that_is_not_a_filename_is_refused(self):
        for bad_id in ("../escape", "a/b", "", "."):
            with self.subTest(bad_id):
                bad = {**self.GOOD_CHECKS, "id": bad_id}
                self.assertTrue(any("id" in why for why in validate(bad)))

    def test_a_label_naming_something_that_is_not_a_check_is_refused(self):
        bad = {**self.GOOD_CHECKS, "labels": [{"check": "Automations"}]}
        self.assertTrue(any("check id" in why for why in validate(bad)))


class TestEveryEntryIsValid(unittest.TestCase):
    def test_the_corpus_is_not_empty(self):
        """An empty corpus and a passing one look identical from a report."""
        self.assertTrue(replay.load_entries())

    def test_each_entry_validates(self):
        for entry in replay.load_entries():
            with self.subTest(entry.get("id")):
                self.assertEqual(validate(entry), [],
                                 f"{entry.get('_path')} is not a valid entry")

    def test_no_two_entries_share_an_id(self):
        ids = [e.get("id") for e in replay.load_entries()]
        self.assertEqual(sorted(ids), sorted(set(ids)))

    def test_every_label_names_a_check_that_exists(self):
        """A label for a check that has been renamed is a label that can
        never be found again, and it would read as the check failing."""
        import checks
        for entry in replay.load_entries():
            if entry.get("kind") != "checks":
                continue
            for label in entry["labels"]:
                with self.subTest(entry["id"], check=label["check"]):
                    self.assertIn(label["check"], checks.CHECK_IDS)


class TestTheDeterministicReplay(unittest.TestCase):
    """The test that fails when a floor moves.

    Every `checks` entry is replayed against the real `run_all` and scored
    against its labels — found, missed, and anything reported that no label
    accounts for. A perfect score is the pass; anything else names the
    house.
    """

    def test_every_checks_entry_scores_exactly_as_labelled(self):
        for entry in replay.load_entries():
            if entry.get("kind") != "checks":
                continue
            with self.subTest(entry["id"]):
                got = replay.replay_checks(entry)
                missed = [r["label"] for r in got["rows"]
                          if r["verdict"] == "missed"]
                self.assertEqual(
                    missed, [],
                    f"{entry['id']}: these labelled defects were NOT found — "
                    "a check has gone quiet on a house that used to prove it")
                self.assertEqual(
                    [f.get("text") for f in got["extra_rows"]], [],
                    f"{entry['id']}: these were reported and nothing labels "
                    "them — a check has started firing on a house that is "
                    "meant to be quiet about them")

    def test_the_clean_house_is_silent_and_that_is_its_whole_label(self):
        entry = next(e for e in replay.load_entries()
                     if e["id"] == "clean-house")
        self.assertEqual(entry["labels"], [])
        got = replay.replay_checks(entry)
        self.assertEqual(got["extra_rows"], [])
        # And nothing was skipped, or "silent" would mean "did not look".
        self.assertEqual(got["skipped"], {})
        self.assertEqual(got["errors"], {})

    def test_the_rehearsal_house_proves_the_checks_the_rehearsal_plants_for(self):
        """Ground truth by construction: the labels are `rehearsal.PLAN`,
        so this entry and `brain doctor --rehearse` cannot disagree about
        what a planted defect is."""
        import rehearsal
        entry = next(e for e in replay.load_entries()
                     if e["id"] == "rehearsal-house")
        planted = {row["check"] for row in rehearsal.PLAN if row.get("check")}
        self.assertEqual({label["check"] for label in entry["labels"]},
                         planted)
        got = replay.replay_checks(entry)
        self.assertEqual(got["found"], len(planted))
        self.assertEqual(got["precision"], 1.0)
        self.assertEqual(got["recall"], 1.0)

    def test_a_house_the_checks_could_not_read_is_reported_as_such(self):
        """"I could not look" and "there was nothing" are different claims
        everywhere else in this add-on, and a corpus that lost the
        distinction would score a broken snapshot as a quiet house."""
        entry = next(e for e in replay.load_entries()
                     if e["id"] == "rehearsal-house")
        blinded = json.loads(json.dumps(entry))
        blinded["snapshot"]["available"]["automations"] = False
        got = replay.replay_checks(blinded)
        self.assertIn("auto.dead_ref", got["skipped"])
        self.assertEqual(got["found"], 0)


class TestOneScorer(unittest.TestCase):
    """`panel/scoring.py` is the one implementation, and `rehearsal.py`
    uses it too — its own tests are what prove that half."""

    def test_precision_and_recall_are_the_obvious_arithmetic(self):
        got = scoring.tally(found=3, planted=4, extra=1)
        self.assertEqual(got["recall"], 0.75)
        self.assertEqual(got["precision"], 0.75)
        self.assertEqual(got["missed"], 1)

    def test_nothing_over_nothing_is_zero_and_not_a_perfect_score(self):
        got = scoring.tally(found=0, planted=0, extra=0)
        self.assertEqual((got["recall"], got["precision"]), (0.0, 0.0))

    def test_one_row_answering_two_labels_is_extra_to_neither(self):
        rows = [{"text": "the hall and the landing sensors are both dead"}]
        got = scoring.score(
            [{"k": "hall"}, {"k": "landing"}], rows,
            lambda label, row: label["k"] in row["text"])
        self.assertEqual(got["found"], 2)
        self.assertEqual(got["extra"], 0)
        self.assertEqual(got["precision"], 1.0)

    def test_rehearsal_scores_through_the_same_arithmetic(self):
        """Not a grep: the two are driven and compared."""
        import rehearsal
        got = rehearsal.score_analyst(
            [{"text": "brain_test_dead_ref names a missing entity"},
             {"text": "brain_test_something_else is odd"}],
            [r for r in rehearsal.PLAN if r.get("check")])
        want = scoring.tally(found=got["found"], planted=got["planted"],
                             extra=got["extra"])
        self.assertEqual(got["recall"], want["recall"])
        self.assertEqual(got["precision"], want["precision"])

    def test_a_repeated_correction_is_named_rather_than_merely_extra(self):
        """A report the homeowner has already said is wrong, made again, is
        the specific mistake the corpus exists to catch."""
        entry = {"labels": [
            {"finding_key": "the porch sensor is stuck on", "verb": "wrong"},
            {"finding_key": "the hall battery is flat", "verb": "done"}]}
        got = scorer.score_analyst(entry, [
            {"text": "The hall battery is flat"},
            {"text": "The porch sensor is stuck on"}])
        self.assertEqual(got["found"], 1)
        self.assertEqual(got["extra"], 1)
        self.assertEqual(got["repeated_corrections"], 1)

    def test_a_summary_sums_counts_rather_than_averaging_rates(self):
        """A mean of per-entry precisions weights a house with two findings
        the same as one with forty."""
        got = scorer.summarise([
            scoring.tally(found=1, planted=1, extra=0),
            scoring.tally(found=10, planted=40, extra=0)])
        self.assertEqual(got["found"], 11)
        self.assertEqual(got["planted"], 41)
        self.assertNotEqual(got["recall"], 0.625)


class TestTheReplayRefusesWhatItCannotHonestlyDo(unittest.TestCase):
    def test_a_search_entry_is_skipped_rather_than_graded_without_tools(self):
        """That run read the house with Home Assistant tools; replaying the
        prompt where they reach nothing grades a model that cannot look
        anything up and reports it as the prompt's fault."""
        entry = {"id": "s", "kind": "analyst", "gather_mode": "search",
                 "bundle": {"domains": {}}, "category": "automations",
                 "labels": [{"finding_key": "k", "verb": "done"}]}
        got = replay.replay_analyst(entry, "", 5, with_tools=False)
        self.assertIn("skipped", got)
        self.assertIn("--with-tools", got["skipped"])

    def test_the_budget_is_checked_before_a_run_not_after_it(self):
        """A cap that stops once it has been passed has already spent the
        run that passed it."""
        entry = {"id": "s", "kind": "analyst", "gather_mode": "snapshot",
                 "bundle": {}, "labels": [{"finding_key": "k",
                                           "verb": "done"}]}
        asked = []

        def boom(*a, **kw):
            asked.append(1)
            raise AssertionError("the replay asked a model over budget")

        old = replay.replay_analyst
        replay.replay_analyst = boom
        try:
            report = replay.run([entry], max_tokens=0)
        finally:
            replay.replay_analyst = old
        self.assertEqual(asked, [])
        self.assertIn("budget", report["results"][0]["skipped"])

    def test_the_prompt_is_rebuilt_with_the_current_builder(self):
        """Not replayed from a stored copy — what is being measured is this
        release's framing and contract."""
        import categories
        entry = {"id": "s", "kind": "analyst", "gather_mode": "snapshot",
                 "category": "automations", "bundle": {"marker": "HELLO"},
                 "labels": []}
        prompt, system, mode = replay.build_prompt_for(entry)
        self.assertEqual(mode, "snapshot")
        self.assertIs(system, categories.SYSTEM_PROMPT)
        self.assertIn("HELLO", prompt)
        # The contract itself, so an entry cannot be scored against a
        # prompt that lost it.
        self.assertIn("JSON only", prompt)

    def test_the_report_renders_without_a_model_having_run(self):
        report = replay.run(replay.load_entries())
        text = replay.render(report)
        self.assertIn("clean-house", text)
        self.assertIn("recall 100%", text)


if __name__ == "__main__":
    unittest.main()
