import type { HassEntity, HomeAssistant } from "../hass";
import type { Translate } from "../i18n";
import type { EntityDomain, OvenModeSpec, PanelAppliance, Preset } from "../types";
import { oven } from "./oven";
import { sousVide } from "./sous-vide";
import type { ApplianceContext, KindModel } from "./types";

export function kindModel(appliance: PanelAppliance): KindModel {
  return appliance.kind === "oven" ? oven : sousVide;
}

/** What the models share across appliances: the oven's modes and the presets. */
export interface Shared {
  modes: ReadonlyMap<string, OvenModeSpec>;
  presets: readonly Preset[];
}

export const NO_SHARED: Shared = { modes: new Map(), presets: [] };

export function sharedFrom(modes: readonly OvenModeSpec[] | undefined, presets: readonly Preset[] | undefined): Shared {
  return { modes: new Map((modes ?? []).map((mode) => [mode.id, mode])), presets: presets ?? [] };
}

export function makeContext(
  appliance: PanelAppliance,
  hass: HomeAssistant,
  t: Translate,
  now: number,
  shared: Shared = NO_SHARED,
): ApplianceContext {
  const entityId = (key: string, ...domains: EntityDomain[]): string | undefined => {
    const byDomain = appliance.entities?.[key];
    if (!byDomain) return undefined;
    if (!domains.length) return Object.values(byDomain)[0];
    for (const domain of domains) if (byDomain[domain]) return byDomain[domain];
    return undefined;
  };
  return {
    appliance,
    hass,
    t,
    now,
    modes: shared.modes,
    presets: shared.presets,
    entityId,
    state(key: string, ...domains: EntityDomain[]): HassEntity | undefined {
      const id = entityId(key, ...domains);
      return id ? hass.states[id] : undefined;
    },
  };
}
