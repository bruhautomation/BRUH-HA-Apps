"""One brAIn, whichever box somebody typed into.

"Let brAIn act without asking" used to reach the chat and the terminal and
nothing else, so a reply under a notification, a reply under a card in
Morph and every task Morph or Design with brAIn handed the automation
listener answered read-only — "I can't change anything here" one screen
over from a chat that just did it. These hold the one rule every such
surface now asks:

* the panel's person-facing replies run `run_agent` on the chat's channel
  while the switch is on, and `run_analyst` while it is off;
* the automation listener widens a task a PERSON asked for (a conversation,
  or one carrying their words) to the full grant with prompts bypassed,
  only while the switch is on, and never widens one nobody typed;
* Morph's Tell and Ask prompts no longer stop at the dashboard.
"""

import asyncio
import importlib
import subprocess
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

LISTENER = BASE_DIR / "brain" / "integrations" / "automation-listener.sh"


def _lift(text: str, name: str) -> str:
    """One shell function out of the real script, braces balanced."""
    start = text.index(f"{name}() {{")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError(f"{name} has no end")


class TestTheListenerWidensOnlyWhatAPersonAskedFor(unittest.TestCase):
    def run_rule(self, conversation: str, words: str, flag: str | None) -> bool:
        fn = _lift(LISTENER.read_text(), "person_task_acts")
        stub = ("" if flag is None else
                f"brain_perms_flag() {{ printf '%s' {flag!r}; }}\n")
        script = stub + fn + f"\nperson_task_acts {conversation!r} {words!r}\n"
        return subprocess.run(["bash", "-c", script]).returncode == 0

    def test_a_conversation_acts_with_the_switch_on(self):
        self.assertTrue(self.run_rule("true", "", "--dangerously-skip-permissions"))

    def test_a_task_carrying_their_words_acts_with_the_switch_on(self):
        self.assertTrue(self.run_rule("", "make a card", "--dangerously-skip-permissions"))

    def test_nothing_is_widened_with_the_switch_off(self):
        self.assertFalse(self.run_rule("true", "make a card", ""))

    def test_a_task_nobody_typed_is_never_widened(self):
        self.assertFalse(self.run_rule("", "", "--dangerously-skip-permissions"))

    def test_no_library_widens_nothing(self):
        self.assertFalse(self.run_rule("true", "make a card", None))

    def test_a_widened_task_runs_full_on_the_chats_channel_without_prompts(self):
        text = LISTENER.read_text()
        body = _lift(text, "process_task")
        widen = body.index('if person_task_acts "$task_conversation" "$task_words"')
        self.assertIn('task_tools=""', body[widen:widen + 300])
        self.assertIn("export BRAIN_CHANNEL=chat", body[widen:widen + 300])
        self.assertIn("tool_flags+=(--permission-mode bypassPermissions)", body)
        # Decided after the words are read, before the scope is turned into flags.
        self.assertLess(body.index("task_words=$(jq"), widen)
        self.assertLess(widen, body.index('task_tool_flags "$task_tools"'))


class TestThePanelsRepliesAreTheChat(unittest.TestCase):
    def setUp(self):
        self.server = importlib.import_module("server")
        self.calls = []
        self._old = (self.server.engine.run_agent, self.server.engine.run_analyst,
                     self.server.eff_skip_permissions)

        def agent(prompt, system, model, timeout, max_turns, source, **kw):
            self.calls.append(("agent", system, timeout, kw))
            return {"ok": True, "text": "Done: made it."}

        def analyst(prompt, system, model, timeout, max_turns, source, **kw):
            self.calls.append(("analyst", system, timeout, kw))
            return {"ok": True, "text": "It reads 61%."}

        self.server.engine.run_agent = agent
        self.server.engine.run_analyst = analyst

    def tearDown(self):
        (self.server.engine.run_agent, self.server.engine.run_analyst,
         self.server.eff_skip_permissions) = self._old

    def switch(self, on):
        self.server.eff_skip_permissions = lambda: on

    def run_once(self):
        s = self.server
        return asyncio.run(s._person_run("q", s.REPLY_SYSTEM, s.REPLY_ACT_SYSTEM,
                                         180, 24, "resident", job="explain",
                                         priority=s.run_queue.PRESS))

    def test_with_the_switch_on_a_reply_acts_on_the_chats_channel(self):
        self.switch(True)
        self.run_once()
        kind, system, timeout, kw = self.calls[0]
        self.assertEqual(kind, "agent")
        self.assertIs(system, self.server.REPLY_ACT_SYSTEM)
        self.assertEqual(kw["env"], {"BRAIN_CHANNEL": "chat"})
        self.assertGreaterEqual(timeout, self.server.PERSON_ACT_TIMEOUT_S)

    def test_with_it_off_a_reply_reads_only(self):
        for off in (False, None):
            self.calls.clear()
            self.switch(off)
            self.run_once()
            kind, system, _t, kw = self.calls[0]
            self.assertEqual(kind, "analyst")
            self.assertIs(system, self.server.REPLY_SYSTEM)
            self.assertNotIn("env", kw)

    def test_the_act_prompts_do_not_say_change_nothing(self):
        s = self.server
        for read, act in ((s.REPLY_SYSTEM, s.REPLY_ACT_SYSTEM),
                          (s.MORPH_REPLY_SYSTEM, s.MORPH_REPLY_ACT_SYSTEM),
                          (s.PANEL_REPLY_SYSTEM, s.PANEL_REPLY_ACT_SYSTEM)):
            self.assertIn("you can change nothing", read)
            self.assertNotIn("change nothing", act)
            self.assertIn("same reach as the brAIn chat", act)

    def test_both_reply_sites_go_through_the_one_rule(self):
        src = (BASE_DIR / "brain" / "panel" / "server.py").read_text()
        for name in ("_morph_answer", "_reply_conversation"):
            body = src[src.index(f"async def {name}("):]
            body = body[:body.index("\nasync def ", 10)]
            self.assertIn("_person_run(", body, name)
            self.assertNotIn("engine.run_analyst", body, name)


class TestMorphDoesTheWholeThing(unittest.TestCase):
    def test_the_tell_prompt_reaches_the_house(self):
        text = (BASE_DIR / "morph" / "service" / "tell.py").read_text()
        self.assertNotIn("MORPH ONLY", text)
        self.assertIn("Never stop at the dashboard half", text)

    def test_ask_is_told_it_can_change_the_dashboard(self):
        text = (BASE_DIR / "morph" / "service" / "converse.py").read_text()
        self.assertNotIn("cannot change the dashboard", text)
        self.assertIn("same reach as the chat", text)

    def test_agents_md_makes_the_sensor_rather_than_asking(self):
        text = (BASE_DIR / "morph" / "defaults" / "AGENTS.md").read_text()
        self.assertNotIn("Never make that sensor unasked", text)
        self.assertNotIn("in so many words", text)
        self.assertIn("make a template sensor", " ".join(text.split()))


if __name__ == "__main__":
    unittest.main()
