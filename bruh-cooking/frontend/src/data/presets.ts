import type { HomeAssistant } from "../hass";
import type { Translate } from "../i18n";
import { formatDuration, formatTemperature, isCelsius, optionLabel, temperatureUnit } from "../kinds/common";
import type { OvenModeSpec, PanelAppliance, Preset } from "../types";

/** A built-in preset's name in the user's language, or a custom one's own name. */
export function presetName(t: Translate, preset: Preset): string {
  if (!preset.builtin && preset.name) return preset.name;
  const key = `preset.${preset.id}`;
  const name = t(key);
  return name === key ? (preset.name ?? preset.id) : name;
}

/**
 * The preset's temperature in the user's unit: a built-in oven preset's own round value in °F,
 * else the Celsius value, converted. Null for a broil or slow cook, which has a level.
 */
export function presetTemperature(hass: HomeAssistant, preset: Preset): number | null {
  const { temperature_c: celsius, temperature_f: fahrenheit } = preset.settings;
  if (!isCelsius(hass) && typeof fahrenheit === "number") return fahrenheit;
  if (typeof celsius !== "number") return null;
  return isCelsius(hass) ? celsius : Math.round(((celsius * 9) / 5 + 32) * 10) / 10;
}

/** "56 °C · 1 h 30 min", or "Air fry · 400 °F · 20 min". */
export function presetSummary(
  hass: HomeAssistant,
  t: Translate,
  preset: Preset,
  modes: ReadonlyMap<string, OvenModeSpec>,
): string {
  const settings = preset.settings;
  const temperature = presetTemperature(hass, preset);
  const temp = temperature === null ? null : formatTemperature(hass, temperature, temperatureUnit(hass), 1);
  const time = settings.duration_s ? formatDuration(t, settings.duration_s) : t("value.until_stopped");
  if (preset.kind === "sous_vide") return [temp, time].join(" · ");
  const mode = settings.mode ? optionLabel(t, "mode", settings.mode) : null;
  const type = settings.mode ? modes.get(settings.mode)?.type : null;
  const level = settings.level ? optionLabel(t, "level", settings.level) : null;
  const parts = [mode, type === "temp" ? temp : level, time, settings.frozen ? t("presets.frozen") : null];
  return parts.filter((part): part is string => Boolean(part)).join(" · ");
}

/**
 * Whether the appliance can cook the preset: its kind, and its limits. A sous vide preset fits
 * the Joule's range; an oven preset needs a mode the panel knows and that can be started.
 */
export function presetFits(preset: Preset, appliance: PanelAppliance, modes: ReadonlyMap<string, OvenModeSpec>): boolean {
  if (preset.kind !== appliance.kind) return false;
  const settings = preset.settings;
  if (preset.kind === "sous_vide") {
    const celsius = settings.temperature_c;
    if (typeof celsius !== "number") return false;
    const { min_temp_c: min, max_temp_c: max, max_cook_s: longest } = appliance.limits;
    return celsius >= min && celsius <= max && (settings.duration_s ?? 0) <= longest;
  }
  const mode = settings.mode ? modes.get(settings.mode) : undefined;
  if (!mode?.remote) return false;
  if (mode.type === "temp") {
    const range = mode.temperature_c;
    const celsius = settings.temperature_c;
    if (!range || typeof celsius !== "number") return false;
    return Math.round(celsius) >= range.min && Math.round(celsius) <= range.max;
  }
  return Boolean(settings.level && mode.levels?.includes(settings.level));
}
