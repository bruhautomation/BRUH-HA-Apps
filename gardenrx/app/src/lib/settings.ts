/**
 * Appearance / UI preferences, persisted to the `app_settings`
 * singleton (single-user app). Theme is applied on `<html data-theme=…>`
 * server-side so there's no flash; "auto" is resolved client-side against
 * `prefers-color-scheme` (see theme-script.tsx).
 */

import type {
  AppSettings,
  ThemeMode,
  FiguresPref,
  DensityPref,
  PhiAlertPref,
} from '@/lib/database.types';

export type { ThemeMode, FiguresPref, DensityPref, PhiAlertPref };

export const DEFAULT_SETTINGS: AppSettings = {
  id: 1,
  theme_mode: 'light',
  figures: 'sans',
  density: 'comfortable',
  phi_alerts: 'loud',
  weather_bar: true,
  updated_at: '',
};

/** The concrete theme to render on the server. "auto" falls back to light and
 *  is upgraded to dark by the pre-paint script when the OS prefers dark. */
export function resolveServerTheme(mode: ThemeMode): 'light' | 'medium' | 'dark' {
  return mode === 'auto' ? 'light' : mode;
}
