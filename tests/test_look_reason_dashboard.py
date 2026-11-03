"""A look that holds a row by saying it is "already on your dashboard" is
reasoning in a circle: the dashboard is where the row is. Like the list and
the queue, the dashboard is brAIn's routing, not a conclusion about the
house."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "brain" / "panel"))

import findings_store  # noqa: E402


class TestDashboardIsRouting(unittest.TestCase):
    def test_sentences_pointing_at_the_dashboard_are_no_reason(self):
        for said in ("The problem is already on your dashboard.",
                     "This is already open on your dashboard.",
                     "Already showing on the dashboard as a card.",
                     "It is already a cleanup chore."):
            self.assertEqual(findings_store.house_reason(said), "", said)

    def test_a_judgement_beside_it_is_kept(self):
        self.assertEqual(findings_store.house_reason(
            "Already on your dashboard. The entity was removed last week."),
            "The entity was removed last week.")


if __name__ == "__main__":
    unittest.main()
