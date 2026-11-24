import { Sun, Sprout, Map, Apple, SprayCan, FlaskConical, CloudSun } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export type NavLink = {
  href: string;
  /** The tab's one name: the sidebar, the phone's bottom bar and the screen's
   *  title all say this, so it has to fit seven to a 360px phone. */
  label: string;
  icon: LucideIcon;
  /** Extra route prefixes that belong to this tab (sub-tab routes). */
  match?: string[];
};

// Workflow order (handoff): Today → garden cluster (Crops · Garden · Harvest)
// → spray workflow (Spray · Products) → Weather. Settings lives behind a gear,
// not a primary tab. "Spray" owns Plan + History; "Products" owns Catalog + Stock.
export const NAV_LINKS: NavLink[] = [
  { href: '/', label: 'Today', icon: Sun },
  { href: '/crops', label: 'Crops', icon: Sprout },
  { href: '/garden', label: 'Garden', icon: Map },
  { href: '/harvest', label: 'Harvest', icon: Apple },
  { href: '/tank', label: 'Spray', icon: SprayCan, match: ['/tank', '/history'] },
  { href: '/products', label: 'Products', icon: FlaskConical, match: ['/products', '/inventory'] },
  { href: '/weather', label: 'Weather', icon: CloudSun },
];

export function isActiveLink(pathname: string, link: { href: string; match?: string[] }): boolean {
  if (link.href === '/') return pathname === '/';
  const prefixes = link.match ?? [link.href];
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
