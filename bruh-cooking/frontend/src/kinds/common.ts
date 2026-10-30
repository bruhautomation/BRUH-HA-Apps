/**
 * What the kind models share: reading entities by key, formatting values the way the panel shows
 * them, and building controls that follow the entities exactly, unavailable states included.
 */
import type { HassEntity, HomeAssistant } from "../hass";
import type { Translate } from "../i18n";
import type { EntityDomain } from "../types";
import type { ApplianceContext, Control, Phase, Section } from "./types";

// ---------------------------------------------------------------------------------------------
// Reading entities

/** An entity's state, or null when it has none ("unavailable", "unknown"). */
export function stateValue(entity: HassEntity | undefined): string | null {
  const state = entity?.state;
  if (state === undefined || state === "" || state === "unavailable" || state === "unknown") return null;
  return state;
}

/** The first state a key has among the domains, in order (any domain if none are given). */
export function read(ctx: ApplianceContext, key: string, ...domains: EntityDomain[]): string | null {
  if (!domains.length) return stateValue(ctx.state(key));
  for (const domain of domains) {
    const value = stateValue(ctx.state(key, domain));
    if (value !== null) return value;
  }
  return null;
}

/** "on" or "off" as a boolean; null when there's no value. Binary sensors and switches. */
export function isOn(ctx: ApplianceContext, key: string, ...domains: EntityDomain[]): boolean | null {
  const state = read(ctx, key, ...(domains.length ? domains : (["binary_sensor", "switch"] as const)));
  return state === "on" ? true : state === "off" ? false : null;
}

export function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || value.trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function numberOf(ctx: ApplianceContext, key: string, ...domains: EntityDomain[]): number | null {
  return toNumber(read(ctx, key, ...domains));
}

export function has(ctx: ApplianceContext, key: string, ...domains: EntityDomain[]): boolean {
  return ctx.entityId(key, ...domains) !== undefined;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** The Status sensor's state: offline, idle, preheating, ready, cooking, done, … */
export function statusOf(ctx: ApplianceContext): string | null {
  return read(ctx, "status", "sensor");
}

/**
 * Where the appliance is in a cook. The oven's door counts while a cook is open; an error the
 * Error sensor reports counts even when the Status sensor hasn't caught up.
 */
export function phaseOf(ctx: ApplianceContext): Phase {
  const status = statusOf(ctx);
  if (!ctx.appliance.available || status === null || status === "offline") return "offline";
  if (status === "error" || isOn(ctx, "problem", "binary_sensor") === true) return "error";
  if (status === "updating") return "updating";
  const open = isOn(ctx, "cook", "switch") === true;
  if (open && isOn(ctx, "door", "binary_sensor") === true) return "door_open";
  switch (status) {
    case "waiting_for_button":
      return "press_start";
    case "preheating":
    case "ready":
    case "cooking":
    case "done":
    case "keeping_warm":
      return status;
    default:
      return "idle";
  }
}

/** A cook is open on the appliance, including one that's over and waiting to be finished. */
export function cookOpen(ctx: ApplianceContext): boolean {
  return isOn(ctx, "cook", "switch") === true;
}

/** A cook is under way: open, and not over with the heater off. */
export function cookActive(ctx: ApplianceContext): boolean {
  return isOn(ctx, "cooking", "binary_sensor") === true;
}

// ---------------------------------------------------------------------------------------------
// Formatting

export function temperatureUnit(hass: HomeAssistant): string {
  return hass.config?.unit_system?.temperature || "°C";
}

export function isCelsius(hass: HomeAssistant): boolean {
  return temperatureUnit(hass).includes("C");
}

/** A temperature in °C in the user's unit. */
export function fromCelsius(hass: HomeAssistant, celsius: number): number {
  return isCelsius(hass) ? celsius : (celsius * 9) / 5 + 32;
}

/** The unit an entity reports in, else the user's. */
export function unitOf(hass: HomeAssistant, entity: HassEntity | undefined): string {
  const unit = entity?.attributes?.unit_of_measurement;
  return typeof unit === "string" && unit ? unit : temperatureUnit(hass);
}

function language(hass: Pick<HomeAssistant, "locale" | "language">): string {
  return hass.locale?.language || hass.language || "en";
}

// The locales Home Assistant's frontend formats each of its number formats with.
const NUMBER_LOCALES: Record<string, string[] | undefined> = {
  comma_decimal: ["en-US", "en"],
  decimal_comma: ["de", "es", "it"],
  space_comma: ["fr", "sv", "cs"],
  system: undefined,
};
const numberFormats = new Map<string, Intl.NumberFormat>();

/**
 * A number as Home Assistant writes it for the user, with `min` to `max` decimals: in their number
 * format ("55,3" with a decimal comma), else their language's; "none" is digits without grouping.
 */
export function formatNumber(hass: Pick<HomeAssistant, "locale" | "language">, value: number, max = 0, min = 0): string {
  const format = hass.locale?.number_format;
  const locales = format === "none" ? "en-US" : format && format in NUMBER_LOCALES ? NUMBER_LOCALES[format] : language(hass);
  const key = `${format}|${String(locales)}|${min}|${max}`;
  let formatter = numberFormats.get(key);
  if (!formatter) {
    const options: Intl.NumberFormatOptions = {
      minimumFractionDigits: min,
      maximumFractionDigits: max,
      ...(format === "none" ? { useGrouping: false } : {}),
    };
    try {
      formatter = new Intl.NumberFormat(locales, options);
    } catch {
      // An unknown language tag throws; the browser's own format still reads.
      formatter = new Intl.NumberFormat(undefined, options);
    }
    numberFormats.set(key, formatter);
  }
  return formatter.format(value);
}

/** "55.3°": up to `decimals` decimals, in the user's number format; "—" when unknown. */
export function formatDegrees(hass: HomeAssistant, value: number | null, decimals = 0): string {
  if (value === null) return "—";
  const text = formatNumber(hass, value, decimals);
  return `${text === "-0" ? "0" : text}°`;
}

/** "56 °C": as `formatDegrees`, with the unit, for sentences. */
export function formatTemperature(hass: HomeAssistant, value: number | null, unit: string, decimals = 0): string {
  if (value === null) return "—";
  const text = formatNumber(hass, value, decimals);
  return `${text === "-0" ? "0" : text} ${unit}`;
}

/** Decimals for a sous vide temperature (one) and an oven's (none). */
export function decimalsFor(ctx: ApplianceContext): number {
  return ctx.appliance.kind === "sous_vide" ? 1 : 0;
}

/**
 * The zone the user sees times in: the server's when their profile asks for it, else undefined
 * for the browser's own.
 */
export function timeZone(hass: Pick<HomeAssistant, "locale" | "config">): string | undefined {
  const choice = hass.locale?.time_zone;
  return choice === "server" ? hass.config?.time_zone || undefined : undefined;
}

/** Whether the browser's own locale uses a 12-hour clock, as "system" asks. */
function systemHour12(): boolean | undefined {
  try {
    return new Intl.DateTimeFormat(undefined, { hour: "numeric" }).resolvedOptions().hour12;
  } catch {
    return undefined;
  }
}

function clockOptions(hass: HomeAssistant): Intl.DateTimeFormatOptions {
  const format = hass.locale?.time_format;
  const zone = timeZone(hass);
  // "language" follows the user's language, which formatting with it already does.
  const hour12 = format === "12" ? true : format === "24" ? false : format === "system" ? systemHour12() : undefined;
  return {
    hour: "numeric",
    minute: "2-digit",
    ...(hour12 === undefined ? {} : { hour12 }),
    ...(zone ? { timeZone: zone } : {}),
  };
}

function formatWith(hass: HomeAssistant, options: Intl.DateTimeFormatOptions, ms: number): string {
  try {
    return new Intl.DateTimeFormat(language(hass), options).format(ms);
  } catch {
    // An unknown language tag or zone throws; English still says when.
    return new Intl.DateTimeFormat("en", { ...options, timeZone: undefined }).format(ms);
  }
}

/** A time of day in the user's format, e.g. "6:42 PM" or "18:42". */
export function formatClock(hass: HomeAssistant, ms: number): string {
  return formatWith(hass, clockOptions(hass), ms);
}

function dayOf(hass: HomeAssistant, ms: number): string {
  return formatWith(hass, { year: "numeric", month: "2-digit", day: "2-digit", timeZone: timeZone(hass) }, ms);
}

/** The time alone when it's today, else the date and time. */
export function formatDateTime(hass: HomeAssistant, ms: number, now: number): string {
  if (dayOf(hass, ms) === dayOf(hass, now)) return formatClock(hass, ms);
  return formatWith(hass, { weekday: "short", ...clockOptions(hass) }, ms);
}

const pad = (value: number) => String(value).padStart(2, "0");

/** Time left as on a timer: "4:05", or "1:04:05" from an hour. Rounds up, so 0:00 means done. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

/** A length of time in words: "45 min", "1 h 30 min", "2 d 4 h". */
export function formatDuration(t: Translate, seconds: number): string {
  const minutes = Math.max(0, Math.round(seconds / 60));
  if (minutes < 60) return t("unit.minutes", { n: minutes });
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 48) return rest ? t("unit.hours_minutes", { h: hours, m: rest }) : t("unit.hours", { n: hours });
  const days = Math.floor(hours / 24);
  const extra = hours % 24;
  return extra ? t("unit.days_hours", { d: days, h: extra }) : t("unit.days", { n: days });
}

const spokenUnits = new Map<string, Intl.NumberFormat | null>();

function spokenUnit(hass: Pick<HomeAssistant, "locale" | "language">, unit: "hour" | "minute"): Intl.NumberFormat | null {
  const key = `${language(hass)}|${unit}`;
  if (!spokenUnits.has(key)) {
    try {
      spokenUnits.set(key, new Intl.NumberFormat(language(hass), { style: "unit", unit, unitDisplay: "long" }));
    } catch {
      spokenUnits.set(key, null);
    }
  }
  return spokenUnits.get(key) ?? null;
}

/**
 * The same length spelled out for a screen reader, in the user's language with its plurals:
 * "1 hour, 30 minutes". Short units read as letters ("h", "min") on some screen readers.
 */
export function spokenDuration(hass: Pick<HomeAssistant, "locale" | "language">, t: Translate, seconds: number): string {
  const minutes = Math.max(0, Math.round(seconds / 60));
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const hourFormat = spokenUnit(hass, "hour");
  const minuteFormat = spokenUnit(hass, "minute");
  if (!hourFormat || !minuteFormat) return formatDuration(t, seconds);
  const parts = [hours ? hourFormat.format(hours) : null, rest || !hours ? minuteFormat.format(rest) : null];
  return parts.filter(Boolean).join(", ");
}

const SECONDS_PER: Record<string, number> = { ms: 0.001, s: 1, min: 60, h: 3600, d: 86400 };

/** A duration sensor in seconds, whatever display unit the user picked for it. */
export function durationSeconds(entity: HassEntity | undefined): number | null {
  const value = toNumber(stateValue(entity));
  if (value === null) return null;
  const unit = entity?.attributes?.unit_of_measurement;
  return value * (typeof unit === "string" && unit in SECONDS_PER ? SECONDS_PER[unit] : 1);
}

/** A Cook time number (minutes) in seconds; null when it has none. */
export function minutesOf(ctx: ApplianceContext, key: string): number | null {
  const minutes = numberOf(ctx, key, "number");
  return minutes === null ? null : minutes * 60;
}

export interface TimeLeft {
  /** Seconds left when last reported. */
  seconds: number;
  /** When it runs out, in ms, while the timer runs; null while it's paused. */
  end: number | null;
}

/**
 * The cook's time left: the Time remaining sensor as of when it was last written, counting down
 * while the Cook end sensor has a time (the timer runs) and holding while it doesn't (paused).
 */
export function timeLeft(ctx: ApplianceContext): TimeLeft | null {
  const entity = ctx.state("time_remaining", "sensor");
  const seconds = durationSeconds(entity);
  if (seconds === null || !entity) return null;
  const running = read(ctx, "cook_end", "sensor") !== null;
  const written = Date.parse(entity.last_updated);
  return { seconds, end: running && Number.isFinite(written) ? written + seconds * 1000 : null };
}

/** Seconds left now. */
export function secondsLeft(left: TimeLeft, now: number): number {
  return left.end === null ? left.seconds : Math.max(0, (left.end - now) / 1000);
}

/**
 * A sensor's value with its unit as Home Assistant shows it: its own formatting where it has it,
 * else one decimal in the user's format.
 */
export function withUnit(hass: HomeAssistant, entity: HassEntity | undefined): string {
  const value = stateValue(entity);
  if (value === null || !entity) return "—";
  if (hass.formatEntityState) {
    try {
      return hass.formatEntityState(entity);
    } catch {
      // A frontend that can't format it; the panel's own formatting below still reads.
    }
  }
  const number = toNumber(value);
  const unit = entity.attributes?.unit_of_measurement;
  const shown = number === null ? value : formatNumber(hass, number, 1);
  return typeof unit === "string" && unit ? `${shown} ${unit}` : shown;
}

export function join(parts: ReadonlyArray<string | null | undefined | false>, separator = " · "): string | null {
  const kept = parts.filter((part): part is string => typeof part === "string" && part !== "");
  return kept.length ? kept.join(separator) : null;
}

/** An option the integration translates, e.g. the oven's modes: the panel's own text for it. */
export function optionLabel(t: Translate, group: string, option: string): string {
  const key = `${group}.${option}`;
  const label = t(key);
  return label === key ? option.replace(/_/g, " ") : label;
}

// ---------------------------------------------------------------------------------------------
// Controls

export interface ControlOptions {
  /** Defaults to the key. */
  id?: string;
  hint?: string | null;
  /** Why the control can't be used right now; the first that's set wins. */
  reasons?: ReadonlyArray<string | null | undefined | false>;
  link?: { text: string; href: string } | null;
}

interface Gate {
  disabled: boolean;
  reason: string | null;
}

/** Whether a control can be used, and why not: offline, a reason the kind knows, then the entity. */
function gate(ctx: ApplianceContext, entity: HassEntity | undefined, options: ControlOptions): Gate {
  if (!ctx.appliance.available) return { disabled: true, reason: ctx.t("reason.offline") };
  for (const reason of options.reasons ?? []) if (reason) return { disabled: true, reason };
  if (!entity || entity.state === "unavailable") return { disabled: true, reason: ctx.t("reason.unavailable") };
  return { disabled: false, reason: null };
}

export function entityFor(ctx: ApplianceContext, key: string, domain: EntityDomain) {
  const entityId = ctx.entityId(key, domain);
  return entityId ? { entityId, entity: ctx.hass.states[entityId] as HassEntity | undefined } : null;
}

/** The id, label, hint and disabled state every control starts from. */
export function base(
  ctx: ApplianceContext,
  key: string,
  label: string,
  entity: HassEntity | undefined,
  options: ControlOptions = {},
) {
  const gated = gate(ctx, entity, options);
  return {
    id: options.id ?? key,
    label,
    hint: options.hint ?? null,
    ...gated,
    link: gated.disabled ? (options.link ?? null) : null,
  };
}

/** A setpoint from a number entity, in the entity's own unit and limits. */
export function numberSetpoint(
  ctx: ApplianceContext,
  key: string,
  label: string,
  options: ControlOptions & { step?: number } = {},
): Control | null {
  const found = entityFor(ctx, key, "number");
  if (!found) return null;
  const attributes = found.entity?.attributes ?? {};
  return {
    kind: "setpoint",
    ...base(ctx, key, label, found.entity, options),
    action: { type: "number", entity_id: found.entityId },
    value: toNumber(stateValue(found.entity)),
    min: toNumber(attributes.min) ?? 0,
    max: toNumber(attributes.max) ?? 100,
    step: options.step ?? toNumber(attributes.step) ?? 1,
    unit: unitOf(ctx.hass, found.entity),
  };
}

/** Minutes from a number entity, with presets. */
export function durationControl(
  ctx: ApplianceContext,
  key: string,
  label: string,
  presets: number[],
  options: ControlOptions & { zero?: string | null } = {},
): Control | null {
  const found = entityFor(ctx, key, "number");
  if (!found) return null;
  const attributes = found.entity?.attributes ?? {};
  const value = toNumber(stateValue(found.entity));
  return {
    kind: "duration",
    ...base(ctx, key, label, found.entity, options),
    action: { type: "number", entity_id: found.entityId },
    value: value === null ? null : Math.round(value),
    min: toNumber(attributes.min) ?? 0,
    max: toNumber(attributes.max) ?? 5760,
    presets,
    zero: options.zero ?? null,
  };
}

/** A select entity's options, translated in `group` (e.g. "mode"). */
export function selectControl(
  ctx: ApplianceContext,
  key: string,
  label: string,
  group: string,
  options: ControlOptions & { tiles?: boolean; fallback?: string | null } = {},
): Control | null {
  const found = entityFor(ctx, key, "select");
  if (!found) return null;
  const offered = found.entity?.attributes?.options;
  const values = Array.isArray(offered) ? offered.filter((option): option is string => typeof option === "string") : [];
  return {
    kind: "select",
    ...base(ctx, key, label, found.entity, options),
    action: { type: "select", entity_id: found.entityId },
    value: stateValue(found.entity) ?? options.fallback ?? null,
    options: values.map((value) => ({ value, label: optionLabel(ctx.t, group, value) })),
    ...(options.tiles ? { tiles: true } : {}),
  };
}

export function switchToggle(
  ctx: ApplianceContext,
  key: string,
  label: string,
  options: ControlOptions = {},
): Control | null {
  const found = entityFor(ctx, key, "switch");
  if (!found) return null;
  const state = stateValue(found.entity);
  return {
    kind: "toggle",
    ...base(ctx, key, label, found.entity, options),
    action: { type: "switch", entity_id: found.entityId },
    value: state === "on" ? true : state === "off" ? false : null,
  };
}

export function reading(
  id: string,
  label: string,
  value: string | null,
  options: { tone?: "normal" | "warning" | "alert"; hint?: string | null } = {},
): Control {
  return {
    kind: "reading",
    id,
    label,
    value: value ?? "—",
    hint: options.hint ?? null,
    ...(options.tone ? { tone: options.tone } : {}),
  };
}

export function section(
  id: string,
  title: string,
  controls: ReadonlyArray<Control | null | undefined>,
  extra: { note?: string | null; collapsed?: boolean } = {},
): Section | null {
  const kept = controls.filter((control): control is Control => Boolean(control));
  if (!kept.length) return null;
  return {
    id,
    title,
    controls: kept,
    ...(extra.note ? { note: extra.note } : {}),
    ...(extra.collapsed ? { collapsed: true } : {}),
  };
}

export function compact<T>(items: ReadonlyArray<T | null | undefined | false>): T[] {
  return items.filter((item): item is T => item !== null && item !== undefined && item !== false);
}

/** Where an admin turns on control of untested appliances. */
export function integrationLink(ctx: ApplianceContext): { text: string; href: string } | null {
  if (ctx.hass.user?.is_admin !== true) return null;
  return { text: ctx.t("reason.open_options"), href: `/config/integrations/integration/bruh_cooking` };
}

/** Why cooks can't be started or changed on an untested appliance; null when they can. */
export function controlReason(ctx: ApplianceContext): string | null {
  if (ctx.appliance.control_allowed) return null;
  return ctx.t("reason.untested", { product: ctx.appliance.product });
}
