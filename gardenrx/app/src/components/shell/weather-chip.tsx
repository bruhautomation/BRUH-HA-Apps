'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { CloudSun } from 'lucide-react';
import { getCurrentSprayRating, type WeatherData } from '@/lib/weather';
import { withBase } from '@/lib/base-path';

/** Topbar weather pill — current temp/wind + spray rating, links to /weather.
 *  Computes the rating with the repo's existing logic (getCurrentSprayRating). */
export function WeatherChip() {
  const router = useRouter();
  const [wx, setWx] = useState<WeatherData | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(withBase('/api/weather'))
      .then((r) => (r.ok ? r.json() : null))
      .then((d: WeatherData | null) => {
        if (!cancelled && d && d.current) setWx(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!wx) return null;
  const rating = getCurrentSprayRating(wx.current, wx.hourly);

  return (
    <button
      type="button"
      className="wx-chip"
      onClick={() => router.push('/weather')}
      aria-label={`Weather: ${Math.round(wx.current.temp)}°, ${wx.current.description}`}
    >
      <div className="wx-ico">
        <CloudSun className="size-4 text-water" />
      </div>
      <div>
        <div className="wx-temp">
          {Math.round(wx.current.temp)}°
          <span className="font-normal text-ink-3"> {Math.round(wx.current.windSpeed)}mph</span>
        </div>
        <div className="wx-loc">
          {wx.current.description} · spray {rating.toLowerCase()}
        </div>
      </div>
    </button>
  );
}
