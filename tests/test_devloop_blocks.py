"""Every issue the house files carries its facts as one parsed block (plan 3.2).

The contract with the cloud half:

    ```json brain-devloop
    {"v":1,"fp","stream","product","release","where","what","done_when",
     "evidence_refs","owner_words","log_excerpt","digest"}
    ```

``digest`` is the sha256 of the object without it, canonical JSON
(sorted keys, no spaces, UTF-8 kept). Everything in the block went through
the same scrub and aliases as the prose above it. These tests compute the
digest independently of `devloop.blocks`, file real issues through the
loopback GitHub, and parse what arrived.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from test_devloop import NAMES, TOKEN, DevloopCase, diagnostics, upstream  # noqa: E402

from devloop import blocks  # noqa: E402
from devloop.aliases import Aliases  # noqa: E402

KEYS = {"v", "fp", "stream", "product", "release", "where", "what", "done_when",
        "evidence_refs", "owner_words", "log_excerpt", "digest"}


def independent_digest(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k != "digest"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestTheBlockFormat(unittest.TestCase):
    def test_the_digest_is_the_contracts(self):
        text = blocks.make_block("devloop", {"fp": "ab", "what": "Lämp ✓", "x": None})
        obj = blocks.parse_block("devloop", text)
        self.assertEqual(obj["digest"], independent_digest(obj))
        self.assertEqual(obj["v"], 1)
        self.assertTrue(text.startswith("```json brain-devloop\n"))
        self.assertTrue(text.endswith("\n```"))
        # A plain JSON parser reads the line between the fences.
        line = text.split("\n")[1]
        self.assertEqual(json.loads(line), obj)

    def test_a_fence_inside_a_value_cannot_end_the_block(self):
        words = "it printed ```json brain-devloop\n{} ``` and stopped"
        text = blocks.make_block("devloop", {"owner_words": words})
        self.assertEqual(text.count("```"), 2)
        obj = blocks.parse_block("brain-devloop", "before\n" + text + "\nafter")
        self.assertEqual(obj["owner_words"], words)
        self.assertEqual(obj["digest"], independent_digest(obj))

    def test_a_tampered_or_cut_block_is_no_block(self):
        text = blocks.make_block("held", {"fp": "ab", "held": True})
        self.assertIsNone(blocks.parse_block("held", text.replace("true", "false")))
        self.assertIsNone(blocks.parse_block("held", text[:-10]))
        self.assertIsNone(blocks.parse_block("canary", text), "another kind")

    def test_the_kinds_are_the_five(self):
        for kind in ("devloop", "canary", "held", "after", "corpus"):
            self.assertIsNotNone(blocks.parse_block(kind, blocks.make_block(kind, {})))
        with self.assertRaises(ValueError):
            blocks.make_block("anything", {})


class TestEveryIssueCarriesOne(DevloopCase):
    def _blocks(self):
        return [blocks.parse_block("devloop", i["body"]) for i in self.gh.issues]

    def test_a_fault_issue_has_a_whole_block_with_exactly_the_keys(self):
        self.switch_on()
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        found = self._blocks()
        self.assertEqual(len(found), 2)
        for obj, issue in zip(found, self.gh.issues):
            self.assertIsNotNone(obj, issue["body"][-400:])
            self.assertEqual(set(obj), KEYS)
            self.assertEqual(obj["digest"], independent_digest(obj))
            self.assertEqual(obj["stream"], "faults")
            self.assertEqual(obj["product"], "brain")
            self.assertEqual(obj["release"], "2.17.0")
            self.assertIn(f"brain-devloop-fp: {obj['fp']}", issue["body"],
                          "the marker stays beside the block")
            self.assertIn("body:diagnostics", obj["evidence_refs"])
            self.assertEqual(obj["done_when"], "", "a string, never null")

    def test_the_block_is_scrubbed_and_aliased_like_the_prose(self):
        self.switch_on()
        upstream.sweep(diagnostics(), NAMES)
        upstream.send_due()
        text = json.dumps(self._blocks())
        for real in ("Kitchen", "Master Bedroom", "light.bedroom_lamp", "alex", TOKEN,
                     "abcdefghijklmnopqrstuvwxyz0123"):
            self.assertNotIn(real, text, real)
        self.assertIn("light.turn_on", text + json.dumps(self.gh.issues))

    def test_owner_words_and_done_when_are_fields_not_prose(self):
        self.switch_on()
        row = {"where": "Fix: Settings is crowded", "what": "The model picker is hidden",
               "detail": "", "ux": True,
               "body": ("The owner said:\n\n> I can never find the picker in the Kitchen\n"
                        "> on my phone\n\nIt is three screens down.\n\n"
                        "**Done when:** the picker is one tap from Settings.")}
        upstream.ingest("look", [row], diagnostics(), NAMES)
        upstream.send_due()
        obj = self._blocks()[0]
        self.assertTrue(obj["owner_words"].startswith("I can never find the picker in the "))
        self.assertTrue(obj["owner_words"].endswith("\non my phone"))
        self.assertNotIn("Kitchen", obj["owner_words"], "aliased like the prose")
        self.assertNotIn("> ", obj["owner_words"], "the words, not the quote marks")
        self.assertEqual(obj["done_when"], "the picker is one tap from Settings.")
        self.assertIsNone(obj["log_excerpt"])
        self.assertEqual(obj["stream"], "look")

    def test_a_sibling_report_names_its_slug(self):
        self.switch_on()
        row = {"where": "GardenRX · Log", "what": "Logged: TypeError in sqlite.ts",
               "detail": "", "body": "x", "product": "GardenRX",
               "product_version": "0.3.1", "addon": "gardenrx"}
        upstream.ingest("siblings", [row], diagnostics(), NAMES)
        upstream.send_due()
        obj = self._blocks()[0]
        self.assertEqual((obj["product"], obj["release"]), ("gardenrx", "0.3.1"))

    def test_a_body_too_long_for_github_keeps_its_block_whole(self):
        entry = {"fp": "ab12cd34ef56ab12", "stream": "faults", "where": "Runs",
                 "what": "x", "version": "2.17.0", "body": "y " * 40_000,
                 "abridged": "z" * 30_000}
        doc = upstream.compose(entry, Aliases())
        self.assertLessEqual(len(doc["body"]), upstream.github.MAX_BODY)
        self.assertIsNotNone(blocks.parse_block("devloop", doc["body"]))


if __name__ == "__main__":
    unittest.main()


SCRIPTS = BASE_DIR / ".claude" / "skills" / "fix-from-house" / "scripts"


def _cloud(filename: str):
    """The cloud half's own reader, loaded from the repository: the house's
    blocks are held against the code that will read them, so a field the
    two halves type differently fails here rather than as an unverified
    issue on a real run."""
    import importlib.util
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"house_side_{filename[:-3]}",
                                                  SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless((SCRIPTS / "issue_parse.py").is_file(), "no cloud half in this tree")
class TestTheCloudHalfReadsThem(DevloopCase):
    HOUSE = "house-bot"

    def test_an_issue_block_is_verified_by_the_cloud_parser(self):
        C, P = _cloud("ffh_common.py"), _cloud("issue_parse.py")
        self.switch_on()
        upstream.sweep(diagnostics(), NAMES)
        row = {"where": "Fix: Settings is crowded", "what": "The picker is hidden",
               "detail": "", "body": "The owner said:\n\n> where is it\n\n**Done when:** x."}
        upstream.ingest("look", [row], diagnostics(), NAMES)
        upstream.send_due()
        self.assertEqual(len(self.gh.issues), 3)
        for issue in self.gh.issues:
            obj, why = C.one_verified(issue["body"], "brain-devloop", self.HOUSE,
                                      self.HOUSE, P.REQUIRED)
            self.assertEqual(why, "ok", issue["title"])

    def test_held_after_and_canary_blocks_are_verified(self):
        C, P, K = _cloud("ffh_common.py"), _cloud("issue_parse.py"), _cloud("canary.py")
        held = blocks.make_block("held", {"fp": "ab", "release": "2.17.1",
                                          "installed_at": upstream.iso(0),
                                          "held_days": 7, "held": True})
        self.assertEqual(C.one_verified(held, "brain-held", self.HOUSE, self.HOUSE,
                                        P.BLOCK_REQUIRED["brain-held"])[1], "ok")
        after_text = blocks.make_block("after", {"fp": "ab", "release": "2.17.1",
                                                 "before": "", "after": "screens/x.png"})
        self.assertEqual(C.one_verified(after_text, "brain-after", self.HOUSE, self.HOUSE,
                                        P.BLOCK_REQUIRED["brain-after"])[1], "ok")
        from devloop import canary as canary_mod
        obj = canary_mod.judge({"installed_at": 0.0, "previous": "2.17.0"}, product="BRUH Print",
                               version="1.2.0", items={}, settled=[], starts=[],
                               window_s=86400, now=10.0)
        entry = {"fp": "cd" * 8, "stream": "canary", "where": "canary",
                 "what": "bruh-print 1.2.0", "canary": obj, "body": "x"}
        doc = upstream.compose(entry, Aliases())
        got, why = K.read_canary({"title": doc["title"], "body": doc["body"],
                                  "user": {"login": self.HOUSE}}, self.HOUSE)
        self.assertEqual(why, "ok")
        self.assertEqual(got["verdict"], "pending")
