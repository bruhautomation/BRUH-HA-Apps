import { NextResponse } from 'next/server';
import { createClient } from '@/lib/db/server';
import { authorized } from '@/lib/ha/auth';
import { ACTIONS } from '@/lib/ha/actions';
import { LOCATION } from '@/config/thresholds';

// What the `gardenrx.*` services call. Token-only — see auth.ts. A refusal is
// a 409 carrying the sentence, which the integration raises as a
// HomeAssistantError so it reaches the automation trace or the card's toast.
export const dynamic = 'force-dynamic';

// A Map, so the name off the wire can only ever select one of these four.
const HANDLERS = new Map(Object.entries(ACTIONS));

export async function POST(request: Request) {
  if (!authorized(request)) {
    return NextResponse.json({ ok: false, error: 'unauthorized' }, { status: 401 });
  }
  let body: { action?: string; data?: Record<string, unknown> };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: 'not JSON' }, { status: 400 });
  }
  const name = String(body.action ?? '');
  const handler = HANDLERS.get(name);
  if (!handler) {
    return NextResponse.json({ ok: false, error: `unknown action "${name}"` }, { status: 400 });
  }
  const data =
    body.data && typeof body.data === 'object' && !Array.isArray(body.data) ? body.data : {};
  const db = await createClient();
  const result = await handler(db, data, new Date(), LOCATION.timezone);
  return NextResponse.json(result, { status: result.ok ? 200 : 409 });
}
