import Link from 'next/link';
import { CloudRain, Droplets, ChevronRight } from 'lucide-react';
import type { DailyRain, RainSummary } from '@/lib/rainfall';
import { DROUGHT_META, WATERING_META, wateringAdvice } from '@/lib/rainfall';
import { SectionHeader } from '@/components/ui/section-header';

/** Weather's rainfall card: a watering call-to-action (rain vs. evapotranspiration
 *  demand), 30-day daily bars, week/month totals, drought status. */
export function RainTracker({
  daily,
  summary,
  avgHighF,
  humidityPct,
  dormant,
}: {
  daily: DailyRain[];
  summary: RainSummary;
  avgHighF?: number | null;
  humidityPct?: number | null;
  /** Most of the garden is dormant or past harvest. */
  dormant?: boolean;
}) {
  if (daily.length === 0) return null;
  const meta = DROUGHT_META[summary.status];
  const advice = wateringAdvice(daily, { avgHighF, humidityPct, dormant });
  const adviceMeta = WATERING_META[advice.status];
  const scaleMax = Math.max(0.25, ...daily.map((d) => d.inches));
  const fmtDay = (key: string) =>
    new Date(`${key}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const midIdx = Math.floor(daily.length / 2);

  return (
    <section className="rounded-2xl bg-card ring-1 ring-black/[0.05] shadow-sm px-4 py-3">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <CloudRain className="w-4 h-4 text-sky-500" />
          <SectionHeader as="h2" title="Rainfall" />
        </div>
        <span
          className={`text-xs font-semibold tracking-wide uppercase px-2 py-0.5 rounded-full ring-1 ${meta.badge}`}
        >
          {meta.label}
        </span>
      </div>

      {/* watering call-to-action — rain vs. evapotranspiration demand */}
      <div
        className={`mb-3 flex items-start gap-3 rounded-lg px-3 py-2 ring-1 ${adviceMeta.badge}`}
      >
        <Droplets className="w-4 h-4 mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-semibold leading-tight">{advice.headline}</p>
          <p className="text-xs leading-snug mt-0.5 opacity-90">{advice.detail}</p>
        </div>
      </div>

      {/* week / month totals */}
      <div className="flex items-baseline gap-6 mb-3">
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-heading font-semibold tracking-tight text-foreground tabular-nums">
            {summary.week.toFixed(2)}
          </span>
          <span className="text-xs text-muted-foreground">in · this week</span>
        </div>
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-heading font-semibold tracking-tight text-foreground tabular-nums">
            {summary.month.toFixed(2)}
          </span>
          <span className="text-xs text-muted-foreground">in · 30 days</span>
        </div>
        <div className="ml-auto text-right text-xs text-muted-foreground/70">
          {summary.daysSinceRain === null
            ? 'no rain logged'
            : summary.daysSinceRain === 0
              ? 'rain today'
              : `${summary.daysSinceRain}d since rain`}
        </div>
      </div>

      {/* days vs rainfall — 30 daily bars */}
      <div className="flex items-end gap-px h-16">
        {daily.map((d) => {
          const pct = d.inches > 0 ? Math.max(6, Math.round((d.inches / scaleMax) * 100)) : 0;
          return (
            <div
              key={d.date}
              className="flex-1 h-full flex items-end"
              title={`${fmtDay(d.date)}: ${d.inches.toFixed(2)}″`}
            >
              <div
                className={`w-full rounded-t-sm ${d.inches > 0 ? 'bg-sky-400 hover:bg-sky-500 transition-colors' : 'bg-muted/40'}`}
                style={{ height: d.inches > 0 ? `${pct}%` : '2px' }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between mt-1 text-xs text-muted-foreground/60">
        <span>{fmtDay(daily[0].date)}</span>
        <span>{fmtDay(daily[midIdx].date)}</span>
        <span>Today</span>
      </div>

      {summary.wettest && summary.wettest.inches > 0 && (
        <p className="text-xs text-muted-foreground/70 mt-2">
          Wettest day: {summary.wettest.inches.toFixed(2)}″ on {fmtDay(summary.wettest.date)}.
        </p>
      )}
    </section>
  );
}

/** Today's one line on watering: the same advice as Weather's Rainfall card,
 *  linking to it, so the card itself is shown once. */
export function RainSummaryLine({
  daily,
  avgHighF,
  humidityPct,
  dormant,
}: {
  daily: DailyRain[];
  avgHighF?: number | null;
  humidityPct?: number | null;
  dormant?: boolean;
}) {
  if (daily.length === 0) return null;
  const advice = wateringAdvice(daily, { avgHighF, humidityPct, dormant });
  return (
    <Link
      href="/weather"
      className={`flex min-h-10 items-center gap-3 rounded-lg px-3 py-2 ring-1 ${WATERING_META[advice.status].badge}`}
    >
      <Droplets className="w-4 h-4 shrink-0" />
      <span className="min-w-0 flex-1 text-sm leading-snug">
        <span className="font-semibold">{advice.headline}</span>
        <span className="opacity-80"> · {advice.rain7.toFixed(2)}″ rain this week</span>
      </span>
      <ChevronRight className="w-4 h-4 shrink-0 opacity-70" />
    </Link>
  );
}
