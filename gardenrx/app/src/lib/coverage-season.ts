import type { PhenologicalStage } from '@/lib/database.types';

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
