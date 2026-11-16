import type { PhenologicalStage } from '@/lib/database.types';

/**
 * The stage of each of a crop's varieties, as the Crops screen shows them: the
 * calendar-applied stage, or dormant for a variety with no stage row (the
 * column's default). Every screen that sorts crops by season reads this, so a
 * crop shown Dormant on Crops is resting everywhere else too.
 */
export function cropStages(
  cropId: number,
  varieties: Array<{ id: number; crop_id: number }>,
  effectiveStages: Array<{ variety_id: number; stage: PhenologicalStage }>
): PhenologicalStage[] {
  return varieties
    .filter((v) => v.crop_id === cropId)
    .map((v) => effectiveStages.find((s) => s.variety_id === v.id)?.stage ?? 'dormant');
}

/**
 * Whether a crop should count toward "coverage is due" right now. A crop whose
 * every variety is dormant or already past harvest is resting: a lapsed spray
 * interval on it is not something to act on, so it stays out of the due and
 * attention counts. A crop with no varieties has no stage to go by and counts.
 */
export function needsCoverageNow(stages: Array<{ stage: PhenologicalStage }>): boolean {
  if (stages.length === 0) return true;
  return stages.some((s) => s.stage !== 'dormant' && s.stage !== 'post_harvest');
}

/**
 * Which treatment types are due (lapsed) on a crop right now. The one place
 * "due" is decided, so Today's attention list and the Crops counts agree: a
 * resting crop is never due, and insecticide is held through bloom.
 */
export function dueTypes(c: {
  active: boolean;
  inBloom: boolean;
  fung: { status: string } | null;
  ins: { status: string } | null;
}): Array<'fungicide' | 'insecticide'> {
  const out: Array<'fungicide' | 'insecticide'> = [];
  if (!c.active) return out;
  if (c.fung?.status === 'red') out.push('fungicide');
  if (!c.inBloom && c.ins?.status === 'red') out.push('insecticide');
  return out;
}

/**
 * Whether most of the garden is resting (dormant or past harvest). Takes one
 * stage list per crop; crops with no varieties have nothing to go by and are
 * left out of the count.
 */
export function mostlyResting(perCrop: Array<Array<{ stage: PhenologicalStage }>>): boolean {
  const withStages = perCrop.filter((s) => s.length > 0);
  if (withStages.length === 0) return false;
  const resting = withStages.filter((s) => !needsCoverageNow(s)).length;
  return resting * 2 > withStages.length;
}

/**
 * Which monitored treatment types a crop is missing right now: lapsed (red), or
 * never sprayed at all. The rule behind Today's "spray is due" and the Weather
 * forecast's spray chips, so a spray window is only offered when Today would
 * ask for a spray. A resting crop misses nothing; insecticide is held in bloom.
 */
export function sprayMissing(c: {
  active: boolean;
  inBloom: boolean;
  monitorFung: boolean;
  monitorIns: boolean;
  fung: { status: string } | null;
  ins: { status: string } | null;
}): Array<'fungicide' | 'insecticide'> {
  const out: Array<'fungicide' | 'insecticide'> = [];
  if (!c.active) return out;
  if (c.monitorFung && (!c.fung || c.fung.status === 'red')) out.push('fungicide');
  if (c.monitorIns && !c.inBloom && (!c.ins || c.ins.status === 'red')) out.push('insecticide');
  return out;
}
