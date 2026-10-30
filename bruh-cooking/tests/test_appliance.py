"""Model logic: status parsing, update ordering and cook requests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import pytest

from custom_components.bruh_cooking.api import StateUpdate, parse_message
from custom_components.bruh_cooking.appliance import (
    MODEL_BOV950,
    MODEL_BSV600,
    MODEL_CSJ100,
    OVEN_MODES,
    CookSettings,
    CookState,
    NextStep,
    StateTracker,
    build_bov950_steps,
    build_edit,
    build_finish_wait,
    build_manual_steps,
    build_next_step,
    default_settings,
    duration_limits,
    oven_mode_defaults,
    parse_status,
    temp_mode_max_seconds,
)

NOW = datetime(2026, 10, 23, 21, 32, 11, tzinfo=UTC)
SERIAL = "J123456"


def csj_point(ts: int, state: str, step: int, remaining: int, **extra) -> dict:
    return {
        "serialNumber": SERIAL,
        "messageType": "applianceDataPoint",
        "version": str(1792805500000 + ts),
        "data": {
            "state": state, "model": "CSJ100", "programStep": step, "bathTemp": 55.1,
            "setPoint": 56.0, "cookTime": 300, "timeRemaining": remaining, "errorState": 0,
            "cookId": "fede07bad08f421d828690c7520c09ba", "guideId": "manual_x",
            "timestamp": ts, "firmwareVersion": "123", "espFirmwareVersion": "52", **extra,
        },
    }


def csj_report(version: int, ts: int, state: str, step: int, remaining: int) -> dict:
    point = csj_point(ts, state, step, remaining)
    return {
        "serialNumber": SERIAL, "messageType": "stateReport", "version": version,
        "data": {"reported": point["data"]},
    }


def feed(tracker: StateTracker, model: str, messages: list[dict]) -> dict:
    for msg in messages:
        tracker.apply(parse_message(msg), model)
    return tracker.state(SERIAL)


class TestCsj:
    def test_cooking_status(self) -> None:
        status = parse_status(MODEL_CSJ100, csj_point(1654132, "ACTIVE", 3, 300)["data"], NOW)
        assert status.state is CookState.COOKING
        assert status.cooking and status.online
        assert status.target_temp_c == 56.0
        assert status.time_remaining_s == 300
        assert status.ends_at == datetime(2026, 10, 23, 21, 37, tzinfo=UTC)

    def test_waiting_for_food_has_no_countdown(self) -> None:
        status = parse_status(MODEL_CSJ100, csj_point(1, "ACTIVE", 2, 0)["data"], NOW)
        assert status.state is CookState.READY
        assert status.time_remaining_s is None
        assert status.cook_time_s == 300

    def test_offline_and_idle(self) -> None:
        assert parse_status(MODEL_CSJ100, {"state": "OFFLINE"}).state is CookState.OFFLINE
        idle = parse_status(MODEL_CSJ100, {"state": "IDLE", "programStep": 0, "setPoint": None})
        assert idle.state is CookState.IDLE and idle.target_temp_c is None

    def test_error_reason(self) -> None:
        data = csj_point(1, "ACTIVE", 5, 0, errorState=2, eventReason=3)["data"]
        status = parse_status(MODEL_CSJ100, data)
        assert status.state is CookState.ERROR
        assert status.error == "low_water_level"

    def test_out_of_order_messages_from_capture(self) -> None:
        """The 21:32:23 Wi-Fi blip: v788 OFFLINE arrived before stale v787."""
        state = feed(StateTracker(), MODEL_CSJ100, [
            csj_point(1655132, "ACTIVE", 3, 299),
            csj_point(1664138, "OFFLINE", 3, 290),
            csj_report(788, 1664138, "OFFLINE", 3, 290),
            csj_report(787, 1655132, "ACTIVE", 3, 299),  # stale: older version
            csj_point(1664138, "ONLINE", 0, 290),
            csj_report(789, 1664138, "ONLINE", 0, 290),
            csj_point(1667192, "ACTIVE", 3, 286),
        ])
        assert state["state"] == "ACTIVE" and state["timeRemaining"] == 286

    def test_stale_point_dropped_but_reboot_accepted(self) -> None:
        tracker = StateTracker()
        feed(tracker, MODEL_CSJ100, [csj_point(1_700_000, "ACTIVE", 3, 100)])
        assert not tracker.apply(parse_message(csj_point(1_690_000, "ACTIVE", 3, 110)), MODEL_CSJ100)
        assert tracker.apply(parse_message(csj_point(5_000, "IDLE", 0, 0)), MODEL_CSJ100)
        assert tracker.state(SERIAL)["state"] == "IDLE"

    def test_edit_keeps_cook(self) -> None:
        data = csj_point(1, "ACTIVE", 3, 120)["data"]
        edit = build_edit(MODEL_CSJ100, data, parse_status(MODEL_CSJ100, data), temperature_c=58)
        assert edit.csj_program["setPoint"] == 58.0
        assert edit.csj_program["cookTime"] == 120
        assert edit.csj_program["programMetadata"]["cookId"] == data["cookId"]


OVEN_SHADOW = {
    "state": "active",
    "model": "BOV950",
    "heaters": [{"cur_temp": 150.5, "temp_sp": 205, "state": 1}],
    "timers": [{"id": 1, "state": 1, "down_from_n": 1080, "now": 900, "timestamp": 0}],
    "appliance": {"mode": 8, "frozen": 0},
    "door": {"state": 1},
    "motors": [{"state": 2}],
    "errors": [],
    "firmware": {"comm_mcu": "1.2", "host_mcu": "3.4"},
    "cookUUID": "uuid-1",
    "currentStep": 1,
}

# A real BOV950 (firmware 1.10.21, set to °F) baking at 200 °F, from issue #1.
REAL_OVEN_IDLE = {
    "timers": [None, None], "state": "idle", "door": 1, "name": "A950TEST0023",
    "serialNumber": "A950TEST0023", "model": "BOV950",
    "sys": {"cpu_temperature": 33, "stm_restart_reason": "power_up", "stm_restart_time": 271},
    "firmware": {"commFirmware": "1.10.131", "teFirmware": "2.4.0", "ctrlFirmware": "1.10.21"},
    "ota": {"state": 0}, "cfg": {"temp_unit": 1, "vol": 11}, "errors": [], "motor": 0,
    "heater": {"state": 0, "temp_sp": 0, "temp_sp_f": 0, "temp_sp_m": 0, "cur_temp": 21},
    "appliance": {"mode": 3, "rotate_state": 1, "preset": 0, "cook_segment": 0, "frozen": 0},
}
REAL_OVEN_COOK = {
    "cookUUID": "cook-1", "currentInstruction": 4, "currentStage": 0, "currentStep": 0,
    "currentStepState": "active", "recipe": "manual_x",
}
REAL_OVEN_PREHEATING = {
    **REAL_OVEN_IDLE, **REAL_OVEN_COOK, "state": "active", "motor": 1,
    "heater": {"state": 1, "temp_sp": 95, "temp_sp_f": 200, "temp_sp_m": 88, "cur_temp": 39},
}
# Waiting for Start to be pressed, the oven leaves out its heater, fan and mode.
REAL_OVEN_WAITING = {
    key: value for key, value in {**REAL_OVEN_IDLE, **REAL_OVEN_COOK}.items()
    if key not in ("heater", "motor", "appliance", "cookUUID")
} | {"state": "physicalButtonPress"}


# The BOV950 keeping warm after a 350 °F bake with Keep warm on (issue #1, 0.08): still an
# active cook, now in the keep warm mode (19), with a fresh hour-long timer at 160 °F.
REAL_OVEN_COOKING_BAKE = {
    **REAL_OVEN_PREHEATING, "currentInstruction": 10,
    "heater": {"state": 2, "temp_sp": 175, "temp_sp_f": 350, "temp_sp_m": 161, "cur_temp": 160},
    "timers": [{"id": 0, "now": 300, "state": 1, "down_from_n": 300, "timestamp": int(NOW.timestamp()) - 290}, None],
}
REAL_OVEN_KEEPING_WARM = {
    **REAL_OVEN_COOKING_BAKE, "currentInstruction": 17,
    "appliance": {"mode": 19, "rotate_state": 0, "preset": 0, "cook_segment": 0, "frozen": 0},
    "heater": {"state": 2, "temp_sp": 70, "temp_sp_f": 160, "temp_sp_m": 65, "cur_temp": 160},
    "timers": [{"id": 0, "now": 3600, "state": 1, "down_from_n": 3600, "timestamp": int(NOW.timestamp()) - 2}, None],
}
# Keep warm's hour runs out the way a cook's timer does (issue #1, 0.09): a report that still
# has the timer, then the heater off and the timers cleared a second later.
REAL_OVEN_KEEP_WARM_OVER = {
    **REAL_OVEN_KEEPING_WARM, "state": "virtualButtonPress", "currentStepState": "done", "currentInstruction": 20,
    "heater": {"state": 2, "temp_sp": 70, "temp_sp_f": 160, "temp_sp_m": 65, "cur_temp": 58},
    "timers": [{"id": 0, "now": 3600, "state": 1, "down_from_n": 3600, "timestamp": int(NOW.timestamp()) - 3600}, None],
}
REAL_OVEN_KEPT_WARM = {
    **REAL_OVEN_KEEP_WARM_OVER, "timers": [None, None],
    "heater": {"state": 0, "temp_sp": 70, "temp_sp_f": 160, "temp_sp_m": 65, "cur_temp": 58},
}
# A broil runs at a level: the oven reports its setpoints as 0, and the level as the preset.
REAL_OVEN_BROILING = {
    **REAL_OVEN_PREHEATING, "currentInstruction": 10,
    "appliance": {"mode": 2, "rotate_state": 0, "preset": 3, "cook_segment": 0, "frozen": 0},
    "heater": {"state": 2, "temp_sp": 0, "temp_sp_f": 0, "temp_sp_m": 0, "cur_temp": 22}, "motor": 0,
    "timers": [{"id": 0, "now": 180, "state": 1, "down_from_n": 180, "timestamp": int(NOW.timestamp()) - 4}, None],
}


class TestKeepWarmAndBroil:
    def test_keeping_warm_after_a_cook(self) -> None:
        cooking = parse_status(MODEL_BOV950, REAL_OVEN_COOKING_BAKE, NOW)
        assert (cooking.state, cooking.cook_time_s) == (CookState.COOKING, 300)
        warm = parse_status(MODEL_BOV950, REAL_OVEN_KEEPING_WARM, NOW, previous=cooking)
        assert (warm.state, warm.mode, warm.active) == (CookState.KEEPING_WARM, "keep_warm", True)
        # Time remaining counts down keep warm's hour; the cook's length and mode stay the cook's.
        assert (warm.time_remaining_s, warm.cook_time_s, warm.cook_mode) == (3598, 300, "bake")
        assert round(warm.target_temp_c, 1) == 71.1  # 160 °F
        assert warm.sensor_target_c == 65
        later = parse_status(MODEL_BOV950, REAL_OVEN_KEEPING_WARM, NOW, previous=warm)
        assert (later.cook_time_s, later.cook_mode) == (300, "bake")
        # Seen only once it was keeping warm, the cook's length and mode are unknown, and stay so.
        unseen = parse_status(MODEL_BOV950, REAL_OVEN_KEEPING_WARM, NOW)
        assert (unseen.cook_time_s, unseen.cook_mode) == (None, None)
        still = parse_status(MODEL_BOV950, REAL_OVEN_KEEPING_WARM, NOW, previous=unseen)
        assert (still.cook_time_s, still.cook_mode) == (None, None)
        assert cooking.cook_mode is None

    def test_keep_warm_runs_out(self) -> None:
        cooking = parse_status(MODEL_BOV950, REAL_OVEN_COOKING_BAKE, NOW)
        warm = parse_status(MODEL_BOV950, REAL_OVEN_KEEPING_WARM, NOW, previous=cooking)
        over = parse_status(MODEL_BOV950, REAL_OVEN_KEEP_WARM_OVER, NOW, previous=warm)
        assert (over.state, over.finished, over.time_remaining_s) == (CookState.DONE, False, 0)
        # Still the cook's length and mode, not keep warm's hour.
        assert (over.mode, over.cook_time_s, over.cook_mode) == ("keep_warm", 300, "bake")
        off = parse_status(MODEL_BOV950, REAL_OVEN_KEPT_WARM, NOW, previous=over)
        assert (off.state, off.finished, off.active, off.cooking) == (CookState.DONE, True, False, True)
        assert (off.cook_time_s, off.cook_mode, off.target_temp_c) == (None, None, None)

    def test_a_broil_has_no_setpoint(self) -> None:
        status = parse_status(MODEL_BOV950, REAL_OVEN_BROILING, NOW)
        assert (status.state, status.mode, status.cook_time_s) == (CookState.COOKING, "broil", 180)
        assert (status.target_temp_c, status.sensor_target_c) == (None, None)

    @pytest.mark.parametrize(
        ("mode", "preset", "level"),
        [
            (2, 3, 3),  # broil on High
            (14, 2, 2),  # bottom broil on Medium (issue #1, 0.10)
            (11, 1, 1),  # slow cook on Low
            (3, 3, None),  # a bake, with the preset left over from a broil
        ],
    )
    def test_the_level_is_the_preset(self, mode: int, preset: int, level: int | None) -> None:
        appliance = {"mode": mode, "rotate_state": 0, "preset": preset, "cook_segment": 0, "frozen": 0}
        status = parse_status(MODEL_BOV950, {**REAL_OVEN_BROILING, "appliance": appliance}, NOW)
        assert status.level == level
        # Keeping warm after the cook, the level stays the cook's.
        warm = parse_status(MODEL_BOV950, REAL_OVEN_KEEPING_WARM, NOW, previous=status)
        assert warm.level == level

    def test_modes_the_oven_wont_start_are_only_reported(self) -> None:
        # The app lists them, but the oven went back to idle at Start (issue #1, 0.10).
        assert not {"gentle_broil", "windy_broil"} & set(OVEN_MODES)
        for mode, option in ((17, "gentle_broil"), (18, "windy_broil")):
            appliance = {"mode": mode, "rotate_state": 0, "preset": 0, "cook_segment": 0, "frozen": 0}
            status = parse_status(MODEL_BOV950, {**REAL_OVEN_BROILING, "appliance": appliance}, NOW)
            assert (status.mode, status.level) == (option, None)


class TestRealOven:
    def test_idle(self) -> None:
        status = parse_status(MODEL_BOV950, REAL_OVEN_IDLE)
        assert (status.state, status.mode) == (CookState.IDLE, "bake")
        assert (status.convection, status.door_open, status.firmware) == ("off", False, "1.10.21")
        # It stops updating cur_temp while idle, so the reading may be hours old.
        assert status.current_temp_c is None

    def test_waiting_for_start(self) -> None:
        status = parse_status(MODEL_BOV950, REAL_OVEN_WAITING)
        assert status.state is CookState.WAITING_FOR_BUTTON
        assert status.current_temp_c is None and status.target_temp_c is None

    def test_preheating(self) -> None:
        status = parse_status(MODEL_BOV950, REAL_OVEN_PREHEATING)
        assert (status.state, status.convection, status.current_temp_c) == (CookState.PREHEATING, "on", 39)
        # 200 °F as set, not the 95 °C the oven rounds its Celsius setpoint to.
        assert status.target_temp_c == pytest.approx(93.33, abs=0.01)
        assert (status.cook_id, status.step_index) == ("cook-1", 0)
        assert status.time_remaining_s is None  # the timer starts after preheating

    def test_celsius_setpoint_when_set_to_celsius(self) -> None:
        shadow = {**REAL_OVEN_PREHEATING, "cfg": {"temp_unit": 0, "vol": 11}}
        assert parse_status(MODEL_BOV950, shadow).target_temp_c == 95

    def test_stopped_is_idle(self) -> None:
        shadow = {**REAL_OVEN_PREHEATING, "state": "stopped"}
        assert parse_status(MODEL_BOV950, shadow).state is CookState.IDLE

    def test_stopping_with_the_heater_off_is_no_new_phase(self) -> None:
        # Stopped while preheating a bake started on its panel, the oven reported the cook once
        # more with the heater off, then went idle (issue #1, 0.10): not preheated and cooking.
        preheating = parse_status(MODEL_BOV950, REAL_OVEN_PREHEATING, NOW)
        stopping = {**REAL_OVEN_PREHEATING, "heater": {**REAL_OVEN_PREHEATING["heater"], "state": 0}}
        assert parse_status(MODEL_BOV950, stopping, NOW, previous=preheating).state is CookState.PREHEATING
        # With nothing before it to go on, it's a cook.
        assert parse_status(MODEL_BOV950, stopping, NOW).state is CookState.COOKING

    def test_timer_with_id_0(self) -> None:
        # Paused while the door was open, 339 s left of 900.
        timer = {"id": 0, "timestamp": 1792885237, "now": 339, "state": 2, "down_from_n": 900, "usage": 6}
        shadow = {**REAL_OVEN_PREHEATING, "timers": [timer, None], "heater": {"state": 2}}
        status = parse_status(MODEL_BOV950, shadow, NOW)
        assert (status.state, status.time_remaining_s, status.cook_time_s) == (CookState.COOKING, 339, 900)
        assert status.ends_at is None

    def test_ready_after_preheating(self) -> None:
        shadow = {**REAL_OVEN_PREHEATING, "state": "virtualButtonPress", "currentStepState": "done",
                  "currentInstruction": 6, "heater": {"state": 2}}
        status = parse_status(MODEL_BOV950, shadow, NOW)
        assert status.state is CookState.READY and status.active

    @pytest.mark.parametrize(
        ("heater", "timer_left", "finished"),
        [
            (2, 0, False),  # the first report: the timer has just run out
            (0, None, True),  # a second later: heater off, timers cleared
        ],
    )
    def test_cook_finished(self, heater: int, timer_left: int | None, finished: bool) -> None:
        timers = [None, None]
        if timer_left is not None:
            sampled = NOW.timestamp() - 600
            timers[0] = {"id": 0, "timestamp": sampled, "now": 600, "state": 1, "down_from_n": 600}
        shadow = {**REAL_OVEN_PREHEATING, "state": "virtualButtonPress", "currentStepState": "done",
                  "currentInstruction": 14, "timers": timers, "heater": {"state": heater}}
        status = parse_status(MODEL_BOV950, shadow, NOW)
        assert status.state is CookState.DONE and status.cooking
        assert (status.finished, status.active) == (finished, not finished)
        if finished:
            assert status.target_temp_c is None

    @pytest.mark.parametrize(("left", "state"), [(2, CookState.DONE), (60, CookState.READY)])
    def test_cook_end_by_a_clock_behind_the_ovens(self, left: int, state: CookState) -> None:
        # The end report came within 2 s of the timer's end, so a clock a little behind the
        # oven's still sees a second or two left; with more to go, the oven is waiting for someone.
        timer = {"id": 0, "timestamp": NOW.timestamp() - 600 + left, "now": 600, "state": 1, "down_from_n": 600}
        shadow = {**REAL_OVEN_PREHEATING, "state": "virtualButtonPress", "currentStepState": "done",
                  "currentInstruction": 14, "timers": [timer, None], "heater": {"state": 2}}
        assert parse_status(MODEL_BOV950, shadow, NOW).state is state

    def test_finish_wait_says_where_the_cook_is(self) -> None:
        shadow = {**REAL_OVEN_PREHEATING, "state": "virtualButtonPress"}
        assert build_finish_wait(MODEL_BOV950, shadow) == {
            "cookUuid": "cook-1",
            "firmware": {"commFirmware": "1.10.131", "ctrlFirmware": "1.10.21", "teFirmware": "2.4.0"},
            "stageIndex": 0,
            "stepIndex": 0,
            "wait": {"user": 2},
        }
        recipe = {"id": "r", "stg": 1, "stp": 2, "phase": 1}
        body = build_finish_wait(MODEL_BOV950, {**shadow, "recipe": recipe})
        assert (body["stageIndex"], body["stepIndex"], body["phaseIndex"]) == (1, 2, 1)
        assert build_finish_wait(MODEL_CSJ100, {"cookId": "x"}) == {}

    def test_next_step_after_preheating(self) -> None:
        shadow = {**REAL_OVEN_PREHEATING, "state": "virtualButtonPress", "currentStepState": "done"}
        assert build_next_step(shadow) == NextStep("manual_x", 1)
        recipe = {"id": "manual_y", "stp": 2}
        assert build_next_step({**shadow, "recipe": recipe}) == NextStep("manual_y", 3)
        with pytest.raises(ValueError):
            build_next_step(REAL_OVEN_IDLE)

    def test_timer_starts_itself_by_default(self) -> None:
        assert default_settings(MODEL_BOV950).auto_start_timer
        assert not default_settings(MODEL_CSJ100).auto_start_timer


class TestTaskEngine:
    def test_oven_status(self) -> None:
        status = parse_status(MODEL_BOV950, OVEN_SHADOW, NOW)
        assert status.state is CookState.PREHEATING
        assert status.current_temp_c == 150.5
        assert status.target_temp_c == 205
        assert status.time_remaining_s == 900 and status.cook_time_s == 1080
        assert status.mode == "air_fry"
        assert status.door_open is False
        assert status.convection == "super"
        assert status.firmware == "3.4"

    @pytest.mark.parametrize(
        ("state", "heater", "expected"),
        [
            ("active", 2, CookState.COOKING),
            ("active", 3, CookState.DONE),
            ("physicalButtonPress", 0, CookState.WAITING_FOR_BUTTON),
            ("virtualButtonPress", 2, CookState.READY),
            ("warming", 2, CookState.KEEPING_WARM),
            ("idle", 0, CookState.IDLE),
            ("offline", 0, CookState.OFFLINE),
        ],
    )
    def test_state_mapping(self, state: str, heater: int, expected: CookState) -> None:
        shadow = {**OVEN_SHADOW, "state": state, "heaters": [{"state": heater}]}
        assert parse_status(MODEL_BOV950, shadow).state is expected

    @pytest.mark.parametrize(
        ("timestamp", "expected"),
        [
            (NOW.timestamp() - 120, 780),  # sampled 2 minutes ago: 2 minutes less left
            (NOW.timestamp() - 2000, 0),  # finished since it was sampled
            (NOW.timestamp() * 1000, 900),  # milliseconds: impossible, so use `now`
        ],
    )
    def test_running_timer_corrects_for_sample_time(self, timestamp: float, expected: int) -> None:
        timer = {"id": 1, "state": 1, "down_from_n": 1080, "now": 900, "timestamp": timestamp}
        status = parse_status(MODEL_BOV950, {**OVEN_SHADOW, "timers": [timer]}, NOW)
        assert status.time_remaining_s == expected
        assert (status.ends_at is None) == (expected == 0)

    def test_skip_timer_value_means_no_timer(self) -> None:
        shadow = {**OVEN_SHADOW, "timers": [{"id": 1, "state": 1, "down_from_n": 388803, "now": 5}]}
        assert parse_status(MODEL_BOV950, shadow).time_remaining_s is None

    def test_door_error(self) -> None:
        shadow = {**OVEN_SHADOW, "errors": [{"code": 29101, "ts": 2}, {"code": 31102, "ts": 1}]}
        status = parse_status(MODEL_BOV950, shadow)
        assert status.state is CookState.ERROR and status.error == "door_open"

    def test_legacy_bsv600_fields(self) -> None:
        shadow = {"state": "active", "temperature": {"current": 54.2, "setpoint": 57},
                  "heater": {"state": 2}, "timer": {"state": 1, "down_from_n": 3600, "now": 10}}
        status = parse_status(MODEL_BSV600, shadow)
        assert (status.current_temp_c, status.target_temp_c, status.time_remaining_s) == (54.2, 57, 10)

    def test_change_report_merges_and_stale_versions_dropped(self) -> None:
        tracker = StateTracker()
        full = {"serialNumber": SERIAL, "messageType": "stateReport", "version": 10,
                "data": {"reported": OVEN_SHADOW}}
        change = {"serialNumber": SERIAL, "messageType": "changeReport", "version": 11,
                  "data": {"reported": {"heaters": [{"cur_temp": 200, "temp_sp": 205, "state": 2}]}}}
        stale = {**full, "version": 9}
        state = feed(tracker, MODEL_BOV950, [full, change, stale])
        assert state["heaters"][0]["cur_temp"] == 200
        assert state["appliance"]["mode"] == 8  # untouched by the partial update

    def test_edit_uses_update_cook(self) -> None:
        status = parse_status(MODEL_BOV950, OVEN_SHADOW)
        edit = build_edit(MODEL_BOV950, OVEN_SHADOW, status, temperature_c=210, duration_s=600)
        assert edit.uuid == "uuid-1" and edit.step == 1
        assert edit.updates == [{"name": "cookSetPoint", "value": 210}, {"name": "cookTime", "value": 600}]


class TestRequests:
    def test_bsv600_steps(self) -> None:
        (step,) = build_manual_steps(MODEL_BSV600, CookSettings(temperature_c=57.25, duration_s=5400))
        assert step["type"] == "sousVideSteps" and step["holdingTemperature"] == 57.2
        assert step["phases"] == [
            {"mode": "sousVide", "temperatureCelsius": 57.2, "seconds": 0},
            {"mode": "sousVide", "temperatureCelsius": 57.2, "seconds": 5400},
        ]
        (hold,) = build_manual_steps(MODEL_BSV600, CookSettings(temperature_c=60))
        assert hold["phases"][1] == {"mode": "sousVide", "temperatureCelsius": 60.0, "skipTimer": True, "seconds": 0}
        with pytest.raises(ValueError):
            build_manual_steps(MODEL_BSV600, CookSettings(temperature_c=95))

    def test_whole_numbers_sent_as_integers(self) -> None:
        """Like the app's JavaScript: 360, not 360.0."""
        (hold,) = build_manual_steps(MODEL_BSV600, CookSettings(temperature_c=60.0))
        assert '"temperatureCelsius": 60,' in json.dumps(hold)
        bake = oven_mode_defaults(OVEN_MODES["bake"])
        bake.temperature_c = 300.0  # clamped to the mode's 250
        steps = build_bov950_steps(bake)
        assert steps[1]["phases"][0]["temperatureCelsius"] == 250
        assert ".0" not in json.dumps(steps)
        status = parse_status(MODEL_BOV950, OVEN_SHADOW)
        edit = build_edit(MODEL_BOV950, OVEN_SHADOW, status, temperature_c=210.0)
        assert json.dumps(edit.updates) == '[{"name": "cookSetPoint", "value": 210}]'

    def test_a_bit_more_is_not_rounded(self) -> None:
        pizza = oven_mode_defaults(OVEN_MODES["pizza"])
        pizza.duration_s = 1001
        (abm,) = [s for s in build_bov950_steps(pizza) if s["stepType"] == "aBitMore"]
        assert abm["phases"][0]["seconds"] == pytest.approx(150.15)  # 0.15 x 1001, as the app

    def test_bake_preheat_then_cook(self) -> None:
        settings = oven_mode_defaults(OVEN_MODES["bake"])
        settings.temperature_c = 180
        preheat, cook, abm, keep_warm = build_bov950_steps(settings)
        phase = {"mode": "bake", "convection": "on", "rotateRemind": False,
                 "temperatureCelsius": 180, "seconds": 1800, "frozen": "off", "keepWarm": False}
        assert preheat == {
            "defaultAutostart": False, "phases": [{**phase, "seconds": 0}], "onComplete": "stayOn",
            "onCompleteTemperature": 70, "rackPosition": ["6"], "stepType": "default",
            "title": "", "type": "ovenSteps",
        }
        assert cook["phases"] == [phase] and cook["onComplete"] == "turnOff"
        assert abm["stepType"] == "aBitMore" and abm["phases"][0]["seconds"] == 360
        assert keep_warm["stepType"] == "keepWarm"
        assert keep_warm["phases"] == [{"mode": "warm", "convection": "on", "temperatureCelsius": 70, "seconds": 3600}]

    def test_air_fry_auto_start_merges_preheat(self) -> None:
        settings = oven_mode_defaults(OVEN_MODES["air_fry"])
        settings.auto_start_timer = True
        settings.keep_warm = True
        steps = build_bov950_steps(settings)
        assert [s["stepType"] for s in steps] == ["default", "aBitMore"]  # keep warm is inline
        assert steps[0]["defaultAutostart"] is True
        assert [p["seconds"] for p in steps[0]["phases"]] == [0, 1080]
        assert steps[0]["onComplete"] == "keepWarm"
        assert steps[0]["phases"][1]["convection"] == "super"

    def test_broil_level_and_limits(self) -> None:
        settings = oven_mode_defaults(OVEN_MODES["broil"])
        settings.duration_s = 3600  # over the 20 minute broil limit
        cook = build_bov950_steps(settings)[0]
        assert cook["rackPosition"] == ["1"]
        assert cook["phases"][0]["level"] == 3 and cook["phases"][0]["seconds"] == 1200
        assert "temperatureCelsius" not in cook["phases"][0]

    def test_proof_has_no_rack_or_keep_warm(self) -> None:
        steps = build_bov950_steps(oven_mode_defaults(OVEN_MODES["proof"]))
        assert [s["stepType"] for s in steps] == ["default", "aBitMore"]
        assert "rackPosition" not in steps[0]

    def test_time_limits(self) -> None:
        assert temp_mode_max_seconds(205) == 4 * 3600
        assert temp_mode_max_seconds(99) == 72 * 3600
        slow = oven_mode_defaults(OVEN_MODES["slow_cook"])
        assert slow.duration_s == 8 * 3600
        assert duration_limits(MODEL_BOV950, slow) == (4 * 3600, 72 * 3600)
        assert duration_limits(MODEL_CSJ100) == (0, 96 * 3600)

    def test_unsupported_mode(self) -> None:
        with pytest.raises(ValueError):
            build_bov950_steps(CookSettings(mode="toast"))


def test_parse_message_shapes() -> None:
    update = parse_message({"serialNumber": "s", "messageType": "changeReport", "version": "12",
                            "data": {"reported": {"a": 1}}})
    assert update == StateUpdate("s", "changeReport", {"a": 1}, False, 12)
    assert parse_message({"serialNumber": "s", "messageType": "pong", "data": {}}) is None


class TestPreheat:
    """The app's getPreheatProgress, for the Preheat sensor and the panel's ring."""

    def test_joule(self) -> None:
        status = parse_status(MODEL_CSJ100, csj_point(1, "ACTIVE", 1, 0, bathTemp=42)["data"])
        assert (status.state, status.preheat_pct) == (CookState.PREHEATING, 75)
        cooking = parse_status(MODEL_CSJ100, csj_point(1, "ACTIVE", 3, 60)["data"])
        assert cooking.preheat_pct is None

    def test_oven_counts_toward_a_little_below_its_sensor_target(self) -> None:
        # At 150 °C and below, 90% of the sensor target: 39 of 79.2.
        status = parse_status(MODEL_BOV950, REAL_OVEN_PREHEATING)
        assert status.preheat_pct == 49
        assert status.sensor_target_c == 88
        # Above it, 15 °C below: 120 of 146.
        hot = {**REAL_OVEN_PREHEATING, "heater": {"state": 1, "temp_sp_m": 161, "cur_temp": 120}}
        assert parse_status(MODEL_BOV950, hot).preheat_pct == 82
        done = {**REAL_OVEN_PREHEATING, "heater": {"state": 1, "temp_sp_m": 161, "cur_temp": 158}}
        assert parse_status(MODEL_BOV950, done).preheat_pct == 100

    def test_only_while_preheating(self) -> None:
        heating = {**REAL_OVEN_PREHEATING, "heater": {**REAL_OVEN_PREHEATING["heater"], "state": 2}}
        status = parse_status(MODEL_BOV950, heating)
        assert (status.state, status.preheat_pct, status.sensor_target_c) == (CookState.COOKING, None, 88)
        idle = parse_status(MODEL_BOV950, REAL_OVEN_IDLE)
        assert (idle.preheat_pct, idle.sensor_target_c) == (None, None)

    def test_joule_turbo(self) -> None:
        shadow = {"state": "active", "heater": {"state": 1, "cur_temp": 28.5, "temp_sp": 57}}
        assert parse_status(MODEL_BSV600, shadow).preheat_pct == 50
        # A sous vide counts its temperature alone, however long it has heated.
        idle = parse_status(MODEL_BSV600, {"state": "idle"}, NOW)
        later = parse_status(MODEL_BSV600, shadow, NOW + timedelta(minutes=10), previous=idle)
        assert (later.preheat_pct, later.preheat_started) == (50, None)

    def test_oven_counts_its_time_limit_too(self) -> None:
        """The oven ends preheating after 5 minutes at the latest (issue #1), so once Home
        Assistant has seen preheating start, it's as far along as the further of its
        temperature and its time."""
        cold = {**REAL_OVEN_PREHEATING, "heater": {"state": 1, "temp_sp_m": 161, "cur_temp": 21}}

        def reading(celsius: float) -> dict:
            return {**cold, "heater": {**cold["heater"], "cur_temp": celsius}}

        waiting = parse_status(MODEL_BOV950, REAL_OVEN_WAITING, NOW)
        start = parse_status(MODEL_BOV950, cold, NOW, previous=waiting)
        assert (start.preheat_started, start.preheat_pct) == (NOW, 14)  # 21 of 146 °C
        # Halfway through the 5 minutes, ahead of its 41% by temperature.
        half = parse_status(MODEL_BOV950, reading(60), NOW + timedelta(seconds=150), previous=start)
        assert (half.preheat_started, half.preheat_pct) == (NOW, 50)
        last = parse_status(MODEL_BOV950, reading(93), NOW + timedelta(seconds=290), previous=half)
        assert last.preheat_pct == 97
        # Near its target sooner, the temperature leads.
        near = parse_status(MODEL_BOV950, reading(140), NOW + timedelta(seconds=60), previous=start)
        assert near.preheat_pct == 96
        # Already preheating at the first report seen: the temperature alone.
        joined = parse_status(MODEL_BOV950, reading(60), NOW + timedelta(seconds=150), previous=None)
        assert (joined.preheat_started, joined.preheat_pct) == (None, 41)
        unknown = parse_status(MODEL_BOV950, reading(70), NOW + timedelta(seconds=160), previous=joined)
        assert (unknown.preheat_started, unknown.preheat_pct) == (None, 48)
        # A warm oven's sensor cooling at first doesn't take progress back (issue #1).
        warm = reading(139)
        first = parse_status(MODEL_BOV950, warm, NOW, previous=waiting)
        assert first.preheat_pct == 95
        cooled = parse_status(MODEL_BOV950, reading(109), NOW + timedelta(seconds=86), previous=first)
        assert cooled.preheat_pct == 95  # not its 75% by temperature, nor 29% of the time
        rising = parse_status(MODEL_BOV950, reading(120), NOW + timedelta(seconds=294), previous=cooled)
        assert rising.preheat_pct == 98  # the time has caught up
        # Once it's ready, the start is forgotten.
        heated = {**cold, "state": "virtualButtonPress", "currentStepState": "done", "heater": {**cold["heater"], "state": 2}}
        ready = parse_status(MODEL_BOV950, heated, NOW + timedelta(seconds=300), previous=last)
        assert (ready.state, ready.preheat_pct, ready.preheat_started) == (CookState.READY, None, None)
