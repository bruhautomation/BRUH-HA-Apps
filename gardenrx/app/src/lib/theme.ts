/**
 * Centralized theme constants — colors, badges, and status styling
 * used across the app. Single source of truth for visual consistency.
 */

import type { SprayRating } from './weather';

// ── Product type colors (fungicide, insecticide, etc.) ──

export const typeColors: Record<string, string> = {
  fungicide: 'bg-violet-50 text-violet-800 ring-1 ring-violet-200/60',
  insecticide: 'bg-sky-50 text-sky-800 ring-1 ring-sky-200/60',
  bactericide: 'bg-teal-50 text-teal-800 ring-1 ring-teal-200/60',
  herbicide: 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200/60',
};

export const typeDot: Record<string, string> = {
  fungicide: 'bg-violet-500',
  insecticide: 'bg-sky-500',
  bactericide: 'bg-teal-500',
  herbicide: 'bg-emerald-500',
};

export const typeFilterStyles: Record<string, { active: string; inactive: string; label: string }> =
  {
    fungicide: {
      active: 'bg-violet-600 text-white shadow-sm',
      inactive: 'bg-violet-50 text-violet-700 ring-1 ring-violet-200/60 hover:ring-violet-300',
      label: 'Fungicide',
    },
    insecticide: {
      active: 'bg-sky-600 text-white shadow-sm',
      inactive: 'bg-sky-50 text-sky-700 ring-1 ring-sky-200/60 hover:ring-sky-300',
      label: 'Insecticide',
    },
    herbicide: {
      active: 'bg-emerald-600 text-white shadow-sm',
      inactive: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/60 hover:ring-emerald-300',
      label: 'Herbicide',
    },
    bactericide: {
      active: 'bg-teal-600 text-white shadow-sm',
      inactive: 'bg-teal-50 text-teal-700 ring-1 ring-teal-200/60 hover:ring-teal-300',
      label: 'Bactericide',
    },
  };

// ── Signal word badge colors ──

export const signalWordColors: Record<string, string> = {
  CAUTION: 'bg-amber-50 text-amber-800 ring-1 ring-amber-200/60',
  WARNING: 'bg-orange-50 text-orange-800 ring-1 ring-orange-200/60',
  DANGER: 'bg-terra-50 text-terra-800 ring-1 ring-terra-200/60',
};

// ── Spray rating colors ──

export const ratingColors: Record<SprayRating, string> = {
  EXCELLENT: 'bg-emerald-500',
  GOOD: 'bg-emerald-400',
  FAIR: 'bg-amber-400',
  POOR: 'bg-terra-400',
};

export const ratingColorsLight: Record<SprayRating, string> = {
  EXCELLENT: 'bg-emerald-100 text-emerald-800',
  GOOD: 'bg-emerald-50 text-emerald-700',
  FAIR: 'bg-amber-50 text-amber-700',
  POOR: 'bg-terra-50 text-terra-700',
};

// ── Urgency config (spray planner) ──

export const urgencyConfig: Record<string, { label: string; dot: string; border: string }> = {
  red: { label: 'Needs spray', dot: 'bg-terra-500', border: 'border-l-terra-400' },
  yellow: { label: 'Degrading', dot: 'bg-amber-500', border: 'border-l-amber-400' },
  green: { label: 'Protected', dot: 'bg-emerald-500', border: 'border-l-emerald-400' },
  none: { label: 'No history', dot: 'bg-muted-foreground/40', border: 'border-l-muted' },
};

// ── Mix product role dot colors ──

export const roleDot: Record<string, string> = {
  'multi-site': 'bg-violet-500',
  'single-site': 'bg-indigo-400',
  insecticide: 'bg-sky-500',
};

// ── Helpers ──

export function formatStage(s: string) {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
