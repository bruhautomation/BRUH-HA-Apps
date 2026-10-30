import type { HomeAssistant } from "../hass";
import type { PanelAppliance } from "../types";

/** One state change from Home Assistant's history; `at` is in ms since the epoch. */
export interface Change {
  state: string;
  at: number;
}

/** One reading on the chart. */
export interface Point {
  at: number;
  value: number;
}

// How far back the Cook switch's history is read for the latest cook: the longest sous vide cook
// is 96 hours.
const COOK_LOOKBACK_MS = 100 * 3600_000;
// The chart shows at most the last day of a cook, which keeps the reply small.
const CHART_SPAN_MS = 24 * 3600_000;
// After a failed fetch (a dropped connection, Home Assistant restarting), when to ask again.
const RETRY_MS = 60_000;
// Points kept per line; more are thinned evenly, keeping the newest.
const POINTS_KEPT = 1500;
// A dropped connection doesn't end a cook.
const GAPS = new Set(["unavailable", "unknown"]);

type Row = {
  s?: unknown;
  lu?: unknown;
  lc?: unknown;
  state?: unknown;
  last_changed?: unknown;
  last_updated?: unknown;
};

/**
 * The rows `history/history_during_period` sends for one entity, oldest first: compressed rows
 * (`{s, lu, lc}` in seconds, what the websocket API sends) or full ones (`{state, last_changed,
 * last_updated}` as ISO strings). A row's change time is `lc`, or `lu` where they're equal.
 */
export function parseRows(rows: unknown): Change[] {
  if (!Array.isArray(rows)) return [];
  const changes: Change[] = [];
  for (const row of rows as Row[]) {
    if (!row || typeof row !== "object") continue;
    const state = row.s ?? row.state;
    const at = toMs(row.lc ?? row.lu ?? row.last_changed ?? row.last_updated);
    if (typeof state === "string" && at !== null) changes.push({ state, at });
  }
  return changes;
}

export function toMs(value: unknown): number | null {
  // Home Assistant sends seconds; a value this large can only already be milliseconds.
  if (typeof value === "number" && Number.isFinite(value)) return value < 1e11 ? value * 1000 : value;
  if (typeof value === "string") {
    const ms = Date.parse(value);
    return Number.isNaN(ms) ? null : ms;
  }
  return null;
}

export interface CookWindow {
  start: number;
  /** Null while the cook is still open. */
  end: number | null;
}

/**
 * The latest cook in a Cook switch's changes: from when it last turned on to when it next turned
 * off, or still open. A brief unavailable spell doesn't end it. Null when the changes show none.
 */
export function latestCook(changes: readonly Change[], now: number): CookWindow | null {
  let cook: CookWindow | null = null;
  let previous: string | undefined;
  for (const change of changes) {
    if (GAPS.has(change.state)) continue;
    if (change.state === "on" && previous !== "on") cook = { start: change.at, end: null };
    else if (change.state !== "on" && previous === "on" && cook) cook = { start: cook.start, end: change.at };
    previous = change.state;
  }
  if (cook && cook.end === null && cook.start > now) return null;
  return cook;
}

/** Numeric readings, leaving out states that aren't numbers. */
export function points(changes: readonly Change[]): Point[] {
  const out: Point[] = [];
  for (const change of changes) {
    const value = Number.parseFloat(change.state);
    if (Number.isFinite(value) && !GAPS.has(change.state)) out.push({ at: change.at, value });
  }
  return out;
}

/** At most `kept` points, thinned evenly; the first and last always stay. */
export function thin(list: readonly Point[], kept = POINTS_KEPT): Point[] {
  if (list.length <= kept) return [...list];
  const step = (list.length - 1) / (kept - 1);
  return Array.from({ length: kept }, (_, index) => list[Math.round(index * step)]);
}

export interface CookChart {
  /** "none" when there's been no cook to show; "failed" when history couldn't be read. */
  status: "loading" | "ready" | "failed" | "none";
  window: CookWindow | null;
  /** The span shown: the cook, or its last day. */
  from: number;
  to: number;
  current: Point[];
  target: Point[];
}

interface Entry {
  key: string;
  status: CookChart["status"];
  window: CookWindow | null;
  current: Point[];
  target: Point[];
  retryAt: number | null;
  /** The state objects last added live, so each change is added once. */
  seen: Record<string, unknown>;
}

function cookSwitch(appliance: PanelAppliance): string | undefined {
  return appliance.entities.cook?.switch;
}

/**
 * The temperature chart's data, read synchronously: a lookup answers with what it has and
 * fetches in the background, then `onChange` asks the panel to draw again. The cook comes from
 * the Cook switch's history, its temperatures from the Temperature sensor and the Target
 * temperature number; live states extend both until the next fetch.
 */
export class CookHistory {
  private readonly entries = new Map<string, Entry>();

  constructor(
    private readonly onChange: () => void = () => {},
    private readonly now: () => number = Date.now,
  ) {}

  chart(hass: HomeAssistant | undefined, appliance: PanelAppliance): CookChart {
    const now = this.now();
    const switchId = cookSwitch(appliance);
    const empty: CookChart = { status: "none", window: null, from: now, to: now, current: [], target: [] };
    if (!hass || !switchId || !hass.states[switchId]) return empty;
    // A new cook, or the end of one, fetches again.
    const key = `${appliance.device_id}|${hass.states[switchId].last_changed}`;
    let entry = this.entries.get(appliance.device_id);
    if (!entry || entry.key !== key || (entry.retryAt !== null && now >= entry.retryAt)) {
      entry = { key, status: "loading", window: entry?.key === key ? entry.window : null, current: [], target: [], retryAt: null, seen: {} };
      this.entries.set(appliance.device_id, entry);
      void this.fetch(hass, appliance, entry);
    }
    if (entry.status === "ready") this.extend(hass, appliance, entry);
    const window = entry.window;
    if (!window) return { ...empty, status: entry.status === "ready" ? "none" : entry.status };
    const to = window.end ?? now;
    const from = Math.max(window.start, to - CHART_SPAN_MS);
    return { status: entry.status, window, from, to, current: thin(entry.current), target: thin(entry.target) };
  }

  /** Adds the live states that came after the fetch. */
  private extend(hass: HomeAssistant, appliance: PanelAppliance, entry: Entry): void {
    if (!entry.window || entry.window.end !== null) return;
    for (const [key, list] of [
      ["current_temperature", entry.current],
      ["target_temperature", entry.target],
    ] as const) {
      const id = key === "current_temperature" ? appliance.entities[key]?.sensor : appliance.entities[key]?.number;
      const state = id ? hass.states[id] : undefined;
      if (!id || !state || entry.seen[id] === state) continue;
      entry.seen[id] = state;
      const value = Number.parseFloat(state.state);
      const at = toMs(state.last_updated);
      if (!Number.isFinite(value) || at === null) continue;
      const last = list[list.length - 1];
      if (last && at <= last.at) continue;
      if (last && last.value === value && list.length > 1 && list[list.length - 2].value === value) list[list.length - 1] = { at, value };
      else list.push({ at, value });
    }
  }

  private async fetch(hass: HomeAssistant, appliance: PanelAppliance, entry: Entry): Promise<void> {
    const switchId = cookSwitch(appliance)!;
    const now = this.now();
    try {
      const switchRows = await history(hass, [switchId], now - COOK_LOOKBACK_MS, now, true);
      let window = latestCook(parseRows(switchRows[switchId]), now);
      // The recorder writes a moment behind the live state: a cook that has only just started
      // may not be in the reply yet.
      const live = hass.states[switchId];
      if (live?.state === "on" && (!window || window.end !== null)) {
        window = { start: toMs(live.last_changed) ?? now, end: null };
      }
      if (this.entries.get(appliance.device_id) !== entry) return;
      entry.window = window;
      if (window) {
        const to = window.end ?? now;
        const from = Math.max(window.start, to - CHART_SPAN_MS);
        const current = appliance.entities.current_temperature?.sensor;
        const target = appliance.entities.target_temperature?.number;
        const ids = [current, target].filter((id): id is string => Boolean(id));
        const rows = ids.length ? await history(hass, ids, from, window.end ?? undefined, true) : {};
        if (this.entries.get(appliance.device_id) !== entry) return;
        entry.current = current ? points(parseRows(rows[current])) : [];
        entry.target = target ? points(parseRows(rows[target])) : [];
      }
      entry.status = "ready";
    } catch {
      if (this.entries.get(appliance.device_id) !== entry) return;
      entry.status = "failed";
      entry.retryAt = this.now() + RETRY_MS;
    }
    this.onChange();
  }
}

async function history(
  hass: HomeAssistant,
  entityIds: string[],
  start: number,
  end: number | undefined,
  includeStart: boolean,
): Promise<Record<string, unknown>> {
  const reply = await hass.callWS<Record<string, unknown> | null>({
    type: "history/history_during_period",
    start_time: new Date(start).toISOString(),
    ...(end === undefined ? {} : { end_time: new Date(end).toISOString() }),
    include_start_time_state: includeStart,
    significant_changes_only: false,
    entity_ids: entityIds,
    minimal_response: true,
    no_attributes: true,
  });
  return reply ?? {};
}
