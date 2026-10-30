/** What both kinds show the same way: the pill, the Start, Stop and Continue buttons, and details. */
import {
  base,
  controlReason,
  cookActive,
  cookOpen,
  entityFor,
  integrationLink,
  isOn,
  numberOf,
  read,
  reading,
  section,
  withUnit,
} from "./common";
import type { ApplianceContext, Control, Phase, Section, StatusPill } from "./types";

/** The Error sensor's words for the appliance's error, as Home Assistant shows them. */
export function errorText(ctx: ApplianceContext): string {
  const entity = ctx.state("error", "sensor");
  const error = read(ctx, "error", "sensor");
  if (!entity || error === null || error === "none") return ctx.t("status.error");
  return withUnit(ctx.hass, entity);
}

/** The status pill for a phase. `pressKey` says which button to press on the appliance. */
export function pillFor(ctx: ApplianceContext, phase: Phase, pressKey: string): StatusPill {
  const t = ctx.t;
  switch (phase) {
    case "offline":
      return { text: t("status.offline"), tone: "gray" };
    case "error":
      return { text: errorText(ctx), tone: "red" };
    case "updating":
      return { text: t("status.updating"), tone: "gray" };
    case "door_open":
      return { text: t("status.door_open"), tone: "amber" };
    case "press_start":
      return { text: t(pressKey), tone: "amber" };
    case "preheating": {
      const percent = numberOf(ctx, "preheat", "sensor");
      return {
        text: percent === null ? t("status.preheating") : t("status.preheating_pct", { n: Math.round(percent) }),
        tone: "warm",
      };
    }
    case "ready":
      return { text: t("status.ready"), tone: "green" };
    case "cooking":
      return { text: t("status.cooking"), tone: "warm" };
    case "done":
      return { text: t("status.done"), tone: "green" };
    case "keeping_warm":
      return { text: t("status.keeping_warm"), tone: "warm" };
    default:
      return { text: t("status.idle"), tone: "neutral" };
  }
}

/** The cook is over and the appliance turned itself off, but it's still open: Finish closes it. */
export function finishedCook(ctx: ApplianceContext): boolean {
  return cookOpen(ctx) && !cookActive(ctx) && read(ctx, "status", "sensor") === "done";
}

/**
 * Start (with the settings below) while no cook is open; Stop, or Finish once a cook is over,
 * while one is; and Continue while the appliance waits for the food to go in or come out.
 */
export function cookSection(ctx: ApplianceContext, startQuestion: string): Control[] {
  const t = ctx.t;
  const cook = entityFor(ctx, "cook", "switch");
  const controls: Control[] = [];
  const reason = controlReason(ctx);
  const link = reason ? integrationLink(ctx) : null;
  if (cook) {
    if (!cookOpen(ctx)) {
      controls.push({
        kind: "action",
        ...base(ctx, "start", t("control.cook"), cook.entity, { reasons: [reason], link, hint: t("hint.start") }),
        action: { type: "switch_on", entity_id: cook.entityId },
        confirm: startQuestion,
        button: t("action.start"),
        tone: "primary",
      });
    } else {
      const finished = finishedCook(ctx);
      // Stopping always works, even where control isn't allowed.
      controls.push({
        kind: "action",
        ...base(ctx, "stop", t("control.cook"), cook.entity, {
          hint: finished ? t("hint.finish") : null,
        }),
        action: { type: "switch_off", entity_id: cook.entityId },
        confirm: finished ? null : t("confirm.stop"),
        button: t(finished ? "action.finish" : "action.stop"),
        tone: finished ? "primary" : "danger",
      });
    }
  }
  const next = entityFor(ctx, "continue", "button");
  if (next && next.entity && next.entity.state !== "unavailable") {
    const done = read(ctx, "status", "sensor") === "done";
    controls.push({
      kind: "action",
      ...base(ctx, "continue", t(done ? "control.food_out" : "control.food_in"), next.entity, {
        reasons: [reason],
        link,
        hint: t(done ? "hint.food_out" : "hint.food_in"),
      }),
      action: { type: "button", entity_id: next.entityId },
      confirm: null,
      button: t(done ? "action.food_out" : "action.food_in"),
      tone: "primary",
    });
  }
  return controls;
}

/** The model, finish and firmware, and any error; open when there's an error to read. */
export function detailsSection(ctx: ApplianceContext): Section | null {
  const t = ctx.t;
  const appliance = ctx.appliance;
  const device = ctx.hass.devices?.[appliance.device_id];
  const problem = isOn(ctx, "problem", "binary_sensor") === true;
  return section(
    "details",
    t("section.details"),
    [
      reading("model", t("control.model"), `${appliance.product} (${appliance.model})`),
      reading("finish", t("control.finish"), t(`finish.${appliance.finish}`)),
      device?.sw_version ? reading("firmware", t("control.firmware"), device.sw_version) : null,
      ctx.state("error", "sensor")
        ? reading("error", t("control.error"), problem ? errorText(ctx) : t("value.no_error"), {
            tone: problem ? "alert" : "normal",
          })
        : null,
      appliance.tested ? null : reading("tested", t("control.tested"), t("value.untested"), { hint: t("hint.untested") }),
    ],
    { collapsed: !problem },
  );
}
