/**
 * Dose calculator for backpack sprayer.
 *
 * Handles per-gallon rates (homeowner products) and per-acre rates
 * (commercial products) by converting through a dilute spray volume
 * assumption of 100 gallons per acre — the standard for tree fruit
 * foliar applications sprayed "to drip."
 *
 * Products that are NOT foliar tank-mix compatible (granulars, soil
 * drenches, pre-emergent herbicides) should have rate_unit set to
 * "granular", "drench", or similar so the calculator can flag them.
 */

import { SPRAYER } from '@/config/thresholds';

const SPRAYER_GALLONS = SPRAYER.gallons;

/** Dilute spray volume: gallons of water applied per acre for tree fruit */
const DILUTE_GAL_PER_ACRE = SPRAYER.diluteGalPerAcre;

export interface DoseResult {
  flOz: number;
  mL: number;
  tbsp: number;
  tsp: number;
  ratePerGallon: number;
  rateUnit: string;
  totalGallons: number;
  /** The most practical display unit for this amount */
  bestDisplay: string;
  bestAmount: number;
  bestUnit: string;
  /** True if this rate cannot be converted for foliar tank mix */
  notFoliar?: boolean;
  /** Warning message if conversion required assumptions */
  warning?: string;
}

/** Units that indicate a non-foliar application */
const NON_FOLIAR_UNITS = ['granular', 'drench', 'granular/drench', 'liquid'];

/**
 * Convert a rate to fl oz per gallon regardless of input unit.
 * Per-acre rates are divided by DILUTE_GAL_PER_ACRE (100 gal/acre).
 */
function normalizeToFlOzPerGallon(
  rate: number,
  unit: string
): { flOzPerGal: number; warning?: string; notFoliar?: boolean } {
  const u = unit.toLowerCase().replace(/\s+/g, '');

  // Non-foliar — can't convert
  if (NON_FOLIAR_UNITS.some((nf) => u.includes(nf))) {
    return { flOzPerGal: 0, notFoliar: true };
  }

  // ── Per-gallon rates (ready to use) ──
  if (u === 'floz/gal' || u === 'floz/gallon') return { flOzPerGal: rate };
  if (u === 'oz/gal') return { flOzPerGal: rate };
  if (u === 'tbsp/gal') return { flOzPerGal: rate * 0.5 };
  if (u === 'tsp/gal') return { flOzPerGal: rate * (1 / 6) };
  if (u === 'ml/gal') return { flOzPerGal: rate / 29.5735 };
  // Dry weight per gallon (WDG/WP granules like Negate). 1 g ≈ 1 mL at density ~1;
  // this keeps the cost ratio correct against a gram-priced bottle. Weight oz handled above.
  if (u === 'g/gal') return { flOzPerGal: rate / 29.5735 };

  // ── Per-2.5 gallon (some Bonide products) ──
  if (u.includes('/2.5gal')) return { flOzPerGal: rate / 2.5 };

  // ── Per-100 gallon (concentrate rates) ──
  if (u === 'oz/100gal' || u === 'floz/100gal') return { flOzPerGal: rate / 100 };
  if (u === 'qt/100gal') return { flOzPerGal: (rate * 32) / 100 };
  if (u === 'pt/100gal') return { flOzPerGal: (rate * 16) / 100 };
  if (u === 'lb/100gal') return { flOzPerGal: (rate * 16) / 100 }; // weight oz ≈ fl oz for WP/WDG

  // ── Per-acre rates → convert through dilute spray volume ──
  if (u === 'floz/acre' || u === 'oz/acre') {
    return {
      flOzPerGal: rate / DILUTE_GAL_PER_ACRE,
      warning: `Converted from ${rate} ${unit} using ${DILUTE_GAL_PER_ACRE} gal/acre dilute spray`,
    };
  }
  if (u === 'pt/acre') {
    return {
      flOzPerGal: (rate * 16) / DILUTE_GAL_PER_ACRE,
      warning: `Converted from ${rate} pt/acre using ${DILUTE_GAL_PER_ACRE} gal/acre dilute spray`,
    };
  }
  if (u === 'qt/acre') {
    return {
      flOzPerGal: (rate * 32) / DILUTE_GAL_PER_ACRE,
      warning: `Converted from ${rate} qt/acre using ${DILUTE_GAL_PER_ACRE} gal/acre dilute spray`,
    };
  }
  if (u === 'lb/acre') {
    // Weight: 1 lb = 16 oz. For WP/WDG powders, use weight oz.
    return {
      flOzPerGal: (rate * 16) / DILUTE_GAL_PER_ACRE,
      warning: `Converted from ${rate} lb/acre using ${DILUTE_GAL_PER_ACRE} gal/acre dilute spray`,
    };
  }

  // ── Per-1000 sq ft ──
  if (u.includes('/1000sqft') || u.includes('/1000sq ft')) {
    // 1 acre ≈ 43.56 × 1000 sq ft
    return {
      flOzPerGal: (rate * 43.56) / DILUTE_GAL_PER_ACRE,
      warning: `Converted from ${rate} ${unit} (pre-emergent rate)`,
    };
  }

  // ── Metric ──
  if (u === 'kg/ha') {
    // 1 kg/ha ≈ 0.89 lb/acre → 14.27 oz/acre → /100 gal
    return {
      flOzPerGal: (rate * 0.89 * 16) / DILUTE_GAL_PER_ACRE,
      warning: `Converted from ${rate} kg/ha`,
    };
  }
  if (u === 'g/ha') {
    return {
      flOzPerGal: (rate * 0.00089 * 16) / DILUTE_GAL_PER_ACRE,
      warning: `Converted from ${rate} g/ha`,
    };
  }

  // ── PPM (parts per million, typically for streptomycin) ──
  if (u === 'ppm') {
    // Can't convert to fl oz without knowing product concentration
    return { flOzPerGal: 0, notFoliar: true };
  }

  // Default: treat as fl oz/gal
  return { flOzPerGal: rate };
}

/**
 * Pick the most practical display unit for a given amount in fl oz.
 */
function bestDisplayUnit(flOz: number): { amount: number; unit: string; display: string } {
  const mL = flOz * 29.5735;
  const tbsp = flOz / 0.5;
  const tsp = flOz / (1 / 6);

  if (flOz < 0.25) {
    return { amount: round(mL, 1), unit: 'mL', display: `${round(mL, 1)} mL` };
  }
  if (flOz < 1) {
    return { amount: round(tsp, 1), unit: 'tsp', display: `${round(tsp, 1)} tsp` };
  }
  if (flOz < 4 && tbsp === Math.round(tbsp)) {
    return { amount: round(tbsp, 1), unit: 'tbsp', display: `${round(tbsp, 1)} tbsp` };
  }
  return { amount: round(flOz, 1), unit: 'fl oz', display: `${round(flOz, 1)} fl oz` };
}

/**
 * Calculate dose for a given rate and sprayer volume.
 */
export function calculateDose(
  ratePerUnit: number,
  rateUnit: string = 'fl oz/gal',
  gallons: number = SPRAYER_GALLONS
): DoseResult {
  const { flOzPerGal, warning, notFoliar } = normalizeToFlOzPerGallon(ratePerUnit, rateUnit);

  if (notFoliar) {
    return {
      flOz: 0,
      mL: 0,
      tbsp: 0,
      tsp: 0,
      ratePerGallon: 0,
      rateUnit,
      totalGallons: gallons,
      bestDisplay: 'N/A',
      bestAmount: 0,
      bestUnit: '',
      notFoliar: true,
    };
  }

  const totalFlOz = flOzPerGal * gallons;
  const mL = totalFlOz * 29.5735;
  const tbsp = totalFlOz / 0.5;
  const tsp = totalFlOz * 6;
  const best = bestDisplayUnit(totalFlOz);

  return {
    flOz: round(totalFlOz, 2),
    mL: round(mL, 1),
    tbsp: round(tbsp, 1),
    tsp: round(tsp, 1),
    ratePerGallon: round(flOzPerGal, 4),
    rateUnit,
    totalGallons: gallons,
    bestDisplay: best.display,
    bestAmount: best.amount,
    bestUnit: best.unit,
    warning,
  };
}

function round(n: number, decimals: number): number {
  const factor = Math.pow(10, decimals);
  return Math.round(n * factor) / factor;
}
