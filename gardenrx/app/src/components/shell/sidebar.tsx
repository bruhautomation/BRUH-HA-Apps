'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Leaf, Settings } from 'lucide-react';
import { NAV_LINKS, isActiveLink } from '@/lib/nav-links';
import { ThemeSwitcher } from '@/components/theme-switcher';
import { Clock } from '@/components/shell/clock';
import { APP_VERSION } from '@/lib/version';
import type { AppSettings } from '@/lib/database.types';

export function Sidebar({ settings }: { settings: AppSettings }) {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      <Link href="/" className="brand" aria-label="GardenRX — Today">
        <div className="brand-mark">
          <Leaf className="size-5" />
        </div>
        <div>
          <div className="brand-name">GardenRx</div>
          <Clock withDate className="brand-sub" />
        </div>
      </Link>

      <div className="nav-label">Manage</div>
      {NAV_LINKS.map((link) => {
        const { href, label, icon: Icon } = link;
        const active = isActiveLink(pathname, link);
        return (
          <Link
            key={href}
            href={href}
            className={`nav-item${active ? ' active' : ''}`}
            aria-current={active ? 'page' : undefined}
          >
            <Icon className="size-[18px]" />
            {label}
          </Link>
        );
      })}

      <div className="sidebar-foot flex flex-col gap-3">
        <ThemeSwitcher settings={settings} />
        <div className="flex items-center justify-between gap-2">
          <Link href="/changelog" className="transition-colors hover:text-leaf">
            v{APP_VERSION} · changelog
          </Link>
          <Link
            href="/settings"
            aria-label="Settings"
            aria-current={pathname.startsWith('/settings') ? 'page' : undefined}
            className={`grid size-7 place-items-center rounded-md transition-colors hover:bg-paper-2 hover:text-leaf ${pathname.startsWith('/settings') ? 'text-leaf' : 'text-ink-3'}`}
          >
            <Settings className="size-4" />
          </Link>
        </div>
      </div>
    </aside>
  );
}
