import { LOCATION, SPRAY_RATING } from '@/config/thresholds';

export type SprayRating = 'EXCELLENT' | 'GOOD' | 'FAIR' | 'POOR';

export interface CurrentConditions {
  temp: number; // Fahrenheit
  windSpeed: number; // mph
  humidity: number; // percent
  precipitation: number; // inches in last hour
  weatherCode: number;
  description: string;
  /** Daylight at the garden right now (absent in data fetched before it was asked for). */
  isDay?: boolean;
}

export interface HourlyForecast {
  time: string; // ISO string
  temp: number;
  windSpeed: number;
  humidity: number;
  precipitation: number;
  weatherCode: number;
  /** Daylight during this hour, from the forecast; absent means unknown. */
  isDay?: boolean;
}

export interface DailyForecast {
  date: string; // YYYY-MM-DD
  tempHigh: number;
  tempLow: number;
  precipSum: number;
  precipChance: number; // max chance of precip that day, %
  windSpeedMax: number;
  weatherCode: number;
}

export interface WeatherData {
  current: CurrentConditions;
  hourly: HourlyForecast[];
  daily: DailyForecast[];
  precipHistory: Array<{ time: string; precipitation: number }>;
}

/**
 * Fetch weather data from Open-Meteo API.
 * Returns current conditions, 72-hour hourly forecast, 7-day daily forecast,
 * and 30-day hourly precipitation history.
 */
export async function fetchWeather(): Promise<WeatherData> {
  // Current + forecast
  const forecastUrl = `https://api.open-meteo.com/v1/forecast?latitude=${LOCATION.lat}&longitude=${LOCATION.lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,weather_code,is_day&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,weather_code&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&forecast_days=7&timezone=${encodeURIComponent(LOCATION.timezone)}`;

  // Historical precipitation (past 30 days)
  const now = new Date();
  const thirtyDaysAgo = new Date(now);
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
  const histStart = thirtyDaysAgo.toISOString().split('T')[0];
  const histEnd = new Date(now.getTime() - 86400000).toISOString().split('T')[0]; // yesterday

  const histUrl = `https://archive-api.open-meteo.com/v1/archive?latitude=${LOCATION.lat}&longitude=${LOCATION.lon}&start_date=${histStart}&end_date=${histEnd}&hourly=precipitation&precipitation_unit=inch&timezone=${encodeURIComponent(LOCATION.timezone)}`;

  const [forecastRes, histRes] = await Promise.all([fetch(forecastUrl), fetch(histUrl)]);

  if (!forecastRes.ok) throw new Error(`Weather forecast fetch failed: ${forecastRes.status}`);

  const forecast = await forecastRes.json();
  const hist = histRes.ok ? await histRes.json() : null;

  // Parse current conditions
  const current: CurrentConditions = {
    temp: forecast.current.temperature_2m,
    windSpeed: forecast.current.wind_speed_10m,
    humidity: forecast.current.relative_humidity_2m,
    precipitation: forecast.current.precipitation,
    weatherCode: forecast.current.weather_code,
    description: weatherCodeToDescription(forecast.current.weather_code),
    isDay: dayFlag(forecast.current.is_day),
  };

  // Parse hourly forecast (next 72 hours)
  const hourly: HourlyForecast[] = forecast.hourly.time
    .slice(0, 72)
    .map((time: string, i: number) => ({
      time,
      temp: forecast.hourly.temperature_2m[i],
      windSpeed: forecast.hourly.wind_speed_10m[i],
      humidity: forecast.hourly.relative_humidity_2m[i],
      precipitation: forecast.hourly.precipitation[i],
      weatherCode: forecast.hourly.weather_code[i],
      isDay: dayFlag(forecast.hourly.is_day?.[i]),
    }));

  // Parse daily forecast
  const daily: DailyForecast[] = forecast.daily.time.map((date: string, i: number) => ({
    date,
    tempHigh: forecast.daily.temperature_2m_max[i],
    tempLow: forecast.daily.temperature_2m_min[i],
    precipSum: forecast.daily.precipitation_sum[i],
    precipChance: forecast.daily.precipitation_probability_max?.[i] ?? 0,
    windSpeedMax: forecast.daily.wind_speed_10m_max[i],
    weatherCode: forecast.daily.weather_code[i],
  }));

  // Parse precipitation history
  const precipHistory: Array<{ time: string; precipitation: number }> = [];
  if (hist?.hourly?.time) {
    for (let i = 0; i < hist.hourly.time.length; i++) {
      precipHistory.push({
        time: hist.hourly.time[i],
        precipitation: hist.hourly.precipitation[i] || 0,
      });
    }
  }
  // Also include today's hourly precip from forecast
  for (let i = 0; i < Math.min(24, forecast.hourly.time.length); i++) {
    if (new Date(forecast.hourly.time[i]) <= now) {
      precipHistory.push({
        time: forecast.hourly.time[i],
        precipitation: forecast.hourly.precipitation[i] || 0,
      });
    }
  }

  return { current, hourly, daily, precipHistory };
}

/** Open-Meteo's is_day (1 or 0) as a boolean; undefined when it is not there. */
function dayFlag(v: unknown): boolean | undefined {
  return v === 1 || v === 0 ? v === 1 : undefined;
}

/**
 * Rate a specific hour for spray suitability.
 */
export function rateSprayWindow(
  temp: number,
  windSpeed: number,
  hoursUntilRain: number | null
): SprayRating {
  // POOR conditions — any of these disqualifies
  if (windSpeed > SPRAY_RATING.windPoor) return 'POOR';
  if (hoursUntilRain !== null && hoursUntilRain <= SPRAY_RATING.rainHoursPoor) return 'POOR';
  if (temp < SPRAY_RATING.tempMinPoor || temp > SPRAY_RATING.tempMaxPoor) return 'POOR';

  // FAIR conditions
  if (windSpeed > SPRAY_RATING.windFair) return 'FAIR';
  if (hoursUntilRain !== null && hoursUntilRain <= SPRAY_RATING.rainHoursFair) return 'FAIR';
  if (temp < SPRAY_RATING.tempMinFair || temp > SPRAY_RATING.tempMaxFair) return 'FAIR';

  // GOOD conditions
  if (windSpeed > SPRAY_RATING.windGood) return 'GOOD';
  if (hoursUntilRain !== null && hoursUntilRain <= SPRAY_RATING.rainHoursGood) return 'GOOD';
  if (temp < SPRAY_RATING.tempMinGood || temp > SPRAY_RATING.tempMaxGood) return 'GOOD';

  return 'EXCELLENT';
}

/**
 * Find the best spray windows in the next 72 hours.
 */
export function findBestSprayWindows(
  hourly: HourlyForecast[],
  maxResults: number = 3,
  now: Date = new Date()
): Array<{
  time: string;
  rating: SprayRating;
  temp: number;
  windSpeed: number;
  hoursUntilRain: number | null;
}> {
  const rated = hourly.map((h, i) => {
    // Find hours until next rain from this point
    let hoursUntilRain: number | null = null;
    for (let j = i + 1; j < hourly.length; j++) {
      if (hourly[j].precipitation > 0.01) {
        hoursUntilRain = j - i;
        break;
      }
    }
    return {
      time: h.time,
      rating: rateSprayWindow(h.temp, h.windSpeed, hoursUntilRain),
      temp: h.temp,
      windSpeed: h.windSpeed,
      hoursUntilRain,
      isDay: h.isDay,
    };
  });

  // Filter to daytime hours (6 AM - 8 PM) and sort by rating
  const ratingOrder: Record<SprayRating, number> = { EXCELLENT: 0, GOOD: 1, FAIR: 2, POOR: 3 };
  return rated
    .filter((w) => {
      const start = new Date(w.time);
      // The forecast starts at midnight: skip hours that are already over.
      if (start.getTime() + 3600000 <= now.getTime()) return false;
      if (w.isDay === false) return false;
      const hour = start.getHours();
      return hour >= 6 && hour <= 20;
    })
    .sort((a, b) => ratingOrder[a.rating] - ratingOrder[b.rating])
    .slice(0, maxResults);
}

/** "YYYY-MM-DDTHH:MM" for `now` on the garden's own clock (the forecast's clock). */
function localStamp(now: Date): string {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: LOCATION.timezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(now)
      .map((x) => [x.type, x.value])
  );
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

function clock12(h: number): { n: number; ap: 'am' | 'pm' } {
  return { n: h % 12 === 0 ? 12 : h % 12, ap: h < 12 || h === 24 ? 'am' : 'pm' };
}

/** "6–7 pm" or "11 am–1 pm" for a window from hour `a` to hour `b` (24h clock). */
function hourRange(a: number, b: number): string {
  const x = clock12(a);
  const y = clock12(b);
  return x.ap === y.ap ? `${x.n}–${y.n} ${y.ap}` : `${x.n} ${x.ap}–${y.n} ${y.ap}`;
}

export interface SprayHour {
  date: string; // YYYY-MM-DD on the garden's clock
  hour: number; // 0-23 on the garden's clock
  rating: SprayRating;
  temp: number;
  wind: number;
  /** Dark by the forecast's daylight flag. */
  dark: boolean;
  /** Good to spray: GOOD or EXCELLENT, between 6 am and 9 pm, and in daylight. */
  ok: boolean;
  /** The hour has already started on the garden's clock. */
  over: boolean;
}

/**
 * Each forecast hour marked good or not by the one rule every spray window uses:
 * a GOOD or EXCELLENT hour between 6 am and 9 pm that is not dark, with `over`
 * for an hour that has already started on the garden's clock. The 3-day grid,
 * the next opening and the forecast's day windows all read this, so they agree.
 */
export function sprayHours(hourly: HourlyForecast[], now: Date = new Date()): SprayHour[] {
  const nowStamp = localStamp(now);
  return hourly.map((h, i) => {
    let until: number | null = null;
    for (let j = i + 1; j < hourly.length; j++) {
      if (hourly[j].precipitation > 0.01) {
        until = j - i;
        break;
      }
    }
    const hour = Number(h.time.slice(11, 13));
    const r = rateSprayWindow(h.temp, h.windSpeed, until);
    const dark = h.isDay === false;
    return {
      date: h.time.slice(0, 10),
      hour,
      rating: r,
      temp: h.temp,
      wind: h.windSpeed,
      dark,
      ok: (r === 'GOOD' || r === 'EXCELLENT') && hour >= 6 && hour <= 20 && !dark,
      over: h.time.slice(0, 13) <= nowStamp.slice(0, 13),
    };
  });
}

/** "today", "tomorrow" or "Sat" for a forecast date, on the garden's clock. */
function dayWord(date: string, now: Date): string {
  const today = localStamp(now).slice(0, 10);
  const tomorrow = new Date(today + 'T12:00:00Z');
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  if (date === today) return 'today';
  if (date === tomorrow.toISOString().slice(0, 10)) return 'tomorrow';
  return new Date(date + 'T12:00:00Z').toLocaleDateString('en-US', {
    weekday: 'short',
    timeZone: 'UTC',
  });
}

/**
 * Rain the forecast still expects over the rest of today and the next `days`
 * days, in inches: today's hours that have not started yet from the hourly
 * forecast, then each later day's forecast total. `by` is the day the running
 * total first reaches `atLeast` ("tomorrow", "Sat"), or null if it never does.
 */
export function rainAhead(
  hourly: HourlyForecast[],
  daily: DailyForecast[],
  now: Date = new Date(),
  { days = 3, atLeast = 0.25 }: { days?: number; atLeast?: number } = {}
): { inches: number; by: string | null } {
  const nowStamp = localStamp(now);
  const today = nowStamp.slice(0, 10);
  let total = 0;
  let by: string | null = null;
  for (const h of hourly) {
    if (h.time.slice(0, 10) !== today || h.time.slice(0, 13) <= nowStamp.slice(0, 13)) continue;
    total += Number(h.precipitation) || 0;
  }
  if (total >= atLeast) by = 'today';
  const later = daily.filter((d) => d.date > today).slice(0, days);
  for (const d of later) {
    total += Number(d.precipSum) || 0;
    if (by == null && total >= atLeast) by = dayWord(d.date, now);
  }
  return { inches: Math.round(total * 100) / 100, by };
}

/** A window shorter than this many hours is offered as a short one. */
export const SHORT_SPRAY_WINDOW_HOURS = 3;

/**
 * The longest stretch of good spray weather still ahead on each forecast day,
 * by the same rule as `nextSprayOpening`: { date → "3–7 pm", hours }. A day
 * with no good hour left is absent.
 */
export function daySprayWindows(
  hourly: HourlyForecast[],
  now: Date = new Date()
): Map<string, { label: string; hours: number }> {
  const good = sprayHours(hourly, now);
  const out = new Map<string, { label: string; hours: number }>();
  let i = 0;
  while (i < good.length) {
    if (!good[i].ok || good[i].over) {
      i++;
      continue;
    }
    let j = i;
    while (
      j + 1 < good.length &&
      good[j + 1].ok &&
      !good[j + 1].over &&
      good[j + 1].date === good[i].date &&
      good[j + 1].hour === good[j].hour + 1
    )
      j++;
    const hours = j - i + 1;
    const prev = out.get(good[i].date);
    if (!prev || hours > prev.hours)
      out.set(good[i].date, { label: hourRange(good[i].hour, good[j].hour + 1), hours });
    i = j + 1;
  }
  return out;
}

/**
 * The next stretch of good spray weather still ahead, in the words Today and
 * Weather both show: "today 6–7 pm", "tomorrow 8–11 am", "Sat 9 am–1 pm".
 * Good means a GOOD or EXCELLENT daytime hour (6 am to 9 pm) starting after the
 * current one: it is asked only when right now is not good, so the hour under
 * way is never offered as the opening. Null when nothing in the forecast qualifies.
 */
export function nextSprayOpening(
  hourly: HourlyForecast[],
  now: Date = new Date()
): { label: string; start: string; end: string } | null {
  const good = sprayHours(hourly, now);
  const first = good.findIndex((g) => g.ok && !g.over);
  if (first < 0) return null;
  const g0 = good[first];
  let last = first;
  while (
    last + 1 < good.length &&
    good[last + 1].ok &&
    good[last + 1].date === g0.date &&
    good[last + 1].hour === good[last].hour + 1
  )
    last++;
  const endHour = good[last].hour + 1;
  return {
    label: `${dayWord(g0.date, now)} ${hourRange(g0.hour, endHour)}`,
    start: hourly[first].time,
    end: hourly[last].time,
  };
}

/**
 * Get current spray-ability rating.
 */
export function getCurrentSprayRating(
  current: CurrentConditions,
  hourly: HourlyForecast[]
): SprayRating {
  let hoursUntilRain: number | null = null;
  for (let i = 0; i < Math.min(24, hourly.length); i++) {
    if (hourly[i].precipitation > 0.01) {
      hoursUntilRain = i;
      break;
    }
  }
  return rateSprayWindow(current.temp, current.windSpeed, hoursUntilRain);
}

function weatherCodeToDescription(code: number): string {
  const descriptions: Record<number, string> = {
    0: 'Clear sky',
    1: 'Mainly clear',
    2: 'Partly cloudy',
    3: 'Overcast',
    45: 'Fog',
    48: 'Depositing rime fog',
    51: 'Light drizzle',
    53: 'Moderate drizzle',
    55: 'Dense drizzle',
    61: 'Slight rain',
    63: 'Moderate rain',
    65: 'Heavy rain',
    66: 'Light freezing rain',
    67: 'Heavy freezing rain',
    71: 'Slight snow',
    73: 'Moderate snow',
    75: 'Heavy snow',
    80: 'Slight rain showers',
    81: 'Moderate rain showers',
    82: 'Violent rain showers',
    85: 'Slight snow showers',
    86: 'Heavy snow showers',
    95: 'Thunderstorm',
    96: 'Thunderstorm with slight hail',
    99: 'Thunderstorm with heavy hail',
  };
  return descriptions[code] || 'Unknown';
}
