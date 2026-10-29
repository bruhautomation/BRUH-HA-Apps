/**
 * The Joule and the Joule Turbo: a circulator clipped in a container of water. They have no
 * display, so the water temperature sits on the container in the drawing instead.
 */
import type { SousVideState } from "../drawings/types";
import {
  compact,
  controlReason,
  cookActive,
  cookOpen,
  durationControl,
  formatClock,
  formatCountdown,
  formatDegrees,
  formatDuration,
  formatTemperature,
  integrationLink,
  isCelsius,
  join,
  minutesOf,
  numberOf,
  numberSetpoint,
  phaseOf,
  read,
  reading,
  secondsLeft,
  section,
  spokenDuration,
  switchToggle,
  timeLeft,
  unitOf,
} from "./common";
import { cookSection, detailsSection, errorText, pillFor } from "./shared";
import type { ApplianceContext, Control, InfoRow, KindModel, Section } from "./types";

// Cook time presets, in minutes; 0 holds the temperature until the cook is stopped.
const COOK_TIMES = [0, 30, 60, 90, 120, 240];

function temperatures(ctx: ApplianceContext) {
  const unit = unitOf(ctx.hass, ctx.state("current_temperature", "sensor"));
  return {
    current: numberOf(ctx, "current_temperature", "sensor"),
    target: numberOf(ctx, "target_temperature", "number"),
    unit,
  };
}

/** A temperature in the user's unit, in °C, for the drawing's tint and steam. */
function celsius(ctx: ApplianceContext, value: number | null): number | null {
  if (value === null) return null;
  return isCelsius(ctx.hass) ? value : ((value - 32) * 5) / 9;
}

function errorKind(ctx: ApplianceContext): SousVideState["error"] {
  if (phaseOf(ctx) !== "error") return null;
  const error = read(ctx, "error", "sensor");
  if (error === "low_water_level") return "low_water";
  if (error === "tipped_over") return "tipped";
  return "other";
}

/** "1 h 30 min" for a cook time in seconds, or "Until stopped". */
function cookTimeText(ctx: ApplianceContext, seconds: number | null): string {
  return seconds ? formatDuration(ctx.t, seconds) : ctx.t("value.until_stopped");
}

export const sousVide: KindModel = {
  phase: phaseOf,

  drawingState(ctx) {
    const phase = phaseOf(ctx);
    const { current, target } = temperatures(ctx);
    const open = ["preheating", "ready", "cooking", "done", "keeping_warm", "press_start"].includes(phase);
    return {
      kind: "sous_vide",
      available: ctx.appliance.available,
      running: open || cookActive(ctx),
      heating: phase === "preheating",
      food: phase === "cooking" || phase === "done",
      waterC: celsius(ctx, current),
      readout: current === null ? null : formatDegrees(ctx.hass, current, 1),
      targetReadout: phase === "preheating" && target !== null ? formatDegrees(ctx.hass, target, 1) : null,
      error: errorKind(ctx),
    };
  },

  status: (ctx) => pillFor(ctx, phaseOf(ctx), "status.press_button_joule"),

  infoRows(ctx) {
    const t = ctx.t;
    const phase = phaseOf(ctx);
    const { current, target } = temperatures(ctx);
    const rows: InfoRow[] = [];
    const now = formatDegrees(ctx.hass, current, 1);
    const goal = formatDegrees(ctx.hass, target, 1);
    if (cookOpen(ctx) || phase === "preheating" || phase === "ready" || phase === "cooking" || phase === "done") {
      rows.push({ label: t("info.water"), value: t("info.now_of_target", { now, target: goal }) });
      const left = timeLeft(ctx);
      if (phase === "cooking" && left) {
        const seconds = secondsLeft(left, ctx.now);
        const ends = left.end === null ? null : t("info.ends", { time: formatClock(ctx.hass, left.end) });
        rows.push({ label: t("info.time_left"), value: join([formatCountdown(seconds * 1000), ends]) ?? "—" });
      } else if (phase === "cooking") {
        rows.push({ label: t("info.time"), value: t("value.until_stopped") });
      } else if (phase === "preheating" || phase === "ready") {
        rows.push({ label: t("info.cook_time"), value: cookTimeText(ctx, minutesOf(ctx, "cook_time")) });
      }
      if (phase === "ready") rows.push({ label: t("info.next"), value: t("info.add_food") });
      if (phase === "done") rows.push({ label: t("info.next"), value: t("info.remove_food") });
      return rows;
    }
    rows.push({ label: t("info.water"), value: now });
    rows.push({ label: t("info.next_cook"), value: join([goal, cookTimeText(ctx, minutesOf(ctx, "cook_time"))]) ?? "—" });
    if (phase === "error") rows.push({ label: t("info.problem"), value: errorText(ctx) });
    return rows;
  },

  display: () => null,

  sections(ctx) {
    const t = ctx.t;
    const { current, target, unit } = temperatures(ctx);
    const active = cookActive(ctx);
    const open = cookOpen(ctx);
    const seconds = minutesOf(ctx, "cook_time");
    const temp = formatTemperature(ctx.hass, target, unit, 1);
    const name = ctx.appliance.product;
    const start = seconds
      ? t("confirm.start_sous_vide", { name, temp, time: cookTimeText(ctx, seconds) })
      : t("confirm.start_sous_vide_hold", { name, temp });
    const left = timeLeft(ctx);
    const status: Array<Control | null> = [
      reading("current_temperature", t("control.water_temperature"), current === null ? null : formatTemperature(ctx.hass, current, unit, 1)),
      open ? reading("target", t("control.target"), formatTemperature(ctx.hass, target, unit, 1)) : null,
      open && phaseOf(ctx) === "cooking"
        ? left
          ? {
              kind: "countdown",
              id: "time_left",
              label: t("control.time_left"),
              end: left.end,
              seconds: left.seconds,
              hint: left.end === null ? t("hint.paused") : t("info.ends", { time: formatClock(ctx.hass, left.end) }),
            }
          : reading("time_left", t("control.time_left"), t("value.until_stopped"))
        : null,
    ];
    // Changing a running cook needs control, as starting one does; the settings for the next
    // cook only change Home Assistant's own settings.
    const editReason = active ? controlReason(ctx) : null;
    const link = editReason ? integrationLink(ctx) : null;
    const settings: Array<Control | null> = [
      numberSetpoint(ctx, "target_temperature", t("control.target_temperature"), {
        step: 0.5,
        reasons: [editReason],
        link,
        hint: active ? t("hint.changes_cook") : null,
      }),
      durationControl(ctx, "cook_time", t("control.cook_time"), COOK_TIMES, {
        reasons: [editReason],
        link,
        zero: t("value.until_stopped"),
        hint: active ? t("hint.changes_time_left") : null,
      }),
      switchToggle(ctx, "auto_start_timer", t("control.auto_start_timer"), {
        hint: t("hint.auto_start_timer"),
      }),
    ];
    return compact<Section>([
      section("cook", t("section.cook"), [...status, ...cookSection(ctx, start)]),
      section("settings", t(active ? "section.this_cook" : "section.next_cook"), settings),
      detailsSection(ctx),
    ]);
  },

  describe(ctx) {
    const t = ctx.t;
    const state = sousVide.drawingState(ctx) as SousVideState;
    const { current, target, unit } = temperatures(ctx);
    const phase = phaseOf(ctx);
    const parts: string[] = [t("describe.sous_vide", { product: ctx.appliance.product })];
    if (state.error === "tipped") parts.push(t("describe.tipped"));
    if (state.error === "low_water") parts.push(t("describe.low_water"));
    if (current !== null) {
      parts.push(
        state.running
          ? t("describe.water_target", {
              now: formatTemperature(ctx.hass, current, unit, 1),
              target: formatTemperature(ctx.hass, target, unit, 1),
            })
          : t("describe.water", { now: formatTemperature(ctx.hass, current, unit, 1) }),
      );
    }
    parts.push(`${pillFor(ctx, phase, "status.press_button_joule").text}.`);
    const left = timeLeft(ctx);
    if (phase === "cooking" && left) parts.push(t("describe.time_left", { time: spokenDuration(ctx.hass, t, secondsLeft(left, ctx.now)) }));
    if (state.food) parts.push(t("describe.food_bag"));
    return parts.join(" ");
  },
};
