#!/usr/bin/env python3
"""A chat test that reloads `chat_session` leaves the chat's prompt wired.

The server wires the appended prompt once, as it is imported
(`chat_session.PROMPT_PROVIDER = _chat_system_prompt`). A chat test that
reloads `chat_session` to re-read its environment sets that back to None,
the server is not imported again, and every later test on the same xdist
worker built a chat with no prompt: test_ask_face_parity failed in CI that
way, deterministically after any file that imports the server followed by
test_chat_no_limit or test_chat_resolutions (test_discuss_safety did the same
until #581). Each of those puts the server's provider back in a cleanup; this
drives their real set-up and tear-down around an empty test, with the server
already imported, and asks whether the wiring survived.
"""

import importlib
import os
import sys
import unittest
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
PANEL = TESTS.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(TESTS))

RELOADERS = (
    ("test_chat_no_limit", "_RegistryCase"),
    ("test_chat_resolutions", "TestARealTurnOffersThem"),
    ("test_discuss_safety", "ChatCase"),
)


@pytest.mark.parametrize("module,case", RELOADERS)
def test_a_chat_test_that_reloads_chat_session_gives_the_prompt_back(module, case):
    import server  # imported first, as on a worker that ran a panel test
    base = getattr(importlib.import_module(module), case)
    empty = type("Empty", (base,), {"test_nothing": lambda self: None})
    result = unittest.TestResult()
    saved = dict(os.environ)  # the cases set variables they do not all pop
    try:
        empty("test_nothing").run(result)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    assert result.wasSuccessful(), result.errors + result.failures
    chat_session = sys.modules["chat_session"]
    assert chat_session.PROMPT_PROVIDER is server._chat_system_prompt
    assert chat_session.ChatSession()._system_prompt()
