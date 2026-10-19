/**
 * Physical form of a treatment, inferred from the unit it's measured in, so the
 * Stock page can talk about the right kind of container and offer sensible units.
 *
 *   liquid → concentrate/RTU in a BOTTLE, measured by volume (fl oz, mL, gal…)
 *   dry    → wettable powder / soluble powder / WDG granule in a BAG or jar,
 *            measured by WEIGHT (lb, oz, g)
 *   count  → pre-measured PACKS / tablets, measured by count
 *
 * Pure module (no React) so both server and client components can use it.
 */

export type ProductForm = 'liquid' | 'dry' | 'count';

/** Volume units (liquids). NOTE: "oz" is treated as WEIGHT — use "fl oz" for fluid. */
export const VOLUME_UNITS = ['mL', 'fl oz', 'tbsp', 'tsp', 'pt', 'qt', 'gal'] as const;
/** Weight units (dry goods — powders, granules, bags). */
export const WEIGHT_UNITS = ['g', 'oz', 'lb'] as const;
/** Count units (packets, tablets). */
export const COUNT_UNITS = ['ct', 'packets'] as const;

/** All units offered in the picker, grouped by form (drives <optgroup>s). */
export const UNIT_GROUPS: { label: string; form: ProductForm; units: readonly string[] }[] = [
  { label: 'Liquid · volume', form: 'liquid', units: VOLUME_UNITS },
  { label: 'Dry · weight', form: 'dry', units: WEIGHT_UNITS },
  { label: 'Count', form: 'count', units: COUNT_UNITS },
];

export function formForUnit(unit: string | null | undefined): ProductForm {
  if (unit && (WEIGHT_UNITS as readonly string[]).includes(unit)) return 'dry';
  if (unit && (COUNT_UNITS as readonly string[]).includes(unit)) return 'count';
  return 'liquid';
}

const CONTAINER: Record<ProductForm, { one: string; many: string }> = {
  liquid: { one: 'bottle', many: 'bottles' },
  dry: { one: 'bag', many: 'bags' },
  count: { one: 'pack', many: 'packs' },
};

/** The container noun for a form, singular by default or plural when count ≠ 1. */
export function containerNoun(form: ProductForm, count = 1): string {
  return Math.abs(count) === 1 ? CONTAINER[form].one : CONTAINER[form].many;
}
