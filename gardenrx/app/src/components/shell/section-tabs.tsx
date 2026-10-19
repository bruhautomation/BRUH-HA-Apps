'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

/** Sub-tabs for a consolidated section (e.g. Spray = Plan + History). */
export const SPRAY_TABS = [
  { href: '/tank', label: 'Plan a mix' },
  { href: '/history', label: 'History' },
];

export const TREATMENT_TABS = [
  { href: '/products', label: 'Catalog' },
  { href: '/inventory', label: 'Your stock' },
];

export function SectionTabs({ tabs }: { tabs: { href: string; label: string }[] }) {
  const pathname = usePathname();
  return (
    <div className="section-tabs" role="tablist">
      {tabs.map((t) => {
        const active = pathname === t.href || pathname.startsWith(`${t.href}/`);
        return (
          <Link
            key={t.href}
            href={t.href}
            role="tab"
            aria-selected={active}
            className={`section-tab${active ? ' active' : ''}`}
          >
            {t.label}
          </Link>
        );
      })}
    </div>
  );
}
