#!/usr/bin/env python3
"""Every integration's strings hold only placeholders hassfest accepts.

hassfest reads any `{...}` in strings.json or translations/*.json as a
placeholder and fails CI unless what is inside is an identifier. A service
description that shows the shape of an object, like `{x, y, z, block}`, is
the usual way in, and it has broken the HA integration validation job three
times. This test catches it before a push.
"""
from __future__ import annotations

import glob
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDENT = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _string_files() -> list[str]:
    found = []
    for comp in glob.glob(os.path.join(ROOT, "*", "custom_components", "*")):
        found += glob.glob(os.path.join(comp, "strings.json"))
        found += glob.glob(os.path.join(comp, "translations", "*.json"))
    return sorted(found)


def _bad_placeholders(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _bad_placeholders(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _bad_placeholders(value, f"{path}[{i}]")
    elif isinstance(node, str):
        for inner in re.findall(r"\{([^{}]*)\}", node):
            if not IDENT.fullmatch(inner):
                yield path, inner


class TestTranslationPlaceholders(unittest.TestCase):
    def test_there_are_files_to_check(self):
        self.assertTrue(_string_files())

    def test_every_placeholder_is_an_identifier(self):
        problems = []
        for path in _string_files():
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for where, inner in _bad_placeholders(data):
                problems.append(f"{os.path.relpath(path, ROOT)}: {where}: {{{inner}}}")
        self.assertEqual(problems, [], "hassfest rejects these placeholders:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
