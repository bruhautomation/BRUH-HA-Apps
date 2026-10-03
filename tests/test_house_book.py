#!/usr/bin/env python3
"""The house book — every sentence cited, nothing secret, and a link that
can be taken back.

  * a code in an automation never reaches the run, and a code the run
    writes anyway never reaches the page (redacted on the way in AND out);
  * a sentence citing nothing that was given is dropped and counted;
  * gap questions are filed as question cases through `triage.gate`, at
    most three a run, never twice about one subject, and their answer is
    TYPED — the route refuses an empty one;
  * Publish writes under the book's own token in a folder the card-mirror
    sweep does not touch (driven against the real `_sync_card_mirrors`),
    and Revoke deletes it and rotates the token so the old URL is dead;
  * the weekly regeneration holds when nothing it reads has moved, holds
    when a gate is closed, and never runs for a house that has not asked
    for a book at all.
"""

import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import house_book  # noqa: E402
from fake_core_ws import drive_app  # noqa: E402


def snap() -> dict:
    return {
        "states": {
            "switch.mains_valve": {"state": "on", "attributes": {
                "friendly_name": "Mains valve"}},
            "binary_sensor.utility_leak": {"state": "off", "attributes": {
                "friendly_name": "Utility leak", "device_class": "moisture"}},
            "alarm_control_panel.home": {"state": "disarmed", "attributes": {
                "friendly_name": "House alarm"}},
            "climate.hall": {"state": "heat", "attributes": {
                "friendly_name": "Hall thermostat"}},
        },
        "entities": [], "devices": [],
        "areas": [{"area_id": "utility", "name": "Utility"}],
        "automations": [
            {"id": "brain_playbook_leak", "alias": "Leak: close the water",
             "triggers": [{"trigger": "state",
                           "entity_id": "binary_sensor.utility_leak",
                           "to": "on"}],
             "actions": [{"action": "switch.turn_off",
                          "target": {"entity_id": "switch.mains_valve"}}]},
            {"id": "arm-at-night", "alias": "Arm at night",
             "actions": [{"action": "alarm_control_panel.alarm_arm_night",
                          "target": {"entity_id": "alarm_control_panel.home"},
                          "data": {"code": "4821"}}]},
        ],
        "scripts": {}, "scenes": [],
    }


def reply(sections=None, questions=None) -> dict:
    return {"sections": sections if sections is not None else [
        {"key": "alarms", "entries": [
            {"text": "If the utility leak alarm sounds, the house closes the "
                     "mains water valve.",
             "sources": [{"kind": "automation", "id": "brain_playbook_leak"},
                         {"kind": "entity", "id": "switch.mains_valve"}]}]}],
        "questions": questions if questions is not None else [
            {"question": "Where is the valve switch.mains_valve closes, in "
                         "case the switch fails?",
             "why": "The leak playbook relies on it.",
             "subject": {"kind": "entity", "id": "switch.mains_valve"}}]}


class TestNothingSecretGoesIn(unittest.TestCase):
    def test_an_alarm_code_never_reaches_the_run(self):
        dig = house_book.digest(snap())
        frame = house_book.frame(dig)
        self.assertNotIn("4821", frame)
        self.assertIn("Arm at night", frame)

    def test_secrets_yaml_is_not_an_input(self):
        """The book reads automations, scripts, scenes and facts — and the
        fingerprint names exactly those files, never secrets.yaml."""
        fp = house_book.fingerprint(snap(), config_dir="/nonexistent")
        self.assertEqual(sorted(fp["parts"]),
                         ["areas", "automations", "facts", "scenes", "scripts"])


class TestEverySentenceIsCited(unittest.TestCase):
    def setUp(self):
        self.dig = house_book.digest(snap())

    def test_a_cited_sentence_stands_with_its_labels(self):
        out = house_book.parse(reply(), self.dig)
        [section] = out["sections"]
        self.assertEqual(section["title"], house_book.SECTIONS["alarms"])
        labels = [s["label"] for s in section["entries"][0]["sources"]]
        self.assertEqual(labels, ["Leak: close the water", "Mains valve"])

    def test_a_sentence_citing_nothing_given_is_dropped_and_counted(self):
        out = house_book.parse(reply(sections=[{"key": "shutoffs", "entries": [
            {"text": "The stopcock is under the sink.", "sources": []},
            {"text": "The gas meter is outside.",
             "sources": [{"kind": "entity", "id": "sensor.gas_invented"}]},
            {"text": "Water closes on a leak.",
             "sources": [{"kind": "automation", "id": "brain_playbook_leak"}]}]}],
            questions=[]), self.dig)
        self.assertEqual(out["uncited"], 2)
        self.assertEqual([e["text"] for e in out["sections"][0]["entries"]],
                         ["Water closes on a leak."])

    def test_a_section_outside_the_vocabulary_is_ignored(self):
        out = house_book.parse(reply(sections=[{"key": "gossip", "entries": [
            {"text": "x", "sources": [{"kind": "area", "id": "utility"}]}]}],
            questions=[]), self.dig)
        self.assertEqual(out["sections"], [])

    def test_a_code_the_run_writes_anyway_is_redacted_on_the_way_out(self):
        out = house_book.parse(reply(sections=[{"key": "alarms", "entries": [
            {"text": "Arm it at night; the alarm code is 4821.",
             "sources": [{"kind": "automation", "id": "arm-at-night"}]}]}],
            questions=[]), self.dig)
        text = out["sections"][0]["entries"][0]["text"]
        self.assertNotIn("4821", text)
        self.assertEqual(out["redacted"], 1)


class TestGapQuestions(unittest.TestCase):
    def setUp(self):
        self.dig = house_book.digest(snap())

    def test_a_question_about_something_given_is_filed_as_a_question(self):
        out = house_book.parse(reply(), self.dig)
        rows = house_book.question_rows(out["questions"], [], 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "question")
        self.assertEqual(rows[0]["source"], house_book.SOURCE)
        self.assertEqual(rows[0]["entity_id"], "switch.mains_valve")
        self.assertEqual(rows[0]["_subject"], "entity:switch.mains_valve")

    def test_never_twice_about_one_subject_and_never_past_the_cap(self):
        out = house_book.parse(reply(), self.dig)
        self.assertEqual(house_book.question_rows(
            out["questions"], ["entity:switch.mains_valve"], 0), [])
        self.assertEqual(house_book.question_rows(
            out["questions"], [], house_book.MAX_OPEN_QUESTIONS), [])

    def test_a_subject_not_given_is_not_asked_about(self):
        out = house_book.parse(reply(questions=[
            {"question": "Where is the boiler?", "subject": {
                "kind": "entity", "id": "water_heater.made_up"}}]), self.dig)
        self.assertEqual(out["questions"], [])

    def test_three_a_run(self):
        q = {"question": "Where?", "subject": {"kind": "area", "id": "utility"}}
        out = house_book.parse(reply(questions=[q] * 6), self.dig)
        self.assertEqual(len(out["questions"]), house_book.MAX_QUESTIONS_PER_RUN)


class TestThePage(unittest.TestCase):
    def test_escaped_and_scriptless(self):
        page = house_book.render_page({"at": 0, "sections": [
            {"title": "Alarms", "entries": [{"text": "<script>x()</script> ok",
                                             "sources": [{"label": "A & B"}]}]}]})
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("A &amp; B", page)
        self.assertIn("noindex", page)


class TestPublishAndRevoke(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (server.WWW_CARD_DIR, house_book.TOKEN_FILE,
                     server.CARD_TOKEN_FILE)
        server.WWW_CARD_DIR = root / "www" / "brain"
        house_book.TOKEN_FILE = root / "secrets" / "house_book_token"
        server.CARD_TOKEN_FILE = root / "secrets" / "card_token"

    def tearDown(self):
        (self.server.WWW_CARD_DIR, house_book.TOKEN_FILE,
         self.server.CARD_TOKEN_FILE) = self._old
        self.tmp.cleanup()

    def test_published_under_its_own_token_and_the_card_sweep_leaves_it(self):
        book = {"at": time.time(), "sections": []}
        path = house_book.publish(book, self.server.WWW_CARD_DIR)
        token = house_book.TOKEN_FILE.read_text().strip()
        self.assertEqual(path, f"/local/brain/book/house-book-{token}.html")
        self.assertNotEqual(token, self.server.get_card_token())
        # The ▦ dialog's sweep deletes every *.html it does not recognise
        # in the mirror folder. It must not reach the book.
        self.assertTrue(self.server._sync_card_mirrors())
        on_disk = self.server.WWW_CARD_DIR / "book" / f"house-book-{token}.html"
        self.assertTrue(on_disk.exists())

    def test_revoke_deletes_and_the_old_url_is_dead(self):
        house_book.publish({"at": 0, "sections": []}, self.server.WWW_CARD_DIR)
        old = house_book.TOKEN_FILE.read_text().strip()
        removed = house_book.revoke(self.server.WWW_CARD_DIR)
        self.assertEqual(removed, 1)
        self.assertEqual(list((self.server.WWW_CARD_DIR / "book").glob("*.html")), [])
        self.assertNotEqual(house_book.TOKEN_FILE.read_text().strip(), old)
        # Publishing again lands at a NEW address.
        path = house_book.publish({"at": 0, "sections": []}, self.server.WWW_CARD_DIR)
        self.assertNotIn(old, path)


class BookPassCase(unittest.TestCase):
    def setUp(self):
        import server
        import settings_store
        self.server = server
        self.settings_store = settings_store
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "inbox").mkdir()
        fs = server.findings_store
        self._fs = {k: getattr(fs, k) for k in
                    ("FINDINGS_FILE", "INBOX_DIR", "SETTLED_FILE", "STATE_FILE")}
        fs.FINDINGS_FILE = root / "findings.json"
        fs.INBOX_DIR = root / "inbox"
        fs.SETTLED_FILE = root / "settled.json"
        fs.STATE_FILE = root / "config" / ".brain" / "state.json"
        self._book = house_book.STORE
        house_book.STORE = str(root / "book.json")
        # The tick also stamps the overnight check when it lands in its
        # window; that stamp belongs in this test's directory, not /data.
        self._schedule = server.schedule_store.STORE
        server.schedule_store.STORE = str(root / "schedule.json")
        self._settings = settings_store.SETTINGS_FILE
        settings_store.SETTINGS_FILE = str(root / "settings.json")
        settings_store.save({"onboarded": True, "auto_enabled": True})
        self._srv = (server.engine.run_claude, server.engine.get_auth,
                     server._book_snapshot, server._offer_findings,
                     server.MEMORY_INBOX_DIR, server._maint_start)
        server.MEMORY_INBOX_DIR = root / "memory-inbox"
        self.calls: list[dict] = []
        self.replies = [{"ok": True, "meta": {"session_id": "hb1"},
                         "data": reply()}]

        def run_claude(prompt, system, *a, **k):
            self.calls.append({"prompt": prompt, **k})
            return self.replies.pop(0) if self.replies else {
                "ok": False, "error": "no reply"}

        async def book_snapshot():
            return snap()

        server.engine.run_claude = run_claude
        server.engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        server._book_snapshot = book_snapshot
        server._offer_findings = lambda rows, now: len(rows)
        server.MAINT_STATE["book"].update(running=False, held="")

    def tearDown(self):
        fs = self.server.findings_store
        for k, v in self._fs.items():
            setattr(fs, k, v)
        house_book.STORE = self._book
        self.server.schedule_store.STORE = self._schedule
        self.settings_store.SETTINGS_FILE = self._settings
        (self.server.engine.run_claude, self.server.engine.get_auth,
         self.server._book_snapshot, self.server._offer_findings,
         self.server.MEMORY_INBOX_DIR, self.server._maint_start) = self._srv
        self.tmp.cleanup()


class TestThePass(BookPassCase):
    def test_a_pressed_book_is_stored_and_its_question_filed(self):
        asyncio.run(self.server._run_book("pressed", snap()))
        state = house_book.load()
        self.assertTrue(state["opted_in"])
        self.assertEqual(state["book"]["run_id"], "hb1")
        self.assertEqual(state["asked"], ["entity:switch.mains_valve"])
        self.assertEqual(self.calls[0]["job"], "house_book")
        [row] = [f for f in self.server.findings_store.list_all()
                 if f.get("source") == house_book.SOURCE]
        self.assertEqual(row["status"], "triaging")
        self.assertEqual(row["kind"], "question")

    def test_the_answer_is_typed_and_goes_into_memory(self):
        asyncio.run(self.server._run_book("pressed", snap()))
        [row] = [f for f in self.server.findings_store.list_all()
                 if f.get("source") == house_book.SOURCE]
        import answers
        situation = answers.situation({"kind": "question", "source": "house_book",
                                       "origin": {"store": "findings",
                                                  "key": row["ts"]}})
        self.assertEqual(situation, "gap")

        async def go(client):
            empty = await client.post(
                f"/api/house_book/question/{row['ts']}/answer", json={})
            good = await client.post(
                f"/api/house_book/question/{row['ts']}/answer",
                json={"note": "Behind the boiler, red lever."})
            return empty.status, good.status

        self.assertEqual(drive_app(self.server.make_app, go), (400, 200))
        self.assertIsNone(self.server.findings_store.get(row["ts"]))
        inbox = "\n".join(p.read_text() for p in
                          Path(self.server.MEMORY_INBOX_DIR).glob("*"))
        self.assertIn("Behind the boiler", inbox)


class TestTheWeeklyRegeneration(BookPassCase):
    def tick(self):
        started = []

        def fake_start(name, factory):
            started.append(name)
            return True

        self.server._maint_start = fake_start
        asyncio.run(self.server._maint_tick(time.time()))
        return started

    def test_a_house_that_never_asked_gets_no_book(self):
        self.assertNotIn("book", self.tick())

    def test_unchanged_inputs_hold_and_say_so(self):
        asyncio.run(self.server._run_book("pressed", snap()))
        self.assertNotIn("book", self.tick())
        self.assertEqual(house_book.load()["held"],
                         "nothing the book reads has changed")

    def test_moved_inputs_run_and_a_closed_gate_holds(self):
        state = house_book.load()
        state.update(opted_in=True, fingerprint={"parts": {"facts": "old"}})
        house_book.save(state)
        self.settings_store.save({"onboarded": True, "auto_enabled": False})
        self.assertNotIn("book", self.tick())
        self.assertIn("paused", house_book.load()["held"])
        state = house_book.load()
        state["last_weekly"] = 0
        house_book.save(state)
        self.settings_store.save({"onboarded": True, "auto_enabled": True})
        self.assertIn("book", self.tick())


if __name__ == "__main__":
    unittest.main()
