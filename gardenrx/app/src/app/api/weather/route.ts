import { fetchWeather, type WeatherData } from '@/lib/weather';
import { NextResponse } from 'next/server';

// Dynamic, with its own two-hour memory: a route prerendered at build time
// would serve the weather for wherever the image was built until its first
// revalidation, and the location is this house's, read when the add-on starts.
export const dynamic = 'force-dynamic';

const TTL_MS = 2 * 60 * 60 * 1000;
let cached: { at: number; data: WeatherData } | null = null;

export async function GET() {
  if (cached && Date.now() - cached.at < TTL_MS) return NextResponse.json(cached.data);
  try {
    const data = await fetchWeather();
    cached = { at: Date.now(), data };
    return NextResponse.json(data);
  } catch (error) {
    console.error('Weather fetch error:', error);
    if (cached) return NextResponse.json(cached.data);
    return NextResponse.json({ error: 'Failed to fetch weather' }, { status: 500 });
  }
}
