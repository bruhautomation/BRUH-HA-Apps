import {
  fetchWeather,
  getCurrentSprayRating,
  rateSprayWindow,
  findBestSprayWindows,
  type SprayRating,
} from '@/lib/weather';
import { dailyRainfall, rainfallSummary } from '@/lib/rainfall';
import { RatingPill } from '@/components/status';
import { SprayWindow3Day } from '@/components/today/spray-window-3day';
import { RainTracker } from '@/components/rain-tracker';
import { Wind, Droplets, CloudRain, Thermometer, Sprout } from 'lucide-react';

export const dynamic = 'force-dynamic';

function wxEmoji(code: number): string {
  if (code === 0) return '☀️';
  if (code <= 2) return '🌤️';
  if (code === 3) return '☁️';
  if (code === 45 || code === 48) return '🌫️';
  if (code >= 51 && code <= 57) return '🌦️';
  if (code >= 61 && code <= 67) return '🌧️';
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return '❄️';
  if (code >= 80 && code <= 82) return '🌧️';
  if (code >= 95) return '⛈️';
  return '☁️';
}

function pill(r: SprayRating): { cls: string; txt: string } {
  if (r === 'EXCELLENT' || r === 'GOOD') return { cls: 'good', txt: 'Spray' };
  if (r === 'FAIR') return { cls: 'ok', txt: 'Caution' };
  return { cls: 'no', txt: 'Hold' };
}

export default async function WeatherPage() {
  const weather = await fetchWeather().catch(() => null);
  if (!weather) {
    return (
      <div className="page">
        <div className="section-title">
          <h2>Weather</h2>
        </div>
        <div className="card panel text-center text-ink-3">Weather is unavailable right now.</div>
      </div>
    );
  }

  const { current, hourly, daily, precipHistory } = weather;
  const rating = getCurrentSprayRating(current, hourly);
  const best = findBestSprayWindows(hourly, 1)[0];

  // hours until next rain
  let nextRainHrs: number | null = null;
  for (let i = 0; i < hourly.length; i++) {
    if (hourly[i].precipitation > 0.01) {
      nextRainHrs = i;
      break;
    }
  }

  // per-day spray rating for the forecast strip
  const rated = hourly.map((h, i) => {
    let hr: number | null = null;
    for (let j = i + 1; j < hourly.length; j++) {
      if (hourly[j].precipitation > 0.01) {
        hr = j - i;
        break;
      }
    }
    return {
      date: h.time.slice(0, 10),
      hour: new Date(h.time).getHours(),
      rating: rateSprayWindow(h.temp, h.windSpeed, hr),
    };
  });
  const order: Record<SprayRating, number> = { EXCELLENT: 0, GOOD: 1, FAIR: 2, POOR: 3 };
  const dayRating = new Map<string, SprayRating>();
  for (const r of rated) {
    if (r.hour < 6 || r.hour > 20) continue;
    const prev = dayRating.get(r.date);
    if (!prev || order[r.rating] < order[prev]) dayRating.set(r.date, r.rating);
  }

  const rainDaily = dailyRainfall(precipHistory, 30);
  const rainSummary = rainDaily.length ? rainfallSummary(rainDaily) : null;
  const avgHigh7 = daily.length
    ? daily.slice(0, 7).reduce((s, d) => s + d.tempHigh, 0) / Math.min(7, daily.length)
    : null;

  const goodNow = rating === 'EXCELLENT' || rating === 'GOOD';
  const bestTime = best
    ? new Date(best.time).toLocaleString('en-US', { weekday: 'short', hour: 'numeric' })
    : null;

  return (
    <div className="page animate-stagger">
      <div className="section-title">
        <h2>Weather</h2>
        <span className="meta">Home orchard · Zone 7b</span>
      </div>

      {/* spray-window recommendation */}
      <div className="window-rec">
        <div className="wr-ico">
          <Sprout className="size-5" />
        </div>
        <div>
          <div className="wr-title">
            {goodNow
              ? 'Good to spray now'
              : bestTime
                ? `Best window: ${bestTime}`
                : 'Hold off for now'}
          </div>
          <div className="wr-sub">
            {goodNow
              ? `Conditions are ${rating.toLowerCase()} — ${Math.round(current.temp)}°, wind ${Math.round(current.windSpeed)} mph.`
              : nextRainHrs != null && nextRainHrs <= 6
                ? `Rain expected in ~${nextRainHrs}h. Let coverage set first.`
                : `Current conditions are ${rating.toLowerCase()}. Check the 3-day window below.`}
          </div>
        </div>
        <div className="ml-auto">
          <RatingPill rating={rating} />
        </div>
      </div>

      <div className="wx-hero">
        {/* conditions now */}
        <div className="card panel">
          <div className="mb-3 flex items-center gap-3">
            <div className="text-4xl">{wxEmoji(current.weatherCode)}</div>
            <div>
              <div className="font-display text-3xl font-semibold leading-none">
                {Math.round(current.temp)}°
              </div>
              <div className="text-sm text-ink-3">{current.description}</div>
            </div>
            <div className="ml-auto">
              <RatingPill rating={rating} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--r-md)] bg-line">
            <Metric
              icon={<Wind className="size-3.5" />}
              k="Wind"
              v={`${Math.round(current.windSpeed)} mph`}
            />
            <Metric
              icon={<Droplets className="size-3.5" />}
              k="Humidity"
              v={`${Math.round(current.humidity)}%`}
            />
            <Metric
              icon={<CloudRain className="size-3.5" />}
              k="Next rain"
              v={nextRainHrs == null ? 'none 72h' : nextRainHrs === 0 ? 'now' : `~${nextRainHrs}h`}
            />
            <Metric
              icon={<Thermometer className="size-3.5" />}
              k="Today"
              v={`${Math.round(daily[0]?.tempHigh ?? current.temp)}° / ${Math.round(daily[0]?.tempLow ?? current.temp)}°`}
            />
          </div>
        </div>

        {/* 3-day spray window */}
        <div className="card panel">
          <div className="panel-h">
            <Sprout className="size-[18px] text-leaf" />
            <h3>3-day spray window</h3>
          </div>
          <SprayWindow3Day hourly={hourly} daily={daily} />
        </div>
      </div>

      {/* forecast strip */}
      <div className="section-title">
        <h2>7-day forecast</h2>
      </div>
      <div
        className="forecast-strip"
        style={{ ['--fc-cols' as string]: Math.min(7, daily.length) }}
      >
        {daily.slice(0, 7).map((d, i) => {
          const r = dayRating.get(d.date);
          const p = r ? pill(r) : null;
          return (
            <div key={d.date} className={`fc-day${i === 0 ? ' today' : ''}`}>
              <div className="fc-dow">
                {i === 0
                  ? 'Today'
                  : new Date(d.date + 'T12:00:00').toLocaleDateString('en-US', {
                      weekday: 'short',
                    })}
              </div>
              <div className="fc-date">
                {new Date(d.date + 'T12:00:00').toLocaleDateString('en-US', {
                  month: 'numeric',
                  day: 'numeric',
                })}
              </div>
              <div className="fc-ico">{wxEmoji(d.weatherCode)}</div>
              <div className="fc-hi">{Math.round(d.tempHigh)}°</div>
              <div className="fc-lo">{Math.round(d.tempLow)}°</div>
              {d.precipSum > 0.01 && <div className="fc-rain">{d.precipSum.toFixed(2)}″</div>}
              {p && <div className={`fc-spray ${p.cls}`}>{p.txt}</div>}
            </div>
          );
        })}
      </div>

      {/* rainfall */}
      {rainSummary && (
        <div className="mt-[var(--gap)]">
          <RainTracker
            daily={rainDaily}
            summary={rainSummary}
            avgHighF={avgHigh7}
            humidityPct={current.humidity}
          />
        </div>
      )}
    </div>
  );
}

function Metric({ icon, k, v }: { icon: React.ReactNode; k: string; v: string }) {
  return (
    <div className="bg-card px-3.5 py-2.5">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-ink-3">
        {icon} {k}
      </div>
      <div className="mono mt-0.5 text-base font-semibold">{v}</div>
    </div>
  );
}
