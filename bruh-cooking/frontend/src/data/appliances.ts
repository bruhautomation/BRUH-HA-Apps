import type { HomeAssistant } from "../hass";
import type { Kind, PanelAppliance } from "../types";
import { collatorFor, languageOf } from "./locale";

/** The name the user knows the appliance by: the device registry's, as Home Assistant shows it. */
export function applianceName(
  appliance: PanelAppliance,
  hass: Pick<HomeAssistant, "devices"> | undefined,
): string {
  const device = hass?.devices?.[appliance.device_id];
  return device?.name_by_user || device?.name || appliance.name;
}

// Within an area: ovens first, then sous vide.
const KIND_RANK: Record<Kind, number> = { oven: 0, sous_vide: 1 };

export interface NamedAppliance {
  appliance: PanelAppliance;
  name: string;
}

export interface AreaGroup {
  /** Null for the appliances whose device has no area. */
  areaId: string | null;
  /** The area's name; null for "No area", which the caller translates. */
  name: string | null;
  appliances: NamedAppliance[];
}

/**
 * Each area's place in Home Assistant's own order: `hass.areas` keeps the order the user arranged
 * areas in, and areas on the same floor stay together, floors in the order they first appear.
 */
function areaOrder(areas: HomeAssistant["areas"] | undefined): Map<string, number> {
  const list = Object.values(areas ?? {});
  const floors = new Map<string, number>();
  for (const area of list) if (area.floor_id && !floors.has(area.floor_id)) floors.set(area.floor_id, floors.size);
  const ranked = list.map((area, index) => ({ id: area.area_id, floor: floors.get(area.floor_id ?? "") ?? floors.size, index }));
  ranked.sort((a, b) => a.floor - b.floor || a.index - b.index);
  return new Map(ranked.map((area, place) => [area.id, place]));
}

/**
 * The overview's sections: one per device area, in Home Assistant's area order, with appliances
 * in no area (or in an area that no longer exists) last. Within an area, ovens come before sous
 * vide, then names in the user's language.
 */
export function groupByArea(
  appliances: readonly PanelAppliance[],
  hass: Pick<HomeAssistant, "devices" | "areas" | "language" | "locale"> | undefined,
): AreaGroup[] {
  const collator = collatorFor(languageOf(hass));
  const groups = new Map<string | null, AreaGroup>();
  for (const appliance of appliances) {
    const areaId = hass?.devices?.[appliance.device_id]?.area_id ?? null;
    const area = areaId ? hass?.areas?.[areaId] : undefined;
    const key = area ? areaId : null;
    let group = groups.get(key);
    if (!group) {
      group = { areaId: key, name: area?.name ?? null, appliances: [] };
      groups.set(key, group);
    }
    group.appliances.push({ appliance, name: applianceName(appliance, hass) });
  }
  for (const group of groups.values()) {
    group.appliances.sort(
      (a, b) =>
        (KIND_RANK[a.appliance.kind] ?? 2) - (KIND_RANK[b.appliance.kind] ?? 2) ||
        collator.compare(a.name, b.name) ||
        a.appliance.device_id.localeCompare(b.appliance.device_id),
    );
  }
  const order = areaOrder(hass?.areas);
  return [...groups.values()].sort((a, b) => {
    if (a.areaId === null || b.areaId === null) return a.areaId === null ? 1 : -1;
    return (order.get(a.areaId) ?? 0) - (order.get(b.areaId) ?? 0);
  });
}

/**
 * Whether a new `hass` changes anything an appliance's card shows. Home Assistant hands every
 * panel a new `hass` on any state change in the house, which on a busy system is many times a
 * second; a card only needs to redraw for its own entities, its device, and the user's
 * language, theme and units.
 */
export function relevantChange(
  previous: HomeAssistant | undefined,
  next: HomeAssistant,
  appliance: PanelAppliance,
): boolean {
  if (!previous) return true;
  if (
    previous.language !== next.language ||
    previous.locale !== next.locale ||
    previous.themes !== next.themes ||
    previous.config !== next.config ||
    previous.user !== next.user ||
    previous.devices?.[appliance.device_id] !== next.devices?.[appliance.device_id]
  ) {
    return true;
  }
  for (const byDomain of Object.values(appliance.entities)) {
    for (const entityId of Object.values(byDomain)) {
      if (entityId && previous.states[entityId] !== next.states[entityId]) return true;
    }
  }
  return false;
}
