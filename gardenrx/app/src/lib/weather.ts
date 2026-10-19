import { LOCATION, SPRAY_RATING } from '@/config/thresholds';

export type SprayRating = 'EXCELLENT' | 'GOOD' | 'FAIR' | 'POOR';

export interface CurrentConditions {
  temp: number; // Fahrenheit
  windSpeed: number; // mph
  humidity: number; // percent
  precipitation: number; // inches in last hour
  weatherCode: number;
  description: string;
}

export interface HourlyForecast {
  time: string; // ISO string
  temp: number;
  windSpeed: number;
  humidity: number;
  precipitation: number;
  weatherCode: number;
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
  const forecastUrl = `https://api.open-meteo.com/v1/forecast?latitude=${LOCATION.lat}&longitude=${LOCATION.lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,weather_code&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,weather_code&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,weather_code&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&forecast_days=7&timezone=${encodeURIComponent(LOCATION.timezone)}`;

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
  maxResults: number = 3
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
    };
  });

  // Filter to daytime hours (6 AM - 8 PM) and sort by rating
  const ratingOrder: Record<SprayRating, number> = { EXCELLENT: 0, GOOD: 1, FAIR: 2, POOR: 3 };
  return rated
    .filter((w) => {
      const hour = new Date(w.time).getHours();
      return hour >= 6 && hour <= 20;
    })
    .sort((a, b) => ratingOrder[a.rating] - ratingOrder[b.rating])
    .slice(0, maxResults);
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
