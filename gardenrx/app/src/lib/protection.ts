import type {
  Product,
  SprayEvent,
  SprayEventProduct,
  SprayEventCrop,
  ActiveIngredient,
  IngredientType,
} from './database.types';
import { COVERAGE_DEFAULTS } from '@/config/thresholds';

// Coverage status for a crop + coverage type
export type CoverageStatus = 'green' | 'yellow' | 'red';

export interface CoverageInfo {
  status: CoverageStatus;
  product: Product;
  coverageType: IngredientType;
  dateApplied: Date;
  daysRemaining: number;
  rainSinceSpray: number; // inches
  rainFastDeadline: Date;
  wasRainedOnBeforeRainFast: boolean;
  label: string; // Human-readable summary
}

interface SprayRecord {
  event: SprayEvent;
  product: Product;
  ingredients: ActiveIngredient[];
  rateApplied: number | null;
}

/**
 * Get all spray records for a specific crop, sorted most recent first.
 */
export function getSprayRecordsForCrop(
  cropId: number,
  sprayEvents: SprayEvent[],
  eventProducts: SprayEventProduct[],
  eventCrops: SprayEventCrop[],
  products: Product[],
  productIngredientMap: Map<number, ActiveIngredient[]>
): SprayRecord[] {
  // Find events that include this crop
  const cropEventIds = new Set(
    eventCrops.filter((ec) => ec.crop_id === cropId).map((ec) => ec.spray_event_id)
  );

  // Index products by id so the inner loop is a O(1) lookup rather than a
  // linear scan of the ~250-row catalog per applied product.
  const productById = new Map(products.map((p) => [p.id, p] as const));

  const records: SprayRecord[] = [];

  for (const event of sprayEvents) {
    if (!cropEventIds.has(event.id)) continue;

    const prods = eventProducts.filter((ep) => ep.spray_event_id === event.id);
    for (const ep of prods) {
      const product = productById.get(ep.product_id);
      if (!product) continue;

      records.push({
        event,
        product,
        ingredients: productIngredientMap.get(product.id) || [],
        rateApplied: ep.rate_applied,
      });
    }
  }

  // Sort most recent first
  records.sort((a, b) => new Date(b.event.date).getTime() - new Date(a.event.date).getTime());
  return records;
}

/**
 * Get the primary coverage type for a product based on its active ingredients.
 * A product is classified by the type of its first ingredient.
 */
export function getProductCoverageType(ingredients: ActiveIngredient[]): IngredientType | null {
  if (ingredients.length === 0) return null;
  // Prefer fungicide > insecticide > bactericide > herbicide
  const priority: IngredientType[] = ['fungicide', 'insecticide', 'bactericide', 'herbicide'];
  for (const type of priority) {
    if (ingredients.some((i) => i.type === type)) return type;
  }
  return ingredients[0].type;
}

/**
 * Compute coverage status for a crop + coverage type.
 * Uses the most recent spray of that type.
 */
export function computeCoverage(
  sprayRecords: SprayRecord[],
  coverageType: IngredientType,
  now: Date,
  precipHistory: Array<{ time: string; precipitation: number }>
): CoverageInfo | null {
  // Find the most recent spray record matching this coverage type
  const record = sprayRecords.find((r) => {
    const type = getProductCoverageType(r.ingredients);
    return type === coverageType;
  });

  if (!record) return null;

  const dateApplied = new Date(record.event.date);
  const product = record.product;
  const intervalDays = product.cover_spray_interval_days || COVERAGE_DEFAULTS.intervalDays;
  const rainFastnessHours = product.rain_fastness_hours || COVERAGE_DEFAULTS.rainFastnessHours;
  const rainTolerance = product.rain_tolerance_inches || COVERAGE_DEFAULTS.rainToleranceInches;

  const expiryDate = new Date(dateApplied);
  expiryDate.setDate(expiryDate.getDate() + intervalDays);

  const rainFastDeadline = new Date(dateApplied);
  rainFastDeadline.setHours(rainFastDeadline.getHours() + rainFastnessHours);

  const cumulativeRainInches = cumulativeRainSince(dateApplied, precipHistory);
  const rainDuringRainFast = cumulativeRainSince(dateApplied, precipHistory, rainFastDeadline);

  const msRemaining = expiryDate.getTime() - now.getTime();
  const daysRemaining = Math.max(0, Math.ceil(msRemaining / (1000 * 60 * 60 * 24)));

  // Determine status
  let status: CoverageStatus;

  if (daysRemaining <= 0) {
    status = 'red';
  } else if (cumulativeRainInches >= rainTolerance * 2) {
    // Rain washed — coverage gone regardless of time
    status = 'red';
  } else if (daysRemaining <= 4 || cumulativeRainInches >= rainTolerance) {
    status = 'yellow';
  } else {
    status = 'green';
  }

  // Rain fell within the rain-fast window, so the spray was vulnerable before bonding.
  const wasRainedOnBeforeRainFast = rainDuringRainFast > 0;

  // Build label
  let label: string;
  if (status === 'red' && daysRemaining <= 0) {
    label = `${product.brand} applied ${formatDate(dateApplied)} — coverage expired`;
  } else if (status === 'red') {
    label = `${product.brand} applied ${formatDate(dateApplied)} — rain-washed (${cumulativeRainInches.toFixed(1)}" since spray)`;
  } else {
    label = `${product.brand} applied ${formatDate(dateApplied)} — ${daysRemaining} day${daysRemaining !== 1 ? 's' : ''} remaining`;
    if (cumulativeRainInches > 0) {
      label += ` (${cumulativeRainInches.toFixed(1)}" rain since spray)`;
    }
  }

  return {
    status,
    product,
    coverageType,
    dateApplied,
    daysRemaining,
    rainSinceSpray: cumulativeRainInches,
    rainFastDeadline,
    wasRainedOnBeforeRainFast,
    label,
  };
}

function formatDate(d: Date): string {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * Compute cumulative rainfall since a given date using hourly precipitation history.
 * precipHistory is an array of { time: string (ISO), precipitation: number (inches) }.
 */
export function cumulativeRainSince(
  since: Date,
  precipHistory: Array<{ time: string; precipitation: number }>,
  until?: Date
): number {
  return precipHistory
    .filter((h) => {
      const t = new Date(h.time);
      return t >= since && (!until || t < until);
    })
    .reduce((sum, h) => sum + h.precipitation, 0);
}
