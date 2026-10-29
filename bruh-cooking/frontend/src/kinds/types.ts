import type { DrawingState } from "../drawings/types";
import type { HassEntity, HomeAssistant } from "../hass";
import type { Translate } from "../i18n";
import type { EntityDomain, OvenModeSpec, PanelAppliance, Preset } from "../types";

/** Status pill colors; the card maps each to a theme-aware color. */
export type Tone = "neutral" | "warm" | "amber" | "green" | "red" | "gray";

export interface StatusPill {
  text: string;
  tone: Tone;
}

/** One label/value row in the card's info panel. */
export interface InfoRow {
  label: string;
  value: string;
}

/** The amber digits on the card's display, with a small caption under them. */
export interface DisplayText {
  text: string;
  caption?: string | null;
  /** Nothing live to show (the oven is off), so the digits are greyed. */
  dim?: boolean;
}

/**
 * Where an appliance is in a cook, from its entities, in the order the pill picks them. The
 * screen reader announcer follows the same phases.
 */
export type Phase =
  | "offline"
  | "error"
  | "updating"
  | "door_open"
  | "press_start"
  | "preheating"
  | "ready"
  | "cooking"
  | "done"
  | "keeping_warm"
  | "idle";

/** What a kind model reads an appliance through. `makeContext` in kinds/index.ts builds it. */
export interface ApplianceContext {
  appliance: PanelAppliance;
  hass: HomeAssistant;
  t: Translate;
  /** Milliseconds since the epoch, for countdowns. */
  now: number;
  /** The oven's modes by id; empty for sous vide. */
  modes: ReadonlyMap<string, OvenModeSpec>;
  presets: readonly Preset[];
  /** The entity id for a key, trying the domains in order (any domain if none given). */
  entityId(key: string, ...domains: EntityDomain[]): string | undefined;
  /** The state object for a key, trying the domains in order (any domain if none). */
  state(key: string, ...domains: EntityDomain[]): HassEntity | undefined;
}

/** How a control applies a new value; `applyAction` in actions.ts makes the call. */
export type ControlAction =
  | { type: "number"; entity_id: string }
  | { type: "select"; entity_id: string }
  | { type: "switch"; entity_id: string }
  | { type: "switch_on"; entity_id: string }
  | { type: "switch_off"; entity_id: string }
  | { type: "button"; entity_id: string };

interface ControlBase {
  /** Stable within the view, e.g. the entity key. */
  id: string;
  label: string;
  /** Disabled with a translated reason, e.g. the appliance being offline. */
  disabled?: boolean;
  reason?: string | null;
  /** Small secondary text under the control. */
  hint?: string | null;
  /** A link under the reason, e.g. to the integration's options for an admin. */
  link?: { text: string; href: string } | null;
}

export type Control =
  | (ControlBase & {
      kind: "setpoint";
      action: ControlAction;
      value: number | null;
      min: number;
      max: number;
      step: number;
      /** "°F" or "°C". */
      unit: string;
    })
  | (ControlBase & {
      kind: "select";
      action: ControlAction;
      value: string | null;
      /** `value` is what the entity takes; `label` is translated. */
      options: Array<{ value: string; label: string }>;
      /** Tiles in a grid (the oven's modes) rather than pills or a dropdown. */
      tiles?: boolean;
    })
  | (ControlBase & { kind: "toggle"; action: ControlAction; value: boolean | null })
  | (ControlBase & {
      kind: "action";
      action: ControlAction;
      /** Asked in the inline confirmation bar first; null acts at once. */
      confirm: string | null;
      /** The button's text, e.g. "Start". */
      button: string;
      tone?: "primary" | "danger";
    })
  | (ControlBase & {
      kind: "duration";
      action: ControlAction;
      /** Minutes. */
      value: number | null;
      min: number;
      max: number;
      /** Minutes; 0 is "Until stopped" when the range starts at 0. */
      presets: number[];
      /** The text for 0 minutes, e.g. "Until stopped". */
      zero?: string | null;
    })
  /** A read-only value, already formatted. */
  | (ControlBase & { kind: "reading"; value: string; tone?: "normal" | "warning" | "alert" })
  /** A read-only time left, ticking until `end` (ms), or still at `seconds` while paused. */
  | (ControlBase & { kind: "countdown"; end: number | null; seconds: number | null });

export interface Section {
  id: string;
  title: string;
  controls: Control[];
  /** Shown once above the controls, e.g. why a running oven cook can't be changed. */
  note?: string | null;
  /** Collapsed until opened, for details. */
  collapsed?: boolean;
}

export interface KindModel {
  phase(ctx: ApplianceContext): Phase;
  drawingState(ctx: ApplianceContext): DrawingState;
  status(ctx: ApplianceContext): StatusPill;
  /** Two or three rows for the overview card. */
  infoRows(ctx: ApplianceContext): InfoRow[];
  /** The card's display, only where the real appliance has one (the oven). */
  display(ctx: ApplianceContext): DisplayText | null;
  /** The full view's sections, everyday controls first (presets and the chart are separate). */
  sections(ctx: ApplianceContext): Section[];
  /** The drawing's description for screen readers. */
  describe(ctx: ApplianceContext): string;
}
