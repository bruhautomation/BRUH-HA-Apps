#!/usr/bin/env python3
"""The day's debug logs are owned by the user the session runs as.

The voice and automation listeners (and the worker pool) run as root and
create `/config/.brain/logs/<kind>-YYYYMMDD.log` owner-only, because the
lines are full transcripts. Created by root, owner-only means root-only:
the session (the `claude` user) could not read a day's logs until the next
boot's `chown -R` handed them over, which blocked every audit of "what did
voice do today" (#642).

Each writer now hands a NEW day's file to `claude` as it creates it — still
0600, so nothing else can read it. Driven here: the shell helper lifted
out of both listeners with `id` and `chown` stubbed, and the pool's
`debug_log` with the root checks stubbed.
"""

import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_assist_exposure import load_pool  # noqa: E402

INTEGRATIONS = Path(__file__).resolve().parent.parent / "brain" / "integrations"
LISTENERS = {"assist": INTEGRATIONS / "assist-listener.sh",
             "automation": INTEGRATIONS / "automation-listener.sh"}


def helper(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^today_log\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert match, f"{path.name} has no today_log"
    return match.group(0)


class TestTheListenersHandTheFileOver(unittest.TestCase):
    def drive(self, kind: str, path: Path):
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "chown.log"
            script = (
                "id() { echo 0; }\n"
                f"chown() {{ echo \"$*\" >> '{calls}'; }}\n"
                f"LOG_DIR='{tmp}'\n" + helper(path)
                + f"f=$(today_log {kind}); echo hello >> \"$f\"; "
                + f"g=$(today_log {kind}); printf '%s\\n%s' \"$f\" \"$g\"\n")
            out = subprocess.run(["bash", "-c", script], capture_output=True,
                                 text=True, check=True).stdout.split("\n")
            self.assertEqual(out[0], out[1], "one file per day")
            made = Path(out[0])
            self.assertTrue(made.name.startswith(f"{kind}-"))
            self.assertEqual(stat.S_IMODE(made.stat().st_mode), 0o600)
            owned = calls.read_text().splitlines()
            # Handed over once, when it was made — not on every append.
            self.assertEqual(owned, [f"claude:claude {made}"])

    def test_both_listeners(self):
        for kind, path in LISTENERS.items():
            with self.subTest(kind):
                self.drive(kind, path)

    def test_no_writer_names_the_day_file_by_hand(self):
        for kind, path in LISTENERS.items():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(f'$LOG_DIR/{kind}-$(date', text)


class TestThePoolHandsItsFileOver(unittest.TestCase):
    def test_a_new_day_file_goes_to_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = load_pool(tmp, {})
            owned = []
            user = unittest.mock.Mock(pw_uid=1234, pw_gid=5678)
            with unittest.mock.patch.object(mod.os, "geteuid", return_value=0), \
                    unittest.mock.patch.object(mod.os, "chown",
                                      side_effect=lambda *a: owned.append(a)), \
                    unittest.mock.patch("pwd.getpwnam", return_value=user):
                mod.debug_log(["first"])
                mod.debug_log(["second"])
            [path] = [p for p in os.listdir(mod.LOG_DIR) if p.startswith("assist-")]
            full = os.path.join(mod.LOG_DIR, path)
            self.assertEqual(owned, [(full, 1234, 5678)])
            self.assertEqual(stat.S_IMODE(os.stat(full).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
