/**
 * A stand-in for Home Assistant's `hass` object, built from panel fixtures: the entities' states,
 * the devices and their area, the user's language, theme and units, and a connection that sends
 * the panel message. Calls are recorded, and history is made up from the fixture's cook.
 */
import type { HassEntity, HomeAssistant } from "../../src/hass";
import type { PanelMessage } from "../../src/types";
import { SHARED, type Fixture } from "./panel";

export interface FakeOptions {
  dark?: boolean;
  language?: string;
  admin?: boolean;
  /** Overrides the fixtures' own unit system. */
  units?: "metric" | "us_customary";
  /** An error every service call fails with, as Home Assistant returns it. */
  failWith?: Record<string, unknown>;
  /** The backend's translations in the user's language, for `loadBackendTranslation`. */
  backend?: Record<string, string>;
}

export interface Call {
  kind: "service" | "ws";
  data: Record<string, unknown>;
}

export interface FakeHass extends HomeAssistant {
  calls: Call[];
  message: PanelMessage;
  /** Replaces states, as Home Assistant hands the panel a new `hass`. */
  withStates(states: Record<string, Partial<HassEntity>>): FakeHass;
}

const ERRORS: Record<string, string> = {
  none: "None",
  low_water_level: "Low water level",
  tipped_over: "Tipped over",
  door_open: "Door open",
  heater_broken: "Heater fault",
  other: "Other",
};

function formatEntityState(entity: HassEntity): string {
  const unit = entity.attributes?.unit_of_measurement;
  const number = Number(entity.state);
  if (entity.entity_id.endsWith("_error")) return ERRORS[entity.state] ?? entity.state;
  if (entity.state !== "" && Number.isFinite(number) && typeof unit === "string") {
    const rounded = unit === "%" || unit === "min" ? Math.round(number) : Math.round(number * 10) / 10;
    return `${rounded} ${unit}`;
  }
  return entity.state;
}

/** The cook's history, made up: the Cook switch on for the last while, the temperature rising. */
function history(hass: FakeHass, message: Record<string, unknown>): Record<string, unknown> {
  const ids = (message.entity_ids as string[]) ?? [];
  const start = Date.parse(String(message.start_time));
  const end = message.end_time ? Date.parse(String(message.end_time)) : Date.now();
  const out: Record<string, unknown[]> = {};
  for (const id of ids) {
    const state = hass.states[id];
    if (!state) continue;
    if (id.startsWith("switch.")) {
      out[id] = [{ s: "off", lu: (end - 6 * 3600_000) / 1000 }, ...(state.state === "on" ? [{ s: "on", lu: (end - 75 * 60_000) / 1000 }] : [])];
      continue;
    }
    const value = Number.parseFloat(state.state);
    if (!Number.isFinite(value)) continue;
    const fahrenheit = state.attributes?.unit_of_measurement === "°F";
    const room = fahrenheit ? 70 : 21;
    const rows: unknown[] = [];
    if (id.startsWith("number.")) {
      rows.push({ s: String(value), lu: start / 1000 });
    } else {
      const span = Math.max(1, end - start);
      for (let index = 0; index <= 120; index++) {
        const at = start + (span * index) / 120;
        const share = Math.min(1, index / 40);
        const wobble = Math.sin(index / 3) * (fahrenheit ? 0.6 : 0.15) * share;
        rows.push({ s: (room + (value - room) * (1 - (1 - share) ** 2) + wobble).toFixed(1), lu: at / 1000 });
      }
    }
    out[id] = rows;
  }
  return out;
}

export function fakeHass(fixtures: readonly Fixture[], options: FakeOptions = {}): FakeHass {
  const units = options.units ?? fixtures[0]?.unit_system ?? "metric";
  const states: Record<string, HassEntity> = {};
  const devices: HomeAssistant["devices"] = {};
  const areas: HomeAssistant["areas"] = {};
  for (const fixture of fixtures) {
    Object.assign(states, fixture.states);
    devices[fixture.device.id] = { ...fixture.device };
    if (fixture.area) areas[fixture.area.area_id] = { ...fixture.area };
  }
  const message: PanelMessage = {
    appliances: fixtures.map((fixture) => fixture.appliance),
    oven_modes: SHARED.oven_modes,
    presets: SHARED.presets,
  };
  const calls: Call[] = [];
  const hass: FakeHass = {
    states,
    devices,
    areas,
    language: options.language ?? "en",
    locale: { language: options.language ?? "en", number_format: "language", time_format: "language" },
    themes: { darkMode: options.dark === true },
    user: { name: "Pat", is_admin: options.admin !== false },
    config: { unit_system: { temperature: units === "us_customary" ? "°F" : "°C" }, time_zone: "UTC" },
    calls,
    message,
    connection: {
      async subscribeMessage<T>(callback: (message: T) => void) {
        setTimeout(() => callback(message as unknown as T), 0);
        return async () => {};
      },
    },
    async callService(domain, service, data, target) {
      calls.push({ kind: "service", data: { domain, service, ...(data ?? {}), ...(target ?? {}) } });
      if (options.failWith) throw options.failWith;
      return null;
    },
    async loadBackendTranslation() {
      const table = options.backend ?? {};
      return (key: string, values?: Record<string, unknown>) =>
        (table[key] ?? "").replace(/\{(\w+)\}/g, (match, name) => String(values?.[name] ?? match));
    },
    async callWS<T>(msg: Record<string, unknown>): Promise<T> {
      calls.push({ kind: "ws", data: msg });
      if (msg.type === "history/history_during_period") return history(hass, msg) as T;
      return null as T;
    },
    formatEntityState,
    withStates(changes) {
      const next = { ...hass.states };
      for (const [id, change] of Object.entries(changes)) next[id] = { ...next[id], ...change } as HassEntity;
      return { ...hass, states: next };
    },
  };
  return hass;
}
