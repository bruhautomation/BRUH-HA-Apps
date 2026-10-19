'use client';

import { useState } from 'react';
import { Monitor, Sun, Cloud, Moon } from 'lucide-react';
import { createClient } from '@/lib/db/client';
import type { AppSettings, ThemeMode } from '@/lib/database.types';

const MODES: { id: ThemeMode; label: string; Icon: typeof Sun }[] = [
  { id: 'auto', label: 'Auto', Icon: Monitor },
  { id: 'light', label: 'Light', Icon: Sun },
  { id: 'medium', label: 'Medium', Icon: Cloud },
  { id: 'dark', label: 'Dark', Icon: Moon },
];

function applyTheme(s: Pick<AppSettings, 'theme_mode' | 'figures'>) {
  const root = document.documentElement;
  root.classList.add('theme-switching');
  root.setAttribute('data-theme-mode', s.theme_mode);
  const eff =
    s.theme_mode === 'auto'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : s.theme_mode;
  root.setAttribute('data-theme', eff);
  root.setAttribute('data-figs', s.figures);
  requestAnimationFrame(() => root.classList.remove('theme-switching'));
}

export function ThemeSwitcher({ settings }: { settings: AppSettings }) {
  const [pref, setPref] = useState(settings);

  function update(patch: Partial<AppSettings>) {
    const next = { ...pref, ...patch };
    setPref(next);
    applyTheme(next);
    // Persist (best-effort — UI already reflects the change).
    const supabase = createClient();
    void supabase
      .from('app_settings')
      .update({ ...patch, updated_at: new Date().toISOString() })
      .eq('id', 1)
      // A query builder runs when it is awaited or .then()'d, never before —
      // a bare `void` on it saved nothing.
      .then(({ error }) => {
        if (error) console.error('Saving the theme failed:', error);
      });
  }

  return (
    <div className="mode-seg" role="group" aria-label="Theme mode">
      {MODES.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          className={pref.theme_mode === id ? 'on' : ''}
          title={label}
          aria-label={label}
          aria-pressed={pref.theme_mode === id}
          onClick={() => update({ theme_mode: id })}
        >
          <Icon className="size-[15px]" />
        </button>
      ))}
    </div>
  );
}
