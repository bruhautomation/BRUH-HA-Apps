/**
 * What the integration's websocket API sends the panel.
 *
 * `custom_components/bruh_cooking/panel_api.py` builds these, `panel_spec.py` the oven
 * modes and `presets.py` the presets. Keep the two sides in step: this file is the contract.
 *
 * Commands:
 * - `{type: "bruh_cooking/panel/subscribe"}`: any user. Replies with a result, then sends a
 *   `PanelMessage` event at once and again whenever anything in it changes.
 * - `{type: "bruh_cooking/panel/apply_preset", device_id, preset_id}`: any user. Fills in
 *   the appliance's cook settings from the preset; nothing starts. Refused with `cook_running`
 *   while a cook is under way.
 * - `{type: "bruh_cooking/panel/save_preset", name?, device_id?, preset_id?}`: admins only.
 *   Without `preset_id`, saves `device_id`'s current settings as a new preset named `name`; with
 *   it, `name` renames the preset and `device_id` replaces its settings. Replies `{preset}`.
 * - `{type: "bruh_cooking/panel/delete_preset", preset_id}`: admins only.
 *
 * Errors carry one of `PanelErrorCode`, which the panel translates, or another code with a
 * message to show as it is.
 */

export type Kind = "sous_vide" | "oven";
export type Model = "CSJ100" | "BSV600" | "BOV950";

/** The Joule and the Joule Turbo are white with polished trim; the oven comes in two steels. */
export type Finish = "white_polished" | "brushed_stainless" | "black_stainless";

export type EntityDomain = "sensor" | "binary_sensor" | "number" | "select" | "switch" | "button";

/**
 * Entity ids by key, then domain, e.g. `{"cook": {"switch": "switch.kitchen_oven_cook"}}`. Keys
 * are the integration's own: the part of each entity's unique id after the appliance's serial
 * number. Disabled entities are left out.
 */
export type EntityMap = Record<string, Partial<Record<EntityDomain, string>>>;

export interface PanelAppliance {
  /** Home Assistant device registry id; the panel's route uses it. */
  device_id: string;
  entry_id: string;
  /** The account's name for it; the panel prefers the device registry's name. */
  name: string;
  model: Model;
  /** The product's name, e.g. "Joule Oven Air Fryer Pro". */
  product: string;
  kind: Kind;
  finish: Finish;
  /** False while the appliance can't be reached, or its entry is reloading. */
  available: boolean;
  /** Control has been confirmed on a real appliance. */
  tested: boolean;
  /** Cooks may be started and changed: tested, or allowed in the integration's options. */
  control_allowed: boolean;
  /** A running cook's temperature and time can be changed (not the oven's). */
  can_edit_cook: boolean;
  /** While an oven cooks, the temperature it holds its own sensor at (°C), below the setpoint. */
  sensor_target_c: number | null;
  limits: { min_temp_c: number; max_temp_c: number; max_cook_s: number };
  entities: EntityMap;
}

export type Accessory = "roasting_pan" | "broil_rack" | "air_fry_basket" | "pizza_pan" | "wire_rack" | "pot";
export type Food =
  | "croissants"
  | "casserole"
  | "chicken"
  | "steak"
  | "fries"
  | "pizza"
  | "cookies"
  | "plate"
  | "dough"
  | "covered_dish"
  | "fruit"
  | "bread"
  | "bagel"
  | "pizza_slice";
/** Which elements glow; the oven doesn't report it, so it follows the mode. */
export type Elements = "top_bottom" | "top" | "bottom" | "outer_top" | "middle_top" | "bottom_low" | "low";

export interface OvenModeSpec {
  /** The Mode select's option, or a mode only the oven itself starts (toast, bagel, …). */
  id: string;
  /** Can be started from Home Assistant; false for modes the oven only reports. */
  remote: boolean;
  type: "temp" | "broil" | "slow_cook" | null;
  /** Rack position, 1 (top) to 8. */
  rack: number;
  preheat?: boolean;
  temperature_c?: { default: number; min: number; max: number; step: number } | null;
  /** Broil and slow-cook levels, in order. */
  levels?: string[] | null;
  default_level?: string | null;
  default_seconds?: number;
  convection?: string[];
  default_convection?: string;
  /** The frozen food option's default; null when the mode doesn't offer it. */
  frozen?: boolean | null;
  keep_warm?: boolean;
  accessory: Accessory;
  food: Food | null;
  elements: Elements;
}

export interface PresetSettings {
  temperature_c?: number | null;
  /** Built-in oven presets carry both units, each a round number. */
  temperature_f?: number;
  /** 0 or absent holds a sous vide cook until it's stopped. */
  duration_s?: number | null;
  mode?: string;
  level?: string;
  convection?: string;
  frozen?: boolean;
}

export interface Preset {
  id: string;
  kind: Kind;
  builtin: boolean;
  /** A custom preset's name; built-in ones are translated by id. */
  name: string | null;
  /** "raw_safe_fish": use fish that's safe to eat raw. */
  note: string | null;
  settings: PresetSettings;
}

export interface PanelMessage {
  appliances: PanelAppliance[];
  oven_modes: OvenModeSpec[];
  presets: Preset[];
}

export type PanelErrorCode =
  | "cook_running"
  | "unknown_appliance"
  | "unknown_preset"
  | "invalid_preset"
  | "too_many_presets"
  | "unavailable"
  | "unauthorized";
