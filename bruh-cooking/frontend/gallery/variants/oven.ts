import type { OvenLcd, OvenState } from "../../src/drawings/types";
import type { Accessory, Elements, Finish, Food } from "../../src/types";
import type { GalleryVariant } from "../types";

const idle: OvenState = {
  kind: "oven",
  available: true,
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

function oven(id: string, title: string, state: Partial<OvenState>, finish: Finish = "brushed_stainless"): GalleryVariant {
  return {
    id: `oven-${finish === "black_stainless" ? "black-" : ""}${id}`,
    title,
    input: { model: "BOV950", finish, state: { ...idle, ...state } },
    width: 560,
    reference: finish === "black_stainless" ? "BOV950_BOV950BST1BUS1_pdp2.png" : "BOV950_BOV950BSS1BUS1_pdp3.png",
  };
}

const baking = { elements: "top_bottom" as Elements, fan: "on" as const, light: true };

/** The display as the oven shows a bake at 350 °F for 30 minutes. */
function lcd(changes: Partial<OvenLcd>): OvenLcd {
  return {
    lit: true,
    mode: "bake",
    temp: "350",
    unit: "F",
    time: "30:00",
    timeUnits: "min_sec",
    convection: "on",
    rack: null,
    prompt: null,
    frozen: false,
    ...changes,
  };
}

// Every mode as it cooks: its rack, accessory, food and elements (panel_spec.OVEN_DRAWING).
const MODES: Array<[string, number, Accessory, Food | null, Elements, OvenState["fan"]]> = [
  ["air_fry", 3, "air_fry_basket", "fries", "top", "super"],
  ["roast", 6, "broil_rack", "chicken", "top_bottom", "on"],
  ["broil", 1, "broil_rack", "steak", "top", "off"],
  ["pizza", 7, "pizza_pan", "pizza", "top_bottom", "on"],
  ["cookies", 5, "roasting_pan", "cookies", "top_bottom", "on"],
  ["reheat", 4, "wire_rack", "plate", "top_bottom", "on"],
  ["slow_cook", 8, "pot", null, "bottom_low", "on"],
  ["proof", 8, "wire_rack", "dough", "bottom_low", "off"],
  ["warm", 4, "wire_rack", "covered_dish", "low", "on"],
  ["dehydrate", 3, "air_fry_basket", "fruit", "low", "super"],
  ["bottom_bake", 6, "roasting_pan", "casserole", "bottom", "on"],
  ["outer_top_broil", 1, "broil_rack", "steak", "outer_top", "off"],
  ["middle_top_broil", 1, "broil_rack", "steak", "middle_top", "off"],
  ["toast", 4, "wire_rack", "bread", "top_bottom", "off"],
  ["bagel", 4, "wire_rack", "bagel", "top_bottom", "off"],
  ["crispy_reheat", 4, "wire_rack", "pizza_slice", "top_bottom", "on"],
];

export const variants: GalleryVariant[] = [
  oven("bake-idle", "Bake, idle: rack 6 and the roasting pan", {}),
  oven("bake-start", "Waiting for Start", { start_prompt: true, lcd: lcd({ lit: false, rack: 6, prompt: "press_start" }) }),
  oven("bake-preheating", "Bake, preheating", { ...baking, lcd: lcd({ rack: 6, prompt: "preheating" }) }),
  oven("bake-cooking", "Bake, cooking", { ...baking, food: "croissants", lcd: lcd({ time: "24:30" }) }),
  oven("bake-door", "Door open while cooking", { food: "croissants", door_open: true, light: true, lcd: lcd({ time: "24:30" }) }),
  oven("bake-done", "Done", { food: "croissants", lcd: lcd({ lit: false, time: "donE", timeUnits: null }) }),
  oven("bake-offline", "Offline", { available: false, lcd: null }),
  oven("bake-idle", "Black stainless, idle", {}, "black_stainless"),
  oven("bake-cooking", "Black stainless, cooking", { ...baking, food: "croissants", lcd: lcd({ time: "24:30" }) }, "black_stainless"),
  oven("bake-start", "Black stainless, waiting for Start", { start_prompt: true, lcd: lcd({ lit: false, rack: 6, prompt: "press_start" }) }, "black_stainless"),
  oven("bake-door", "Black stainless, door open", { food: "croissants", door_open: true, light: true, lcd: lcd({ time: "24:30" }) }, "black_stainless"),
  ...MODES.map(([mode, rack, accessory, food, elements, fan]) =>
    oven(`mode-${mode.replace(/_/g, "-")}`, mode, {
      mode,
      rack,
      accessory,
      food,
      elements,
      fan,
      light: true,
      frozen: mode === "pizza",
      lcd: lcd({ mode, time: "12:00", convection: fan }),
    }),
  ),
];
