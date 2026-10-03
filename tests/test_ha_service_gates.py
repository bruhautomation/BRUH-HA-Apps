#!/usr/bin/env python3
"""The integration's services, driven through their registered handlers.

Three things these hold, each against the real `__init__.py` loaded behind
tests/brain_ha_env.py:

* **Who may ask.** A task runs with the Supervisor's token behind every
  Home Assistant tool and, at `tools: full`, a shell in /config — so its
  reach is an admin's whatever the caller's own account is. Home Assistant
  admin-gates only `async_register_admin_service`, which cannot return
  response data, and nothing here asked: a wall tablet's login could name
  `tools: full` and get a root-equivalent run. A context with no user (an
  automation, a script) is the system, and passes — the power tools' rule.
* **A failure is a failure.** A run the listener says failed raises
  `HomeAssistantError` with the listener's own sentence, which is what puts
  it in an automation's trace; `brain.ask` never answers with the sentence
  as `response` and `data: None` beside it.
* **A guess answered here closes.** `brain.answer_question` crosses to the
  panel as a request and the panel confirms or rejects the guess through
  the Findings tab's own code — driven end to end, the integration's writer
  into the panel's real drain.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_ha_env as env  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"


class FakeServices:
    def __init__(self):
        self.handlers = {}
        self.calls = []

    def async_register(self, domain, name, handler, schema=None, **kw):
        self.handlers[name] = handler

    def has_service(self, domain, name):
        return name in self.handlers

    async def async_call(self, domain, service, data=None, **kw):
        self.calls.append((domain, service, data))


class FakeAuth:
    def __init__(self, users):
        self.users = users

    async def async_get_user(self, user_id):
        return self.users.get(user_id)


class FakeBus:
    def __init__(self):
        self.fired = []

    def async_fire(self, event, data=None):
        self.fired.append((event, data))


class FakeHass:
    def __init__(self, base: Path, users: dict | None = None):
        self.base = base
        self.data = {}
        self.config = types.SimpleNamespace(
            path=lambda *parts: os.path.join(str(base), *parts))
        self.services = FakeServices()
        self.auth = FakeAuth(users or {})
        self.bus = FakeBus()

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)

    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)


ADMIN = types.SimpleNamespace(id="admin", is_admin=True, name="Ben")
GUEST = types.SimpleNamespace(id="guest", is_admin=False, name="Wall tablet")


def call(data: dict, user_id=None):
    return types.SimpleNamespace(data=data, context=env.Context(user_id))


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.pkg = env.load_integration()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hass = FakeHass(self.tmp, {"admin": ADMIN, "guest": GUEST})
        self.sent: list[dict] = []
        self.answer: object = {"text": "All quiet.", "data": None}
        bridge_cls = self.pkg.bridge.ClaudeBridge
        test = self

        class RecordingBridge(bridge_cls):
            async def async_send_task_full(self, **kw):
                test.sent.append(kw)
                if isinstance(test.answer, Exception):
                    raise test.answer
                return test.answer

            async def async_send_task(self, **kw):
                return (await self.async_send_task_full(**kw))["text"]

            async def async_send_conversation(self, **kw):
                test.sent.append(kw)
                if isinstance(test.answer, Exception):
                    raise test.answer
                return test.answer["text"]

        self.bridge = RecordingBridge(self.hass)
        self.hass.data[self.pkg.const.DOMAIN] = {"entry": self.bridge}
        self.pkg._register_services(self.hass)

    def run_service(self, name, data, user_id=None):
        handler = self.hass.services.handlers[name]
        return asyncio.new_event_loop().run_until_complete(
            handler(call(data, user_id)))


class TestWhoMayRunATask(ServiceCase):

    def test_a_non_admin_asking_for_the_full_grant_is_refused(self):
        with self.assertRaises(env.Unauthorized):
            self.run_service("run_task", {"prompt": "tidy /config",
                                          "tools": "full"}, "guest")
        self.assertEqual(self.sent, [], "the run started before the refusal")

    def test_the_default_scope_is_the_full_grant_and_so_is_refused(self):
        """`tools` left out is `full` — what every task before the field
        asked for — so leaving it out may not be the way round the gate."""
        with self.assertRaises(env.Unauthorized):
            self.run_service("run_task", {"prompt": "tidy /config"}, "guest")

    def test_the_house_scope_acts_on_the_house_and_is_refused_too(self):
        with self.assertRaises(env.Unauthorized):
            self.run_service("run_task", {"prompt": "x", "tools": "house"},
                             "guest")

    def test_a_non_admin_may_ask_a_read_only_question(self):
        got = self.run_service("run_task", {"prompt": "is the door shut?",
                                            "tools": "read_only"}, "guest")
        self.assertEqual(got["response"], "All quiet.")

    def test_an_automation_is_the_system_and_passes(self):
        got = self.run_service("run_task", {"prompt": "x", "tools": "full"})
        self.assertEqual(got["response"], "All quiet.")

    def test_an_admin_passes(self):
        self.run_service("run_task", {"prompt": "x", "tools": "full"}, "admin")
        self.assertEqual(self.sent[0]["tools"], "full")

    def test_a_user_that_does_not_exist_is_refused(self):
        with self.assertRaises(env.UnknownUser):
            self.run_service("run_task", {"prompt": "x", "tools": "full"},
                             "nobody")

    def test_the_model_a_task_names_reaches_the_bridge(self):
        """The service's schema took `model` and the handler dropped it."""
        self.run_service("run_task", {"prompt": "x", "model": "haiku"})
        self.assertEqual(self.sent[0]["model"], "haiku")

    def test_ask_is_read_only_by_default_and_gated_above_it(self):
        self.run_service("ask", {"question": "anything open?"}, "guest")
        self.assertEqual(self.sent[0]["tools"], "read_only")
        with self.assertRaises(env.Unauthorized):
            self.run_service("ask", {"question": "x", "tools": "house"},
                             "guest")

    def test_a_prompt_is_the_voice_level_and_needs_no_admin(self):
        got = self.run_service("send_prompt", {"prompt": "hello"}, "guest")
        self.assertEqual(got["response"], "All quiet.")
        self.assertNotIn("access", self.sent[0])


class TestWhatOnlyAnAdminMayTeach(ServiceCase):
    """Memory is handed to every later run — voice, the fixer, every card —
    so a fact, a study and a drafted automation are an admin's to give."""

    def test_the_writers_refuse_a_non_admin(self):
        for name, data in (
                ("add_memory", {"fact": "The door code is 1234"}),
                ("study", {"topic": "heating"}),
                ("intent", {"sentence": "turn the porch light off later"}),
                ("answer_question", {"ts": 1, "answer": "yes"})):
            with self.subTest(service=name):
                with self.assertRaises(env.Unauthorized):
                    self.run_service(name, data, "guest")

    def test_a_reserved_source_is_refused_however_it_is_spelled(self):
        """`correction` is what the pipeline treats as the homeowner having
        typed it, so a caller may not file under it."""
        for source in ("correction", "Correction!", "confirmed", "person"):
            with self.subTest(source=source):
                with self.assertRaises(env.ServiceValidationError):
                    self.run_service("add_memory", {"fact": "x",
                                                    "source": source}, "admin")
        inbox = self.tmp / ".brain" / "memory" / "inbox"
        self.assertFalse(inbox.exists() and any(inbox.iterdir()))

    def test_an_ordinary_fact_from_an_admin_is_queued(self):
        self.run_service("add_memory", {"fact": "Solar peaks at 13:00",
                                        "source": "automation"}, "admin")
        files = list((self.tmp / ".brain" / "memory" / "inbox").glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        line = json.loads(files[0].read_text().splitlines()[0])
        self.assertEqual(line["source"], "automation")


class TestAFailedRunRaises(ServiceCase):
    """Against the REAL bridge reading a result file shaped exactly as the
    listener writes one (tests/test_task_failures.py drives the listener)."""

    def setUp(self):
        super().setUp()
        self.real = self.pkg.bridge.ClaudeBridge(self.hass, timeout=10)
        self.hass.data[self.pkg.const.DOMAIN] = {"entry": self.real}

    def answer_with(self, result: dict):
        bridge = self.real

        async def answer_later():
            for _ in range(400):
                names = [n for n in os.listdir(bridge.tasks_dir)
                         if n.endswith(".json")] \
                    if os.path.isdir(bridge.tasks_dir) else []
                if names:
                    task = json.loads(Path(bridge.tasks_dir, names[0]).read_text())
                    os.makedirs(bridge.task_results_dir, exist_ok=True)
                    Path(bridge.task_results_dir, f"{task['id']}.json").write_text(
                        json.dumps({"id": task["id"], **result}))
                    return
                await asyncio.sleep(0.02)
        return answer_later

    def run_answered(self, name, data, result, user_id=None):
        handler = self.hass.services.handlers[name]

        async def main():
            helper = asyncio.ensure_future(self.answer_with(result)())
            try:
                return await handler(call(data, user_id))
            finally:
                await helper
        return asyncio.new_event_loop().run_until_complete(main())

    FAILED = {"result": "Claude's saved login has expired. Open brAIn from the "
                        "sidebar and press ⚙ → Claude account → Sign in again.",
              "status": "failed", "error": "auth"}

    def test_a_task_the_listener_failed_raises_its_sentence(self):
        with self.assertRaises(env.HomeAssistantError) as caught:
            self.run_answered("run_task", {"prompt": "x"}, self.FAILED)
        self.assertIn("Sign in again", str(caught.exception))
        self.assertNotIsInstance(caught.exception, self.pkg.bridge.BrainRunError)

    def test_ask_never_answers_a_failure_as_a_response_with_no_data(self):
        """Before: `{"response": "<the error>", "data": None}`, which a
        template's `| default(false)` read as a real answer."""
        with self.assertRaises(env.HomeAssistantError):
            self.run_answered("ask", {"question": "anything wrong?",
                                      "schema": {"type": "object"}},
                              self.FAILED)

    def test_a_completed_task_is_still_an_answer(self):
        got = self.run_answered("ask", {"question": "x"},
                                {"result": "Nothing.", "status": "completed",
                                 "data": {"wrong": False}})
        self.assertEqual(got, {"response": "Nothing.",
                               "data": {"wrong": False}})

    def test_a_timeout_raises_rather_than_answering(self):
        self.answer = TimeoutError("No response within 10s")
        self.hass.data[self.pkg.const.DOMAIN] = {"entry": self.bridge}
        with self.assertRaises(env.HomeAssistantError) as caught:
            self.run_service("run_task", {"prompt": "x"})
        self.assertIn("did not finish in time", str(caught.exception))


class TestInsightJobs(ServiceCase):
    """An insight job fires on a timer, so it is held to the rules every
    other unattended run is."""

    def setUp(self):
        super().setUp()

        class Plain:
            def __init__(self, text, hass):
                self.text = text

            def async_render(self, parse_result=False):
                return self.text

        self.pkg.Template = Plain
        import datetime as _dt  # noqa: PLC0415
        self.pkg.dt_util = types.SimpleNamespace(
            utcnow=lambda: _dt.datetime.now(_dt.timezone.utc))
        self.entry = types.SimpleNamespace(
            entry_id="job1", title="Morning", options={},
            data={"entry_type": "insight", "insight_prompt": "Summarise the night."})

    def run_insight(self, scheduled=True):
        asyncio.new_event_loop().run_until_complete(
            self.pkg._async_run_insight(self.hass, self.entry,
                                        scheduled=scheduled))
        return json.loads((self.tmp / ".brain" / "insights" / "job1.json").read_text())

    def test_it_reads_and_never_acts(self):
        """It inherited the project grant — Bash and file edits included."""
        self.run_insight()
        self.assertEqual(self.sent[0]["tools"], "read_only")

    def test_it_asks_the_listener_for_memory_and_says_it_was_scheduled(self):
        self.run_insight(scheduled=True)
        self.assertIs(self.sent[0]["memory"], True)
        self.assertIs(self.sent[0]["scheduled"], True)
        # No byte-cut of memory.md in front of the prompt any more.
        self.assertNotIn("Known about this home", self.sent[0]["prompt"])

    def test_a_press_is_not_scheduled(self):
        """`brain.run_insight` is somebody asking, and asking by hand always
        runs — the pause and the budget are for runs nobody pressed."""
        self.hass.config_entries = types.SimpleNamespace(
            async_entries=lambda domain: [self.entry])
        handler = self.hass.services.handlers["run_insight"]

        async def main():
            await handler(call({"name": "morning"}))
            for _ in range(200):
                if self.sent:
                    return
                await asyncio.sleep(0.01)
        asyncio.new_event_loop().run_until_complete(main())
        self.assertIs(self.sent[0]["scheduled"], False)

    def test_a_failed_run_is_an_error_and_never_a_report(self):
        """An expired login was filed as that morning's report and pushed
        to a phone."""
        self.entry.data["notify_service"] = "notify.mobile_app_phone"
        self.answer = {"text": "Last night was quiet.", "data": None}
        first = self.run_insight()
        self.assertIsNone(first["error"])
        self.hass.services.calls.clear()

        self.answer = self.pkg.bridge.BrainRunError(
            "Claude's saved login has expired.", "auth")
        second = self.run_insight()
        self.assertEqual(second["error_code"], "auth")
        self.assertIn("expired", second["error"])
        # The last good report is kept beside the error, not replaced by it.
        self.assertEqual(second["markdown"], first["markdown"])
        self.assertEqual(second["last_success"], first["last_success"])
        self.assertEqual([c for c in self.hass.services.calls
                          if c[0] == "notify"], [],
                         "a failure was pushed to a phone as a report")
        fired = [d for e, d in self.hass.bus.fired if "insight" in e]
        self.assertFalse(fired[-1]["success"])


class TestAGuessAnsweredInHomeAssistantCloses(ServiceCase):
    """The integration's writer into the panel's real drain."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(PANEL_DIR))
        self.hyp = importlib.import_module("hypotheses")
        self.fr = importlib.import_module("finding_requests")
        self.findings_store = importlib.import_module("findings_store")
        self.knowledge_store = importlib.import_module("knowledge_store")
        self.server = importlib.import_module("server")
        memory = self.tmp / ".brain" / "memory"
        memory.mkdir(parents=True)
        saved = {
            (self.hyp, "HYPOTHESES_FILE"): memory / "hypotheses.jsonl",
            (self.fr, "REQUEST_DIR"): Path(
                self.pkg.requests.requests_dir(self.hass)),
            (self.server, "MEMORY_INBOX_DIR"): self.tmp / "inbox",
            (self.knowledge_store, "KNOWLEDGE_FILE"): str(self.tmp / "knowledge.json"),
            (self.findings_store, "FINDINGS_FILE"): self.tmp / "findings.json",
            (self.findings_store, "SETTLED_FILE"): self.tmp / "settled.json",
            (self.findings_store, "INBOX_DIR"): self.tmp / "findings-inbox",
            (self.findings_store, "STATE_FILE"): self.tmp / "nowhere" / "state.json",
        }
        for (mod, attr), value in saved.items():
            old = getattr(mod, attr)
            setattr(mod, attr, value)
            self.addCleanup(setattr, mod, attr, old)
        self.guess = self.hyp.propose("The garage plug is the beer fridge",
                                      topic="devices")
        self.assertIsNotNone(self.guess)

    def facts(self) -> list[dict]:
        inbox = self.tmp / "inbox"
        out = []
        for path in sorted(inbox.glob("*.jsonl")) if inbox.is_dir() else []:
            out += [json.loads(line) for line in path.read_text().splitlines()
                    if line.strip()]
        return out

    def drain(self):
        return asyncio.new_event_loop().run_until_complete(
            self.server._apply_finding_requests())

    def test_a_yes_confirms_the_guess_and_files_its_claim(self):
        self.run_service("answer_question", {"ts": self.guess["ts"],
                                             "answer": "Yes, that's right"},
                         "admin")
        got = self.drain()
        self.assertTrue(got[0]["ok"], got)
        self.assertEqual(self.hyp.list_all("open"), [])
        self.assertEqual([f["source"] for f in self.facts()], ["confirmed"])
        self.assertIn("beer fridge", self.facts()[0]["fact"])

    def test_a_no_with_a_reason_rejects_it_and_files_the_reason(self):
        """Before: the typed answer was queued as a high-confidence FACT and
        the guess stayed open, so a "no" became something brAIn knew."""
        self.run_service("answer_question", {
            "question": "garage plug is the beer fridge",
            "answer": "No — it's the chest freezer"}, "admin")
        self.drain()
        self.assertEqual(self.hyp.list_all("open"), [])
        self.assertEqual([h["status"] for h in self.hyp.list_all()],
                         ["rejected"])
        facts = self.facts()
        self.assertEqual([f["source"] for f in facts], ["correction"])
        self.assertIn("chest freezer", facts[0]["fact"])

    def test_an_answer_that_is_neither_is_refused_and_writes_nothing(self):
        with self.assertRaises(env.ServiceValidationError):
            self.run_service("answer_question", {"ts": self.guess["ts"],
                                                 "answer": "Like weekends"},
                             "admin")
        self.assertEqual(self.drain(), [])

    def test_a_guess_that_is_not_open_is_refused_by_name(self):
        with self.assertRaises(env.ServiceValidationError):
            self.run_service("answer_question", {"ts": 12345, "answer": "yes"},
                             "admin")


if __name__ == "__main__":
    unittest.main()
