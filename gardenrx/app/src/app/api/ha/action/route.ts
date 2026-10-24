import { NextResponse } from 'next/server';
import { createClient } from '@/lib/db/server';
import { authorized } from '@/lib/ha/auth';
import {
  addCrop,
  addVariety,
  adjustInventory,
  completeQueuedSpray,
  deleteHarvest,
  deleteQueuedSpray,
  getHarvests,
  logHarvest,
  logNote,
  logSpray,
  queueSpray,
  type ActionResult,
} from '@/lib/ha/actions';
import type { DbClient } from '@/lib/db/query';
import { LOCATION } from '@/config/thresholds';

// What the `gardenrx.*` services call. Token-only — see auth.ts. A refusal is
// a 409 carrying the sentence, which the integration raises as a
// HomeAssistantError so it reaches the automation trace or the card's toast.
export const dynamic = 'force-dynamic';

/** The name off the wire chooses a branch, never a function by name. */
function run(
  name: string,
  db: DbClient,
  data: Record<string, unknown>,
  now: Date
): Promise<ActionResult> | null {
  const tz = LOCATION.timezone;
  switch (name) {
    case 'log_harvest':
      return logHarvest(db, data, now, tz);
    case 'delete_harvest':
      return deleteHarvest(db, data);
    case 'complete_queued_spray':
      return completeQueuedSpray(db, data, now, tz);
    case 'delete_queued_spray':
      return deleteQueuedSpray(db, data);
    case 'log_spray':
      return logSpray(db, data, now, tz);
    case 'queue_spray':
      return queueSpray(db, data, now, tz);
    case 'adjust_inventory':
      return adjustInventory(db, data, now, tz);
    case 'add_crop':
      return addCrop(db, data, now, tz);
    case 'add_variety':
      return addVariety(db, data, now, tz);
    case 'log_note':
      return logNote(db, data, now, tz);
    case 'get_harvests':
      return getHarvests(db, data, now, tz);
    default:
      return null;
  }
}

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
  const data =
    body.data && typeof body.data === 'object' && !Array.isArray(body.data) ? body.data : {};
  const pending = run(name, await createClient(), data, new Date());
  if (!pending) {
    return NextResponse.json({ ok: false, error: `unknown action "${name}"` }, { status: 400 });
  }
  const result = await pending;
  return NextResponse.json(result, { status: result.ok ? 200 : 409 });
}
