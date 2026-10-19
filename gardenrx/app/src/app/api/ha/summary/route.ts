import { NextResponse } from 'next/server';
import { createClient } from '@/lib/db/server';
import { authorized } from '@/lib/ha/auth';
import { loadGardenRows } from '@/lib/ha/load';
import { buildSummary } from '@/lib/ha/summary';
import { LOCATION } from '@/config/thresholds';

// What the `gardenrx` integration polls for its sensors. Token-only — see auth.ts.
export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  if (!authorized(request)) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }
  try {
    const rows = await loadGardenRows(await createClient());
    return NextResponse.json(buildSummary(rows, new Date(), LOCATION.timezone));
  } catch (e) {
    return NextResponse.json(
      { error: `the garden could not be read: ${e instanceof Error ? e.message : String(e)}` },
      { status: 500 }
    );
  }
}
