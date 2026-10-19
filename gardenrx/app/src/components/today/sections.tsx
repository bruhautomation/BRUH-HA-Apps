import Link from 'next/link';
import { ChevronRight, CloudSun, CloudOff } from 'lucide-react';
import type { HourlyForecast, DailyForecast, SprayRating } from '@/lib/weather';
import { CropAvatar } from '@/components/crop-glyph';
import { CovDot, RatingPill } from '@/components/status';
import { SprayWindow3Day } from '@/components/today/spray-window-3day';

export type AttentionItem = {
  cropId: number;
  cropName: string;
  cropGroup: string | null;
  due: string[];
  soon: string[];
  inBloom: boolean;
};

export function NeedsAttention({ items }: { items: AttentionItem[] }) {
  if (items.length === 0) return null;
  const shown = items.slice(0, 6);
  const extra = items.length - shown.length;
  return (
    <section className="t-sec">
      <div className="t-sec-h">
        <h2>Needs attention</h2>
        <span className="n">{items.length}</span>
      </div>
      <div className="row-list">
        {shown.map((it) => (
          <Link key={it.cropId} href={`/crops/${it.cropId}`} className="row-item">
            <CropAvatar name={it.cropName} group={it.cropGroup} size={38} />
            <div className="ri-body">
              <div className="ri-name">{it.cropName}</div>
              <div className="ri-tags">
                {it.due.map((d) => (
                  <span key={d} className="ri-tag due">
                    {d} due
                  </span>
                ))}
                {it.soon.map((s) => (
                  <span key={s} className="ri-tag soon">
                    {s} soon
                  </span>
                ))}
                {it.inBloom && (
                  <span
                    className="ri-tag"
                    style={{ background: 'var(--bloom-bg)', color: 'var(--bloom)' }}
                  >
                    In bloom
                  </span>
                )}
              </div>
            </div>
            <ChevronRight className="size-4 shrink-0 text-ink-3" />
          </Link>
        ))}
        {extra > 0 && (
          <Link
            href="/crops"
            className="row-item justify-center text-[13px] font-semibold text-ink-3"
          >
            +{extra} more
          </Link>
        )}
      </div>
    </section>
  );
}

export type ComingUpItem = { cropId: number; cropName: string; type: string; daysLeft: number };

export function ComingUp({ items }: { items: ComingUpItem[] }) {
  if (items.length === 0) return null;
  return (
    <section className="t-sec">
      <div className="t-sec-h">
        <h2>Coming up</h2>
      </div>
      <div className="row-list">
        {items.map((it) => (
          <Link key={`${it.cropId}-${it.type}`} href={`/crops/${it.cropId}`} className="row-item">
            <CovDot status="green" />
            <div className="ri-body">
              <span className="text-sm font-semibold capitalize">{it.type}</span>
              <span className="text-ink-3"> · {it.cropName}</span>
            </div>
            <span className="ri-right">
              {it.daysLeft === 0 ? 'today' : it.daysLeft === 1 ? 'tomorrow' : `in ${it.daysLeft}d`}
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function SprayConditions({
  rating,
  temp,
  wind,
  humidity,
  description,
  hourly,
  daily,
}: {
  rating: SprayRating | null;
  temp: number;
  wind: number;
  humidity: number;
  description: string;
  hourly: HourlyForecast[];
  daily: DailyForecast[];
}) {
  return (
    <section className="t-sec">
      <div className="t-sec-h">
        <h2>Spray window — 3 days</h2>
        <div className="spacer" />
        <Link href="/weather" className="more">
          Weather <ChevronRight className="size-3.5" />
        </Link>
      </div>
      <div className="card panel" style={{ padding: 18 }}>
        <div className="mb-4 flex items-center gap-3.5 border-b border-line pb-4">
          <div className="grid size-10 shrink-0 place-items-center rounded-[10px] bg-water-bg">
            <CloudSun className="size-5 text-water" />
          </div>
          <div>
            <div className="font-display text-xl font-semibold">
              {Math.round(temp)}°
              <span className="text-sm font-normal text-ink-3"> {description}</span>
            </div>
            <div className="mono text-xs text-ink-3">
              Wind {Math.round(wind)} mph · {Math.round(humidity)}% RH
            </div>
          </div>
          <div className="ml-auto text-right">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-3">
              Right now
            </div>
            {rating && <RatingPill rating={rating} />}
          </div>
        </div>
        <SprayWindow3Day hourly={hourly} daily={daily} />
      </div>
    </section>
  );
}

export function WeatherUnavailable() {
  return (
    <section className="t-sec">
      <div className="t-sec-h">
        <h2>Spray window — 3 days</h2>
      </div>
      <div className="card panel" style={{ padding: 18 }}>
        <div className="flex items-center gap-3.5">
          <div
            className="grid size-10 shrink-0 place-items-center rounded-[10px]"
            style={{ background: 'var(--warn-bg)' }}
          >
            <CloudOff className="size-5" style={{ color: 'var(--warn)' }} />
          </div>
          <div>
            <div className="font-display text-[15px] font-semibold">Weather unavailable</div>
            <div className="mt-0.5 text-[13px] text-ink-2">
              Couldn&apos;t load conditions right now. Check wind, temperature, and rain timing
              yourself before spraying.
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
