/**
 * Rainfall aggregation + a simple home-garden drought heuristic, built from the
 * hourly precipitation history that `fetchWeather()` already returns.
 */

export type DroughtStatus = 'wet' | 'adequate' | 'dry' | 'drought';

export interface DailyRain {
  date: string; // YYYY-MM-DD (location-local calendar day)
  inches: number;
}

function round2(n: number) {
  return Math.round(n * 100) / 100;
}

/**
 * Roll hourly precip into per-day totals for the last `days` calendar days,
 * ending on the most recent day present in the data (so it's stable regardless
 * of the server's timezone). Missing days are filled with 0.
 */
export function dailyRainfall(
  history: Array<{ time: string; precipitation: number }>,
  days = 30
): DailyRain[] {
  const byDate = new Map<string, number>();
  let maxKey = '';
  for (const h of history) {
    const d = h.time.slice(0, 10); // YYYY-MM-DD from the API's local-tz timestamp
    byDate.set(d, (byDate.get(d) ?? 0) + (Number(h.precipitation) || 0));
    if (d > maxKey) maxKey = d;
  }
  if (!maxKey) return [];

  // Walk back `days` calendar days from the last data day, in UTC, so the
  // date-only keys don't drift with server timezone.
  const [y, m, d] = maxKey.split('-').map(Number);
  const end = new Date(Date.UTC(y, m - 1, d));
  const out: DailyRain[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const dt = new Date(end);
    dt.setUTCDate(end.getUTCDate() - i);
    const key = `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}-${String(dt.getUTCDate()).padStart(2, '0')}`;
    out.push({ date: key, inches: round2(byDate.get(key) ?? 0) });
  }
  return out;
}

export interface RainSummary {
  week: number; // last 7 days, inches
  month: number; // last 30 days, inches
  daysSinceRain: number | null; // days since a day with >= 0.1"
  wettest: DailyRain | null;
  status: DroughtStatus;
  monthExpected: number; // the window's reference: ~1"/week growing, about half resting
}

const RAIN_DAY = 0.1; // a day with at least this much counts as "it rained"

/**
 * The 30-day total against what the garden needs in this season. A growing
 * garden wants ~1"/week; a resting one (most crops dormant or past harvest)
 * draws about half of that, and "drought" is a growing-season word: a resting
 * garden that is short of its reference is at most "dry".
 */
export function rainfallSummary(daily: DailyRain[], opts: { dormant?: boolean } = {}): RainSummary {
  const n = daily.length;
  const lastN = (k: number) => daily.slice(Math.max(0, n - k)).reduce((s, d) => s + d.inches, 0);
  const week = round2(lastN(7));
  const month = round2(lastN(30));

  let daysSinceRain: number | null = null;
  for (let i = n - 1; i >= 0; i--) {
    if (daily[i].inches >= RAIN_DAY) {
      daysSinceRain = n - 1 - i;
      break;
    }
  }

  const wettest = daily.reduce<DailyRain | null>(
    (best, d) => (!best || d.inches > best.inches ? d : best),
    null
  );

  // Gardens want roughly 1 inch of water per week while growing; compare the
  // window total to the season's share of that.
  const weekly = opts.dormant ? RESTING_SHARE : 1.0;
  const monthExpected = round2((Math.min(30, n) / 7) * weekly);
  const ratio = monthExpected > 0 ? month / monthExpected : 0;
  const status: DroughtStatus =
    ratio < 0.33 && !opts.dormant
      ? 'drought'
      : ratio < 0.66
        ? 'dry'
        : ratio < 1.5
          ? 'adequate'
          : 'wet';

  return { week, month, daysSinceRain, wettest, status, monthExpected };
}

export const DROUGHT_META: Record<DroughtStatus, { label: string; badge: string; bar: string }> = {
  drought: {
    label: 'Drought',
    badge: 'bg-rose-100 text-rose-700 ring-rose-300/60',
    bar: 'bg-rose-400',
  },
  dry: {
    label: 'Dry',
    badge: 'bg-amber-100 text-amber-700 ring-amber-300/60',
    bar: 'bg-amber-400',
  },
  adequate: {
    label: 'Adequate',
    badge: 'bg-emerald-100 text-emerald-700 ring-emerald-300/60',
    bar: 'bg-emerald-400',
  },
  wet: {
    label: 'Wet',
    badge: 'bg-sky-100 text-sky-700 ring-sky-300/60',
    bar: 'bg-sky-400',
  },
};

// ── Watering recommendation ──

/** With the garden resting, highs below this mean resting plants: no watering call. */
const RESTING_WARM_F = 75;
/** Resting plants draw roughly this share of a growing garden's weekly water. */
const RESTING_SHARE = 0.5;

/** Forecast rain this size or more in the next few days: wait for it rather than water. */
export const RAIN_AHEAD_WAIT = 0.25;

export type WateringStatus = 'soak' | 'water-soon' | 'ok' | 'wet' | 'rest' | 'wait';

/** Rain the forecast expects soon (`rainAhead` in lib/weather). */
export interface RainAhead {
  inches: number;
  /** The day the expected rain reaches RAIN_AHEAD_WAIT, in Today's words. */
  by: string | null;
}

export interface WateringAdvice {
  status: WateringStatus;
  rain7: number; // last 7 days of rain, inches
  targetWeekly: number; // evapotranspiration-adjusted weekly need, inches
  deficit: number; // shortfall vs target, inches (>= 0)
  headline: string; // the one instruction
  detail: string; // why, in one line
  /** Rain the forecast expects soon, when it was asked. */
  ahead: RainAhead | null;
}

/**
 * Should you water this week? Plants want a deep soak roughly weekly — twice a
 * week in real heat — so we compare the *last 7 days* of rain against a weekly
 * target that scales with evapotranspiration demand (hotter and drier air pull
 * more moisture) and with the season: a resting garden (most crops dormant or
 * past harvest) needs about half, and outside real heat it is never told to
 * water, only reminded to check the soil after a dry spell. When the forecast
 * (`ahead`) has RAIN_AHEAD_WAIT or more coming, a call to water becomes "wait
 * for the rain", unless a soak in real heat is short of what the rain will bring.
 */
export function wateringAdvice(
  daily: DailyRain[],
  opts: {
    avgHighF?: number | null;
    humidityPct?: number | null;
    dormant?: boolean;
    ahead?: RainAhead | null;
  } = {}
): WateringAdvice {
  const base = pastRainAdvice(daily, opts);
  const ahead = opts.ahead ?? null;
  const advice = { ...base, ahead };
  // The forecast has the last word on a call to water: rain on the way does the
  // watering. In real heat a soak waits only when the rain coming covers the
  // shortfall, since plants cannot go days short in that heat.
  const asksToWater =
    base.status === 'water-soon' ||
    base.status === 'soak' ||
    (base.status === 'rest' && base.deficit > base.targetWeekly * 0.6);
  if (!ahead || !asksToWater || ahead.inches < RAIN_AHEAD_WAIT) return advice;
  const due = `${ahead.inches.toFixed(2)}″ of rain is forecast${ahead.by ? ` by ${ahead.by}` : ''}`;
  const hot = opts.avgHighF != null && opts.avgHighF >= 88;
  if (base.status === 'soak' && hot && ahead.inches < base.deficit)
    return { ...advice, detail: `${base.detail} ${due}, short of what is missing.` };
  return {
    ...advice,
    status: 'wait',
    headline: 'Wait for the rain',
    detail: `${due}; ${base.rain7.toFixed(2)}″ fell in the last 7 days. If the soil is still dry a few inches down after it, water then.`,
  };
}

/** The call from the last 7 days of rain alone, before the forecast is read. */
function pastRainAdvice(
  daily: DailyRain[],
  opts: { avgHighF?: number | null; humidityPct?: number | null; dormant?: boolean }
): Omit<WateringAdvice, 'ahead'> {
  const n = daily.length;
  const rain7 = round2(daily.slice(Math.max(0, n - 7)).reduce((s, d) => s + d.inches, 0));
  const high = opts.avgHighF ?? null;
  const hum = opts.humidityPct ?? null;

  // Base ~1"/week, scaled by heat (evapotranspiration demand).
  let target =
    high == null
      ? 1.0
      : high >= 95
        ? 1.8
        : high >= 88
          ? 1.5
          : high >= 80
            ? 1.2
            : high >= 70
              ? 1.0
              : high >= 60
                ? 0.8
                : 0.6;
  // Dry air pulls more moisture from soil and leaves; humid air, less.
  if (hum != null) target += hum < 40 ? 0.2 : hum < 55 ? 0.1 : hum > 80 ? -0.15 : 0;
  target = Math.max(0.5, Math.min(2.2, Math.round(target * 10) / 10));
  if (opts.dormant) target = Math.round(target * RESTING_SHARE * 10) / 10;

  const deficit = round2(Math.max(0, target - rain7));
  const heatNote = high != null ? `, highs near ${Math.round(high)}°` : '';
  const rainNote = `${rain7.toFixed(2)}″ of rain in the last 7 days`;

  if (rain7 >= target * 1.4) {
    return {
      status: 'wet',
      rain7,
      targetWeekly: target,
      deficit,
      headline: 'Skip watering',
      detail: `${rainNote}, well above the ~${target.toFixed(1)}″ this week calls for${heatNote}.`,
    };
  }
  if (opts.dormant && (high == null || high < RESTING_WARM_F)) {
    // Resting plants in cool weather barely draw on the soil: a soft note at most.
    return {
      status: 'rest',
      rain7,
      targetWeekly: target,
      deficit,
      headline:
        deficit > target * 0.6
          ? 'Check the soil before winter'
          : 'No watering needed while the garden rests',
      detail:
        deficit > target * 0.6
          ? `Most of the garden is dormant${heatNote}; ${rainNote}. If the soil is dry a few inches down, one deep watering will carry the roots into winter.`
          : `Most of the garden is dormant${heatNote}; ${rainNote} covers its ~${target.toFixed(1)}″ a week.`,
    };
  }

  const hot = high != null && high >= 88;
  if (deficit <= 0.2)
    return {
      status: 'ok',
      rain7,
      targetWeekly: target,
      deficit,
      headline: 'No watering needed',
      detail: `${rainNote} covers about ${target.toFixed(1)}″ of need${heatNote}.`,
    };
  // A resting garden in heat is never told to water now: the soft call at most.
  if (deficit <= target * 0.6 || opts.dormant)
    return {
      status: 'water-soon',
      rain7,
      targetWeekly: target,
      deficit,
      headline: 'Water in a day or two',
      detail: `${rainNote} vs ~${target.toFixed(1)}″ needed${heatNote}: one deep soak covers it.`,
    };
  return {
    status: 'soak',
    rain7,
    targetWeekly: target,
    deficit,
    headline: hot ? 'Water now, and again in a few days' : 'Water now',
    detail: `Only ${rainNote} vs ~${target.toFixed(1)}″ needed${heatNote}.`,
  };
}

export const WATERING_META: Record<WateringStatus, { badge: string; bar: string }> = {
  soak: { badge: 'bg-rose-100 text-rose-700 ring-rose-300/60', bar: 'bg-rose-400' },
  'water-soon': { badge: 'bg-amber-100 text-amber-700 ring-amber-300/60', bar: 'bg-amber-400' },
  ok: { badge: 'bg-emerald-100 text-emerald-700 ring-emerald-300/60', bar: 'bg-emerald-400' },
  wet: { badge: 'bg-sky-100 text-sky-700 ring-sky-300/60', bar: 'bg-sky-400' },
  wait: { badge: 'bg-sky-100 text-sky-700 ring-sky-300/60', bar: 'bg-sky-400' },
  rest: { badge: 'bg-muted/60 text-foreground/80 ring-border/60', bar: 'bg-muted' },
};
