import { Sun, Sprout, Map, Apple, SprayCan, FlaskConical, CloudSun } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export type NavLink = {
  href: string;
  label: string;
  short: string;
  icon: LucideIcon;
  /** Extra route prefixes that belong to this tab (sub-tab routes). */
  match?: string[];
};

// Workflow order (handoff): Today → garden cluster (Crops · Garden · Harvest)
// → spray workflow (Spray · Treatments) → Weather. Settings lives behind a gear,
// not a primary tab. "Spray" owns Plan + History; "Treatments" owns Catalog + Stock.
export const NAV_LINKS: NavLink[] = [
  { href: '/', label: 'Today', short: 'Today', icon: Sun },
  { href: '/crops', label: 'Crops', short: 'Crops', icon: Sprout },
  { href: '/garden', label: 'Garden Map', short: 'Garden', icon: Map },
  { href: '/harvest', label: 'Harvest', short: 'Harvest', icon: Apple },
  { href: '/tank', label: 'Spray', short: 'Spray', icon: SprayCan, match: ['/tank', '/history'] },
  {
    href: '/products',
    label: 'Treatments',
    short: 'Treat',
    icon: FlaskConical,
    match: ['/products', '/inventory'],
  },
  { href: '/weather', label: 'Weather', short: 'Weather', icon: CloudSun },
];

export function isActiveLink(pathname: string, link: { href: string; match?: string[] }): boolean {
  if (link.href === '/') return pathname === '/';
  const prefixes = link.match ?? [link.href];
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
