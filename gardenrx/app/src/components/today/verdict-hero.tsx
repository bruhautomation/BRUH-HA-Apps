import Link from 'next/link';
import {
  SprayCan,
  Gauge,
  Thermometer,
  Wind,
  Flower2,
  TriangleAlert,
  ChevronRight,
  CloudOff,
} from 'lucide-react';
import type { SprayRating } from '@/lib/weather';
import { RatingPill } from '@/components/status';

type State = 'spray-now' | 'hold-weather' | 'bloom-only' | 'upcoming' | 'clear';

type Props = {
  rating: SprayRating | null;
  temp: number | null;
  wind: number | null;
  fungDue: string[];
  insDue: string[];
  dueCropIds: number[];
  bloomCrops: string[];
  weatherBlocker: string | null;
  weatherUnavailable: boolean;
  upcoming: { cropName: string; type: string; daysLeft: number } | null;
  unprotectedCount: number;
  totalCrops: number;
  phiCount: number;
};

function names(arr: string[]): string {
  if (arr.length === 1) return arr[0];
  if (arr.length === 2) return `${arr[0]} & ${arr[1]}`;
  if (arr.length === 3) return arr.join(', ');
  return `${arr.length} crops`;
}

function dueDate(daysLeft: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysLeft);
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
}

const PALETTE: Record<State, { color: string; eyebrow: string; pulse: boolean }> = {
  'spray-now': { color: 'var(--terra)', eyebrow: 'Spray today', pulse: true },
  'hold-weather': { color: 'var(--warn)', eyebrow: 'Hold off', pulse: false },
  'bloom-only': { color: 'var(--bloom)', eyebrow: 'Bloom in progress', pulse: false },
  upcoming: { color: 'var(--leaf)', eyebrow: 'On track', pulse: false },
  clear: { color: 'var(--leaf)', eyebrow: 'All clear', pulse: false },
};

export function VerdictHero(props: Props) {
  const {
    rating,
    temp,
    wind,
    fungDue,
    insDue,
    dueCropIds,
    bloomCrops,
    weatherBlocker,
    weatherUnavailable,
    upcoming,
    phiCount,
  } = props;
  const planHref = dueCropIds.length ? `/tank?crops=${dueCropIds.join(',')}` : '/tank';
  const sprayOk = rating === 'EXCELLENT' || rating === 'GOOD';
  const actionable = fungDue.length > 0 || insDue.length > 0;

  let state: State;
  if (actionable && sprayOk) state = 'spray-now';
  else if (actionable && !sprayOk) state = 'hold-weather';
  else if (bloomCrops.length > 0) state = 'bloom-only';
  else if (upcoming && upcoming.daysLeft <= 7) state = 'upcoming';
  else state = 'clear';

  const p = PALETTE[state];

  let head = '';
  let sub: React.ReactNode = null;
  let action: React.ReactNode = null;

  if (state === 'spray-now') {
    const both = fungDue.length > 0 && insDue.length > 0;
    if (both) {
      head = 'Coverage is due';
      sub = (
        <>
          <strong>{fungDue.length}</strong> need fungicide, <strong>{insDue.length}</strong> need
          insecticide. Conditions are {rating?.toLowerCase()}.
        </>
      );
    } else if (fungDue.length) {
      head = names(fungDue);
      sub = (
        <>
          <strong>Fungicide</strong> coverage has lapsed
          {fungDue.length > 3 ? ` across ${fungDue.length} crops` : ''}. Conditions are{' '}
          {rating?.toLowerCase()} to spray.
        </>
      );
    } else {
      head = names(insDue);
      sub = (
        <>
          <strong>Insecticide</strong> coverage has lapsed
          {insDue.length > 3 ? ` across ${insDue.length} crops` : ''}. Conditions are{' '}
          {rating?.toLowerCase()} to spray.
        </>
      );
    }
    action = (
      <Link href={planHref} className="btn btn-primary">
        <SprayCan className="size-4" /> Plan a spray
      </Link>
    );
  } else if (state === 'hold-weather') {
    const cnt = new Set([...fungDue, ...insDue]).size;
    head = `${cnt} ${cnt === 1 ? 'crop needs' : 'crops need'} spraying`;
    sub = weatherUnavailable ? (
      <>
        <strong>Couldn&apos;t load current weather.</strong> Check wind, temperature, and rain
        timing before you spray.
      </>
    ) : (
      <>
        <strong>{weatherBlocker || 'Conditions are poor.'}</strong> Check the spray window for the
        next opening.
      </>
    );
  } else if (state === 'bloom-only') {
    head = `${names(bloomCrops)} in bloom`;
    sub = (
      <>No insecticide until petal fall — pollinators are visiting. Everything else is protected.</>
    );
  } else if (state === 'upcoming' && upcoming) {
    head = `${upcoming.type[0].toUpperCase()}${upcoming.type.slice(1)} for ${upcoming.cropName}`;
    sub = (
      <>
        Due in{' '}
        <strong>
          {upcoming.daysLeft} {upcoming.daysLeft === 1 ? 'day' : 'days'}
        </strong>{' '}
        · {dueDate(upcoming.daysLeft)}. Everything else is green.
      </>
    );
  } else {
    head = 'All crops protected';
    sub = <>Nothing due this week. Check back tomorrow.</>;
  }

  return (
    <div
      className="verdict accent-card rise"
      style={{ ['--ac' as string]: p.color, ['--vc' as string]: p.color }}
    >
      <div className="v-eyebrow">
        <span className={`v-dot${p.pulse ? ' pulse' : ''}`}>
          <i className="ping" />
          <i />
        </span>
        {p.eyebrow}
      </div>
      <h1 className="v-head">{head}</h1>
      <div className="v-sub">{sub}</div>

      {(action || state === 'bloom-only') && (
        <div className="v-actions">
          {action}
          {state === 'bloom-only' && (
            <span className="v-metaitem" style={{ color: 'var(--bloom)' }}>
              <Flower2 className="size-[15px]" /> Pollinators active
            </span>
          )}
        </div>
      )}

      <div className="v-meta">
        {weatherUnavailable && (
          <span className="v-metaitem" style={{ color: 'var(--warn)' }}>
            <CloudOff className="size-[15px]" /> Weather unavailable
          </span>
        )}
        {rating && actionable && (
          <span className="v-metaitem">
            <Gauge className="size-[15px] text-ink-3" />
            <span className="k">Spray now:</span> <RatingPill rating={rating} size="sm" />
          </span>
        )}
        {temp != null && (
          <span className="v-metaitem">
            <Thermometer className="size-[15px] text-ink-3" />
            <b>{Math.round(temp)}°</b>
          </span>
        )}
        {wind != null && (
          <span className="v-metaitem">
            <Wind className="size-[15px] text-ink-3" />
            <b>{Math.round(wind)} mph</b>
          </span>
        )}
        {phiCount > 0 && (
          <Link
            href="/harvest"
            className="v-metaitem"
            style={{ marginLeft: 'auto', color: 'var(--danger)', fontWeight: 600 }}
            title="Pre-harvest interval — sprayed too recently to harvest safely"
            aria-label={`${phiCount} crops under a pre-harvest interval — not safe to harvest yet`}
          >
            <TriangleAlert className="size-[15px]" /> {phiCount} under PHI{' '}
            <ChevronRight className="size-3.5" />
          </Link>
        )}
      </div>
    </div>
  );
}
