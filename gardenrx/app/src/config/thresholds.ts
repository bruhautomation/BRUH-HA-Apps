/**
 * Centralized thresholds and magic numbers for spray decisions,
 * weather ratings, and coverage calculations.
 */

// ── Location ──

// Inside Home Assistant the add-on's start script reads the house's own
// location and time zone from Home Assistant and passes them in, so the
// forecast is for this garden. These are read on the server only; the
// defaults are the orchard the app was first written for.
const num = (v: string | undefined, fallback: number) => {
  const n = Number(v);
  return v !== undefined && v !== '' && Number.isFinite(n) ? n : fallback;
};

export const LOCATION = {
  lat: num(process.env.GARDENRX_LATITUDE, 35.6513),
  lon: num(process.env.GARDENRX_LONGITUDE, -78.8336),
  timezone: process.env.GARDENRX_TIMEZONE || 'America/New_York',
};

// ── Weather spray rating thresholds ──

export const SPRAY_RATING = {
  /** Wind speed above this = POOR (mph) */
  windPoor: 10,
  /** Wind speed above this = FAIR (mph) */
  windFair: 8,
  /** Wind speed above this = GOOD (mph) */
  windGood: 5,

  /** Hours until rain at or below this = POOR */
  rainHoursPoor: 2,
  /** Hours until rain at or below this = FAIR */
  rainHoursFair: 6,
  /** Hours until rain at or below this = GOOD */
  rainHoursGood: 12,

  /** Temp below this = POOR (°F) */
  tempMinPoor: 40,
  /** Temp below this = FAIR (°F) */
  tempMinFair: 45,
  /** Temp below this = GOOD (°F) */
  tempMinGood: 50,

  /** Temp above this = POOR (°F) */
  tempMaxPoor: 95,
  /** Temp above this = FAIR (°F) */
  tempMaxFair: 90,
  /** Temp above this = GOOD (°F) */
  tempMaxGood: 85,
} as const;

// ── Coverage defaults (used when product doesn't specify) ──

export const COVERAGE_DEFAULTS = {
  /** Default cover spray interval in days */
  intervalDays: 14,
  /** Default rain fastness in hours */
  rainFastnessHours: 2,
  /** Default rain tolerance in inches */
  rainToleranceInches: 2,
} as const;

// ── Interlock thresholds ──

export const INTERLOCK = {
  /** Sulfur phytotoxicity threshold (°F) */
  sulfurMaxTemp: 85,
  /** Wind speed warning threshold (mph) */
  windWarning: 5,
  /** Wind speed block threshold (mph) */
  windBlock: 10,
  /** Low temp warning (°F) */
  tempLowWarning: 45,
  /** High temp warning (°F) */
  tempHighWarning: 90,
} as const;

// ── Sprayer defaults ──

export const SPRAYER = {
  /** Default backpack sprayer volume in gallons */
  gallons: 4,
  /** Dilute spray volume: gallons per acre for tree fruit */
  diluteGalPerAcre: 100,
} as const;
