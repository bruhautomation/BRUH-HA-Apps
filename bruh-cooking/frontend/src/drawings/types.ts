import type { TemplateResult } from "lit";
import type { Accessory, Elements, Finish, Food, Model } from "../types";

/**
 * Everything a drawing needs. Drawings are pure: the same input gives the same picture, so the
 * gallery can render any state without Home Assistant.
 */
export interface DrawingInput {
  /**
   * Unique per rendered drawing. Prefix every SVG id (gradients, filters, clip paths, masks)
   * with it: several drawings share one shadow root, and duplicate ids resolve to the wrong
   * definition.
   */
  uid: string;
  model: Model;
  finish: Finish;
  state: DrawingState;
  /** The page theme. The appliance looks the same in both; only the floor shadow adapts. */
  theme: "light" | "dark";
  /** Still water, steam and fan. */
  reducedMotion?: boolean;
  /**
   * The height in CSS pixels the drawing is shown at, when the caller knows it. Drawings size
   * their readouts from it, so a label is the same size on screen on a small card and in the
   * large full view. Without it, they use a share of the drawing's own height.
   */
  pixelHeight?: number;
}

export interface SousVideState {
  kind: "sous_vide";
  /** False while the appliance can't be reached: draw it desaturated, its light off. */
  available: boolean;
  /** A cook is open: the water circulates and the light is on. */
  running: boolean;
  /** Heating up to the target: steam rises as the water warms. */
  heating: boolean;
  /** The food bag is in the water. */
  food: boolean;
  /** The water temperature in °C, for its tint and steam; null when unknown. */
  waterC: number | null;
  /** The water temperature on the container, formatted ("55.3°"); null when unknown. */
  readout: string | null;
  /** The target while heating up, formatted; null otherwise. */
  targetReadout: string | null;
  /** Low water draws the water below the minimum line; tipped draws the circulator on its side. */
  error: "low_water" | "tipped" | "other" | null;
}

export interface OvenDisplay {
  /** The big digits: a temperature, the time left, "Done" or "Off". */
  main: string;
  /** The line under them, e.g. the mode. */
  caption: string | null;
  /** Nothing live to show: the display is dim. */
  dim: boolean;
}

/**
 * What the oven's own display shows: its words and digits are fixed segments, lit or not, as on
 * the real LCD.
 */
export interface OvenLcd {
  /** Lit orange while the oven runs; pale (black on black stainless) otherwise. */
  lit: boolean;
  /** The mode the arrow points at in the display's list of functions. */
  mode: string;
  /** Up to three digits or letters for the temperature row: "350", or a level ("HI"). */
  temp: string | null;
  /** The temperature's unit, shown beside a temperature. */
  unit: "F" | "C" | null;
  /** The time row: "24:30", "1:30" or "donE". */
  time: string | null;
  /** The units beside the time. */
  timeUnits: "min_sec" | "hr_min" | null;
  convection: "off" | "on" | "super";
  /** The rack position the display asks for; null hides it. */
  rack: number | null;
  prompt: "press_start" | "preheating" | null;
  frozen: boolean;
}

export interface OvenState {
  kind: "oven";
  available: boolean;
  /** The mode drawn: the running one, else the one chosen for the next cook. */
  mode: string;
  /** Rack position, 1 (top) to 8. */
  rack: number;
  accessory: Accessory;
  /** The food on the accessory, or null when it's empty. */
  food: Food | null;
  /** Frozen food is on: pizza looks frosted. */
  frozen: boolean;
  /** Which elements glow; null when none do. */
  elements: Elements | null;
  fan: "off" | "on" | "super";
  door_open: boolean;
  /** The cavity is lit: the door is open, or a cook is under way. */
  light: boolean;
  /** The oven's display; null while it's asleep or offline. */
  lcd: OvenLcd | null;
  /** The oven waits for its Start button, which is lit. */
  start_prompt: boolean;
  error: boolean;
}

export type DrawingState = SousVideState | OvenState;

/**
 * Draws an appliance as an `html` template holding one `<svg>` with a viewBox in true
 * proportions (1 unit = 1 mm).
 */
export type DrawingRenderer = (input: DrawingInput) => TemplateResult;
