import type { CoverageStatus } from '@/lib/protection';
import type { SprayRating } from '@/lib/weather';

/** Status → CSS color var. Status carries ONE meaning, only on indicators. */
export function covColor(status: CoverageStatus | 'untracked' | null | undefined): string {
  return status === 'red'
    ? 'var(--danger)'
    : status === 'yellow'
      ? 'var(--warn)'
      : status === 'green'
        ? 'var(--leaf)'
        : 'var(--ink-3)';
}

export function covLabel(status: CoverageStatus | 'untracked' | null | undefined): string {
  return status === 'red'
    ? 'Lapsed'
    : status === 'yellow'
      ? 'Degrading'
      : status === 'green'
        ? 'Protected'
        : 'Untracked';
}

export function CovDot({
  status,
  size = 8,
}: {
  status: CoverageStatus | 'untracked' | null | undefined;
  size?: number;
}) {
  return (
    <span
      style={{ width: size, height: size, background: covColor(status) }}
      className="inline-block shrink-0 rounded-full"
    />
  );
}

const RATING_COLORS: Record<SprayRating, [string, string]> = {
  EXCELLENT: ['var(--leaf)', 'var(--safe-bg)'],
  GOOD: ['var(--leaf)', 'var(--safe-bg)'],
  FAIR: ['var(--warn)', 'var(--warn-bg)'],
  POOR: ['var(--danger)', 'var(--danger-bg)'],
};

export function RatingPill({ rating, size = 'md' }: { rating: SprayRating; size?: 'sm' | 'md' }) {
  const [fg, bg] = RATING_COLORS[rating] ?? RATING_COLORS.FAIR;
  return (
    <span
      className="rating-pill"
      style={{ color: fg, background: bg, fontSize: size === 'sm' ? 10.5 : 11.5 }}
    >
      {rating}
    </span>
  );
}
