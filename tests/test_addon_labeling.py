#!/usr/bin/env python3
"""The "Which add-on?" dropdown and the label workflow have to agree.

Every issue and discussion template asks which add-on the report is about,
and the label-by-addon workflow turns that answer into a label so the
answer is filterable rather than merely present.

The failure mode is silent: someone adds a dropdown option, the workflow
has no mapping for it, and those reports quietly stop being labelled. So
every option is checked against the workflow's map, and the ones that map
to nothing have to be deliberate rather than forgotten.
"""

import os
import re
import unittest

import yaml

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
GITHUB_DIR = os.path.join(BASE_DIR, ".github")
WORKFLOW = os.path.join(GITHUB_DIR, "workflows", "label-by-addon.yml")

# Options that intentionally produce no label. A wrong label is worse than
# none: people filter on these, and "unsure" is not a product.
DELIBERATELY_UNMAPPED = {"Other / unsure", "Other"}


def template_files():
    paths = []
    for sub in ("ISSUE_TEMPLATE", "DISCUSSION_TEMPLATE"):
        directory = os.path.join(GITHUB_DIR, sub)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.endswith((".yml", ".yaml")) and name != "config.yml":
                paths.append(os.path.join(directory, name))
    return paths


def addon_options(path):
    """The options of the `addon` dropdown, or None if the form has none."""
    with open(path) as f:
        form = yaml.safe_load(f)
    for field in form.get("body") or []:
        if field.get("type") == "dropdown" and field.get("id") == "addon":
            return field["attributes"]["options"]
    return None


def workflow_map_keys():
    """Keys of the MAP object in the workflow's inline script."""
    with open(WORKFLOW) as f:
        script = f.read()
    block = script.split("const MAP = {", 1)[1].split("};", 1)[0]
    return set(re.findall(r"'([^']+)':", block))


class TestEveryTemplateAsks(unittest.TestCase):

    def test_there_are_templates_to_check(self):
        self.assertTrue(template_files(), "no issue/discussion templates found")

    def test_every_template_has_the_dropdown(self):
        for path in template_files():
            with self.subTest(template=os.path.basename(path)):
                self.assertIsNotNone(
                    addon_options(path),
                    "template has no `addon` dropdown, so nothing can route it",
                )

    def test_the_dropdown_is_required(self):
        """An optional dropdown is one most people skip, and an unanswered
        one cannot be labelled."""
        for path in template_files():
            with self.subTest(template=os.path.basename(path)):
                with open(path) as f:
                    form = yaml.safe_load(f)
                field = next(b for b in form["body"]
                             if b.get("id") == "addon")
                self.assertTrue(
                    (field.get("validations") or {}).get("required"),
                    "the add-on dropdown must be required",
                )


class TestWorkflowCoversEveryOption(unittest.TestCase):

    def test_every_option_is_mapped_or_deliberately_not(self):
        mapped = workflow_map_keys()
        for path in template_files():
            for option in addon_options(path) or []:
                with self.subTest(template=os.path.basename(path),
                                  option=option):
                    self.assertTrue(
                        option in mapped or option in DELIBERATELY_UNMAPPED,
                        f"'{option}' gets no label and is not in the "
                        f"deliberately-unmapped list — reports choosing it "
                        f"would silently go unlabelled",
                    )

    def test_the_map_has_no_option_no_template_offers(self):
        offered = set()
        for path in template_files():
            offered.update(addon_options(path) or [])
        stale = sorted(workflow_map_keys() - offered)
        self.assertEqual([], stale, f"map entries nothing offers: {stale}")

    def test_both_products_are_mapped(self):
        mapped = workflow_map_keys()
        self.assertIn("brAIn", mapped)
        self.assertIn("BRUH Minecraft", mapped)
        self.assertIn("BRight", mapped)


class TestBodyParsing(unittest.TestCase):
    """The regex is the load-bearing part: if it stops matching, the
    workflow succeeds and silently labels nothing.

    The pattern is lifted out of the workflow rather than copied, so
    editing it there is what these cases are checking.
    """

    @classmethod
    def setUpClass(cls):
        with open(WORKFLOW) as f:
            script = f.read()
        pattern = re.search(r"body\.match\(/(.+?)/i\)", script).group(1)
        cls.pattern = re.compile(pattern, re.IGNORECASE)

    def _answer(self, body):
        m = self.pattern.search(body)
        return m.group(1).strip() if m else None

    def test_reads_a_standard_issue_form_body(self):
        body = "### Which add-on?\n\nbrAIn\n\n### Add-on version\n\n1.19.0"
        self.assertEqual("brAIn", self._answer(body))

    def test_reads_it_without_a_blank_line(self):
        body = "### Which add-on?\nBRUH Minecraft\n\n### Next"
        self.assertEqual("BRUH Minecraft", self._answer(body))

    def test_tolerates_trailing_whitespace(self):
        body = "### Which add-on?   \n\n  brAIn  \n"
        self.assertEqual("brAIn", self._answer(body))

    def test_reads_an_option_containing_a_slash(self):
        body = "### Which add-on?\n\nThe repository / docs\n"
        self.assertEqual("The repository / docs", self._answer(body))

    def test_returns_nothing_when_the_question_is_absent(self):
        for body in ("### What happened?\n\nIt broke\n", "brAIn is broken", ""):
            with self.subTest(body=body[:20]):
                self.assertIsNone(self._answer(body))

    def test_the_map_matches_exactly_not_by_prefix(self):
        """"Other" is a prefix of "Other / unsure". A prefix match would
        label every unsure report as whatever "Other" mapped to."""
        mapped = workflow_map_keys()
        for option in DELIBERATELY_UNMAPPED:
            with self.subTest(option=option):
                self.assertNotIn(option, mapped)
        with open(WORKFLOW) as f:
            script = f.read()
        self.assertIn("MAP[answer]", script,
                      "lookup must be an exact key lookup")
        # `.startsWith(` — the call, not the word. The comment above the
        # lookup says why it isn't used, and prose must not fail a test.
        self.assertNotIn(".startsWith(", script)
        self.assertNotIn(".includes(answer", script)


class TestWorkflowShape(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(WORKFLOW) as f:
            cls.raw = f.read()
        cls.wf = yaml.safe_load(cls.raw)

    def test_it_runs_for_issues_and_discussions(self):
        # PyYAML reads a bare `on:` key as the boolean True.
        triggers = self.wf.get("on") or self.wf.get(True)
        self.assertIn("issues", triggers)
        self.assertIn("discussion", triggers)

    def test_it_has_the_write_permissions_it_needs(self):
        perms = self.wf["jobs"]["label"]["permissions"]
        self.assertEqual("write", perms.get("issues"))
        self.assertEqual("write", perms.get("discussions"))

    def test_it_labels_discussions_via_graphql(self):
        """REST cannot label a discussion; only the GraphQL mutation can."""
        self.assertIn("addLabelsToLabelable", self.raw)

    def test_it_never_removes_a_label(self):
        """A maintainer relabelling something by hand must not be undone by
        the next edit to the body."""
        self.assertNotIn("removeLabelsFromLabelable", self.raw)
        self.assertNotIn("removeLabel", self.raw)


if __name__ == "__main__":
    unittest.main()
