#!/usr/bin/env python3
"""`sys.history_incomplete` after a restart, with recorder excludes (#702,
#707).

It called "history is incomplete" serious on four of twelve sampled
entities and stood the history checks down, while the recorder was fine:
every hit was an entity the recorder excludes on purpose (a network
counter) or one whose `last_changed` a restart reset while its value
stayed the same. Driven through the real probe rule, the real snapshot
reader of configuration.yaml and the real check.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import ha_data  # noqa: E402
from checks import _util, snapshot, system  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400.0
RESTART = NOW - 3 * 3600


def iso(ts: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def row(eid: str, state: str, when: float) -> dict:
    return {"entity_id": eid, "state": state, "last_changed": iso(when)}


def live(state: str, when: float) -> dict:
    return {"state": state, "attributes": {}, "last_changed": iso(when)}


class _Config(unittest.TestCase):

    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cfg, True)

    def write(self, name: str, text: str) -> None:
        (self.cfg / name).write_text(text, encoding="utf-8")


class TestAfterARestart(_Config):

    def series_and_states(self):
        # Two network counters the recorder excludes, two sensors a restart
        # re-stamped with the value they already had, and one recorded
        # sensor whose value changed with no row for it.
        series = {
            "sensor.router_wan_rx": [row("sensor.router_wan_rx", "10", NOW - 3 * DAY)],
            "sensor.router_wan_tx": [row("sensor.router_wan_tx", "11", NOW - 3 * DAY)],
            "sensor.porch_lux": [row("sensor.porch_lux", "40", NOW - 2 * DAY)],
            "binary_sensor.shed_door": [row("binary_sensor.shed_door", "off", NOW - 2 * DAY)],
            "sensor.kitchen_temp": [row("sensor.kitchen_temp", "20.5", NOW - 2 * DAY)],
            "sensor.attic_temp": [row("sensor.attic_temp", "30.0", NOW - 2 * DAY)],
        }
        states = {
            "sensor.router_wan_rx": live("99", RESTART + 60),
            "sensor.router_wan_tx": live("98", RESTART + 61),
            "sensor.porch_lux": live("40", RESTART + 70),
            "binary_sensor.shed_door": live("off", RESTART + 75),
            "sensor.kitchen_temp": live("22.0", NOW - 2 * 3600),
            "sensor.attic_temp": live("31.0", NOW - 3600),
        }
        return series, states

    def snap(self, recorded_changed: bool = True) -> dict:
        series, states = self.series_and_states()
        if not recorded_changed:
            states["sensor.kitchen_temp"] = live("20.5", RESTART + 80)
            states["sensor.attic_temp"] = live("30.0", RESTART + 81)
        cut = ha_data.history_cutoffs(series, states, NOW)
        return {"states": states,
                "history_health": {"probed": len(series), "cut": cut, "hours": 96},
                "recorder_filter": snapshot.load_recorder_filter(str(self.cfg))}

    def test_excluded_and_unchanged_entities_raise_nothing(self):
        self.write("configuration.yaml", "recorder: !include recorder.yaml\n")
        self.write("recorder.yaml", "exclude:\n  entity_globs:\n"
                   "    - sensor.*_rx\n    - sensor.*_tx\n")
        snap = self.snap(recorded_changed=False)
        self.assertEqual(_util.history_cut(snap), {})
        self.assertEqual(system.history_incomplete(snap, NOW), [])

    def test_a_recorded_value_that_changed_with_no_row_still_fires(self):
        self.write("configuration.yaml",
                   "recorder:\n  exclude:\n    entity_globs: [sensor.*_rx, sensor.*_tx]\n")
        snap = self.snap()
        self.assertEqual(set(_util.history_cut(snap)),
                         {"sensor.kitchen_temp", "sensor.attic_temp"})
        rows = system.history_incomplete(snap, NOW)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("router", rows[0]["detail"])
        self.assertNotIn("porch", rows[0]["detail"])

    def test_without_the_exclude_the_counters_are_still_judged(self):
        self.write("configuration.yaml", "homeassistant:\n  name: Home\n")
        cut = _util.history_cut(self.snap(recorded_changed=False))
        self.assertEqual(set(cut), {"sensor.router_wan_rx", "sensor.router_wan_tx"})


class TestTheRecorderFilter(_Config):

    def test_home_assistants_order(self):
        flt = {"include": {"domains": ["sensor"], "entities": ["light.porch"]},
               "exclude": {"entity_globs": ["sensor.*_rx"],
                           "entities": ["sensor.noisy"], "domains": ["camera"]}}
        ex = _util.recorder_excludes
        self.assertTrue(ex(flt, "sensor.wan_rx"))
        self.assertTrue(ex(flt, "sensor.noisy"))
        self.assertTrue(ex(flt, "camera.door"))
        self.assertFalse(ex(flt, "sensor.hall_temp"))
        self.assertFalse(ex(flt, "light.porch"))
        # An include names what is recorded: the rest is not.
        self.assertTrue(ex(flt, "switch.kettle"))
        # No filter excludes nothing.
        self.assertFalse(ex({}, "sensor.wan_rx"))
        self.assertFalse(ex(None, "sensor.wan_rx"))

    def test_an_include_outside_the_config_folder_is_not_followed(self):
        self.write("configuration.yaml", "recorder: !include ../../etc/x.yaml\n")
        self.assertEqual(snapshot.load_recorder_filter(str(self.cfg)), {})

    def test_no_file_and_a_broken_file_read_as_no_filter(self):
        self.assertEqual(snapshot.load_recorder_filter(str(self.cfg)), {})
        self.write("configuration.yaml", "recorder: [unclosed\n")
        self.assertEqual(snapshot.load_recorder_filter(str(self.cfg)), {})

    def test_the_probe_does_not_ask_about_an_excluded_entity(self):
        states = {"sensor.wan_rx": live("1", NOW - 3 * 3600),
                  "sensor.hall": live("2", NOW - 3 * 3600)}
        asked = {}

        async def fake_get(session, path, timeout=0, params=None):
            asked["params"] = params
            return []

        real = ha_data._rest_get
        self.addCleanup(setattr, ha_data, "_rest_get", real)
        ha_data._rest_get = fake_get
        import asyncio
        asyncio.run(snapshot._history_probe(
            None, states, NOW, {"exclude": {"entity_globs": ["sensor.*_rx"]}}))
        sent = str(asked["params"])
        self.assertIn("sensor.hall", sent)
        self.assertNotIn("sensor.wan_rx", sent)


if __name__ == "__main__":
    unittest.main()
