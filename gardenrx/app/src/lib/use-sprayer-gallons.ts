'use client';

import { useSyncExternalStore } from 'react';
import { SPRAYER } from '@/config/thresholds';

const KEY = 'gardenrx:sprayer_gallons';

function subscribe(cb: () => void) {
  window.addEventListener('storage', cb);
  window.addEventListener('gardenrx:sprayer_gallons_changed', cb);
  return () => {
    window.removeEventListener('storage', cb);
    window.removeEventListener('gardenrx:sprayer_gallons_changed', cb);
  };
}

function getSnapshot(): number {
  const raw = window.localStorage.getItem(KEY);
  const n = raw ? parseFloat(raw) : NaN;
  return !isNaN(n) && n > 0 ? n : SPRAYER.gallons;
}

function getServerSnapshot(): number {
  return SPRAYER.gallons;
}

export function useSprayerGallons(): [number, (n: number) => void] {
  const gallons = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const set = (n: number) => {
    if (n > 0) {
      window.localStorage.setItem(KEY, String(n));
      window.dispatchEvent(new Event('gardenrx:sprayer_gallons_changed'));
    }
  };
  return [gallons, set];
}
