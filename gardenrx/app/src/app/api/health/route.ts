import { NextResponse } from 'next/server';
import { getDatabase } from '@/lib/db/sqlite';

// The add-on's own watch on the app. It opens the database, because a server
// that answers while its database will not open is not a working garden.
export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    getDatabase().prepare('SELECT 1').all();
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 503 });
  }
}
