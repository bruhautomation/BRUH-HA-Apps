'use client';

import { useEffect, useState } from 'react';
import { Clock as ClockIcon } from 'lucide-react';

/**
 * Live clock in the visitor's current timezone, ticking each second.
 * `withDate` renders a compact "time · date" line (used under the sidebar logo);
 * the default is an icon + time chip for the mobile top bar.
 */
export function Clock({ withDate = false, className }: { withDate?: boolean; className?: string }) {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    const tick = () => setNow(new Date());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const time = now ? now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '';
  const date = now
    ? now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
    : '';

  if (withDate) {
    return (
      <div className={className} suppressHydrationWarning>
        {time ? `${time} · ${date}` : ' '}
      </div>
    );
  }

  return (
    <div
      className={
        className ??
        'hidden min-[420px]:inline-flex items-center gap-1.5 font-mono text-sm font-semibold text-ink-2 tabular-nums whitespace-nowrap select-none'
      }
      aria-label="Current time"
      suppressHydrationWarning
    >
      <ClockIcon className="size-3.5 text-ink-3" aria-hidden />
      <span>{time || ' '}</span>
    </div>
  );
}
