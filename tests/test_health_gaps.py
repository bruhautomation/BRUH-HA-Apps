#!/usr/bin/env python3
"""The verdict said `ok` beside a Status sensor reading `needs_restart`.

A real house reported a health verdict of `ok`, an empty problems list
and the sentence "everything brAIn runs is running", while the same
payload carried a pending integration restart and a voice pool whose own
heartbeat had stopped. The faults-vs-verdict split is deliberate and
stays (`reports.faults` is the inventory, `health` the verdict); what is
pinned here is the two things the verdict itself was missing:

* a worker pool PROCESS that is alive and has stopped going round — its
  heartbeat file stale — answers voice no better than a dead one, and the
  roll-call's `running: true` hid it;
* a restart Home Assistant still owes is something a person has to do,
  so the health sensor saying `ok` beside `sensor.brain_status` saying
  `needs_restart` was two surfaces disagreeing about the same install.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import health  # noqa: E402
import reports  # noqa: E402

NOW = 1_700_000_000.0


def diag(**over) -> dict:
    payload = {
        "auth": {"state": "ok"},
        "daemons": {name: {"running": True} for name in (
            "ttyd", "usage_tracker", "memory_consolidator", "study_watcher",
            "assist_worker_pool", "automation_listener")}
        | {"assist_listener": {"running": False}},
        "checks": {"finished_at": int(NOW - 1800), "ran": ["a"], "error": ""},
        "journal": {"runs": 20, "by_outcome": {"ok": 20}},
        "usage": {"source": "account", "used_percent": 12},
        "options": {"enable_terminal": True,
                    "enable_assist_integration": True,
                    "assist_fast_mode": True,
                    "enable_automation_integration": True, "learning": True,
                    "checks_interval_hours": 6},
    }
    payload.update(over)
    return payload


def pool(**row) -> dict:
    d = diag()
    d["daemons"]["assist_worker_pool"] = {"running": True, **row}
    return d


class TestAPoolThatStoppedGoingRound(unittest.TestCase):
    def test_a_stale_heartbeat_on_a_running_pool_is_voice_down(self):
        got = health.verdict(pool(heartbeat_age_s=900, workers=0), now=NOW)
        self.assertNotEqual(got["state"], "ok")
        self.assertIn("assist_pool", {p["id"] for p in got["problems"]})
        self.assertNotIn("running", got["reason"].replace(
            "not running", ""))
        self.assertIn("voice", got["reason"])

    def test_a_fresh_heartbeat_is_an_idle_pool_not_a_dead_one(self):
        # Workers are per conversation: none open is a pool nobody is
        # talking to, which is the ordinary state between commands.
        got = health.verdict(pool(heartbeat_age_s=20, workers=0), now=NOW)
        self.assertEqual(got["state"], "ok")

    def test_a_payload_with_no_heartbeat_figure_accuses_nobody(self):
        # A mirror from before the figure existed: "I could not look".
        self.assertEqual(health.verdict(pool(), now=NOW)["state"], "ok")

    def test_classic_mode_does_not_read_the_pools_heartbeat(self):
        d = pool(heartbeat_age_s=900)
        d["daemons"]["assist_worker_pool"]["running"] = False
        d["daemons"]["assist_listener"] = {"running": True}
        d["options"]["assist_fast_mode"] = False
        self.assertEqual(health.verdict(d, now=NOW)["state"], "ok")

    def test_the_window_matches_the_integrations_sensor(self):
        # One number for "a heartbeat this old is a pool that stopped",
        # read by the panel's verdict and the HA connectivity sensor.
        sys.path.insert(0, str(BASE_DIR / "brain" / "custom_components"
                               / "brain"))
        import assist_health  # noqa: E402
        self.assertEqual(health.POOL_HEARTBEAT_STALE_S,
                         assist_health.HEARTBEAT_FRESH_S)


class TestARestartHomeAssistantStillOwes(unittest.TestCase):
    def restart(self) -> dict:
        return diag(versions={"addon": "2.17.19", "integration": {
            "loaded": "2.17.17", "required": "2.17.19",
            "restart_pending": True}})

    def test_it_degrades_the_verdict_and_names_the_restart(self):
        got = health.verdict(self.restart(), now=NOW)
        self.assertEqual(got["state"], "degraded")
        self.assertIn("restart", got["reason"].lower())
        self.assertIn("Restart Home Assistant", got["fix"])
        self.assertIn("2.17.17", got["fix"])

    def test_no_restart_owed_is_silent(self):
        d = diag(versions={"integration": {"loaded": "2.17.19",
                                           "required": "2.17.19",
                                           "restart_pending": False}})
        self.assertEqual(health.verdict(d, now=NOW)["state"], "ok")

    def test_the_inventory_says_it_once(self):
        d = self.restart()
        d["health"] = health.verdict(d, now=NOW)
        rows = reports.faults(d)
        about = [r for r in rows if "restart" in
                 f"{r['what']} {r.get('detail') or ''}".lower()]
        self.assertEqual(len(about), 1, rows)


class TestTheQuietSentenceIsTrue(unittest.TestCase):
    def test_a_roll_call_nobody_could_take_does_not_claim_everything_runs(self):
        got = health.verdict(diag(daemons={}), now=NOW)
        self.assertEqual(got["state"], "ok")
        self.assertNotEqual(got["reason"], "everything brAIn runs is running")

    def test_a_full_roll_call_still_says_so(self):
        got = health.verdict(diag(), now=NOW)
        self.assertEqual(got["reason"], "everything brAIn runs is running")


class TestTheRollCallReadsTheHeartbeat(unittest.TestCase):
    """The panel's roll-call carries the pool's heartbeat age, read off the
    file's mtime, for a pool process that is really in the table."""

    def test_a_running_pool_carries_its_heartbeat_age(self):
        import importlib
        import os
        import subprocess
        import tempfile
        import time
        from unittest.mock import patch
        server = importlib.import_module("server")
        with tempfile.TemporaryDirectory() as tmp:
            beat = Path(tmp) / "pool_status.json"
            beat.write_text("{}")
            old = time.time() - 900
            os.utime(beat, (old, old))
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)",
                 "assist-worker-pool.py"])
            try:
                with patch.object(server, "POOL_STATUS_FILE", beat):
                    for _ in range(50):
                        rows = server._daemon_rollcall()
                        if rows.get("assist_worker_pool", {}).get("running"):
                            break
                        time.sleep(0.05)
                pool = rows["assist_worker_pool"]
                self.assertTrue(pool["running"])
                self.assertGreaterEqual(pool["heartbeat_age_s"], 899)
                d = diag()
                d["daemons"]["assist_worker_pool"] = pool
                self.assertIn("assist_pool", {p["id"] for p in
                                              health.problems(d, now=NOW)})
            finally:
                proc.kill()
                proc.wait()


class TestTheRestartIsOneRepairNotTwo(unittest.TestCase):
    """The restart flow already raises its own Repairs entry; the health
    sensor reads degraded over a pending restart but does not raise a
    second entry about the same fact."""

    def test_the_health_sensor_raises_no_second_repair_for_a_restart(self):
        import asyncio
        import json
        import os
        import tempfile
        import test_numbers_agree
        sensor_mod, _ = test_numbers_agree._import_platforms()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".brain").mkdir()

            class Config:
                def path(self, *parts):
                    return str(root.joinpath(*parts))

            class Hass:
                config = Config()

                async def async_add_executor_job(self, func, *args):
                    return func(*args)

            d = diag(versions={"integration": {"loaded": "1.0", "required": "1.1",
                                               "restart_pending": True}})
            d["health"] = health.verdict(d, now=NOW)
            (root / ".brain" / "diagnostics.json").write_text(json.dumps(d))
            entity = sensor_mod.BrainHealthSensor(None)
            entity.hass = Hass()
            calls = []
            entity._sync_repair = lambda state, reason: calls.append(state)
            asyncio.run(entity.async_update())
            self.assertEqual(entity._attr_native_value, "degraded")
            self.assertEqual(calls, ["ok"])
            # Anything else beside it still raises.
            d["daemons"]["automation_listener"] = {"running": False}
            d["health"] = health.verdict(d, now=NOW)
            (root / ".brain" / "diagnostics.json").write_text(json.dumps(d))
            os.utime(root / ".brain" / "diagnostics.json")
            asyncio.run(entity.async_update())
            self.assertEqual(calls[-1], "failed")


if __name__ == "__main__":
    unittest.main()
