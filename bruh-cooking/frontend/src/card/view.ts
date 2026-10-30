import { nothing, type TemplateResult } from "lit";
import { renderDrawing } from "../drawings/index";
import type { DrawingInput, DrawingState } from "../drawings/types";
import { kindModel, makeContext, type Shared } from "../kinds/index";
import type { DisplayText, InfoRow, StatusPill } from "../kinds/types";
import type { HomeAssistant } from "../hass";
import type { Translate } from "../i18n";
import type { PanelAppliance } from "../types";

/** What the overview card shows for an appliance, from its kind model. */
export interface CardView {
  status: StatusPill;
  rows: InfoRow[];
  display: DisplayText | null;
  state: DrawingState;
  /** The drawing's description, for screen readers. */
  description: string;
}

const reported = new Set<string>();
// A message that changes every time (one quoting a value, say) would otherwise grow the set
// on every clock tick.
const REPORTS_KEPT = 200;

/**
 * Runs one piece of a kind model or drawing, so an appliance whose state surprises it shows a
 * plainer card instead of breaking the whole panel. Each failure is logged once, not on every
 * clock tick.
 */
export function attempt<T>(what: string, run: () => T, fallback: T): T {
  try {
    return run();
  } catch (error) {
    const key = `${what}: ${String(error)}`;
    if (!reported.has(key) && reported.size < REPORTS_KEPT) {
      reported.add(key);
      console.error(`Breville+ panel: ${what} failed`, error);
    }
    return fallback;
  }
}

/** A drawing state to fall back on when the model trips over the appliance's state. */
export function fallbackState(appliance: PanelAppliance): DrawingState {
  if (appliance.kind === "oven") {
    return {
      kind: "oven",
      available: appliance.available,
      mode: "bake",
      rack: 6,
      accessory: "roasting_pan",
      food: null,
      frozen: false,
      elements: null,
      fan: "off",
      door_open: false,
      light: false,
      lcd: null,
      start_prompt: false,
      error: false,
    };
  }
  return {
    kind: "sous_vide",
    available: appliance.available,
    running: false,
    heating: false,
    food: false,
    waterC: null,
    readout: null,
    targetReadout: null,
    error: null,
  };
}

export function cardView(
  appliance: PanelAppliance,
  hass: HomeAssistant,
  t: Translate,
  now: number,
  shared: Shared,
): CardView {
  const model = kindModel(appliance);
  const ctx = makeContext(appliance, hass, t, now, shared);
  const what = (part: string) => `${appliance.kind} ${part} for ${appliance.device_id}`;
  const state = attempt(what("drawing state"), () => model.drawingState(ctx), fallbackState(appliance));
  const description = attempt(what("description"), () => model.describe(ctx), appliance.product);
  if (!appliance.available) {
    // Nothing it last reported can be trusted, so the display goes dark; the info rows show the
    // entities' own unavailable values.
    return {
      status: { text: t("status.offline"), tone: "gray" },
      rows: attempt(what("info rows"), () => model.infoRows(ctx), []),
      display: null,
      state: { ...state, available: false },
      description,
    };
  }
  return {
    status: attempt(what("status"), () => model.status(ctx), { text: "", tone: "neutral" }),
    rows: attempt(what("info rows"), () => model.infoRows(ctx), []),
    display: attempt(what("display"), () => model.display(ctx), null),
    state,
    description,
  };
}

export function prefersReducedMotion(): boolean {
  try {
    return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** The drawing's input. `pixelHeight` is the height it's shown at (see DrawingSize). */
export function drawingInput(
  appliance: PanelAppliance,
  state: DrawingState,
  hass: Pick<HomeAssistant, "themes"> | undefined,
  uid: string,
  pixelHeight?: number,
): DrawingInput {
  return {
    uid,
    model: appliance.model,
    finish: appliance.finish,
    state: appliance.available ? state : { ...state, available: false },
    theme: hass?.themes?.darkMode ? "dark" : "light",
    reducedMotion: prefersReducedMotion(),
    ...(pixelHeight ? { pixelHeight } : {}),
  };
}

/** The appliance's drawing; nothing if it fails. */
export function safeDrawing(input: DrawingInput): TemplateResult | typeof nothing {
  return attempt<TemplateResult | typeof nothing>(`${input.state.kind} drawing`, () => renderDrawing(input), nothing);
}
