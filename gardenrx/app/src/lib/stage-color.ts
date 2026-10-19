import type { PhenologicalStage } from '@/lib/database.types';

export const STAGE_ORDER: PhenologicalStage[] = [
  'dormant',
  'bud_break',
  'green_tip',
  'tight_cluster',
  'pink',
  'bloom',
  'petal_fall',
  'fruit_set',
  'green_fruit',
  'cover_spray',
  'pre_harvest',
  'harvest',
  'post_harvest',
];

export function stageIndex(s: PhenologicalStage): number {
  const i = STAGE_ORDER.indexOf(s);
  return i < 0 ? 0 : i;
}

const STAGE_VAR: Record<PhenologicalStage, string> = {
  dormant: '--st-dormant',
  bud_break: '--st-budbreak',
  green_tip: '--st-greentip',
  tight_cluster: '--st-tightcluster',
  pink: '--st-pink',
  bloom: '--st-bloom',
  petal_fall: '--st-petalfall',
  fruit_set: '--st-fruit',
  green_fruit: '--st-fruit',
  cover_spray: '--st-fruit',
  pre_harvest: '--st-fruit',
  harvest: '--st-fruit',
  post_harvest: '--st-dormant',
};

/** CSS color for a stage dot/track (the design's phenology hue scale). */
export function stageVarColor(s: PhenologicalStage): string {
  return `var(${STAGE_VAR[s] ?? '--st-dormant'})`;
}

export function stageLabel(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
