import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

/**
 * The one section heading. Two levels:
 *   level 1 — the page title (--fs-title, an h1 unless `as` says otherwise);
 *   level 2 — a section or card heading (--fs-card, an h2 unless `as` says otherwise).
 * An optional count (`meta`) and actions sit on the same baseline. `inCard`
 * adds the gap between a card's heading and its content. Nothing else sets a
 * heading's size or case: no uppercase tracked labels, no per-page sizes.
 */
export function SectionHeader({
  level = 2,
  as,
  title,
  icon,
  meta,
  actions,
  actionsClassName,
  inCard = false,
  className,
}: {
  level?: 1 | 2;
  as?: 'h1' | 'h2' | 'h3';
  title: ReactNode;
  icon?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  actionsClassName?: string;
  inCard?: boolean;
  className?: string;
}) {
  const Tag = as ?? (level === 1 ? 'h1' : 'h2');
  return (
    <div className={cn('sh', level === 1 ? 'sh-1' : 'sh-2', inCard && 'in-card', className)}>
      {icon ? <span className="sh-icon">{icon}</span> : null}
      <Tag>{title}</Tag>
      {meta ? <span className="meta">{meta}</span> : null}
      <span className="spacer" />
      {actions ? <div className={cn('sh-actions', actionsClassName)}>{actions}</div> : null}
    </div>
  );
}
