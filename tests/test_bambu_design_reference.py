#!/usr/bin/env python3
"""The design chat says so when it cannot read a reference, and asks for numbers.

A link or a photo is something the designer cannot open or see (it runs no
tools). Pretending to read it, or going quiet, leaves the person guessing:
it must say it cannot, and ask for the measurements it would have read off it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_bambu_design_printing import designer  # noqa: E402


class TestAReferenceItCannotRead(unittest.TestCase):
    def test_the_brief_says_a_link_or_photo_cannot_be_opened_and_asks_for_sizes(self):
        brief = designer.brief()
        self.assertIn("cannot open a link or see a photo", brief)
        self.assertIn("ask for the measurements", brief)
