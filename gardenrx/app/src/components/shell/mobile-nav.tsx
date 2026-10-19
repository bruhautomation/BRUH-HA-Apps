'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { NAV_LINKS, isActiveLink } from '@/lib/nav-links';

export function MobileNav() {
  const pathname = usePathname();
  return (
    <nav className="mobile-nav" aria-label="Primary">
      {NAV_LINKS.map((link) => {
        const { href, short, icon: Icon } = link;
        const active = isActiveLink(pathname, link);
        return (
          <Link
            key={href}
            href={href}
            className={`mn-item${active ? ' active' : ''}`}
            aria-current={active ? 'page' : undefined}
          >
            <Icon className="size-[19px]" />
            <span className="mn-lbl">{short}</span>
          </Link>
        );
      })}
    </nav>
  );
}
