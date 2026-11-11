"""Run the suite as if no Claude CLI is installed, which is what CI is.

Several routes start a background sign-in check (`validate_auth`), and a
test that drives one without stubbing the engine reaches `_claude_argv`.
On CI's runners there is no `claude` on PATH, so the spawn fails at once.
In a Claude Code cloud session there is one (`/opt/node22/bin/claude`), so
the same test started a real CLI and the next test that needed a run-queue
seat waited on it: `test_memory_cleanup`'s presses took 87s and 23s instead
of a third of a second, and some runs hung outright.

It is set before EVERY test rather than once at import, because the chat
tests set `BRAIN_CLAUDE_BIN` to their own fake and pop it in teardown,
which took a once-only default away for every test after them. A test that
wants a CLI still sets the variable itself; this only fills it when empty.
"""

import os
import tempfile

import pytest

NO_CLI = "/nonexistent/claude-not-installed-in-tests"

# Files the panel writes for the terminal, pointed somewhere that is not the
# machine's own /data before any panel module is imported: a cloud session
# has a real /data, and a test that opened a window wrote the next real
# terminal's first message into it.
_SANDBOX = tempfile.mkdtemp(prefix="brain-tests-")
os.environ.setdefault("BRAIN_TERMINAL_PROMPT_FILE",
                      os.path.join(_SANDBOX, "brain-terminal-prompt.md"))
os.environ.setdefault("BRAIN_TERMINAL_HANDOFF",
                      os.path.join(_SANDBOX, "terminal-handoff.json"))
# The checks collector's ledger of failing integration entries: every test
# that drives `checks.snapshot.collect` would otherwise stamp the real one.
os.environ.setdefault("BRAIN_ENTRY_FAILING_FILE",
                      os.path.join(_SANDBOX, "entry-failing.json"))
# brAIn's switches (features.py) and the shell's files (shell_link.py): a
# test that starts the panel publishes them, and on a box with a real
# /config/.brain that turned Personality off for every test after it. The
# features file sits in a folder that does not exist, so nothing is written
# and every switch reads as a house that never chose.
os.environ.setdefault("BRAIN_FEATURES_FILE",
                      os.path.join(_SANDBOX, "unwritten", "features.json"))
os.environ.setdefault("BRAIN_SHARED_DIR", os.path.join(_SANDBOX, "unwritten"))
os.environ.setdefault("BRAIN_INGRESS_HIDDEN_FILE",
                      os.path.join(_SANDBOX, "ingress_hidden.json"))


@pytest.fixture(autouse=True)
def _no_real_claude_cli():
    os.environ.setdefault("BRAIN_CLAUDE_BIN", NO_CLI)
    yield


# ---------------------------------------------------------------------------
# The `slow` mark, applied here rather than in each file
# ---------------------------------------------------------------------------
#
# `-m "not slow"` is the fast local run, and a mark nothing carries is a
# filter that filters nothing. These are the tests measured at half a second
# or more under four xdist workers (2026-10-08) — nearly all of them spawn a
# subprocess, stand up a real server or hold a lock, which is the waiting
# that makes the serial suite six minutes of wall clock for two of CPU; the
# rest walk the whole source tree. Listed here, by node id, rather than as
# decorators scattered over sixty files, so one place says what the fast run
# leaves out, and a file another change is editing need not be touched to
# mark it. An entry is a file, a class or a single test; a class or file
# where at least half the tests are slow is named whole.
#
# A renamed test would drop out of this list silently, so
# tests/test_slow_marks.py holds every entry to a file, class and function
# that exists. Skipping these is a way to iterate, never a pass: CI runs
# them.
