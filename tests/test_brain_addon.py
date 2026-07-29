#!/usr/bin/env python3
"""Tests for the BRain add-on: the merged Terminal + Insights add-on.

Covers what is genuinely new in BRain rather than re-testing the code it
inherited:

- the merged manifest (one ingress port, both faces switchable, no
  leftover git-backup options)
- the `brain` / `ha` CLI dispatchers and the split between them
- the edit journal hook that replaced git auto-backup
- `brain undo`
- the ttyd reverse proxy that makes the terminal a tab
"""

import json
import os
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "brain"
SCRIPTS = ADDON_DIR / "scripts"
PANEL = ADDON_DIR / "panel"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

class TestBrainManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text())

    def test_identity(self):
        self.assertEqual(self.config["name"], "BRain")
        self.assertEqual(self.config["slug"], "brain")

    def test_ingress_is_the_panel_not_ttyd(self):
        """One ingress port, owned by the panel — the terminal is proxied."""
        self.assertTrue(self.config["ingress"])
        self.assertEqual(self.config["ingress_port"], 8099)

    def test_ttyd_still_published_for_direct_access(self):
        self.assertIn("7681/tcp", self.config["ports"])

    def test_both_faces_are_switchable(self):
        for opt in ("enable_terminal", "enable_insights"):
            self.assertIn(opt, self.config["options"])
            self.assertIn(opt, self.config["schema"])

    def test_git_backup_options_are_gone(self):
        """Auto-backup was removed in favour of the edit journal."""
        for opt in ("auto_backup", "backup_interval_minutes"):
            self.assertNotIn(opt, self.config["options"])
            self.assertNotIn(opt, self.config["schema"])

    def test_edit_journal_option_present(self):
        self.assertIn("edit_journal_days", self.config["options"])

    def test_learning_option_is_not_assist_scoped(self):
        """Learning spans voice, insights and study — not just Assist."""
        self.assertIn("learning", self.config["options"])
        self.assertNotIn("assist_learning", self.config["options"])

    def test_every_option_has_a_schema_entry(self):
        for key in self.config["options"]:
            self.assertIn(key, self.config["schema"], f"{key} has no schema")

    def test_discovery_announces_the_brain_domain(self):
        self.assertEqual(self.config["discovery"], ["brain"])

    def test_version_matches_integration_manifest(self):
        manifest = json.loads(
            (ADDON_DIR / "custom_components" / "brain" / "manifest.json").read_text())
        self.assertEqual(manifest["version"], self.config["version"])
        self.assertEqual(manifest["domain"], "brain")


class TestNoStaleReferences(unittest.TestCase):
    """The rename has to be complete or half the add-on talks to itself."""

    def _all_text_files(self):
        skip_suffix = {".png", ".jpg", ".svg", ".ico"}
        # The changelog documents the rename, so the old names belong there.
        skip_names = {"CHANGELOG.md"}
        for path in ADDON_DIR.rglob("*"):
            if not path.is_file() or path.suffix in skip_suffix:
                continue
            if path.name in skip_names:
                continue
            try:
                yield path, path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

    def test_no_legacy_identifiers_remain(self):
        legacy = "bruh" + "_claude"  # split so this test never matches itself
        offenders = [str(p.relative_to(BASE_DIR))
                     for p, t in self._all_text_files() if legacy in t]
        self.assertEqual(offenders, [], f"stale {legacy} refs: {offenders}")

    def test_no_bruh_env_prefix_remains(self):
        offenders = [str(p.relative_to(BASE_DIR))
                     for p, t in self._all_text_files() if "BRUH_" in t]
        self.assertEqual(offenders, [], f"stale BRUH_ env refs: {offenders}")

    def test_worker_pool_moved_off_the_panel_port(self):
        """8099 is the panel's; the pool's internal API must not collide."""
        pool = (ADDON_DIR / "integrations" / "assist-worker-pool.py").read_text()
        self.assertIn('"BRAIN_API_PORT", "8098"', pool)


class TestPanelBranding(unittest.TestCase):
    """The panel is the only thing most users ever see, and a bulk rename
    can't reach text that is split across HTML tags."""

    @classmethod
    def setUpClass(cls):
        cls.html = (PANEL / "index.html").read_text()
        cls.js = (PANEL / "app.js").read_text()

    def test_wordmark_reads_brain(self):
        self.assertIn('BR<span class="grad">ain</span>', self.html)

    def test_no_old_product_names_are_rendered(self):
        """Catches the split-tag case: `BRUH <span>Insights</span>` reads as
        "BRUH Insights" on screen but never matches a naive replace."""
        import re
        text = re.sub(r"<[^>]+>", "", self.html)
        text = re.sub(r"\s+", " ", text)
        for stale in ("BRUH Insights", "BRUH Terminal", "BRUH Claude"):
            self.assertNotIn(stale, text, f"panel still shows {stale!r}")

    def test_panel_does_not_send_users_to_itself(self):
        """Hints inherited from the standalone add-ons told you to go run a
        command in the *other* add-on. Now that there is only one, that
        advice points at the thing you are already looking at."""
        for stale in ("BRain add-on? Run", "if <b>BRain</b> is installed"):
            self.assertNotIn(stale, self.html)

    def test_no_retired_cli_names_in_the_ui(self):
        for stale in ("ha-share-login", "ha-memory", "ha-backup"):
            self.assertNotIn(stale, self.html, f"panel references {stale}")

    def test_three_view_tabs_exist(self):
        for view in ("insights", "terminal", "memory"):
            self.assertIn(f'data-view="{view}"', self.html)
            self.assertIn(f'id="view{view.capitalize()}"', self.html)

    def test_terminal_frame_is_lazy_and_points_at_the_proxy(self):
        self.assertIn('id="termFrame"', self.html)
        self.assertIn('src="about:blank"', self.html)
        self.assertIn('frame.src = "terminal/"', self.js)

    def test_memory_pane_is_adopted_rather_than_duplicated(self):
        """Duplicating the markup would duplicate every id with it."""
        self.assertIn("adoptMemoryPane", self.js)
        self.assertEqual(self.html.count('id="kAddForm"'), 1)


# ---------------------------------------------------------------------------
# CLI dispatchers
# ---------------------------------------------------------------------------

def run_cli(script: str, *args, env=None):
    full_env = {**os.environ, "BRAIN_SCRIPTS_DIR": str(SCRIPTS), **(env or {})}
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        capture_output=True, text=True, env=full_env, timeout=30)


class TestCliDispatchers(unittest.TestCase):
    def test_brain_help_lists_its_faculties(self):
        out = run_cli("brain.sh", "help").stdout
        for word in ("memory", "learn", "ask", "undo", "doctor"):
            self.assertIn(word, out)

    def test_ha_help_lists_ha_operations(self):
        out = run_cli("ha.sh", "help").stdout
        for word in ("log", "reload", "entity", "service", "context"):
            self.assertIn(word, out)

    def test_bare_invocation_shows_usage(self):
        for script in ("brain.sh", "ha.sh"):
            self.assertIn("Usage:", run_cli(script).stdout)

    def test_ha_redirects_brain_faculties(self):
        """`ha memory` should point at `brain memory`, not just fail."""
        res = run_cli("ha.sh", "memory")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("brain memory", res.stderr)

    def test_brain_suggests_ha_for_unknown_subcommands(self):
        res = run_cli("brain.sh", "reload")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("ha reload", res.stderr)

    def test_every_delegated_script_exists(self):
        """A dispatcher entry pointing at a missing script is a dead command."""
        missing = []
        for script in (SCRIPTS / "brain.sh", SCRIPTS / "ha.sh"):
            for line in script.read_text().splitlines():
                line = line.strip()
                if line.startswith(")") or "delegate " not in line:
                    continue
                target = line.split("delegate ", 1)[1].split()[0]
                if not target.endswith(".sh"):
                    continue
                if not (SCRIPTS / target).exists():
                    missing.append(f"{script.name} -> {target}")
        self.assertEqual(missing, [], f"dispatcher points at missing scripts: {missing}")


# ---------------------------------------------------------------------------
# Edit journal (the git-auto-backup replacement)
# ---------------------------------------------------------------------------

class TestEditJournal(unittest.TestCase):
    """The PreToolUse hook must snapshot before an edit, and never block one."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.watched = self.root / "config"
        self.watched.mkdir()
        self.journal = self.root / "journal"

    def tearDown(self):
        self.tmp.cleanup()

    def _hook(self, payload: dict, extra_env=None):
        """Run the hook with WATCH_ROOTS repointed at the temp config dir."""
        src = (SCRIPTS / "brain-edit-snapshot.py").read_text().replace(
            'WATCH_ROOTS = ("/config",)', f'WATCH_ROOTS = ({str(self.watched)!r},)')
        runner = self.root / "hook.py"
        runner.write_text(src)
        env = {**os.environ, "BRAIN_EDIT_JOURNAL": str(self.journal),
               **(extra_env or {})}
        return subprocess.run(
            [sys.executable, str(runner)], input=json.dumps(payload),
            capture_output=True, text=True, env=env, timeout=30)

    def _index(self):
        path = self.journal / "index.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line]

    def test_snapshots_existing_file_before_edit(self):
        target = self.watched / "automations.yaml"
        target.write_text("before")
        res = self._hook({"tool_name": "Edit",
                          "tool_input": {"file_path": str(target)}})
        self.assertEqual(res.returncode, 0)

        entries = self._index()
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["existed"])
        snap = self.journal / "snapshots" / entries[0]["snapshot"]
        self.assertEqual(snap.read_text(), "before",
                         "snapshot must hold the PRIOR contents")

    def test_records_creation_with_no_snapshot(self):
        """A new file has nothing to restore — undo deletes it instead."""
        target = self.watched / "brand-new.yaml"
        self._hook({"tool_name": "Write",
                    "tool_input": {"file_path": str(target)}})
        entries = self._index()
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0]["existed"])
        self.assertEqual(entries[0]["snapshot"], "")

    def test_ignores_paths_outside_the_watched_root(self):
        outside = self.root / "elsewhere.yaml"
        outside.write_text("x")
        self._hook({"tool_name": "Write",
                    "tool_input": {"file_path": str(outside)}})
        self.assertEqual(self._index(), [])

    def test_never_snapshots_secrets(self):
        secrets = self.watched / "secrets.yaml"
        secrets.write_text("api_key: hunter2")
        self._hook({"tool_name": "Edit",
                    "tool_input": {"file_path": str(secrets)}})
        self.assertEqual(self._index(), [])

    def test_ignores_non_editing_tools(self):
        target = self.watched / "a.yaml"
        target.write_text("x")
        self._hook({"tool_name": "Bash", "tool_input": {"file_path": str(target)}})
        self.assertEqual(self._index(), [])

    def test_malformed_input_exits_clean(self):
        """A hook that errors would block the edit — it must always exit 0."""
        runner_src = (SCRIPTS / "brain-edit-snapshot.py").read_text()
        runner = self.root / "hook.py"
        runner.write_text(runner_src)
        res = subprocess.run(
            [sys.executable, str(runner)], input="not json at all",
            capture_output=True, text=True,
            env={**os.environ, "BRAIN_EDIT_JOURNAL": str(self.journal)},
            timeout=30)
        self.assertEqual(res.returncode, 0)

    def test_prunes_snapshots_past_the_retention_window(self):
        target = self.watched / "old.yaml"
        target.write_text("x")
        self._hook({"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
        snap = next((self.journal / "snapshots").iterdir())
        stale = time.time() - 40 * 86400
        os.utime(snap, (stale, stale))

        other = self.watched / "new.yaml"
        other.write_text("y")
        self._hook({"tool_name": "Edit", "tool_input": {"file_path": str(other)}},
                   extra_env={"BRAIN_EDIT_JOURNAL_DAYS": "14"})
        self.assertFalse(snap.exists(), "snapshot older than the window survived")


class TestBrainUndo(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.journal = self.root / "journal"
        (self.journal / "snapshots").mkdir(parents=True)
        self.target = self.root / "automations.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def _journal_entry(self, existed=True, contents="original"):
        snapshot = ""
        if existed:
            snapshot = "1700000000-abc-automations.yaml"
            (self.journal / "snapshots" / snapshot).write_text(contents)
        entry = {"ts": 1700000000.0, "path": str(self.target), "tool": "Edit",
                 "snapshot": snapshot, "existed": existed}
        (self.journal / "index.jsonl").write_text(json.dumps(entry) + "\n")

    def _undo(self, *args):
        return subprocess.run(
            ["bash", str(SCRIPTS / "brain-undo.sh"), *args],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BRAIN_EDIT_JOURNAL": str(self.journal)})

    def test_lists_recent_edits(self):
        self._journal_entry()
        out = self._undo().stdout
        self.assertIn("automations.yaml", out)
        self.assertIn("modified", out)

    def test_restores_prior_contents(self):
        self._journal_entry(contents="the original")
        self.target.write_text("claude's version")
        res = self._undo("1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.target.read_text(), "the original")

    def test_undoing_a_creation_removes_the_file(self):
        self._journal_entry(existed=False)
        self.target.write_text("created by claude")
        self._undo("1")
        self.assertFalse(self.target.exists())

    def test_empty_journal_is_not_an_error(self):
        res = self._undo()
        self.assertEqual(res.returncode, 0)

    def test_out_of_range_index_fails_clearly(self):
        self._journal_entry()
        res = self._undo("99")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("No edit #99", res.stderr)


# ---------------------------------------------------------------------------
# Memory: hypotheses replace the old open-ended question list
# ---------------------------------------------------------------------------

class TestMemoryHypotheses(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name) / "memory"
        self.mem.mkdir(parents=True)
        self.hyp = self.mem / "hypotheses.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_hypotheses(self, *entries):
        self.hyp.write_text("".join(json.dumps(e) + "\n" for e in entries))

    def _mem(self, *args):
        return subprocess.run(
            ["bash", str(SCRIPTS / "brain-memory.sh"), *args],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BRAIN_MEMORY_DIR": str(self.mem)})

    def _open_hypothesis(self, text="The garage fridge is meant to run 24/7"):
        self._write_hypotheses(
            {"ts": int(time.time()), "text": text, "topic": "devices",
             "status": "open"})
        return text

    def test_lists_open_hypotheses(self):
        text = self._open_hypothesis()
        out = self._mem("hypotheses").stdout
        self.assertIn(text, out)

    def test_confirming_settles_it_and_queues_a_fact(self):
        text = self._open_hypothesis()
        res = self._mem("confirm", text)
        self.assertEqual(res.returncode, 0, res.stderr)

        statuses = [json.loads(line)["status"]
                    for line in self.hyp.read_text().splitlines() if line]
        self.assertEqual(statuses, ["confirmed"])

        # The confirmed guess becomes a plain fact in the inbox — no
        # "Q: ... -> A: ..." string anywhere.
        queued = list((self.mem / "inbox").glob("*.jsonl"))
        self.assertEqual(len(queued), 1)
        fact = json.loads(queued[0].read_text().splitlines()[0])
        self.assertEqual(fact["fact"], text)
        self.assertNotIn("Q:", fact["fact"])

    def test_rejecting_settles_without_queueing_a_fact(self):
        text = self._open_hypothesis()
        self._mem("reject", text)
        statuses = [json.loads(line)["status"]
                    for line in self.hyp.read_text().splitlines() if line]
        self.assertEqual(statuses, ["rejected"])
        self.assertFalse(list((self.mem / "inbox").glob("*.jsonl")))

    def test_matches_on_a_distinctive_fragment(self):
        """Users shouldn't have to retype a whole sentence."""
        self._open_hypothesis()
        res = self._mem("confirm", "garage fridge")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_ambiguous_fragment_refuses_rather_than_guessing(self):
        self._write_hypotheses(
            {"ts": 1, "text": "The garage fridge runs 24/7", "status": "open"},
            {"ts": 2, "text": "The garage heater runs 24/7", "status": "open"})
        res = self._mem("confirm", "24/7")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("more than one", res.stderr)

    def test_settled_hypotheses_are_not_offered_again(self):
        self._write_hypotheses(
            {"ts": 1, "text": "Already answered", "status": "confirmed"},
            {"ts": 2, "text": "Wrong track", "status": "rejected"})
        out = self._mem("hypotheses").stdout
        self.assertNotIn("Already answered", out)
        self.assertNotIn("Wrong track", out)

    def test_forget_queues_a_removal(self):
        self._mem("add", "a fact")
        self._mem("forget", "the old thermostat")
        facts = []
        for f in (self.mem / "inbox").glob("*.jsonl"):
            facts += [json.loads(x)["fact"] for x in f.read_text().splitlines() if x]
        self.assertIn("FORGET: the old thermostat", facts)

    def test_empty_state_is_never_an_error(self):
        for args in (["hypotheses"], ["log"], ["inbox"], ["list"]):
            self.assertEqual(self._mem(*args).returncode, 0, args)


class TestMemoryChangeLog(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name) / "memory"
        (self.mem / "snapshots").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _mem(self, *args):
        return subprocess.run(
            ["bash", str(SCRIPTS / "brain-memory.sh"), *args],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BRAIN_MEMORY_DIR": str(self.mem)})

    def _log_entry(self):
        (self.mem / "snapshots" / "100.md").write_text("# Home Memory\n\n- old line\n")
        (self.mem / "memory.log.jsonl").write_text(json.dumps({
            "ts": 1700000000, "snapshot": "snapshots/100.md",
            "source": "consolidation",
            "added": ["a new thing"], "removed": [],
        }) + "\n")

    def test_log_lists_changes(self):
        self._log_entry()
        out = self._mem("log").stdout
        self.assertIn("+1", out)
        self.assertIn("consolidation", out)

    def test_log_show_prints_the_lines(self):
        self._log_entry()
        out = self._mem("log", "--show", "1").stdout
        self.assertIn("a new thing", out)

    def test_undo_restores_the_snapshot(self):
        self._log_entry()
        (self.mem / "memory.md").write_text("# Home Memory\n\n- old line\n- a new thing\n")
        res = self._mem("undo", "1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("a new thing", (self.mem / "memory.md").read_text())

    def test_undo_out_of_range_fails_clearly(self):
        self._log_entry()
        res = self._mem("undo", "99")
        self.assertNotEqual(res.returncode, 0)


# ---------------------------------------------------------------------------
# Terminal reverse proxy
# ---------------------------------------------------------------------------

class TestTerminalProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load by path under a unique name. brain/panel and brain/panel
        # both contain a `server.py`, so putting either on sys.path decides
        # which one every OTHER test file gets — import order should not
        # silently repoint another module's tests at a different add-on.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "brain_terminal_proxy", PANEL / "terminal_proxy.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.mod = module

    def test_registers_prefix_and_wildcard_routes(self):
        from aiohttp import web
        app = web.Application()
        self.mod.setup(app)
        canonical = {r.resource.canonical for r in app.router.routes()}
        self.assertIn("/terminal", canonical)
        self.assertIn("/terminal/{path}", canonical)

    def test_strips_hop_by_hop_headers(self):
        cleaned = self.mod._clean({
            "Connection": "upgrade", "Upgrade": "websocket",
            "Transfer-Encoding": "chunked", "Host": "x", "Content-Length": "3",
            "Cookie": "keep=me",
        })
        self.assertEqual(cleaned, {"Cookie": "keep=me"})

    def test_respects_the_enable_terminal_switch(self):
        original = os.environ.get("BRAIN_ENABLE_TERMINAL")
        try:
            os.environ["BRAIN_ENABLE_TERMINAL"] = "false"
            self.assertFalse(self.mod._enabled())
            os.environ["BRAIN_ENABLE_TERMINAL"] = "true"
            self.assertTrue(self.mod._enabled())
        finally:
            if original is None:
                os.environ.pop("BRAIN_ENABLE_TERMINAL", None)
            else:
                os.environ["BRAIN_ENABLE_TERMINAL"] = original

    def test_upstream_url_maps_onto_ttyd_root(self):
        """/terminal/ws must reach ttyd's /ws, or the session never opens."""
        class FakeRequest:
            match_info = {"path": "ws"}
            query_string = ""
        self.assertEqual(self.mod._upstream_url(FakeRequest()),
                         f"{self.mod.TTYD_BASE}/ws")

    def test_upstream_url_preserves_query_string(self):
        class FakeRequest:
            match_info = {"path": "token"}
            query_string = "arg=1&arg=2"
        self.assertEqual(self.mod._upstream_url(FakeRequest()),
                         f"{self.mod.TTYD_BASE}/token?arg=1&arg=2")


if __name__ == "__main__":
    unittest.main()
