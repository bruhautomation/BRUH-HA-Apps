import { Beaker, Bug } from 'lucide-react';
import type { CoverageInfo } from '@/lib/protection';
import { covColor, covLabel } from '@/components/status';

function fmtDate(d: Date): string {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** Protection coverage meter (design cov-meter): days-left bar + product/date +
 *  rain-since. Suppressed → "Held — bloom" (no insecticide while pollinating). */
export function CoverageMeter({
  cov,
  type,
  suppressed,
}: {
  cov: CoverageInfo | null;
  type: 'fungicide' | 'insecticide';
  suppressed?: boolean;
}) {
  const Icon = type === 'fungicide' ? Beaker : Bug;
  const label = type === 'fungicide' ? 'Fungicide' : 'Insecticide';

  if (suppressed) {
    return (
      <div className="cov-meter">
        <div className="cov-top">
          <span className="cov-name">
            <Icon className="size-3.5" /> {label}
          </span>
          <span className="cov-stat" style={{ color: 'var(--bloom)' }}>
            Held — bloom
          </span>
        </div>
        <div className="cov-track">
          <div
            className="cov-fill"
            style={{ width: '100%', background: 'var(--bloom)', opacity: 0.35 }}
          />
        </div>
        <div className="cov-sub">No insecticide while pollinators are active.</div>
      </div>
    );
  }

  if (!cov) {
    return (
      <div className="cov-meter">
        <div className="cov-top">
          <span className="cov-name">
            <Icon className="size-3.5" /> {label}
          </span>
          <span className="cov-stat" style={{ color: 'var(--ink-3)' }}>
            Untracked
          </span>
        </div>
        <div className="cov-track" />
        <div className="cov-sub">No {type} history yet.</div>
      </div>
    );
  }

  const color = covColor(cov.status);
  const interval = cov.product.cover_spray_interval_days ?? 14;
  const pct =
    cov.status === 'red' ? 100 : Math.max(6, Math.min(100, (cov.daysRemaining / interval) * 100));

  return (
    <div className="cov-meter">
      <div className="cov-top">
        <span className="cov-name">
          <Icon className="size-3.5" /> {label}
        </span>
        <span className="cov-stat" style={{ color }}>
          {covLabel(cov.status)}
          {cov.status !== 'red' ? ` · ${cov.daysRemaining}d` : ''}
        </span>
      </div>
      <div className="cov-track">
        <div className="cov-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="cov-sub">
        {cov.product.brand} · {fmtDate(cov.dateApplied)}
        {cov.wasRainedOnBeforeRainFast ? (
          <span style={{ color: 'var(--warn)' }}>
            {' '}
            · rain-washed ({cov.rainSinceSpray.toFixed(1)}″)
          </span>
        ) : cov.rainSinceSpray > 0 ? (
          ` · ${cov.rainSinceSpray.toFixed(1)}″ rain since`
        ) : (
          ''
        )}
      </div>
    </div>
  );
}
