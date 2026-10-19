/**
 * Shared visual identity for the three garden areas, used by both the Stock page
 * filters/badges and the Spray History filter so they look and behave the same.
 * `badge` is the soft idle pill; `chip` is the saturated active-filter state.
 */
import { Apple, Sprout, Flower2, type LucideIcon } from 'lucide-react';
import type { CropCategory } from '@/lib/crop-category';

export const AREA_STYLE: Record<CropCategory, { icon: LucideIcon; badge: string; chip: string }> = {
  Orchard: {
    icon: Apple,
    badge: 'bg-amber-50 text-amber-800 ring-amber-200/70',
    chip: 'bg-amber-600 text-white ring-amber-600 shadow-sm',
  },
  Garden: {
    icon: Sprout,
    badge: 'bg-emerald-50 text-emerald-800 ring-emerald-200/70',
    chip: 'bg-emerald-700 text-white ring-emerald-700 shadow-sm',
  },
  Landscape: {
    icon: Flower2,
    badge: 'bg-violet-50 text-violet-800 ring-violet-200/70',
    chip: 'bg-violet-600 text-white ring-violet-600 shadow-sm',
  },
};
