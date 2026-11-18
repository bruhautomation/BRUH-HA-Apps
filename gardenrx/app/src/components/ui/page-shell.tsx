import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { SectionHeader } from '@/components/ui/section-header';

/**
 * The one page wrapper. The title and the body share it, so they share one
 * left edge, one gutter and one max-width. Two named widths: `wide`
 * (--page-wide, dense screens) and `narrow` (--page-read, reading screens and
 * forms); the default is --page. The sections inside are spaced by the shell's
 * `gap` (--section-gap), never by a margin on the child. The top bar reads the
 * same width, so its content lines up with the page.
 */
export function PageShell({
  width = 'default',
  title,
  meta,
  actions,
  actionsClassName,
  header,
  stagger = false,
  className,
  children,
  ...rest
}: {
  width?: 'default' | 'wide' | 'narrow';
  title?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  actionsClassName?: string;
  /** A custom first block in place of the standard title (it still sits inside the shell). */
  header?: ReactNode;
  stagger?: boolean;
  className?: string;
  children?: ReactNode;
} & Omit<React.HTMLAttributes<HTMLDivElement>, 'title'>) {
  return (
    <div
      {...rest}
      className={cn('page', stagger && 'animate-stagger', className)}
      data-width={width === 'default' ? undefined : width}
    >
      {header ??
        (title ? (
          <SectionHeader
            level={1}
            title={title}
            meta={meta}
            actions={actions}
            actionsClassName={actionsClassName}
          />
        ) : null)}
      {children}
    </div>
  );
}
