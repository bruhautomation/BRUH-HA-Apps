"""Per-model knowledge: reading appliance state and building cook requests.

Joule (CSJ100) behaviour was verified against a real appliance. BSV600 and
BOV950 support follows the Breville+ app (1.96.0) code; the BOV950's has since
been tried on a real oven (issue #1), the BSV600's is unverified.
No Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any

from .api import (
    CSJ_MAX_TEMP_C,
    CSJ_MIN_TEMP_C,
    MODE_SOUS_VIDE,
    MODEL_CSJ100,
    STEP_TYPE_SOUS_VIDE,
    CsjProgramStep,
    StateUpdate,
    build_csj_edit_program,
    build_csj_manual_steps,
    csj_firmware,
)

MODEL_BSV600 = "BSV600"
MODEL_BOV950 = "BOV950"

HOUR = 3600
MINUTE = 60


class Kind(StrEnum):
    SOUS_VIDE = "sous_vide"
    OVEN = "oven"


@dataclass(frozen=True)
class ModelInfo:
    model: str
    product: str
    manufacturer: str
    kind: Kind
    min_temp_c: float
    max_temp_c: float
    max_cook_s: int
    # Whether control has been confirmed on a real appliance. Untested models
    # are monitor-only unless the user allows control in the options.
    tested: bool = False
    # Whether a running cook's temperature and time can be changed. The app
    # offers no way to for the oven, which ignored update-cook (issue #1).
    can_edit_cook: bool = True


MODELS: dict[str, ModelInfo] = {
    MODEL_CSJ100: ModelInfo(
        MODEL_CSJ100, "Joule Sous Vide", "ChefSteps", Kind.SOUS_VIDE,
        CSJ_MIN_TEMP_C, CSJ_MAX_TEMP_C, 96 * HOUR, tested=True,
    ),
    MODEL_BSV600: ModelInfo(
        MODEL_BSV600, "Joule Turbo Sous Vide", "Breville", Kind.SOUS_VIDE,
        20.0, 92.0, 96 * HOUR,
    ),
    MODEL_BOV950: ModelInfo(
        MODEL_BOV950, "Joule Oven Air Fryer Pro", "Breville", Kind.OVEN,
        27.0, 250.0, 72 * HOUR, tested=True, can_edit_cook=False,
    ),
}
# The app's doesApplianceSupportFinishWaitCommand. For other models (the
# oven), its button goes on to the recipe's next cook step with send-step.
FINISH_WAIT_MODELS = frozenset({MODEL_CSJ100, MODEL_BSV600})


class CookState(StrEnum):
    """Normalized appliance state shown in Home Assistant."""

    OFFLINE = "offline"
    IDLE = "idle"
    PREHEATING = "preheating"
    READY = "ready"  # at temperature, waiting for the food
    COOKING = "cooking"
    DONE = "done"  # finished, waiting for the food to come out
    KEEPING_WARM = "keeping_warm"
    WAITING_FOR_BUTTON = "waiting_for_button"  # press a button on the appliance
    ERROR = "error"
    UPDATING = "updating"


RUNNING_STATES = {
    CookState.PREHEATING,
    CookState.READY,
    CookState.COOKING,
    CookState.DONE,
    CookState.KEEPING_WARM,
    CookState.WAITING_FOR_BUTTON,
}
# States in which finish-wait (the app's virtual button press) applies.
WAITING_STATES = {CookState.READY, CookState.DONE}


# -- BOV950 modes ---------------------------------------------------------------


class OvenModeType(StrEnum):
    TEMP = "temp"
    BROIL = "broil"  # BOV950BroilLevel
    SLOW_COOK = "slow_cook"  # BOV950SlowCookLevel


class BroilLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class SlowCookLevel(IntEnum):
    LOW = 1
    HIGH = 2


CONVECTION_ALL = ("off", "on", "super")


@dataclass(frozen=True)
class OvenMode:
    """One entry of the app's bov950ModeConfigs."""

    option: str  # Home Assistant option id
    cms: str  # mode string used in recipe steps
    task_engine: int  # appliance.mode value reported by the oven
    type: OvenModeType
    preheat: bool
    rack: int | None
    convection: str
    convection_allowed: tuple[str, ...]
    keep_warm_allowed: bool
    a_bit_more: tuple[float, int, int]  # factor, minimum s, maximum s
    frozen_default: bool | None = None  # None: frozen option not offered
    temp: tuple[int, int, int] | None = None  # default, min, max (°C)
    time: tuple[int, int | None] = (30 * MINUTE, None)  # default, max (None: by temp)
    level: int | None = None
    round_to: int = 5

    def max_seconds(self, temp_c: float | None, level: int | None = None) -> int:
        if self.type is OvenModeType.SLOW_COOK:
            return 72 * HOUR if (level or self.level) == SlowCookLevel.LOW else 12 * HOUR
        if self.time[1] is not None:
            return self.time[1]
        return temp_mode_max_seconds(temp_c if temp_c is not None else self.temp[0])

    def default_seconds(self, level: int | None = None) -> int:
        if self.type is OvenModeType.SLOW_COOK:
            return 8 * HOUR if (level or self.level) == SlowCookLevel.LOW else 6 * HOUR
        return self.time[0]

    def min_seconds(self, level: int | None = None) -> int:
        if self.type is OvenModeType.SLOW_COOK:
            return 4 * HOUR if (level or self.level) == SlowCookLevel.LOW else 2 * HOUR
        return MINUTE  # ovens can't skip the timer


def temp_mode_max_seconds(temp_c: float) -> int:
    """getTempModeMaxTime: hotter cooks are limited to shorter times."""
    if temp_c >= 200:
        return 4 * HOUR
    if temp_c >= 150:
        return 8 * HOUR
    if temp_c >= 100:
        return 12 * HOUR
    return 72 * HOUR


def _broil(option: str, cms: str, task_engine: int) -> OvenMode:
    return OvenMode(
        option, cms, task_engine, OvenModeType.BROIL, preheat=False, rack=1,
        convection="off", convection_allowed=("off",), keep_warm_allowed=True,
        a_bit_more=(0.2, 30, 240), time=(10 * MINUTE, 20 * MINUTE),
        level=BroilLevel.HIGH,
    )


def _bake(option: str, cms: str, task_engine: int) -> OvenMode:
    return OvenMode(
        option, cms, task_engine, OvenModeType.TEMP, preheat=True, rack=6,
        convection="on", convection_allowed=CONVECTION_ALL, keep_warm_allowed=True,
        a_bit_more=(0.2, 120, 1800), temp=(165, 50, 250), time=(30 * MINUTE, None),
    )


OVEN_MODES: dict[str, OvenMode] = {
    m.option: m
    for m in (
        _bake("bake", "bake", 3),
        OvenMode(
            "air_fry", "airFry", 8, OvenModeType.TEMP, preheat=True, rack=3,
            convection="super", convection_allowed=("super",), keep_warm_allowed=True,
            a_bit_more=(0.2, 60, 360), temp=(205, 150, 250), time=(18 * MINUTE, HOUR),
        ),
        OvenMode(
            "roast", "roast", 4, OvenModeType.TEMP, preheat=True, rack=6,
            convection="on", convection_allowed=CONVECTION_ALL, keep_warm_allowed=True,
            a_bit_more=(0.1, 120, 1800), temp=(205, 50, 250), time=(HOUR, None),
        ),
        _broil("broil", "broil", 2),
        OvenMode(
            "pizza", "pizza", 6, OvenModeType.TEMP, preheat=True, rack=7,
            convection="on", convection_allowed=CONVECTION_ALL, keep_warm_allowed=True,
            a_bit_more=(0.15, 60, 360), frozen_default=True, temp=(205, 150, 250),
            time=(16 * MINUTE, HOUR),
        ),
        OvenMode(
            "cookies", "cookies", 10, OvenModeType.TEMP, preheat=True, rack=5,
            convection="on", convection_allowed=CONVECTION_ALL, keep_warm_allowed=True,
            a_bit_more=(0.15, 60, 360), frozen_default=False, temp=(165, 100, 250),
            time=(11 * MINUTE, HOUR),
        ),
        OvenMode(
            "reheat", "reheat", 9, OvenModeType.TEMP, preheat=False, rack=None,
            convection="on", convection_allowed=CONVECTION_ALL, keep_warm_allowed=True,
            a_bit_more=(0.2, 180, 600), frozen_default=False, temp=(165, 70, 250),
            time=(15 * MINUTE, 2 * HOUR),
        ),
        OvenMode(
            "slow_cook", "slowCook", 11, OvenModeType.SLOW_COOK, preheat=False, rack=8,
            convection="on", convection_allowed=("on",), keep_warm_allowed=True,
            a_bit_more=(0.2, 1200, 5400), level=SlowCookLevel.LOW,
        ),
        OvenMode(
            "proof", "proof", 7, OvenModeType.TEMP, preheat=False, rack=None,
            convection="on", convection_allowed=CONVECTION_ALL, keep_warm_allowed=False,
            a_bit_more=(0.25, 300, 1800), temp=(29, 27, 38), time=(HOUR, 24 * HOUR),
            round_to=1,
        ),
        OvenMode(
            "warm", "warm", 5, OvenModeType.TEMP, preheat=False, rack=None,
            convection="on", convection_allowed=CONVECTION_ALL, keep_warm_allowed=False,
            a_bit_more=(0.2, 600, 3600), temp=(70, 45, 120), time=(HOUR, None),
        ),
        OvenMode(
            "dehydrate", "dehydrate", 12, OvenModeType.TEMP, preheat=False, rack=3,
            convection="super", convection_allowed=CONVECTION_ALL, keep_warm_allowed=False,
            a_bit_more=(0.2, 1800, 3600), temp=(52, 30, 80), time=(12 * HOUR, 72 * HOUR),
            round_to=1,
        ),
        _bake("bottom_bake", "bottomBake", 13),
        _broil("bottom_broil", "bottomBroil", 14),
        _broil("outer_top_broil", "outerTopBroil", 15),
        _broil("middle_top_broil", "middleTopBroil", 16),
    )
}

# Reported appliance.mode values (ModeTaskEngine) -> mode option, including
# modes that can only be started on the appliance itself. The app also has
# Crispier air fry (gentleBroil, 17) and Convection broil (windyBroil, 18), but
# a BOV950 sent either from the cloud went back to idle when Start was pressed
# (issue #1), so they're only reported.
TASK_ENGINE_MODES: dict[int, str] = {
    0: "toast", 1: "bagel", 17: "gentle_broil", 18: "windy_broil", 19: "keep_warm",
    23: "sous_vide", 24: "turbo", 26: "crispy_reheat",
    **{m.task_engine: m.option for m in OVEN_MODES.values()},
}
REPORTED_MODE_OPTIONS = sorted(set(TASK_ENGINE_MODES.values()))

KEEP_WARM_MAX_C = 70
KEEP_WARM_SECONDS = HOUR
SKIP_TIMER_VALUE = 388803  # magicSkipTimerValue: timer skipped / hold


class HeaterState(IntEnum):
    OFF = 0
    PREHEATING = 1
    HEATING = 2
    FINISHED = 3


class TimerState(IntEnum):
    RESET = 0
    RUNNING = 1
    PAUSED = 2


CONVECTION_STATES = {0: "off", 1: "on", 2: "super"}
# cfg.temp_unit of an appliance set to show °F (seen on a US BOV950).
TEMP_UNIT_FAHRENHEIT = 1

# Joule eventReason values (CSJ100ShadowApplianceState.EventReason).
CSJ_EVENT_REASONS = {
    2: "button_pressed", 3: "low_water_level", 4: "tipped_over", 5: "overheating",
    6: "power_loss", 7: "heater_thermistor_failure", 8: "bath_thermistor_failure",
    12: "stuck_motor", 14: "firmware_crash",
}
# Error codes reported by newer appliances (ErrorCodes).
ERROR_CODES = {
    31102: "low_water_level", 29102: "tipped_over", 11202: "heater_thermistor_failure",
    11210: "bath_thermistor_failure", 16102: "bad_motor", 16103: "stuck_motor",
    31101: "water_leakage", 31103: "current_leakage", 22101: "heater_broken",
    29104: "firmware_crash", 29101: "door_open",
}
ERROR_OPTIONS = sorted({"none", "other", *CSJ_EVENT_REASONS.values(), *ERROR_CODES.values()})


# -- status ------------------------------------------------------------------------


@dataclass
class ApplianceStatus:
    """What Home Assistant shows for one appliance."""

    online: bool = False
    state: CookState = CookState.OFFLINE
    current_temp_c: float | None = None
    target_temp_c: float | None = None
    time_remaining_s: int | None = None
    cook_time_s: int | None = None
    ends_at: datetime | None = None
    mode: str | None = None  # reported mode option
    convection: str | None = None
    door_open: bool | None = None
    error: str = "none"
    error_code: int | None = None
    firmware: str | None = None
    cook_id: str | None = None
    step_index: int = 0
    # The cook ended and the appliance turned its heater off; the cook stays
    # open on the appliance until it's stopped.
    finished: bool = False
    # How far preheating has got, in percent; None unless preheating.
    preheat_pct: int | None = None
    # When an oven was seen to start preheating; None when preheating was
    # already under way at the first report Home Assistant saw.
    preheat_started: datetime | None = None
    # While an oven keeps warm after a cook, the mode it cooked in; None when
    # Home Assistant didn't see the cook.
    cook_mode: str | None = None
    # The temperature an oven holds its own sensor at while it cooks
    # (heater.temp_sp_m), below the setpoint.
    sensor_target_c: float | None = None
    # A running broil or slow cook's level, as the oven reports it.
    level: int | None = None

    @property
    def cooking(self) -> bool:
        """A cook is open on the appliance, including one that has finished."""
        return self.state in RUNNING_STATES

    @property
    def active(self) -> bool:
        """A cook is under way: open, and not finished with the heater off."""
        return self.cooking and not self.finished


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def preheat_progress(current: float | None, target: float | None) -> int | None:
    """Percent of the way to `target`, as the app's getPreheatProgress."""
    if current is None or not target or target <= 0:
        return None
    return max(0, min(100, round(100 * current / target)))


# An oven ends preheating after 5 minutes at the latest, whatever its sensor
# reads: three 175 °C bakes from cold each ended at 300 s, at 91-106 °C, while
# a warm air fry got within 15 °C of its sensor target first (issue #1).
OVEN_PREHEAT_LIMIT_S = 300


def oven_preheat_target(sensor_target_c: float) -> float:
    """What an oven's preheat counts toward: a little below its sensor target.

    The app's getPreheatProgress: 15 °C below it, or 90% of it at 150 °C and
    below.
    """
    return 0.9 * sensor_target_c if sensor_target_c <= 150 else sensor_target_c - 15


def _ends_at(now: datetime, remaining: int | None) -> datetime | None:
    if not remaining:
        return None
    end = now + timedelta(seconds=remaining)
    # Round to the minute so the timestamp doesn't change with every update.
    return (end + timedelta(seconds=30)).replace(second=0, microsecond=0)


def parse_status(
    model: str,
    state: dict[str, Any],
    now: datetime | None = None,
    previous: ApplianceStatus | None = None,
) -> ApplianceStatus:
    """The appliance's status from its state; `previous` is the status of the report before."""
    now = now or datetime.now(UTC)
    if model == MODEL_CSJ100:
        return _parse_csj(state, now)
    return _parse_task_engine(model, state, now, previous)


def _parse_csj(s: dict[str, Any], now: datetime) -> ApplianceStatus:
    raw_state = str(s.get("state") or "OFFLINE").upper()
    step = s.get("programStep")
    status = ApplianceStatus(
        online=raw_state != "OFFLINE",
        current_temp_c=_num(s.get("bathTemp")),
        firmware=s.get("firmwareVersion"),
        cook_id=s.get("cookId"),
        mode="sous_vide",
    )
    if not status.online:
        return status
    status.state = {
        CsjProgramStep.PRE_HEAT: CookState.PREHEATING,
        CsjProgramStep.WAIT_FOR_FOOD: CookState.READY,
        CsjProgramStep.COOK: CookState.COOKING,
        CsjProgramStep.WAIT_FOR_REMOVE_FOOD: CookState.DONE,
        CsjProgramStep.ERROR: CookState.ERROR,
        CsjProgramStep.WAIT_FOR_UPDATE: CookState.UPDATING,
    }.get(step, CookState.IDLE)
    if status.state is not CookState.IDLE or raw_state == "ACTIVE":
        status.target_temp_c = _num(s.get("setPoint"))
        status.cook_time_s = int(s["cookTime"]) if s.get("cookTime") else None
    if status.state is CookState.COOKING:
        status.time_remaining_s = int(s.get("timeRemaining") or 0)
        status.ends_at = _ends_at(now, status.time_remaining_s)
    if status.state is CookState.PREHEATING:
        status.preheat_pct = preheat_progress(status.current_temp_c, status.target_temp_c)
    if s.get("errorState"):
        reason = s.get("eventReason")
        status.error = CSJ_EVENT_REASONS.get(reason, "other")
        status.error_code = reason
        status.state = CookState.ERROR
    return status


def _main_timer(s: dict[str, Any]) -> dict[str, Any] | None:
    """The app's getMainTimer: the timer with id 1, else the first one.

    A real BOV950 numbers its only timer 0.
    """
    timers = s.get("timers")
    if isinstance(timers, list):
        for timer in timers:
            if isinstance(timer, dict) and timer.get("id") == 1:
                return timer
        return timers[0] if timers and isinstance(timers[0], dict) else None
    timer = s.get("timer")  # older BSV600 firmware
    return timer if isinstance(timer, dict) else None


# The report that a cook is over reached Home Assistant within 2 seconds of the
# timer's end each time (issue #1), so a clock a second or two behind the
# oven's would still see time left.
TIMER_END_SLACK_S = 5


def _timer_ran_out(timer: dict[str, Any] | None, now: datetime) -> bool:
    if not timer or timer.get("state") != TimerState.RUNNING:
        return False
    if timer.get("down_from_n") in (None, SKIP_TIMER_VALUE):
        return False
    return _running_remaining(timer, int(timer.get("now") or 0), now) <= TIMER_END_SLACK_S


def _shadow_index(s: dict[str, Any], key: str, short: str) -> Any:
    """getCurrentStage/getCurrentStep: from a shadow recipe object if there is one."""
    recipe = s.get("recipe")
    if isinstance(recipe, dict) and recipe.get(short) is not None:
        return recipe[short]
    return s.get(key)


def _preheat_started(previous: ApplianceStatus | None, now: datetime) -> datetime | None:
    """When preheating began: kept while it lasts, or now when the report before
    showed the oven idle or waiting for Start. Unknown when it was already under
    way at the first report seen."""
    if previous is None:
        return None
    if previous.state is CookState.PREHEATING:
        return previous.preheat_started
    if previous.state in (CookState.IDLE, CookState.WAITING_FOR_BUTTON):
        return now
    return None


def _parse_task_engine(
    model: str, s: dict[str, Any], now: datetime, previous: ApplianceStatus | None = None
) -> ApplianceStatus:
    raw_state = str(s.get("state") or "offline")
    heaters = s.get("heaters")
    heater = heaters[0] if isinstance(heaters, list) and heaters else s.get("heater")
    heater = heater if isinstance(heater, dict) else {}
    legacy = s.get("temperature") if isinstance(s.get("temperature"), dict) else {}
    appliance = s.get("appliance") if isinstance(s.get("appliance"), dict) else {}
    firmware = s.get("firmware") if isinstance(s.get("firmware"), dict) else {}

    status = ApplianceStatus(
        online=raw_state != "offline",
        current_temp_c=_num(heater.get("cur_temp", legacy.get("current"))),
        firmware=firmware.get("host_mcu") or firmware.get("ctrlFirmware"),
        cook_id=s.get("cookUUID"),
        mode=TASK_ENGINE_MODES.get(appliance.get("mode")),
    )
    step = _shadow_index(s, "currentStep", "stp")
    status.step_index = step if isinstance(step, int) else 0

    door = s.get("door")
    if isinstance(door, dict):
        door = door.get("state")
    if isinstance(door, int):
        status.door_open = door == 0  # DoorState.OPEN
    motors = s.get("motors")
    motor = motors[0] if isinstance(motors, list) and motors else s.get("motor")
    if isinstance(motor, dict):
        motor = motor.get("state")
    if isinstance(motor, int):  # a real BOV950 reports just the number
        status.convection = CONVECTION_STATES.get(motor)

    errors = [e for e in s.get("errors") or [] if isinstance(e, dict)]
    if errors:
        latest = max(errors, key=lambda e: e.get("ts") or 0)
        status.error_code = latest.get("code")
        status.error = ERROR_CODES.get(status.error_code, "other")

    if not status.online:
        return status
    heater_state = heater.get("state")
    timer = _main_timer(s)
    if raw_state in ("onboarding",) or s.get("onboardingState") in ("notStarted",):
        status.state = CookState.UPDATING
    elif raw_state == "physicalButtonPress":
        status.state = CookState.WAITING_FOR_BUTTON
    elif raw_state == "virtualButtonPress":
        # Waiting for the app: food in after preheating, or the cook is over.
        # When a BOV950's timer runs out it turns the heater off and clears
        # the timer, a second after a report that still has the timer.
        over = heater_state in (HeaterState.OFF, HeaterState.FINISHED) or _timer_ran_out(timer, now)
        status.state = CookState.DONE if over else CookState.READY
        status.finished = heater_state == HeaterState.OFF
    elif raw_state == "warming" or (raw_state == "active" and status.mode == "keep_warm"):
        # A real BOV950 keeps warm after a cook as an active cook in the keep
        # warm mode, with a new hour-long timer (issue #1); the app also knows
        # a "warming" state.
        status.state = CookState.KEEPING_WARM
    elif raw_state == "active":
        status.state = {
            HeaterState.PREHEATING: CookState.PREHEATING,
            HeaterState.FINISHED: CookState.DONE,
        }.get(heater_state, CookState.COOKING)
        if (
            heater_state == HeaterState.OFF
            and previous is not None
            and previous.state in (CookState.PREHEATING, CookState.COOKING)
        ):
            # Stopped during a cook started on its own panel, an oven reported
            # it once more with the heater off before going idle (issue #1):
            # it hasn't moved on.
            status.state = previous.state
    else:
        status.state = CookState.IDLE
    if errors:
        status.state = CookState.ERROR
        status.finished = False
    if status.state is CookState.IDLE and MODELS[model].kind is Kind.OVEN:
        # An idle oven stops updating cur_temp after a while, leaving the last
        # reading in place for hours (59 °C long after it cooled, issue #1).
        status.current_temp_c = None

    if status.active:
        status.target_temp_c = _target_temp_c(s, heater, legacy)
        if MODELS[model].kind is Kind.OVEN:
            status.sensor_target_c = _num(heater.get("temp_sp_m")) or None
        running = OVEN_MODES.get(status.mode or "")
        if running is not None and running.type in (OvenModeType.BROIL, OvenModeType.SLOW_COOK):
            # A broil or slow cook reports its level as the preset: 1 to 3 as
            # sent, in six cooks (issue #1). Other modes can leave the last
            # cook's there.
            level = _num(appliance.get("preset"))
            status.level = int(level) if level else None
        if status.state is CookState.PREHEATING:
            target = status.target_temp_c
            if MODELS[model].kind is Kind.OVEN:
                held = status.sensor_target_c or target
                target = oven_preheat_target(held) if held else None
            status.preheat_pct = preheat_progress(status.current_temp_c, target)
            if MODELS[model].kind is Kind.OVEN:
                # The oven ends preheating when it's near its target or after
                # its time limit, so it's as far along as the further of the two.
                status.preheat_started = _preheat_started(previous, now)
                if status.preheat_started is not None:
                    elapsed = (now - status.preheat_started).total_seconds()
                    timed = max(0, min(100, round(100 * elapsed / OVEN_PREHEAT_LIMIT_S)))
                    status.preheat_pct = max(status.preheat_pct or 0, timed)
            # A warm oven's sensor can cool before it heats (issue #1), but
            # progress never goes back during a preheat.
            if (
                previous is not None
                and previous.state is CookState.PREHEATING
                and previous.cook_id == status.cook_id
                and previous.preheat_pct is not None
            ):
                status.preheat_pct = max(status.preheat_pct or 0, previous.preheat_pct)
        # Keeping warm after a cook, and in the report that ends keep warm, the
        # cook's mode, level and length are the ones it had while cooking, when
        # Home Assistant saw it: the mode is keep warm's now, and the timer keep
        # warm's hour.
        warming = status.state is CookState.KEEPING_WARM or status.mode == "keep_warm"
        seen_cooking = (
            warming
            and previous is not None
            and previous.cook_id == status.cook_id
            and (previous.state is CookState.COOKING or previous.cook_mode is not None)
        )
        if seen_cooking:
            status.cook_mode = previous.cook_mode or previous.mode
            status.level = previous.level
        if timer and timer.get("down_from_n") not in (None, SKIP_TIMER_VALUE):
            status.cook_time_s = int(timer["down_from_n"])
            if warming:
                status.cook_time_s = previous.cook_time_s if seen_cooking else None
            if timer.get("state") in (TimerState.RUNNING, TimerState.PAUSED):
                remaining = int(timer.get("now") or 0)
                if timer.get("state") == TimerState.RUNNING:
                    remaining = _running_remaining(timer, remaining, now)
                    status.ends_at = _ends_at(now, remaining)
                status.time_remaining_s = remaining
    return status


def _target_temp_c(
    s: dict[str, Any], heater: dict[str, Any], legacy: dict[str, Any]
) -> float | None:
    """The setpoint in °C, taken from the °F one when the appliance shows °F.

    The appliance rounds the setpoint to its own steps in each unit: a 200 °F
    cook reports temp_sp 95 (°C) but temp_sp_f 200.
    """
    cfg = s.get("cfg") if isinstance(s.get("cfg"), dict) else {}
    fahrenheit = _num(heater.get("temp_sp_f"))
    if cfg.get("temp_unit") == TEMP_UNIT_FAHRENHEIT and fahrenheit:
        return (fahrenheit - 32) * 5 / 9
    # A broil runs at a level, and reports a setpoint of 0 (issue #1).
    return _num(heater.get("temp_sp", legacy.get("setpoint"))) or None


def _running_remaining(timer: dict[str, Any], remaining: int, now: datetime) -> int:
    """Seconds left on a running timer, worked out as the app does.

    `now` is the seconds left when the appliance sampled it, at `timestamp`
    (epoch seconds), so a report that arrives late is corrected for the delay.
    """
    sampled = _num(timer.get("timestamp"))
    if not sampled or timer.get("now") is None:
        return remaining
    left = int(sampled + remaining - now.timestamp())
    # Ignore impossible values, such as from a clock that's far off.
    if left > (_num(timer.get("down_from_n")) or 0):
        return remaining
    return max(left, 0)


# -- state tracking -------------------------------------------------------------


def deep_merge(base: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in change.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


CSJ_REORDER_WINDOW_MS = 120_000


@dataclass
class _Meta:
    report_version: int | None = None
    versions: dict[str, int] = field(default_factory=dict)
    device_ts: int | None = None


class StateTracker:
    """Merge websocket updates per appliance and drop stale ones.

    Joule: messages can arrive out of order, so they are ordered by the
    device uptime counter in `timestamp`; a large backwards jump means the
    Joule rebooted. Newer appliances: like the app, drop any version that is
    not newer than the last one applied (tracked per message type, since the
    Joule mixes shadow versions and epoch-millisecond versions).
    """

    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._meta: dict[str, _Meta] = {}

    def state(self, serial: str) -> dict[str, Any]:
        return self._states.get(serial, {})

    def apply(self, update: StateUpdate, model: str) -> bool:
        meta = self._meta.setdefault(update.serial, _Meta())
        if model == MODEL_CSJ100:
            if not self._csj_fresh(update, meta):
                return False
        elif update.version is not None:
            last = meta.versions.get(update.message_type)
            if last is not None and update.version <= last:
                return False
            meta.versions[update.message_type] = update.version
        current = self._states.get(update.serial, {})
        self._states[update.serial] = (
            dict(update.state) if update.replace else deep_merge(current, update.state)
        )
        return True

    @staticmethod
    def _csj_fresh(update: StateUpdate, meta: _Meta) -> bool:
        if update.replace and update.version is not None:
            if meta.report_version is not None and update.version < meta.report_version:
                return False
            meta.report_version = update.version
        ts = update.state.get("timestamp")
        if isinstance(ts, int) and meta.device_ts is not None:
            if 0 < meta.device_ts - ts <= CSJ_REORDER_WINDOW_MS:
                return False
        if isinstance(ts, int):
            meta.device_ts = ts
        return True


# -- cook requests -------------------------------------------------------------


@dataclass
class CookSettings:
    """What the next cook should use; edited through number/select entities."""

    temperature_c: float | None = None
    duration_s: int | None = None  # sous vide: None or 0 holds until stopped
    mode: str | None = None  # oven mode option
    convection: str | None = None
    level: int | None = None
    auto_start_timer: bool = False
    keep_warm: bool = False
    frozen: bool | None = None


def default_settings(model: str) -> CookSettings:
    if model == MODEL_BOV950:
        settings = oven_mode_defaults(OVEN_MODES["bake"])
        # As in the app, the oven starts its timer itself once preheated.
        settings.auto_start_timer = True
        return settings
    return CookSettings(temperature_c=60.0, duration_s=None)


def oven_mode_defaults(mode: OvenMode) -> CookSettings:
    return CookSettings(
        temperature_c=float(mode.temp[0]) if mode.temp else None,
        duration_s=mode.default_seconds(),
        mode=mode.option,
        convection=mode.convection,
        level=mode.level,
        frozen=mode.frozen_default,
    )


def temp_limits(model: str, settings: CookSettings | None = None) -> tuple[float, float]:
    if model == MODEL_BOV950:
        mode = OVEN_MODES.get(settings.mode if settings else None) if settings else None
        if mode and mode.temp:
            return float(mode.temp[1]), float(mode.temp[2])
    info = MODELS[model]
    return info.min_temp_c, info.max_temp_c


def duration_limits(model: str, settings: CookSettings | None = None) -> tuple[int, int]:
    if model == MODEL_BOV950 and settings and settings.mode in OVEN_MODES:
        mode = OVEN_MODES[settings.mode]
        return mode.min_seconds(settings.level), mode.max_seconds(settings.temperature_c, settings.level)
    return 0, MODELS[model].max_cook_s


def firmware_for(model: str, state: dict[str, Any]) -> dict[str, Any]:
    if model == MODEL_CSJ100:
        return csj_firmware(state)
    fw = state.get("firmware") if isinstance(state.get("firmware"), dict) else {}
    out = {
        "commFirmware": fw.get("comm_mcu", fw.get("commFirmware")),
        "ctrlFirmware": fw.get("host_mcu", fw.get("ctrlFirmware")),
    }
    if fw.get("teFirmware") is not None:
        out["teFirmware"] = fw["teFirmware"]
    return out


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _js_number(value: float) -> float:
    """A whole number as an int, so it's sent as 360 like the app sends it, not 360.0."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def build_manual_steps(model: str, settings: CookSettings) -> list[dict[str, Any]]:
    """Recipe steps for load-manual-recipe, as the app's getManualCookSteps."""
    if model == MODEL_CSJ100:
        return build_csj_manual_steps(
            settings.temperature_c, settings.duration_s or None,
            auto_start_timer=settings.auto_start_timer,
        )
    if model == MODEL_BSV600:
        return build_bsv600_steps(settings)
    if model == MODEL_BOV950:
        return build_bov950_steps(settings)
    raise ValueError(f"Unsupported model {model}")


def build_bsv600_steps(settings: CookSettings) -> list[dict[str, Any]]:
    """getBSV600ManualCookSteps: a preheat phase, then the timed or held cook."""
    low, high = temp_limits(MODEL_BSV600)
    if settings.temperature_c is None or not low <= settings.temperature_c <= high:
        raise ValueError(f"Temperature must be {low}-{high} °C")
    temp = _js_number(round(settings.temperature_c * 10) / 10)
    phase = {"mode": MODE_SOUS_VIDE, "temperatureCelsius": temp}
    cook = (
        {**phase, "seconds": int(settings.duration_s)}
        if settings.duration_s
        else {**phase, "skipTimer": True, "seconds": 0}
    )
    return [
        {
            "defaultAutostart": settings.auto_start_timer,
            "holdingTemperature": temp,
            "phases": [{**phase, "seconds": 0}, cook],
            "stepType": "default",
            "title": "",
            "type": STEP_TYPE_SOUS_VIDE,
        }
    ]


def bov950_phase(settings: CookSettings) -> dict[str, Any]:
    """getBOV950ManualCookPhase for the temperature, broil and slow-cook modes."""
    mode = OVEN_MODES.get(settings.mode or "")
    if mode is None:
        raise ValueError(f"Mode {settings.mode!r} can't be started remotely")
    convection = settings.convection or mode.convection
    if convection not in mode.convection_allowed:
        convection = mode.convection
    frozen = settings.frozen if mode.frozen_default is not None else None
    phase: dict[str, Any] = {
        "mode": mode.cms,
        "convection": convection,
        "rotateRemind": False,
    }
    if mode.type is OvenModeType.TEMP:
        low, high = float(mode.temp[1]), float(mode.temp[2])
        temp = settings.temperature_c if settings.temperature_c is not None else mode.temp[0]
        phase["temperatureCelsius"] = _js_number(_clamp(round(temp), low, high))
    else:
        allowed = BroilLevel if mode.type is OvenModeType.BROIL else SlowCookLevel
        level = settings.level if settings.level in {int(v) for v in allowed} else mode.level
        phase["level"] = int(level)
    seconds = settings.duration_s or mode.default_seconds(phase.get("level"))
    phase["seconds"] = int(
        _clamp(
            seconds,
            mode.min_seconds(phase.get("level")),
            mode.max_seconds(phase.get("temperatureCelsius"), phase.get("level")),
        )
    )
    phase["frozen"] = "on" if (frozen if frozen is not None else mode.frozen_default) else "off"
    phase["keepWarm"] = bool(settings.keep_warm and mode.keep_warm_allowed)
    return phase


def build_bov950_steps(settings: CookSettings) -> list[dict[str, Any]]:
    """getBOV950ManualCookStepsFromCookPhases for a single-phase manual cook."""
    mode = OVEN_MODES.get(settings.mode or "")
    phase = bov950_phase(settings)
    temp = phase.get("temperatureCelsius")
    end_temp = min(temp if temp is not None else KEEP_WARM_MAX_C, KEEP_WARM_MAX_C)
    on_complete = "keepWarm" if phase["keepWarm"] else "turnOff"
    rack = [str(mode.rack)] if mode.rack is not None else None

    def step(phases: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        out: dict[str, Any] = {**extra, "phases": phases}
        out.setdefault("onComplete", on_complete)
        out["onCompleteTemperature"] = end_temp
        if rack is not None:
            out["rackPosition"] = rack
        out.update({"stepType": out.get("stepType", "default"), "title": "", "type": "ovenSteps"})
        return out

    steps: list[dict[str, Any]] = []
    preheat_phase = {**phase, "seconds": 0}
    if not mode.preheat:
        steps.append(step([phase]))
    elif not settings.auto_start_timer:
        steps.append(step([preheat_phase], defaultAutostart=False, onComplete="stayOn"))
        steps.append(step([phase]))
    else:
        steps.append(step([preheat_phase, phase], defaultAutostart=True))

    factor, low, high = mode.a_bit_more
    # Not rounded, as in the app (getBOV950ManualCookABMStep).
    abm_seconds = _js_number(max(low, min(high, factor * phase["seconds"])))
    steps.append(step([{**phase, "seconds": abm_seconds}], stepType="aBitMore"))
    if mode.keep_warm_allowed and not phase["keepWarm"]:
        steps.append(
            {
                "phases": [
                    {
                        "mode": "warm",
                        "convection": "on",
                        "temperatureCelsius": end_temp,
                        "seconds": KEEP_WARM_SECONDS,
                    }
                ],
                "onComplete": "turnOff",
                "stepType": "keepWarm",
                "title": "",
                "type": "ovenSteps",
            }
        )
    return steps


def build_finish_wait(model: str, state: dict[str, Any]) -> dict[str, Any]:
    """Fields finish-wait adds to {applianceModel, timestamp} (useFinishWaitCommand).

    The app also sends where the cook is, for the Joule Turbo. The Joule's
    bare finish-wait was verified.
    """
    if model == MODEL_CSJ100:
        return {}
    body: dict[str, Any] = {
        "cookUuid": state.get("cookUUID"),
        "firmware": firmware_for(model, state),
    }
    recipe = state.get("recipe")
    if isinstance(recipe, dict) and recipe.get("phase") is not None:
        body["phaseIndex"] = recipe["phase"]
    body["stageIndex"] = _shadow_index(state, "currentStage", "stg")
    body["stepIndex"] = _shadow_index(state, "currentStep", "stp")
    body["wait"] = {"user": 2}
    return body


@dataclass(frozen=True)
class NextStep:
    recipe_id: str
    step_index: int


def build_next_step(state: dict[str, Any]) -> NextStep:
    """What send-step needs to go on from a waiting step (NextRecipeStep).

    The app picks the next step that isn't "a bit more", keep warm or a
    preheat. A manual cook waits after its preheat step, so that's the next
    one: the cook step.
    """
    recipe = state.get("recipe")
    recipe_id = recipe.get("id") if isinstance(recipe, dict) else recipe
    step = _shadow_index(state, "currentStep", "stp")
    if not recipe_id or not isinstance(step, int):
        raise ValueError("No cook is waiting")
    return NextStep(str(recipe_id), step + 1)


@dataclass(frozen=True)
class EditRequest:
    """How to change a running cook: CSJ program or update-cook updates."""

    csj_program: dict[str, Any] | None = None
    updates: list[dict[str, Any]] | None = None
    uuid: str = ""
    step: int = 0


def build_edit(
    model: str,
    state: dict[str, Any],
    status: ApplianceStatus,
    *,
    temperature_c: float | None = None,
    duration_s: int | None = None,
) -> EditRequest:
    if model == MODEL_CSJ100:
        return EditRequest(
            csj_program=build_csj_edit_program(
                state, set_point_c=temperature_c, cook_time_s=duration_s
            )
        )
    updates = []
    if temperature_c is not None:
        updates.append({"name": "cookSetPoint", "value": _js_number(temperature_c)})
    if duration_s is not None:
        updates.append({"name": "cookTime", "value": int(duration_s)})
    if not status.cook_id:
        raise ValueError("No cook is running")
    return EditRequest(updates=updates, uuid=status.cook_id, step=status.step_index)
