/**
 * The panel's fixtures: one appliance each, as the integration sends it and with its entities'
 * states, written by tests/test_panel_fixtures.py from the real integration. Shared with the
 * backend's tests, so both sides work from the same states.
 */
import type { HassEntity } from "../../src/hass";
import type { OvenModeSpec, PanelAppliance, Preset } from "../../src/types";
import joule_cooking from "../../../tests/fixtures/panel/joule-cooking.json";
import joule_cooking_us from "../../../tests/fixtures/panel/joule-cooking-us.json";
import joule_done from "../../../tests/fixtures/panel/joule-done.json";
import joule_idle from "../../../tests/fixtures/panel/joule-idle.json";
import joule_low_water from "../../../tests/fixtures/panel/joule-low-water.json";
import joule_preheating from "../../../tests/fixtures/panel/joule-preheating.json";
import joule_ready from "../../../tests/fixtures/panel/joule-ready.json";
import oven_cooking from "../../../tests/fixtures/panel/oven-cooking.json";
import oven_cooking_metric from "../../../tests/fixtures/panel/oven-cooking-metric.json";
import oven_door_open from "../../../tests/fixtures/panel/oven-door-open.json";
import oven_finished from "../../../tests/fixtures/panel/oven-finished.json";
import oven_idle from "../../../tests/fixtures/panel/oven-idle.json";
import oven_keeping_warm from "../../../tests/fixtures/panel/oven-keeping-warm.json";
import oven_preheating from "../../../tests/fixtures/panel/oven-preheating.json";
import oven_press_start from "../../../tests/fixtures/panel/oven-press-start.json";
import oven_ready from "../../../tests/fixtures/panel/oven-ready.json";
import shared from "../../../tests/fixtures/panel/shared.json";

export interface Fixture {
  /** When the states were written (ISO). */
  now: string;
  unit_system: "metric" | "us_customary";
  appliance: PanelAppliance;
  device: {
    id: string;
    name: string;
    name_by_user: string | null;
    area_id: string | null;
    model: string | null;
    model_id: string | null;
    manufacturer: string | null;
    sw_version: string | null;
  };
  area: { area_id: string; name: string } | null;
  states: Record<string, HassEntity>;
}

export const FIXTURES: Record<string, Fixture> = {
  "joule-cooking": joule_cooking as unknown as Fixture,
  "joule-cooking-us": joule_cooking_us as unknown as Fixture,
  "joule-done": joule_done as unknown as Fixture,
  "joule-idle": joule_idle as unknown as Fixture,
  "joule-low-water": joule_low_water as unknown as Fixture,
  "joule-preheating": joule_preheating as unknown as Fixture,
  "joule-ready": joule_ready as unknown as Fixture,
  "oven-cooking": oven_cooking as unknown as Fixture,
  "oven-cooking-metric": oven_cooking_metric as unknown as Fixture,
  "oven-door-open": oven_door_open as unknown as Fixture,
  "oven-finished": oven_finished as unknown as Fixture,
  "oven-idle": oven_idle as unknown as Fixture,
  "oven-keeping-warm": oven_keeping_warm as unknown as Fixture,
  "oven-preheating": oven_preheating as unknown as Fixture,
  "oven-press-start": oven_press_start as unknown as Fixture,
  "oven-ready": oven_ready as unknown as Fixture,
};

export const SHARED = shared as unknown as { oven_modes: OvenModeSpec[]; presets: Preset[] };
