#!/usr/bin/env python3
"""Five quiet failures in the panel's own housekeeping.

None of these is a feature being wrong; each is a piece of bookkeeping that
was right about the moment it was written down and wrong a moment later.

* **A rewrite is a write of what was READ** — `_drop_from_inbox` reads every
  memory inbox file and rewrites the one holding the dropped line, and the
  consolidator is a separate process that ARCHIVES those files by moving
  them into `processed/`. Landing the rewrite after the move recreates the
  file at its inbox path, so a press that removed one fact resurrects every
  other fact in it as pending and the next pass files them a second time.
  The old recipe is run here on the same fixture to show it doing exactly
  that, because a guard measured against a described failure is a guard
  measured against nothing.
* **`asyncio.create_task` only SCHEDULES**, so a guard read inside the
  coroutine is one two presses in the same tick both walk past. Every other
  spawn in `server.py` flips its flag synchronously first; the scene
  designer did not, and two presses on one room bought two Claude naming
  runs.
* **`JOBS` had no ending.** A card's job is keyed on the card, but a fix or
  a plan is keyed on a finding's timestamp, so the dict grew for the life of
  the process and only a restart emptied it.
* **Blocking IO on the event loop** — a `Path.read_text` in a coroutine is a
  disk read that stops every other request while it happens, and the panel
  did one per past run, per card read, per asset served.
* **One analytical pass was still posting the whole house.** Onboarding's
  recommend step ran the tool-free path long after every other one had
  moved to a map plus read-only tools, which is the pass least able to
  afford it: it is asked to say which cards THIS home should have, and a
  capped snapshot is the part of the house that fitted under the cap.

The static-asset test asserts the bytes are unchanged as well as the thread
they were read on: a cache that serves something subtly different is a
worse bug than the read it replaced.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import atomic_write  # noqa: E402

from test_todo_list import PanelCase  # noqa: E402


# ---------------------------------------------------------------------------
# B2 — the inbox line dropped out from under a consolidation pass
# ---------------------------------------------------------------------------

FACTS = [
    {"ts": 1, "source": "panel", "fact": "the hall radiator is the cold one"},
    {"ts": 2, "source": "panel", "fact": "the dryer is in the garage"},
    {"ts": 3, "source": "voice", "fact": "bins go out on a Tuesday"},
]


def old_drop_from_inbox(server, item_id: str) -> bool:
    """`_drop_from_inbox` as it shipped: read everything, rewrite the file.

    Lifted rather than described, so the failure this fix is about is one
    the suite has watched happen — `consolidator_lock_check`'s arrangement.
    """
    kept: dict[Path, list[dict]] = {}
    dropped: set[Path] = set()
    for path, obj in server._inbox_lines():
        if server._inbox_id(str(obj.get("source") or ""),
                            str(obj["fact"]).strip()) == item_id:
            dropped.add(path)
        else:
            kept.setdefault(path, []).append(obj)
    if not dropped:
        return False
    for path in dropped:
        lines = kept.get(path, [])
        try:
            if lines:
                atomic_write.write_lines(path, lines)
            else:
                path.unlink()
        except OSError:
            # What the shipped version did: a line it could not remove was
            # left for the next pass. Kept as it was, because this function
            # is here to reproduce that behaviour and not to improve on it.
            pass
    return True


class InboxRaceCase(unittest.TestCase):
    """A real inbox directory, a real lock file, a real archive move."""

    @classmethod
    def setUpClass(cls):
        import importlib
        cls.server = importlib.import_module("server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.inbox = tmp / "inbox"
        self.processed = self.inbox / "processed"
        self.inbox.mkdir(parents=True)
        self.processed.mkdir()
        self.lock = tmp / ".consolidate.lock"
        self.lock.write_text("")
        self._old = (self.server.MEMORY_INBOX_DIR, self.server.CONSOLIDATE_LOCK)
        self.server.MEMORY_INBOX_DIR = self.inbox
        self.server.CONSOLIDATE_LOCK = self.lock
        self.queued = self.inbox / "1700000000-panel.jsonl"
        self.write_queue()

    def tearDown(self):
        (self.server.MEMORY_INBOX_DIR,
         self.server.CONSOLIDATE_LOCK) = self._old
        self.tmp.cleanup()

    def write_queue(self) -> None:
        self.queued.write_text(
            "".join(json.dumps(f) + "\n" for f in FACTS), encoding="utf-8")

    def dropped_id(self) -> str:
        return self.server._inbox_id(FACTS[1]["source"], FACTS[1]["fact"])

    def archive(self) -> None:
        """What `brain-memory-consolidate.sh` does once a pass has filed."""
        self.queued.rename(self.processed / self.queued.name)

    def test_the_old_recipe_resurrects_a_queue_a_pass_had_taken(self):
        """The failure, on the real fixture, before the fix is asserted."""
        item_id = self.dropped_id()
        real = self.server._inbox_lines

        def read_then_lose_the_race():
            lines = real()
            self.archive()          # the consolidator files and archives
            return lines

        self.server._inbox_lines = read_then_lose_the_race
        try:
            old_drop_from_inbox(self.server, item_id)
        finally:
            self.server._inbox_lines = real

        self.assertTrue(
            self.queued.exists(),
            "the old recipe was supposed to recreate the archived file")
        back = [json.loads(ln) for ln in
                self.queued.read_text().splitlines() if ln.strip()]
        self.assertEqual([f["fact"] for f in back],
                         [FACTS[0]["fact"], FACTS[2]["fact"]],
                         "two already-filed facts came back as pending")

    def test_a_file_archived_mid_press_is_not_recreated(self):
        item_id = self.dropped_id()
        real = self.server._inbox_lines

        def read_then_lose_the_race():
            lines = real()
            self.archive()
            return lines

        self.server._inbox_lines = read_then_lose_the_race
        try:
            self.assertTrue(self.server._drop_from_inbox(item_id))
        finally:
            self.server._inbox_lines = real

        self.assertFalse(self.queued.exists(),
                         "the inbox file was recreated after a pass took it")
        # And the pass's own archive is exactly as it left it.
        archived = [json.loads(ln) for ln in
                    (self.processed / self.queued.name).read_text().splitlines()
                    if ln.strip()]
        self.assertEqual(len(archived), 3)
        self.assertEqual(self.server._inbox_pending(), 0)

    def test_the_ordinary_press_still_takes_the_line_out(self):
        self.assertTrue(self.server._drop_from_inbox(self.dropped_id()))
        left = [json.loads(ln) for ln in
                self.queued.read_text().splitlines() if ln.strip()]
        self.assertEqual([f["fact"] for f in left],
                         [FACTS[0]["fact"], FACTS[2]["fact"]])
        self.assertEqual(self.server._inbox_pending(), 2)

    def test_dropping_the_only_line_removes_the_file(self):
        only = {"ts": 9, "source": "panel", "fact": "the loft hatch sticks"}
        self.queued.write_text(json.dumps(only) + "\n", encoding="utf-8")
        self.assertTrue(self.server._drop_from_inbox(
            self.server._inbox_id(only["source"], only["fact"])))
        self.assertFalse(self.queued.exists())

    def test_an_unknown_id_is_still_a_no(self):
        self.assertFalse(self.server._drop_from_inbox("0" * 16))
        self.assertEqual(self.server._inbox_pending(), 3)

    def test_a_pass_holding_the_lock_does_not_make_the_press_wait(self):
        """The probe is SHARED and non-blocking, `_consolidation_running`'s
        rule: asking a question must never be something a real pass can
        block on, and a press that hung for the length of a consolidation
        is a panel that has stopped answering."""
        script = (
            "import fcntl, sys, time\n"
            "fd = open(sys.argv[1], 'r')\n"
            "fcntl.flock(fd, fcntl.LOCK_EX)\n"
            "print('held', flush=True)\n"
            "time.sleep(30)\n"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", script, str(self.lock)],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            started = time.time()
            self.assertTrue(self.server._drop_from_inbox(self.dropped_id()))
            self.assertLess(time.time() - started, 5,
                            "the press waited on the consolidator's lock")
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()
        # It still did the work: the lock is a shortcut, the fingerprint is
        # the guard, and with the file untouched there was nothing to stop.
        left = [json.loads(ln) for ln in
                self.queued.read_text().splitlines() if ln.strip()]
        self.assertEqual(len(left), 2)


# ---------------------------------------------------------------------------
# B5 — two presses, one room, two Claude runs
# ---------------------------------------------------------------------------

class SceneDesignCase(PanelCase):
    def setUp(self):
        super().setUp()
        self.server.SCENES_INFLIGHT.clear()
        self.spawned: list[str] = []
        self._patched = (
            self.server.checks.snapshot.collect_rooms,
            self.server.scenes.build,
            self.server.proposals.knows,
            self.server.automation_writer.protected_patterns,
            self.server._name_and_offer,
        )
        self.release = asyncio.Event()

        async def collect_rooms():
            # Two awaits, so a second call really does land inside the
            # first — without them the test would pass on serialisation
            # rather than on the guard.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return {"states": {}}

        async def name_and_offer(obj, area):
            self.spawned.append(area)
            await self.release.wait()

        self.server.checks.snapshot.collect_rooms = collect_rooms
        self.server.scenes.build = lambda *a, **k: {
            "scene": {"lights": ["light.a", "light.b"]}}
        self.server.proposals.knows = lambda obj: False
        self.server.automation_writer.protected_patterns = lambda: []
        self.server._name_and_offer = name_and_offer

    async def settle(self) -> None:
        """Let every spawned naming run reach its end.

        A task still pending when the loop closes is a warning printed
        against whichever test happens to be running next, which is the
        shape of noise that makes a suite stop being read.
        """
        await asyncio.sleep(0)          # let the task start
        self.release.set()
        for _ in range(50):
            await asyncio.sleep(0)
            if not self.server.SCENES_INFLIGHT:
                return

    def tearDown(self):
        (self.server.checks.snapshot.collect_rooms,
         self.server.scenes.build,
         self.server.proposals.knows,
         self.server.automation_writer.protected_patterns,
         self.server._name_and_offer) = self._patched
        self.server.SCENES_INFLIGHT.clear()
        super().tearDown()

    def test_two_presses_for_one_room_spawn_one_naming_run(self):
        async def body():
            first, second = await asyncio.gather(
                self.server._design_scenes("Kitchen"),
                self.server._design_scenes("kitchen"))
            await self.settle()
            return first, second

        first, second = asyncio.run(body())
        self.assertEqual(self.spawned, ["Kitchen"],
                         "the second press bought a second Claude run")
        self.assertEqual(first.get("scenes"), "Kitchen")
        self.assertIn("already composing", second.get("refused", ""))
        self.assertEqual(second.get("area"), "kitchen")

    def test_the_claim_is_given_back_when_the_run_ends(self):
        async def body():
            out = await self.server._design_scenes("Kitchen")
            # The wrapper's `finally` runs on the task, not on us.
            await self.settle()
            return out

        asyncio.run(body())
        self.assertEqual(self.server.SCENES_INFLIGHT, set())

    def test_a_refusal_does_not_lock_the_room_out(self):
        """Every ending that spawns nothing hands the claim straight back,
        or one unreadable house means that room can never be asked for
        again without a restart."""
        self.server.scenes.build = lambda *a, **k: {
            "refused": "the box room has one light in it"}

        async def body():
            return [await self.server._design_scenes("Box room")
                    for _ in range(2)]

        outs = asyncio.run(body())
        self.assertEqual(self.server.SCENES_INFLIGHT, set())
        for out in outs:
            self.assertIn("one light", out["refused"])
        self.assertEqual(self.spawned, [])

    def test_a_house_that_could_not_be_read_hands_the_claim_back(self):
        async def boom():
            raise RuntimeError("Home Assistant said no")

        self.server.checks.snapshot.collect_rooms = boom
        out = asyncio.run(self.server._design_scenes("Kitchen"))
        self.assertIn("could not read the house", out["refused"])
        self.assertEqual(self.server.SCENES_INFLIGHT, set())

    def test_a_different_room_is_never_held_up(self):
        async def body():
            outs = await asyncio.gather(
                self.server._design_scenes("Kitchen"),
                self.server._design_scenes("Landing"))
            await self.settle()
            return outs

        outs = asyncio.run(body())
        self.assertEqual(sorted(self.spawned), ["Kitchen", "Landing"])
        for out in outs:
            self.assertNotIn("refused", out)


# ---------------------------------------------------------------------------
# B6 — a job ledger with no ending
# ---------------------------------------------------------------------------

class JobPruneCase(PanelCase):
    def finished(self, job_id: str, age_s: float) -> None:
        self.server.JOBS[job_id] = {"kind": "fix", "state": "done",
                                    "updated_at": time.time() - age_s}

    def test_a_finished_job_is_forgotten_once_it_is_old(self):
        self.finished("fix:1700000001", self.server.JOB_TTL_S + 60)
        self.finished("plan:1700000002", self.server.JOB_TTL_S + 60)
        self.server._set_job("fix:1700000003", state="done")
        self.assertEqual(sorted(self.server.JOBS), ["fix:1700000003"])

    def test_a_fresh_one_is_kept_because_somebody_may_be_reading_it(self):
        self.finished("fix:1700000001", 5)
        self.server._set_job("fix:1700000002", state="error", error="nope")
        self.assertEqual(sorted(self.server.JOBS),
                         ["fix:1700000001", "fix:1700000002"])

    def test_a_running_job_is_never_taken_however_old_it_looks(self):
        """The record is how the worker finds its own `kind` and how the
        status poll reports a spinner; evicting one live is a card that
        generates into nothing."""
        for state in ("queued", "generating", "planning", "fixing",
                      "searching"):
            with self.subTest(state=state):
                self.server.JOBS.clear()
                self.server.JOBS["live"] = {
                    "kind": "fix", "state": state,
                    "updated_at": time.time() - 30 * 86400}
                for n in range(self.server.MAX_JOBS + 20):
                    self.finished(f"fix:{n}", 1)
                self.server._prune_jobs()
                self.assertIn("live", self.server.JOBS)

    def test_the_cap_bounds_a_burst_the_age_has_not_caught_up_with(self):
        for n in range(self.server.MAX_JOBS + 40):
            self.finished(f"fix:{n}", 1)
        self.server._prune_jobs()
        self.assertLessEqual(len(self.server.JOBS), self.server.MAX_JOBS)

    def test_the_oldest_go_first(self):
        self.finished("fix:old", 60)
        self.finished("fix:new", 1)
        old_cap = self.server.MAX_JOBS
        self.server.MAX_JOBS = 1
        try:
            self.server._prune_jobs()
        finally:
            self.server.MAX_JOBS = old_cap
        self.assertEqual(sorted(self.server.JOBS), ["fix:new"])

    def test_a_run_that_is_still_queued_is_not_charged_for_the_cap(self):
        """The cap bounds what has FINISHED — a panel with 200 runs in
        flight has a different problem, and dropping one to make room
        would be the only copy of what that run is."""
        old_cap = self.server.MAX_JOBS
        self.server.MAX_JOBS = 2
        try:
            for n in range(5):
                self.server.JOBS[f"live:{n}"] = {
                    "kind": "fix", "state": "queued", "updated_at": time.time()}
            self.server._prune_jobs()
        finally:
            self.server.MAX_JOBS = old_cap
        self.assertEqual(len(self.server.JOBS), 5)


# ---------------------------------------------------------------------------
# B7 — the reads that were happening on the event loop
# ---------------------------------------------------------------------------

class OffTheLoopCase(PanelCase):
    """Every read here used to happen in the coroutine that served it."""

    def setUp(self):
        super().setUp()
        self.reads: list[tuple[str, str]] = []
        self._read_text = Path.read_text

        def watched(path, *a, **k):
            self.reads.append((threading.current_thread().name, str(path)))
            return self._read_text(path, *a, **k)

        Path.read_text = watched

    def tearDown(self):
        Path.read_text = self._read_text
        super().tearDown()

    def threads_for(self, name: str) -> list[str]:
        """Which threads read the file this test is about.

        Keyed on the path rather than on "anything read during the
        request": the panel reads its settings, its credential store and
        half a dozen other things while a test server starts, and a test
        that failed because one of THOSE happened on the loop would be a
        test about something it never claimed to be about.
        """
        return [thread for thread, path in self.reads
                if path.endswith(name)]

    def write_run(self, card="energy", ts="2026-09-17T08-00-00") -> dict:
        obj = {"generated_at": "2026-09-17T08:00:00", "title": "Last week",
               "html": "<p>x</p>"}
        hdir = self.server.INSIGHTS_DIR / "history" / card
        hdir.mkdir(parents=True, exist_ok=True)
        (hdir / f"{ts}.json").write_text(json.dumps(obj), encoding="utf-8")
        return obj

    def test_a_stored_run_is_read_off_the_event_loop(self):
        obj = self.write_run()

        async def body(client):
            res = await client.get(
                "/api/insight/energy/history/2026-09-17T08-00-00")
            self.assertEqual(res.status, 200)
            return await res.json()

        self.reads.clear()
        got = self.drive(body)
        self.assertEqual(got["title"], obj["title"])
        threads = self.threads_for("2026-09-17T08-00-00.json")
        self.assertTrue(threads, "nothing read the file at all")
        self.assertNotIn("MainThread", threads,
                         "the stored run was read on the event loop")

    def test_the_listing_is_read_off_the_event_loop_too(self):
        self.write_run()
        self.write_run(ts="2026-09-16T08-00-00")

        async def body(client):
            res = await client.get("/api/insight/energy/history")
            self.assertEqual(res.status, 200)
            return await res.json()

        self.reads.clear()
        payload = self.drive(body)
        self.assertEqual([r["ts"] for r in payload["runs"]],
                         ["2026-09-17T08-00-00", "2026-09-16T08-00-00"])
        threads = self.threads_for("2026-09-16T08-00-00.json")
        self.assertTrue(threads, "nothing read the past runs at all")
        self.assertNotIn("MainThread", threads)

    def test_a_missing_run_is_still_a_404(self):
        async def body(client):
            res = await client.get(
                "/api/insight/energy/history/2026-09-17T08-00-00")
            return res.status

        self.assertEqual(self.drive(body), 404)

    def test_the_panel_serves_its_own_files_byte_for_byte(self):
        on_disk = {name: (self.server.HERE / name).read_bytes()
                   for name in ("style.css", "app.js", "docs.js")}

        async def body(client):
            out = {}
            for name in on_disk:
                res = await client.get(f"/{name}")
                self.assertEqual(res.status, 200)
                out[name] = await res.read()
            return out

        self.assertEqual(self.drive(body), on_disk)

    def test_the_index_still_carries_the_version_and_is_read_off_the_loop(self):
        async def body(client):
            # Emptied HERE rather than before `drive`, because startup warms
            # the cache off the loop — pop it earlier and the request is a
            # cache hit that reads nothing, which proves the cache works and
            # says nothing about the thread the miss would have read on.
            self.server._STATIC_CACHE.pop("index.html", None)
            self.reads.clear()
            res = await client.get("/")
            self.assertEqual(res.status, 200)
            return await res.text()

        html = self.drive(body)
        self.assertIn(self.server.ADDON_VERSION, html)
        self.assertNotIn("{{VERSION}}", html)
        threads = self.threads_for("index.html")
        self.assertTrue(threads, "the page was never read at all")
        self.assertNotIn("MainThread", threads)

    def test_an_asset_read_once_is_served_from_memory(self):
        """Not an optimisation for its own sake: the second request costs a
        `stat` where it used to cost the whole file, and app.js is the
        biggest thing the panel serves."""
        self.server._read_static("app.js")          # warm it
        before = len(self.threads_for("app.js"))
        self.server._read_static("app.js")
        self.assertEqual(len(self.threads_for("app.js")), before,
                         "the cached asset was read from disk again")


# ---------------------------------------------------------------------------
# B10 — the one analytical pass still posting the whole house
# ---------------------------------------------------------------------------

ORIENTATION = {
    "meta": {"now": "2026-09-18T09:00:00", "timezone": "Europe/London"},
    "entity_count": 812,
    "domains": {"sensor": 400, "light": 40},
    "areas": {"Kitchen": 30},
    "anchors": [{"e": "weather.home", "s": "cloudy"}],
}

RECOMMENDED = json.dumps({
    "recommendations": [{"title": "Heat pump share", "icon": "🔥",
                         "focus": "climate.heat_pump against the rest",
                         "why": "it is 60% of what the house draws"}],
    "shipped": [], "sparse": False})


class OnboardingRecommendCase(PanelCase):
    def setUp(self):
        super().setUp()
        import engine
        import ha_data
        self.engine, self.ha_data = engine, ha_data
        self.calls: list[tuple] = []
        self._patched = (engine.get_auth, engine.run_analyst,
                         engine.run_claude, ha_data.collect_orientation,
                         ha_data.collect_bundle)
        # The panel re-earns its auth verdict at startup with a real
        # `claude -p` turn, so run_claude has a legitimate caller here; what
        # is watched for is the recommend prompt reaching it.
        auth_check = engine.run_claude
        self.analyst_reply = {"ok": True, "text": RECOMMENDED, "error": "",
                              "meta": {}}
        self.claude_reply = {"ok": True, "text": RECOMMENDED, "error": "",
                             "meta": {}}

        async def orientation(question=None):
            return dict(ORIENTATION)

        async def bundle(*a, **k):
            self.calls.append(("bundle", a, k))
            return {"entities": [{"e": "climate.heat_pump", "s": "heat"}]}

        def analyst(prompt, system, *a, **k):
            self.calls.append(("analyst", prompt, system))
            return self.analyst_reply

        def run_claude(prompt, system="", *a, **k):
            if system != self.server.onboarding.RECOMMEND_SYSTEM:
                return auth_check(prompt, system, *a, **k)
            self.calls.append(("snapshot", prompt, system))
            return self.claude_reply

        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        engine.run_analyst = analyst
        engine.run_claude = run_claude
        ha_data.collect_orientation = orientation
        ha_data.collect_bundle = bundle

    def tearDown(self):
        (self.engine.get_auth, self.engine.run_analyst, self.engine.run_claude,
         self.ha_data.collect_orientation,
         self.ha_data.collect_bundle) = self._patched
        super().tearDown()

    def recommend(self):
        async def body(client):
            res = await client.post("/api/onboarding/recommend")
            return res.status, await res.text()

        return self.drive(body)

    def test_the_recommend_pass_is_an_analyst_run_over_the_map(self):
        status, text = self.recommend()
        self.assertEqual(status, 200, text)
        self.assertEqual([c[0] for c in self.calls], ["analyst"],
                         "the whole house was posted in a tool-free turn")
        prompt = self.calls[0][1]
        self.assertIn("MAP OF THIS HOME", prompt)
        self.assertIn("read-only Home Assistant tools", prompt)
        self.assertIn('"entity_count":812', prompt.replace(" ", ""))
        self.assertEqual(self.calls[0][2],
                         self.server.onboarding.RECOMMEND_SYSTEM)
        self.assertEqual(
            [r["title"] for r in json.loads(text)["recommendations"]],
            ["Heat pump share"])

    def test_the_system_prompt_says_the_tools_are_read_only(self):
        self.assertIn("READ-ONLY", self.server.onboarding.RECOMMEND_SYSTEM)

    def test_a_map_that_could_not_be_collected_falls_back_to_the_snapshot(self):
        """`_search_run`'s floor, one step earlier in a person's day: the
        one screen between a fresh install and having any cards must not
        dead-end because a map fetch timed out."""
        async def boom(question=None):
            raise RuntimeError("Home Assistant said no")

        self.ha_data.collect_orientation = boom
        status, text = self.recommend()
        self.assertEqual(status, 200, text)
        self.assertEqual([c[0] for c in self.calls], ["bundle", "snapshot"])
        self.assertIn("HOME DATA SNAPSHOT", self.calls[1][1])

    def test_a_searching_run_that_failed_falls_back_too(self):
        self.analyst_reply = {"ok": False, "text": "", "error": "timed out",
                              "meta": {}}
        status, text = self.recommend()
        self.assertEqual(status, 200, text)
        self.assertEqual([c[0] for c in self.calls],
                         ["analyst", "bundle", "snapshot"])

    def test_a_reply_that_did_not_parse_falls_back_too(self):
        self.analyst_reply = {"ok": True, "text": "I'm sorry, I can't do that.",
                              "error": "", "meta": {}}
        status, text = self.recommend()
        self.assertEqual(status, 200, text)
        self.assertEqual([c[0] for c in self.calls],
                         ["analyst", "bundle", "snapshot"])

    def test_neither_path_reading_the_house_is_a_502_and_not_a_500(self):
        async def boom(question=None):
            raise RuntimeError("Home Assistant said no")

        async def bundle_boom(*a, **k):
            raise RuntimeError("Home Assistant said no")

        self.ha_data.collect_orientation = boom
        self.ha_data.collect_bundle = bundle_boom
        status, text = self.recommend()
        self.assertEqual(status, 502)
        self.assertIn("could not read Home Assistant", text)
        self.assertEqual(self.calls, [])

    def test_both_runs_failing_says_what_the_last_one_said(self):
        self.analyst_reply = {"ok": False, "text": "", "error": "timed out",
                              "meta": {}}
        self.claude_reply = {"ok": False, "text": "",
                             "error": "the model was overloaded", "meta": {}}
        status, text = self.recommend()
        self.assertEqual(status, 502)
        self.assertIn("overloaded", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
