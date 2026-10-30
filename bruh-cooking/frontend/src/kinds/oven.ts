/**
 * The Joule Oven Air Fryer Pro. Its display shows the temperature while preheating, the time
 * left while cooking, and "End" once done. A cook that's under way can't be changed, as in the
 * app, so the settings are for the next cook.
 */
import type { OvenDisplay, OvenLcd, OvenState } from "../drawings/types";
import type { OvenModeSpec } from "../types";
import {
  compact,
  cookActive,
  cookOpen,
  durationControl,
  formatClock,
  formatCountdown,
  formatDegrees,
  formatDuration,
  formatTemperature,
  fromCelsius,
  isCelsius,
  isOn,
  join,
  minutesOf,
  numberOf,
  numberSetpoint,
  optionLabel,
  phaseOf,
  read,
  reading,
  secondsLeft,
  section,
  selectControl,
  spokenDuration,
  switchToggle,
  temperatureUnit,
  timeLeft,
} from "./common";
import { cookSection, detailsSection, errorText, finishedCook, pillFor } from "./shared";
import type { ApplianceContext, Control, InfoRow, KindModel, Phase, Section } from "./types";

// The oven bakes when the mode is unknown.
const FALLBACK_MODE: OvenModeSpec = {
  id: "bake",
  remote: true,
  type: "temp",
  rack: 6,
  accessory: "roasting_pan",
  food: "croissants",
  elements: "top_bottom",
};
// Cook time presets, in minutes, kept to those inside the mode's limits.
const COOK_TIMES = [5, 10, 15, 20, 30, 45, 60, 90, 120, 240, 480];
const HEATING: ReadonlySet<Phase> = new Set(["preheating", "ready", "cooking", "keeping_warm"]);
// The display lights orange while the oven runs.
const LIT: ReadonlySet<Phase> = new Set(["preheating", "ready", "cooking", "keeping_warm", "door_open"]);
// A broil or slow cook's level as the display's segments spell it.
const LEVEL_GLYPHS: Record<string, string> = { low: "Lo", medium: "MEd", high: "HI" };
const WITH_FOOD: ReadonlySet<Phase> = new Set(["cooking", "done", "keeping_warm"]);

/** The mode shown: the running one while a cook is open, else the one chosen for the next. */
function modeId(ctx: ApplianceContext): string | null {
  if (cookOpen(ctx)) {
    const active = read(ctx, "active_mode", "sensor");
    if (active) return active;
  }
  return read(ctx, "oven_mode", "select");
}

function modeOf(ctx: ApplianceContext): OvenModeSpec {
  const id = modeId(ctx);
  return (id && ctx.modes.get(id)) || ctx.modes.get("bake") || FALLBACK_MODE;
}

/**
 * The mode drawn. Keeping warm after a cook, it's the cook's own, which Mode still shows, so the
 * food stays in the oven; a keep warm started on the oven draws its own covered dish.
 */
function drawnMode(ctx: ApplianceContext, phase: Phase): OvenModeSpec {
  if (phase === "keeping_warm") {
    const cooked = read(ctx, "oven_mode", "select");
    const spec = cooked ? ctx.modes.get(cooked) : undefined;
    if (spec) return spec;
  }
  return modeOf(ctx);
}

function modeName(ctx: ApplianceContext): string {
  return optionLabel(ctx.t, "mode", modeId(ctx) ?? modeOf(ctx).id);
}

/** The target in the user's unit; a broil or slow cook has a level instead. */
function target(ctx: ApplianceContext): number | null {
  return numberOf(ctx, "target_temperature", "number");
}

/** "400°", or the level ("High"), for the mode's type. */
function setting(ctx: ApplianceContext, mode: OvenModeSpec): string | null {
  if (mode.type === "broil" || mode.type === "slow_cook") {
    const level = read(ctx, "level", "select");
    return level ? optionLabel(ctx.t, "level", level) : null;
  }
  const value = target(ctx);
  return value === null ? null : formatDegrees(ctx.hass, value);
}

function convection(ctx: ApplianceContext, mode: OvenModeSpec): string | null {
  const value = read(ctx, "convection", "select");
  // Air fry has only Super; saying so adds nothing.
  if (!value || (mode.convection?.length ?? 0) <= 1) return null;
  return optionLabel(ctx.t, "convection_summary", value);
}

/** The temperature the oven holds its own sensor at, in the user's unit, while it cooks. */
function sensorTarget(ctx: ApplianceContext): number | null {
  const celsius = ctx.appliance.sensor_target_c;
  return celsius === null || celsius === undefined ? null : fromCelsius(ctx.hass, celsius);
}

function ovenDisplay(ctx: ApplianceContext, phase: Phase): OvenDisplay | null {
  const t = ctx.t;
  const mode = modeName(ctx);
  const current = numberOf(ctx, "current_temperature", "sensor");
  const set = setting(ctx, modeOf(ctx));
  switch (phase) {
    case "offline":
      return null;
    case "preheating":
      return { main: formatDegrees(ctx.hass, current), caption: join([mode, set]), dim: false };
    case "ready":
      return { main: formatDegrees(ctx.hass, current ?? target(ctx)), caption: t("display.ready"), dim: false };
    case "cooking":
    case "keeping_warm":
    case "door_open": {
      const left = timeLeft(ctx);
      if (left) return { main: formatCountdown(secondsLeft(left, ctx.now) * 1000), caption: join([mode, set]), dim: false };
      return { main: formatDegrees(ctx.hass, current), caption: join([mode, set]), dim: false };
    }
    // The display lights orange only while the oven runs: it's white while it waits for Start,
    // and again once the cook is over (the instruction book).
    case "done":
      return { main: t("display.end"), caption: mode, dim: true };
    case "press_start":
      return { main: set ?? mode, caption: t("display.press_start"), dim: true };
    case "error":
      return { main: t("display.error"), caption: errorText(ctx), dim: false };
    default:
      return { main: t("display.off"), caption: null, dim: true };
  }
}

/** The time as the display shows it: "24:30" (minutes and seconds) under an hour, else "1:30" (hours and minutes). */
function lcdClock(seconds: number): { text: string; units: "min_sec" | "hr_min" } {
  const total = Math.max(0, Math.ceil(seconds));
  const pad = (value: number) => String(value).padStart(2, "0");
  if (total < 3600) return { text: `${Math.floor(total / 60)}:${pad(total % 60)}`, units: "min_sec" };
  const minutes = Math.floor(total / 60);
  return { text: `${Math.floor(minutes / 60)}:${pad(minutes % 60)}`, units: "hr_min" };
}

/**
 * What the oven's own display shows, segment by segment: asleep while idle; the mode, its
 * temperature or level, the time and the rack while it waits for Start or preheats; the time
 * counting down while it cooks; "donE" once it's done.
 */
function ovenLcd(ctx: ApplianceContext, phase: Phase): OvenLcd | null {
  if (phase === "offline" || phase === "idle" || phase === "updating") return null;
  const mode = modeOf(ctx);
  const error = phase === "error";
  const warm = phase === "keeping_warm";
  // A setpoint under the mode's lowest can't be the cook's: the digits stay blank.
  const lowest = mode.temperature_c ? fromCelsius(ctx.hass, mode.temperature_c.min) : null;
  const reported = target(ctx);
  const value = reported !== null && lowest !== null && reported < lowest - 1 ? null : reported;
  const level = read(ctx, "level", "select");
  const temp = error
    ? "Err"
    : warm
      ? null
      : mode.type === "temp"
        ? value === null
          ? null
          : String(Math.round(value))
        : level
          ? (LEVEL_GLYPHS[level] ?? null)
          : null;
  const left = timeLeft(ctx);
  const counting = phase === "cooking" || phase === "door_open" || warm;
  const seconds = counting ? (left ? secondsLeft(left, ctx.now) : null) : minutesOf(ctx, "cook_time");
  const clock = phase === "done" ? { text: "donE", units: null } : error || seconds === null ? { text: null, units: null } : lcdClock(seconds);
  const fan = read(ctx, "convection", "select");
  return {
    lit: LIT.has(phase),
    mode: warm ? "keep_warm" : mode.id,
    temp,
    unit: mode.type === "temp" && !error && !warm ? (isCelsius(ctx.hass) ? "C" : "F") : null,
    time: clock.text,
    timeUnits: clock.units,
    convection: fan === "on" || fan === "super" ? fan : "off",
    rack: phase === "press_start" || phase === "preheating" ? mode.rack : null,
    prompt: phase === "press_start" ? "press_start" : phase === "preheating" ? "preheating" : null,
    frozen: mode.frozen !== null && mode.frozen !== undefined && isOn(ctx, "frozen", "switch") === true,
  };
}

function accessoryName(ctx: ApplianceContext, mode: OvenModeSpec): string {
  return ctx.t(`accessory.${mode.accessory}`);
}

export const oven: KindModel = {
  phase: phaseOf,

  drawingState(ctx): OvenState {
    const phase = phaseOf(ctx);
    const mode = drawnMode(ctx, phase);
    const open = isOn(ctx, "door", "binary_sensor") === true;
    const heating = HEATING.has(phase) && !open;
    const fan = read(ctx, "convection", "select");
    return {
      kind: "oven",
      available: ctx.appliance.available,
      mode: mode.id,
      rack: mode.rack,
      accessory: mode.accessory,
      food: WITH_FOOD.has(phase) || (phase === "door_open" && cookActive(ctx)) ? mode.food : null,
      frozen: mode.frozen !== null && mode.frozen !== undefined && isOn(ctx, "frozen", "switch") === true,
      elements: heating ? (phase === "keeping_warm" ? "low" : mode.elements) : null,
      fan: heating && (fan === "on" || fan === "super") ? fan : "off",
      door_open: open,
      light: open || heating || phase === "cooking",
      lcd: ovenLcd(ctx, phase),
      start_prompt: phase === "press_start",
      error: phase === "error",
    };
  },

  status: (ctx) => pillFor(ctx, phaseOf(ctx), "status.press_start_oven"),

  infoRows(ctx) {
    const t = ctx.t;
    const phase = phaseOf(ctx);
    const mode = modeOf(ctx);
    const summary = join([modeName(ctx), setting(ctx, mode), convection(ctx, mode)]) ?? "—";
    const rack = t("info.rack_value", { n: mode.rack, accessory: accessoryName(ctx, mode) });
    const rows: InfoRow[] = [];
    if (phase === "idle" || phase === "offline" || phase === "error" || phase === "updating") {
      const seconds = minutesOf(ctx, "cook_time");
      rows.push({ label: t("info.next_cook"), value: join([summary, seconds ? formatDuration(t, seconds) : null]) ?? "—" });
      rows.push({ label: t("info.rack"), value: rack });
      if (phase === "error") rows.push({ label: t("info.problem"), value: errorText(ctx) });
      return rows;
    }
    rows.push({ label: t("info.mode"), value: summary });
    const current = numberOf(ctx, "current_temperature", "sensor");
    if (phase === "preheating" || phase === "ready" || phase === "press_start") {
      if (current !== null) rows.push({ label: t("info.oven"), value: formatDegrees(ctx.hass, current) });
      rows.push({ label: t("info.rack"), value: rack });
      return rows;
    }
    const left = timeLeft(ctx);
    if (left && phase !== "done") {
      const ends = left.end === null ? t("info.paused") : t("info.ends", { time: formatClock(ctx.hass, left.end) });
      rows.push({ label: t("info.time_left"), value: join([formatCountdown(secondsLeft(left, ctx.now) * 1000), ends]) ?? "—" });
    }
    if (phase === "done") rows.push({ label: t("info.next"), value: t(finishedCook(ctx) ? "info.oven_finished" : "info.remove_food") });
    else if (current !== null && rows.length < 3) rows.push({ label: t("info.oven"), value: formatDegrees(ctx.hass, current) });
    return rows;
  },

  display(ctx) {
    const display = ovenDisplay(ctx, phaseOf(ctx));
    return display ? { text: display.main, caption: display.caption, dim: display.dim } : null;
  },

  sections(ctx) {
    const t = ctx.t;
    const phase = phaseOf(ctx);
    const mode = modeOf(ctx);
    const unit = temperatureUnit(ctx.hass);
    const active = cookActive(ctx);
    const open = cookOpen(ctx);
    const current = numberOf(ctx, "current_temperature", "sensor");
    const sensor = sensorTarget(ctx);
    const left = timeLeft(ctx);
    const seconds = minutesOf(ctx, "cook_time");
    const what = join([modeName(ctx), mode.type === "temp" ? formatTemperature(ctx.hass, target(ctx), unit) : setting(ctx, mode)], " ");
    const start = t("confirm.start_oven", { mode: what ?? modeName(ctx), time: seconds ? formatDuration(t, seconds) : "—" });
    const door = isOn(ctx, "door", "binary_sensor");
    const status: Array<Control | null> = [
      open || current !== null
        ? reading("current_temperature", t("control.oven_temperature"), formatTemperature(ctx.hass, current, unit), {
            hint: sensor !== null ? t("hint.sensor_target", { temp: formatTemperature(ctx.hass, sensor, unit) }) : null,
          })
        : null,
      open ? reading("mode", t("control.mode"), join([modeName(ctx), setting(ctx, mode), convection(ctx, mode)])) : null,
      open && left && phase !== "done"
        ? {
            kind: "countdown",
            id: "time_left",
            label: t("control.time_left"),
            end: left.end,
            seconds: left.seconds,
            hint: left.end === null ? t("hint.paused") : t("info.ends", { time: formatClock(ctx.hass, left.end) }),
          }
        : null,
      door === null ? null : reading("door", t("control.door"), t(door ? "value.open" : "value.closed"), { tone: door && open ? "warning" : "normal" }),
      phase === "idle" || phase === "preheating" || phase === "ready"
        ? reading("rack", t("control.rack"), t("info.rack_value", { n: mode.rack, accessory: accessoryName(ctx, mode) }))
        : null,
    ];
    // As in the app, a running cook can't be changed: the settings wait for the next one.
    const locked = active ? t("reason.oven_running") : null;
    const reasons = [locked];
    const modes = selectControl(ctx, "oven_mode", t("control.mode"), "mode", { tiles: true, reasons });
    const temperature = mode.type === "temp" ? numberSetpoint(ctx, "target_temperature", t("control.temperature"), { reasons }) : null;
    const level =
      mode.type === "broil" || mode.type === "slow_cook" ? selectControl(ctx, "level", t(`control.level_${mode.type}`), "level", { reasons }) : null;
    const limits = durationControl(ctx, "cook_time", t("control.cook_time"), COOK_TIMES, { reasons });
    const time =
      limits && limits.kind === "duration"
        ? { ...limits, presets: COOK_TIMES.filter((minutes) => minutes >= limits.min && minutes <= limits.max) }
        : limits;
    const fan = (mode.convection?.length ?? 0) > 1 ? selectControl(ctx, "convection", t("control.convection"), "convection", { reasons }) : null;
    const settings: Array<Control | null> = [
      modes,
      temperature,
      level,
      time,
      fan,
      mode.frozen !== null && mode.frozen !== undefined ? switchToggle(ctx, "frozen", t("control.frozen"), { reasons, hint: t("hint.frozen") }) : null,
      mode.keep_warm ? switchToggle(ctx, "keep_warm", t("control.keep_warm"), { reasons, hint: t("hint.keep_warm") }) : null,
      mode.preheat ? switchToggle(ctx, "auto_start_timer", t("control.auto_start_timer"), { reasons, hint: t("hint.auto_start_timer_oven") }) : null,
    ];
    return compact<Section>([
      section("cook", t("section.cook"), [...status, ...cookSection(ctx, start)]),
      section("settings", t(active ? "section.this_cook" : "section.next_cook"), settings, { note: locked }),
      detailsSection(ctx),
    ]);
  },

  describe(ctx) {
    const t = ctx.t;
    const state = oven.drawingState(ctx) as OvenState;
    const phase = phaseOf(ctx);
    const mode = modeOf(ctx);
    const parts = [t(`describe.oven_${ctx.appliance.finish}`, { product: ctx.appliance.product })];
    parts.push(`${pillFor(ctx, phase, "status.press_start_oven").text}.`);
    if (phase !== "idle" && phase !== "offline") {
      const summary = join([modeName(ctx), setting(ctx, mode)], ", ");
      if (summary) parts.push(t("describe.mode", { mode: summary }));
    }
    const current = numberOf(ctx, "current_temperature", "sensor");
    if (current !== null) parts.push(t("describe.oven_temperature", { temp: formatTemperature(ctx.hass, current, temperatureUnit(ctx.hass)) }));
    const left = timeLeft(ctx);
    if (left && (phase === "cooking" || phase === "door_open")) {
      parts.push(t(left.end === null ? "describe.time_paused" : "describe.time_left", { time: spokenDuration(ctx.hass, t, secondsLeft(left, ctx.now)) }));
    }
    const accessory = accessoryName(ctx, mode);
    parts.push(
      state.food
        ? t("describe.rack_food", { n: state.rack, accessory, food: t(`food.${state.food}`) })
        : t("describe.rack", { n: state.rack, accessory }),
    );
    if (state.door_open) parts.push(t("describe.door_open"));
    if (state.fan !== "off") parts.push(t(`describe.fan_${state.fan}`));
    return parts.join(" ");
  },
};
