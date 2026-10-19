/**
 * Date-driven phenology for the Holly Springs, NC orchard/garden (USDA 7b/8a,
 * Wake County Piedmont). Each crop group has a typical year-round sequence of
 * phenological stages keyed by the local calendar, so the app can show the
 * *current* stage for today's date instead of a value that has to be edited by
 * hand (and goes stale the moment the season moves on).
 *
 * Model: one entry per stage transition, `{ stage, start }`, where `start` is a
 * `"MM-DD"` day of the year. Entries are listed in ascending calendar order and
 * each stage runs until the next one begins; the final entry is the late-fall
 * `dormant` window, which wraps across the new year back to the first spring
 * stage. To find the current stage we take the latest entry whose `start` is on
 * or before today — or, before the first spring transition, the wrapped dormant
 * window.
 *
 * Dates are deliberate, hand-tuned approximations for the Triangle/Piedmont and
 * are cross-checked against the harvest windows in `variety-catalog.ts`. They
 * lump together the varieties within a group (early vs. late cultivars bloom and
 * ripen a couple of weeks apart), so they describe the group's representative
 * timing rather than any single variety. A grower can always pin a variety to an
 * exact stage with the per-variety override on the crop page.
 *
 * Only the true bee-pollinated fruit groups (pome, stone, berries, grapes,
 * pawpaw) pass through the `bloom` stage, because `bloom` drives the
 * orchard-wide pollinator insecticide interlock. Annual vegetables, herbs, turf
 * and ornamentals — whose flowering is continuous, undesirable (bolting), or not
 * a crop-pollination event — progress through vegetative/fruit stages instead so
 * they never trip that safety block out of season.
 */

import type { PhenologicalStage, VarietyStage, Variety, Crop, CropGroup } from './database.types';
import { LOCATION } from '@/config/thresholds';

interface StageWindow {
  stage: PhenologicalStage;
  /** Day the stage typically begins, as "MM-DD" (local Holly Springs calendar). */
  start: string;
}

// Keyed by `crop_groups.name`. Each list is ascending by `start`, ending on the
// late-season dormant/pre-plant window that wraps the year.
export const PHENOLOGY_CALENDAR: Record<string, StageWindow[]> = {
  // ── Tree & vine fruit (pass through bloom) ──
  'Pome Fruit': [
    { stage: 'bud_break', start: '02-20' },
    { stage: 'green_tip', start: '03-05' },
    { stage: 'tight_cluster', start: '03-20' },
    { stage: 'pink', start: '03-30' },
    { stage: 'bloom', start: '04-07' },
    { stage: 'petal_fall', start: '04-20' },
    { stage: 'fruit_set', start: '05-01' },
    { stage: 'green_fruit', start: '05-25' },
    { stage: 'harvest', start: '07-20' },
    { stage: 'post_harvest', start: '11-05' },
    { stage: 'dormant', start: '11-25' },
  ],
  'Stone Fruit': [
    { stage: 'bud_break', start: '02-05' },
    { stage: 'green_tip', start: '02-20' },
    { stage: 'pink', start: '03-01' },
    { stage: 'bloom', start: '03-12' },
    { stage: 'petal_fall', start: '03-28' },
    { stage: 'fruit_set', start: '04-12' },
    { stage: 'green_fruit', start: '05-05' },
    { stage: 'harvest', start: '06-01' },
    { stage: 'post_harvest', start: '09-01' },
    { stage: 'dormant', start: '11-20' },
  ],
  Berries: [
    { stage: 'bud_break', start: '02-25' },
    { stage: 'green_tip', start: '03-10' },
    { stage: 'tight_cluster', start: '03-20' },
    { stage: 'bloom', start: '03-30' },
    { stage: 'petal_fall', start: '04-18' },
    { stage: 'fruit_set', start: '05-02' },
    { stage: 'green_fruit', start: '05-18' },
    { stage: 'harvest', start: '06-01' },
    { stage: 'post_harvest', start: '08-15' },
    { stage: 'dormant', start: '11-20' },
  ],
  Grapes: [
    { stage: 'bud_break', start: '03-15' },
    { stage: 'green_tip', start: '03-30' },
    { stage: 'tight_cluster', start: '04-20' },
    { stage: 'bloom', start: '05-05' },
    { stage: 'fruit_set', start: '05-25' },
    { stage: 'green_fruit', start: '06-20' },
    { stage: 'harvest', start: '08-10' },
    { stage: 'post_harvest', start: '10-15' },
    { stage: 'dormant', start: '11-20' },
  ],
  Pawpaw: [
    { stage: 'bud_break', start: '03-15' },
    { stage: 'green_tip', start: '04-01' },
    { stage: 'bloom', start: '04-10' },
    { stage: 'fruit_set', start: '05-01' },
    { stage: 'green_fruit', start: '06-01' },
    { stage: 'dormant', start: '11-15' },
  ],

  // ── Warm-season fruiting vegetables (no bloom: flower + fruit run together) ──
  Cucurbits: [
    { stage: 'bud_break', start: '04-20' },
    { stage: 'green_tip', start: '05-10' },
    { stage: 'fruit_set', start: '06-20' },
    { stage: 'green_fruit', start: '07-10' },
    { stage: 'dormant', start: '10-15' },
  ],
  Nightshades: [
    { stage: 'bud_break', start: '04-20' },
    { stage: 'green_tip', start: '05-05' },
    { stage: 'fruit_set', start: '06-05' },
    { stage: 'green_fruit', start: '07-10' },
    { stage: 'dormant', start: '10-25' },
  ],
  Legumes: [
    { stage: 'bud_break', start: '04-15' },
    { stage: 'green_tip', start: '05-05' },
    { stage: 'fruit_set', start: '06-05' },
    { stage: 'green_fruit', start: '06-25' },
    { stage: 'dormant', start: '10-15' },
  ],

  // ── Cool-season & root crops (spring cycle; summer/winter fallow) ──
  Brassicas: [
    { stage: 'bud_break', start: '02-15' },
    { stage: 'green_tip', start: '03-10' },
    { stage: 'green_fruit', start: '04-25' },
    { stage: 'dormant', start: '06-15' },
  ],
  'Leafy Greens': [
    { stage: 'bud_break', start: '02-20' },
    { stage: 'green_tip', start: '03-10' },
    { stage: 'green_fruit', start: '04-15' },
    { stage: 'dormant', start: '06-01' },
  ],
  'Root Vegetables': [
    { stage: 'bud_break', start: '03-01' },
    { stage: 'green_tip', start: '04-01' },
    { stage: 'green_fruit', start: '05-20' },
    { stage: 'dormant', start: '07-01' },
  ],
  Alliums: [
    { stage: 'bud_break', start: '02-01' },
    { stage: 'green_tip', start: '03-15' },
    { stage: 'green_fruit', start: '06-01' },
    { stage: 'dormant', start: '07-15' },
  ],

  // ── Perennials & long-season plantings ──
  Herbs: [
    { stage: 'bud_break', start: '03-01' },
    { stage: 'green_tip', start: '04-01' },
    { stage: 'green_fruit', start: '09-15' },
    { stage: 'dormant', start: '11-20' },
  ],
  'Turf Grass': [
    { stage: 'bud_break', start: '03-15' },
    { stage: 'green_tip', start: '04-15' },
    { stage: 'green_fruit', start: '10-01' },
    { stage: 'dormant', start: '11-15' },
  ],
  'Orchard Floor': [
    { stage: 'bud_break', start: '02-15' },
    { stage: 'green_tip', start: '04-15' },
    { stage: 'green_fruit', start: '09-01' },
    { stage: 'dormant', start: '11-15' },
  ],
  Ornamentals: [
    { stage: 'bud_break', start: '02-20' },
    { stage: 'green_tip', start: '03-15' },
    { stage: 'green_fruit', start: '05-01' },
    { stage: 'dormant', start: '11-15' },
  ],
};

/** Numeric "MM-DD" (month*100 + day) for cheap calendar comparison. */
function mdNum(md: string): number {
  const dash = md.indexOf('-');
  return Number(md.slice(0, dash)) * 100 + Number(md.slice(dash + 1));
}

/** Today's month/day in the orchard's local timezone (server runs in UTC). */
function localMdNum(now: Date): number {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: LOCATION.timezone,
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const month = Number(parts.find((p) => p.type === 'month')?.value ?? '1');
  const day = Number(parts.find((p) => p.type === 'day')?.value ?? '1');
  return month * 100 + day;
}

/**
 * The phenological stage a crop group is typically in on `now` in Holly Springs.
 * Returns null for groups without a calendar (e.g. structures, or crops with no
 * group), so callers can fall back to whatever is stored.
 */
export function deriveStage(
  groupName: string | null | undefined,
  now: Date = new Date()
): PhenologicalStage | null {
  if (!groupName) return null;
  const windows = PHENOLOGY_CALENDAR[groupName];
  if (!windows || windows.length === 0) return null;

  const today = localMdNum(now);
  // Default to the final (late-fall dormant) window, which covers the wrap into
  // the new year before the first spring transition.
  let current = windows[windows.length - 1].stage;
  for (const w of windows) {
    if (mdNum(w.start) <= today) current = w.stage;
    else break;
  }
  return current;
}

/**
 * Replace each variety's stored stage with the date-derived stage for its crop
 * group, leaving manual overrides (and any variety whose group has no calendar)
 * untouched. Returns a new array so every downstream consumer — dashboards,
 * crop pages, the spray planner, and the safety interlocks — sees the current
 * stage without any of them having to know about the calendar.
 */
export function applyPhenology(
  varietyStages: VarietyStage[],
  varieties: Pick<Variety, 'id' | 'crop_id'>[],
  crops: Pick<Crop, 'id' | 'crop_group_id'>[],
  cropGroups: Pick<CropGroup, 'id' | 'name'>[],
  now: Date = new Date()
): VarietyStage[] {
  const groupNameById = new Map(cropGroups.map((g) => [g.id, g.name]));
  const groupIdByCrop = new Map(crops.map((c) => [c.id, c.crop_group_id]));
  const groupByVariety = new Map<number, string | null>();
  for (const v of varieties) {
    const gid = groupIdByCrop.get(v.crop_id) ?? null;
    groupByVariety.set(v.id, gid != null ? (groupNameById.get(gid) ?? null) : null);
  }

  const derivedByGroup = new Map<string, PhenologicalStage | null>();
  const derivedFor = (name: string | null): PhenologicalStage | null => {
    if (!name) return null;
    if (!derivedByGroup.has(name)) derivedByGroup.set(name, deriveStage(name, now));
    return derivedByGroup.get(name) ?? null;
  };

  return varietyStages.map((vs) => {
    if (vs.is_manual_override) return vs;
    // Variety not in the supplied list (e.g. other crops on a single-crop page):
    // leave it alone rather than guess.
    if (!groupByVariety.has(vs.variety_id)) return vs;
    const derived = derivedFor(groupByVariety.get(vs.variety_id) ?? null);
    return derived ? { ...vs, stage: derived } : vs;
  });
}
