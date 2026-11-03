#!/usr/bin/env python3
"""A request whose answer nobody reads does not print it into the log.

The automation listener fired `brain_task_complete` with `curl -s -X POST
… || true` and no `-o`, so Home Assistant's `{"message": "Event
brain_task_complete fired."}` went to stdout with no newline and glued onto
the next line of the add-on log — including the "Processing task" lines a
log reader parses (#637). The same shape fired `brain_restart_required` and
a persistent notification from run.sh.

The rule, over every script the add-on runs as a daemon: a `curl` that is
a statement of its own (not inside `$(…)`, not piped) and ends `|| true`
is fire-and-forget, and must send its body to `-o /dev/null`.
"""

import re
import unittest
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent / "brain"
SCRIPTS = [BRAIN / "run.sh", *sorted((BRAIN / "integrations").glob("*.sh"))]


def commands(text: str) -> list[tuple[int, str]]:
    """Every shell command with its backslash continuations joined."""
    out, buf, start = [], "", 0
    for n, line in enumerate(text.splitlines(), 1):
        if not buf:
            start = n
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        out.append((start, buf + line))
        buf = ""
    return out


def fire_and_forget(cmd: str) -> bool:
    s = cmd.strip()
    return (s.startswith("curl ") and "|" not in s.replace("|| true", "")
            and s.endswith("|| true"))


class TestNoAnswerIsPrinted(unittest.TestCase):
    def test_every_discarded_answer_goes_to_dev_null(self):
        bad = []
        for path in SCRIPTS:
            for line, cmd in commands(path.read_text(encoding="utf-8")):
                if fire_and_forget(cmd) and not re.search(r"\s-o\s+/dev/null\b", cmd):
                    bad.append(f"{path.name}:{line}")
        self.assertEqual(bad, [], "a curl whose answer is thrown away prints "
                                  "it into the log; add -o /dev/null")

    def test_the_rule_finds_the_shape_it_is_about(self):
        sample = ('curl -s -X POST \\\n    -d "$p" \\\n'
                  '    "http://x/events/e" 2>/dev/null || true\n')
        [(_, cmd)] = commands(sample)
        self.assertTrue(fire_and_forget(cmd))
        self.assertFalse(fire_and_forget('x=$(curl -s "http://x") || true'))


if __name__ == "__main__":
    unittest.main()
