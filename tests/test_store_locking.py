#!/usr/bin/env python3
"""The stores' read-modify-write, and the writes it used to lose.

`atomic_write` makes a write indivisible and does nothing at all for a
*read-modify-write*, which is what every store in the panel performs: read
the whole file, change one entry, write it all back. A line another writer
appended between the read and the rename is not corrupted — it is gone,
and nothing raises, because the file the winner wrote is complete and
correct and simply predates it.

Three stores had it, each with its own second writer:

* ``hypotheses.jsonl`` has THREE, in three processes — the panel,
  ``brain-learn.sh`` appending with a bare ``>>``, and the consolidator's
  expiry rewrite. So the lock has to be one a Python module and a shell
  script can both take, which is why it is ``flock`` on a named sidecar
  and why both halves of that name are read out of the real files below.
* ``knowledge.json`` and ``feedback.json`` are written from the panel's
  own thread pool (``asyncio.to_thread``), so two overlapping requests are
  genuinely two threads loading the same list.

Every case reproduces the loss against the OLD recipe before asserting the
new one holds, and the hypothesis case drives a real subprocess appending
to the real file rather than a thread pretending to be one — the writer
that was losing rows is a shell script, and a thread is not one.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
SCRIPTS = BASE_DIR / "brain" / "scripts"
sys.path.insert(0, str(PANEL))

import atomic_write  # noqa: E402
import feedback_store  # noqa: E402
import hypotheses  # noqa: E402
import knowledge_store  # noqa: E402


# ---------------------------------------------------------------------------
# The two halves have to name the same file, or the lock is decoration
# ---------------------------------------------------------------------------

class TestBothHalvesNameTheSameLock(unittest.TestCase):
    """A lock whose Python half and shell half name different files is not
    a weaker lock, it is no lock — and it fails silently, which is the one
    property this whole module exists to remove. So the suffix is read out
    of the shell library rather than written down a second time here."""

    LIB = SCRIPTS / "brain-memory-lock.sh"

    def test_the_shell_library_ships(self):
        self.assertTrue(self.LIB.is_file(),
                        "brain-learn.sh and the consolidator both source this")

    def test_the_suffix_is_the_same_on_both_sides(self):
        shell = subprocess.run(
            ["bash", "-c",
             f'. "{self.LIB}"; brain_store_lock_path /tmp/store.jsonl'],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(shell.returncode, 0, shell.stderr)
        self.assertEqual(shell.stdout.strip(),
                         str(atomic_write.lock_path("/tmp/store.jsonl")))

    def test_the_shell_half_opens_the_lock_read_only(self):
        """`>` truncates the holder's file at open AND needs write
        permission on a file the other user may have created — the panel is
        root and a study session is `claude`."""
        text = self.LIB.read_text()
        self.assertIn("exec 7< ", text)
        self.assertNotIn("exec 7> ", text)

    def test_the_shell_half_keeps_off_the_consolidation_lock_s_fd(self):
        """The consolidator holds its pass lock on fd 9 and probes on 8 while
        this runs inside it; reusing either drops the lock that says only one
        consolidation runs at a time."""
        body = self.LIB.read_text()
        for stolen in ("exec 9<", "exec 9>", "exec 8<", "exec 8>"):
            self.assertNotIn(stolen, body)

    def test_it_polls_rather_than_asking_flock_to_wait(self):
        """BusyBox's flock takes only -sxnu and answers `-w` with usage and
        exit 1 — the same status as "the lock is held". That mistake once
        stopped memory updating at all."""
        body = self.LIB.read_text()
        self.assertIn("flock -n 7", body)
        self.assertNotIn("flock -w", body)


# ---------------------------------------------------------------------------
# The lock itself
# ---------------------------------------------------------------------------

class TestLockedHelper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "store.json"

    def test_it_is_a_sidecar_and_not_the_store(self):
        """`os.replace` swaps in a new inode, so a lock taken on the store
        is released into a file nobody can reach the moment the write
        lands, and the next writer locks a different inode."""
        with atomic_write.locked(self.store) as held:
            self.assertTrue(held)
            atomic_write.write_json(self.store, {"a": 1})
        lock = atomic_write.lock_path(self.store)
        self.assertTrue(lock.exists())
        self.assertNotEqual(lock, self.store)
        self.assertEqual(json.loads(self.store.read_text()), {"a": 1})

    def test_the_lock_file_is_owner_only_and_root_hands_it_over(self):
        """Root and the `claude` user each have to be able to take a lock
        the other created. Not by a group bit — anyone on the box could
        then stall a store's writers, and a scanner reads it as exactly
        that — but by ownership: root opens anything, so a lock the
        `claude` user owns is one both halves can take."""
        with atomic_write.locked(self.store):
            pass
        mode = atomic_write.lock_path(self.store).stat().st_mode & 0o777
        self.assertEqual(mode & 0o077, 0, oct(mode))
        # The owner is the store's own user where that is not root, else
        # the `claude` user; and only root hands it over.
        with mock.patch.object(atomic_write, "_preserved",
                               return_value=(0o644, 1234, 5678)):
            self.assertEqual(atomic_write._lock_owner(self.store), (1234, 5678))
        given: list[tuple] = []
        with mock.patch.object(atomic_write, "_preserved",
                               return_value=(0o644, 1234, 5678)), \
                mock.patch.object(atomic_write.os, "getuid", return_value=0), \
                mock.patch.object(atomic_write.os, "fchown",
                                  side_effect=lambda *a: given.append(a)):
            other = self.store.with_name("other.jsonl")
            with atomic_write.locked(other):
                pass
        self.assertEqual([g[1:] for g in given], [(1234, 5678)])
        # Not root: nothing to hand over, and nothing raised.
        given.clear()
        with mock.patch.object(atomic_write.os, "getuid", return_value=1000), \
                mock.patch.object(atomic_write.os, "fchown",
                                  side_effect=lambda *a: given.append(a)):
            with atomic_write.locked(self.store.with_name("third.jsonl")):
                pass
        self.assertEqual(given, [])

    def test_it_really_excludes_another_process(self):
        lock_held = threading.Event()
        release = threading.Event()

        def holder():
            with atomic_write.locked(self.store):
                lock_held.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        self.addCleanup(t.join)
        self.assertTrue(lock_held.wait(5))

        # A separate PROCESS, because flock is per open file description —
        # a second thread in this process would happily re-take it.
        probe = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(f"""
                import sys, time
                sys.path.insert(0, {str(PANEL)!r})
                import atomic_write
                start = time.monotonic()
                with atomic_write.locked({str(self.store)!r}, timeout=0.2) as held:
                    print(int(held), round(time.monotonic() - start, 2))
            """)], capture_output=True, text=True, timeout=30)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        got, waited = probe.stdout.split()
        self.assertEqual(got, "0", "the lock was held and was taken anyway")
        self.assertGreaterEqual(float(waited), 0.15, "it did not wait at all")
        release.set()

    def test_a_lock_it_cannot_take_never_refuses_the_work(self):
        """Past the timeout the caller proceeds unlocked, because what that
        leaves is exactly the behaviour every one of these stores had
        before — where refusing loses a homeowner's press over a stale
        lock, or over a filesystem that cannot lock at all."""
        lock = atomic_write.lock_path(self.store)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()
        import fcntl
        fd = os.open(lock, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            # Held by this process's own fd, so a SECOND open in the same
            # process still contends (flock keys on the description, not
            # the pid).
            with atomic_write.locked(self.store, timeout=0.05) as held:
                self.assertFalse(held)
        finally:
            os.close(fd)
            atomic_write.write_json(self.store, {"wrote": "anyway"})
        self.assertEqual(json.loads(self.store.read_text()), {"wrote": "anyway"})

    def test_shared_readers_do_not_block_each_other(self):
        """Asking a question of the file must never be something a real
        writer can be blocked by — or blocked on."""
        with atomic_write.locked(self.store, shared=True) as first:
            self.assertTrue(first)
            probe = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(f"""
                    import sys
                    sys.path.insert(0, {str(PANEL)!r})
                    import atomic_write
                    with atomic_write.locked(
                            {str(self.store)!r}, shared=True, timeout=0.5) as h:
                        print(int(h))
                """)], capture_output=True, text=True, timeout=30)
            self.assertEqual(probe.stdout.strip(), "1", probe.stderr)


# ---------------------------------------------------------------------------
# B1 — the hypothesis queue, against a real appending subprocess
# ---------------------------------------------------------------------------

APPENDER = textwrap.dedent("""
    import json, os, sys, time
    path, lock_lib, count, use_lock = sys.argv[1:5]
    sys.path.insert(0, os.path.dirname(lock_lib))
    import atomic_write
    for i in range(int(count)):
        line = json.dumps({"ts": 900000 + i, "text": "appended %d" % i,
                           "topic": "shell", "status": "open"})
        if use_lock == "1":
            with atomic_write.locked(path):
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\\n")
        else:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\\n")
        time.sleep(0.002)
""")


class HypothesisRaceCase(unittest.TestCase):
    ROUNDS = 60

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "hypotheses.jsonl"
        self._old = hypotheses.HYPOTHESES_FILE
        hypotheses.HYPOTHESES_FILE = self.path
        self.addCleanup(setattr, hypotheses, "HYPOTHESES_FILE", self._old)
        self.script = Path(self.tmp.name) / "appender.py"
        self.script.write_text(APPENDER)

    def _appender(self, use_lock: bool):
        return subprocess.Popen(
            [sys.executable, str(self.script), str(self.path),
             str(PANEL / "atomic_write.py"), str(self.ROUNDS),
             "1" if use_lock else "0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _appended(self) -> set[str]:
        return {e["text"] for e in hypotheses._read()
                if e["text"].startswith("appended ")}

    def _rewrite(self):
        """The panel's own shape: read the whole file, change ONE entry,
        write it all back. Nothing here removes a row — every append that
        goes missing went missing in the window."""
        entries = hypotheses._read()
        for e in entries:
            if e.get("text") == "panel":
                e["ts"] = int(e.get("ts") or 0) + 1
                break
        else:
            entries.append({"ts": 1, "text": "panel", "status": "expired"})
        hypotheses._write(entries)

    def _rewrite_repeatedly(self, locked: bool):
        """`locked=False` is the shipped code."""
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if locked:
                with atomic_write.locked(self.path):
                    self._rewrite()
            else:
                # The window, spelled out: the read and the rename are two
                # steps and an appender runs between them.
                entries = hypotheses._read()
                time.sleep(0.002)
                entries.append({"ts": 1, "text": "panel", "status": "expired"})
                hypotheses._write(entries)
            time.sleep(0.001)


class TestTheUnlockedReadModifyWriteLosesTheAppend(HypothesisRaceCase):
    def test_the_old_recipe_is_the_bug(self):
        """Not a test of our code — a test of the claim about the code it
        replaces, so the fix below is measured against a demonstrated
        failure rather than a described one."""
        proc = self._appender(use_lock=False)
        self._rewrite_repeatedly(locked=False)
        proc.wait(timeout=30)
        lost = self.ROUNDS - len(self._appended())
        self.assertGreater(
            lost, 0,
            "the unlocked read-modify-write was expected to swallow an "
            "append; if this stops failing the race window has moved, not "
            "closed")


class TestTheLockKeepsTheAppend(HypothesisRaceCase):
    def test_nothing_appended_under_the_lock_is_lost(self):
        proc = self._appender(use_lock=True)
        self._rewrite_repeatedly(locked=True)
        proc.wait(timeout=30)
        self.assertEqual(len(self._appended()), self.ROUNDS,
                         "an append landed inside a rewrite's window")


class TestTheQueueTakesItsOwnLock(HypothesisRaceCase):
    """The same claim through the module's own API rather than through a
    hand-rolled rewrite: `propose`/`confirm`/`reject`/`reopen` are the four
    read-modify-writes, and a real appending process runs against them."""

    def test_a_real_appender_survives_the_modules_own_writes(self):
        proc = self._appender(use_lock=True)
        deadline = time.monotonic() + 2.0
        n = 0
        while time.monotonic() < deadline:
            claim = f"a guess number {n}"
            entry = hypotheses.propose(claim, "panel")
            if entry:
                hypotheses.reject(entry["ts"], note="not here")
                hypotheses.reopen(entry["ts"])
                hypotheses.confirm(entry["ts"])
            n += 1
        proc.wait(timeout=30)
        self.assertEqual(len(self._appended()), self.ROUNDS)


class TestTheCapIsSettledUnderTheLock(HypothesisRaceCase):
    def test_two_threads_proposing_at_once_cannot_overfill_the_queue(self):
        """`propose` used to ask `is_known` and `budget` — two separate
        reads — and append on a third. Two runs proposing at once both saw
        room for one more and both took it, so a queue whose whole design
        is that it holds three held four."""
        def one(n):
            hypotheses.propose(f"claim number {n}", "race")

        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            list(pool.map(one, range(24)))
        self.assertEqual(len(hypotheses.list_all("open")), hypotheses.MAX_OPEN)

    def test_a_guess_is_never_proposed_twice(self):
        def one(_):
            hypotheses.propose("The garage fridge runs all year", "race")

        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            list(pool.map(one, range(16)))
        self.assertEqual(len(hypotheses.list_all()), 1)


class TestAReadIsNotAWrite(HypothesisRaceCase):
    """`list_all` expires stale entries, so asking what is open rewrote the
    file on every call — the Findings tab was a writer, competing with the
    two that had something to say."""

    def test_listing_a_fresh_queue_writes_nothing(self):
        hypotheses.propose("Something recent", "panel")
        before = self.path.stat().st_mtime_ns
        time.sleep(0.01)
        for _ in range(5):
            hypotheses.list_all("open")
        self.assertEqual(self.path.stat().st_mtime_ns, before,
                         "a read rewrote the queue")

    def test_something_that_has_aged_out_is_still_expired(self):
        stale = int(time.time()) - (hypotheses.TTL_DAYS + 1) * 86400
        self.path.write_text(json.dumps(
            {"ts": stale, "text": "Old guess", "status": "open"}) + "\n")
        self.assertEqual(hypotheses.list_all("open"), [])
        self.assertEqual([e["status"] for e in hypotheses.list_all()], ["expired"])
        # ...and written down, so the next pass does not re-derive it.
        stored = json.loads(self.path.read_text().splitlines()[0])
        self.assertEqual(stored["status"], "expired")


class TestTheRealShellLibraryTakesTheSameLock(HypothesisRaceCase):
    """The claim that matters, driven rather than argued.

    Every test above proves Python excludes Python. The writer that was
    actually losing rows is a shell script, so this appends with the real
    `brain_with_store_lock` out of `brain-memory-lock.sh` — the same
    function `brain-learn.sh` sources — while the Python store rewrites the
    same file. A flock the two halves take on two different files, or with
    a flag BusyBox refuses, would pass every grep in this module and fail
    exactly here.
    """

    SHELL_APPENDER = textwrap.dedent("""
        set -u
        . "$1"
        path="$2"
        rounds="$3"
        append() {
            local i="$1"
            local row
            row=$(printf '{"ts": %d, "text": "appended %d", "topic": "shell", "status": "open"}' "$((900000 + i))" "$i")
            printf '%s\n' "$row" >> "$path"
        }
        i=0
        while [ "$i" -lt "$rounds" ]; do
            brain_with_store_lock "$path" append "$i"
            i=$((i + 1))
            sleep 0.002
        done
    """)

    def test_a_real_shell_append_survives_the_panels_rewrite(self):
        runner = Path(self.tmp.name) / "append.sh"
        runner.write_text(self.SHELL_APPENDER)
        proc = subprocess.Popen(
            ["bash", str(runner), str(SCRIPTS / "brain-memory-lock.sh"),
             str(self.path), str(self.ROUNDS)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._rewrite_repeatedly(locked=True)
        _, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, err.decode())
        self.assertEqual(len(self._appended()), self.ROUNDS,
                         "a shell append landed inside the panel's window — "
                         "the two halves are not taking one lock")

    def test_taking_the_lock_does_not_swallow_the_callers_stderr(self):
        """`exec 7< f 2>/dev/null` with no command applies BOTH redirects
        to the shell for good — the first cut did exactly that, and every
        line a caller wrote to stderr afterwards (the consolidator's log,
        `brain memory`'s "the panel is not answering") went to /dev/null.
        Measured through a real bash rather than read, because the line
        looks right."""
        runner = Path(self.tmp.name) / "stderr.sh"
        runner.write_text(textwrap.dedent("""
            set -u
            . "$1"
            noop() { :; }
            brain_with_store_lock "$2" noop
            echo "still-heard" >&2
            # And the lock fd itself is released, not left open for the
            # process — a second take must succeed without waiting.
            BRAIN_STORE_LOCK_WAIT=0 brain_with_store_lock "$2" noop
            echo "twice" >&2
        """))
        proc = subprocess.run(
            ["bash", str(runner), str(SCRIPTS / "brain-memory-lock.sh"),
             str(self.path)], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("still-heard", proc.stderr)
        self.assertIn("twice", proc.stderr)


class TestTheConsolidatorTakesIt(HypothesisRaceCase):
    """`retire_stale_hypotheses` rewrites the whole queue, which makes the
    consolidator the third writer. Its own pass lock does not help: that
    one says only one CONSOLIDATION runs at a time, and the writer it loses
    to is a study session.

    Driven through the real script — sourced, its `--help` arm printing and
    stopping — so this is the shipped function and not a copy of it.
    """

    SCRIPT = SCRIPTS / "brain-memory-consolidate.sh"

    def _retire_loop(self, locked: bool, seconds: float = 2.0):
        # Dropping the lock leaves exactly the shipped-before body: read the
        # file with jq, rename the result over the top.
        unlock = "" if locked else \
            'brain_with_store_lock() { shift; "$@"; };'
        script = (f'. "{self.SCRIPT}" --help > /dev/null; {unlock}'
                  f'end=$(( $(date +%s) + {int(seconds)} ));'
                  'while [ "$(date +%s)" -lt "$end" ]; do'
                  '  retire_stale_hypotheses; done')
        return subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=120,
            env={**os.environ,
                 "BRAIN_MEMORY_DIR": str(self.path.parent),
                 "BRAIN_STORE_LOCK_LIB": str(SCRIPTS / "brain-memory-lock.sh")})

    def _seed_stale(self):
        stale = int(time.time()) - 365 * 86400
        self.path.write_text(json.dumps(
            {"ts": stale, "text": "Old guess", "status": "open"}) + "\n")

    def test_the_unlocked_rewrite_is_the_bug(self):
        """The claim about the code this replaces, demonstrated."""
        self._seed_stale()
        proc = self._appender(use_lock=True)
        done = self._retire_loop(locked=False)
        proc.wait(timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertLess(
            len(self._appended()), self.ROUNDS,
            "the unlocked expiry rewrite was expected to swallow an append; "
            "if this stops failing the window moved rather than closed")

    def test_it_holds_the_queues_lock_while_it_rewrites(self):
        self._seed_stale()
        proc = self._appender(use_lock=True)
        done = self._retire_loop(locked=True)
        proc.wait(timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self._appended()), self.ROUNDS,
                         "the expiry rewrite swallowed an append")
        # ...and it still did its job.
        self.assertEqual([e["status"] for e in hypotheses._read()
                          if e["text"] == "Old guess"], ["expired"])

    def test_it_creates_the_lock_beside_the_queue(self):
        self.path.write_text(json.dumps(
            {"ts": int(time.time()), "text": "Fresh", "status": "open"}) + "\n")
        self.assertEqual(self._retire_loop(locked=True, seconds=1).returncode, 0)
        self.assertTrue(atomic_write.lock_path(self.path).exists(),
                        "the consolidator did not take the queue's own lock")


# ---------------------------------------------------------------------------
# B13 — the two panel stores, two threads each
# ---------------------------------------------------------------------------

class ThreadedStoreCase(unittest.TestCase):
    WRITERS = 8
    ROUNDS = 12

    def _race(self, add):
        """Every writer adds ROUNDS distinct entries at once."""
        start = threading.Barrier(self.WRITERS)

        def writer(n):
            start.wait()
            for i in range(self.ROUNDS):
                add(n, i)

        with concurrent.futures.ThreadPoolExecutor(self.WRITERS) as pool:
            list(pool.map(writer, range(self.WRITERS)))


class TestKnowledgeStoreLocking(ThreadedStoreCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "knowledge.json"
        self._old = knowledge_store.KNOWLEDGE_FILE
        knowledge_store.KNOWLEDGE_FILE = str(self.path)
        self.addCleanup(setattr, knowledge_store, "KNOWLEDGE_FILE", self._old)
        self._old_h = hypotheses.HYPOTHESES_FILE
        hypotheses.HYPOTHESES_FILE = Path(self.tmp.name) / "hypotheses.jsonl"
        self.addCleanup(setattr, hypotheses, "HYPOTHESES_FILE", self._old_h)

    def _unlocked_add_fact(self, text):
        """add_fact with the lock taken out — the shipped code."""
        data = knowledge_store._load()
        time.sleep(0.001)
        data["facts"].append({"ts": 0, "text": text, "source": "x",
                              "category": ""})
        knowledge_store._write(data)

    def test_the_old_recipe_is_the_bug(self):
        self._race(lambda n, i: self._unlocked_add_fact(f"fact {n}-{i}"))
        kept = len(knowledge_store.list_facts())
        self.assertLess(kept, self.WRITERS * self.ROUNDS,
                        "the unlocked read-modify-write was expected to lose "
                        "facts; if it stops, the window moved rather than closed")

    def test_no_fact_is_lost(self):
        self._race(lambda n, i: knowledge_store.add_fact(f"fact {n}-{i}"))
        self.assertEqual(len(knowledge_store.list_facts()),
                         self.WRITERS * self.ROUNDS)

    def test_no_question_is_lost(self):
        self._race(lambda n, i: knowledge_store.record_question(f"q {n}-{i}?"))
        self.assertEqual(len(knowledge_store.list_questions()),
                         self.WRITERS * self.ROUNDS)

    def test_a_fact_added_twice_at_once_is_stored_once(self):
        """The dedup read and the append are one decision, so two threads
        cannot both find the ledger empty and both announce."""
        self._race(lambda n, i: knowledge_store.add_fact("The beacon is the "
                                                         "office lamp"))
        self.assertEqual(len(knowledge_store.list_facts()), 1)

    def test_answering_and_dismissing_do_not_erase_each_other(self):
        for n in range(self.WRITERS):
            knowledge_store.record_question(f"q {n}?")
        rows = knowledge_store.list_questions()

        def settle(n, i):
            if i % 2:
                knowledge_store.answer_question(f"q {n}?", "yes")
            else:
                knowledge_store.dismiss_question(rows[n]["ts"])

        self._race(settle)
        self.assertEqual(len(knowledge_store.list_questions()), self.WRITERS)


class TestFeedbackStoreLocking(ThreadedStoreCase):
    # Under MAX_PER_CATEGORY, or the store's own cap drops entries and the
    # count says nothing about the race.
    ROUNDS = 8

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "feedback.json"
        self._old = feedback_store.FEEDBACK_FILE
        feedback_store.FEEDBACK_FILE = str(self.path)
        self.addCleanup(setattr, feedback_store, "FEEDBACK_FILE", self._old)

    def _unlocked_add(self, cat, text):
        data = feedback_store._load()
        entries = feedback_store._entries(data, cat)
        time.sleep(0.001)
        entries.append({"ts": len(entries), "text": text})
        data["categories"][cat] = entries[-feedback_store.MAX_PER_CATEGORY:]
        feedback_store._write(data)

    def test_the_old_recipe_is_the_bug(self):
        """Feedback on eight different cards at once: the file holds every
        category, so entries on unrelated cards are what get lost."""
        self._race(lambda n, i: self._unlocked_add(f"cat{n}", f"note {i}"))
        kept = sum(len(feedback_store.list_feedback(f"cat{n}"))
                   for n in range(self.WRITERS))
        self.assertLess(kept, self.WRITERS * self.ROUNDS)

    def test_no_entry_on_any_category_is_lost(self):
        self._race(lambda n, i: feedback_store.add_feedback(f"cat{n}",
                                                            f"note {i}"))
        for n in range(self.WRITERS):
            self.assertEqual(len(feedback_store.list_feedback(f"cat{n}")),
                             self.ROUNDS, f"cat{n}")

    def test_removing_from_one_category_keeps_the_others(self):
        for n in range(self.WRITERS):
            feedback_store.add_feedback(f"cat{n}", "keep me")
        victims = {n: feedback_store.add_feedback(f"cat{n}", "drop me")["ts"]
                   for n in range(self.WRITERS)}

        def drop(n, i):
            if i == 0:
                feedback_store.remove_feedback(f"cat{n}", victims[n])

        self._race(drop)
        for n in range(self.WRITERS):
            self.assertEqual([e["text"] for e in
                              feedback_store.list_feedback(f"cat{n}")],
                             ["keep me"], f"cat{n}")


# ---------------------------------------------------------------------------
# B15 — one reader, so it cannot miss either writer
# ---------------------------------------------------------------------------

class TestRejectionsReachTheCardPrompt(unittest.TestCase):
    """A rejection is bookkept in two stores and only the panel's own route
    wrote both: `brain memory reject` and `brain-learn.sh`'s fallback write
    the hypothesis queue alone. So a correction given while the panel was
    down — which is exactly when somebody reaches for the CLI — reached the
    consolidator and never reached a single card prompt, for ever."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old_k = knowledge_store.KNOWLEDGE_FILE
        knowledge_store.KNOWLEDGE_FILE = os.path.join(self.tmp.name, "k.json")
        self.addCleanup(setattr, knowledge_store, "KNOWLEDGE_FILE", self._old_k)
        self._old_h = hypotheses.HYPOTHESES_FILE
        hypotheses.HYPOTHESES_FILE = Path(self.tmp.name) / "hypotheses.jsonl"
        self.addCleanup(setattr, hypotheses, "HYPOTHESES_FILE", self._old_h)

    def _reject_through_the_queue_only(self, text, note=""):
        entry = hypotheses.propose(text, "cli")
        self.assertIsNotNone(entry)
        return hypotheses.reject(entry["ts"], note=note)

    def test_a_rejection_the_panel_never_saw_is_in_the_prompt(self):
        self._reject_through_the_queue_only(
            "The attic fan is broken", note="it is on a manual switch")
        block = knowledge_store.prompt_block()
        self.assertIn("REJECTED", block)
        self.assertIn("The attic fan is broken", block)
        # The reason is the half that generalises, so it travels with it.
        self.assertIn("it is on a manual switch", block)

    def test_the_panels_own_dismissals_still_render(self):
        q = knowledge_store.record_question("Is the fridge failing?")
        knowledge_store.dismiss_question(q["ts"])
        self.assertIn("Is the fridge failing?", knowledge_store.prompt_block())

    def test_both_writers_render_together(self):
        q = knowledge_store.record_question("Is the fridge failing?")
        knowledge_store.dismiss_question(q["ts"])
        self._reject_through_the_queue_only("The attic fan is broken")
        block = knowledge_store.prompt_block()
        for line in ("Is the fridge failing?", "The attic fan is broken"):
            self.assertIn(line, block)

    def test_a_rejection_written_to_both_stores_is_rendered_once(self):
        """The panel's route writes the pair, and the same claim listed
        twice reads as two different dead ends."""
        claim = "The attic fan is broken"
        q = knowledge_store.record_question(claim)
        knowledge_store.dismiss_question(q["ts"])
        self._reject_through_the_queue_only(claim, note="it is manual")
        block = knowledge_store.prompt_block()
        self.assertEqual(block.count(claim), 1, block)

    def test_the_half_that_carries_the_reason_is_the_one_kept(self):
        """A rejection recorded in both stores is one dead end, and the
        hypothesis half is the one that may carry the sentence explaining
        it — which is worth more than the rejection, because "no" retires
        one claim and the reason rules out everything built on the same
        mistake."""
        claim = "The attic fan is broken"
        q = knowledge_store.record_question(claim)
        knowledge_store.dismiss_question(q["ts"])
        self._reject_through_the_queue_only(claim, note="it is on a manual switch")
        block = knowledge_store.prompt_block()
        self.assertEqual(block.count(claim), 1, block)
        self.assertIn("it is on a manual switch", block)

    def test_an_empty_pair_renders_nothing(self):
        knowledge_store.add_fact("The office lamp is called the beacon")
        knowledge_store.record_question("Should the porch light stay on?")
        hypotheses.propose("An open guess nobody answered", "cli")
        self.assertEqual(knowledge_store.prompt_block(), "")

    def test_it_stays_capped_over_the_union(self):
        for i in range(hypotheses.MAX_OPEN):
            entry = hypotheses.propose(f"queue claim {i} " + "y" * 300, "cli")
            hypotheses.reject(entry["ts"])
        for i in range(60):
            q = knowledge_store.record_question(f"question {i} " + "x" * 400)
            knowledge_store.dismiss_question(q["ts"])
        block = knowledge_store.prompt_block()
        self.assertLessEqual(len(block), knowledge_store.PROMPT_MAX_CHARS)

    def test_an_unreadable_queue_is_a_thinner_prompt_and_not_a_failure(self):
        q = knowledge_store.record_question("Is the fridge failing?")
        knowledge_store.dismiss_question(q["ts"])
        # A directory where the queue should be: every read of it raises.
        boom = Path(self.tmp.name) / "wedged"
        boom.mkdir()
        hypotheses.HYPOTHESES_FILE = boom
        self.assertIn("Is the fridge failing?", knowledge_store.prompt_block())


class TestNothingTakesItsOwnLockTwice(unittest.TestCase):
    """flock keys on the open file description, not on the process — so a
    locked function that calls another locked function on the SAME store
    blocks on itself for the whole timeout and then runs unlocked, which is
    the guard quietly switching itself off. Read rather than driven,
    because "this call does not appear" is the one shape of claim a read
    can honestly make, and the deadlock it prevents is not something a test
    can schedule.
    """

    STORES = ("hypotheses", "knowledge_store", "feedback_store")

    def _lockers(self, tree):
        import ast
        out = set()
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if any(isinstance(n, ast.Call)
                   and getattr(n.func, "id", "") == "_locked"
                   for n in ast.walk(fn)):
                out.add(fn.name)
        return out

    def test_no_locked_function_calls_another(self):
        import ast
        for name in self.STORES:
            with self.subTest(store=name):
                tree = ast.parse((PANEL / f"{name}.py").read_text())
                lockers = self._lockers(tree)
                self.assertTrue(lockers, f"{name} takes no lock at all")
                nested = []
                for fn in (n for n in ast.walk(tree)
                           if isinstance(n, ast.FunctionDef)
                           and n.name in lockers):
                    for n in ast.walk(fn):
                        if (isinstance(n, ast.Call)
                                and getattr(n.func, "id", "") in lockers - {fn.name}):
                            nested.append(f"{fn.name} -> {n.func.id}")
                self.assertEqual(nested, [], f"{name}: {nested}")


if __name__ == "__main__":
    unittest.main()
