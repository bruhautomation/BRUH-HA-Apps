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

import pytest

NO_CLI = "/nonexistent/claude-not-installed-in-tests"


@pytest.fixture(autouse=True)
def _no_real_claude_cli():
    os.environ.setdefault("BRAIN_CLAUDE_BIN", NO_CLI)
    yield
