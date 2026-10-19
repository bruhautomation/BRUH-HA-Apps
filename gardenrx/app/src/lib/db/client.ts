/**
 * The database, for client components.
 *
 * The browser has no route to a database — inside Home Assistant it can only
 * reach the panel through ingress — so each query is POSTed to the app's own
 * `/api/db`, which runs it with the server's executor. The builder is shared
 * with `./server`, so a screen written against one works against the other.
 */

import { withBase } from '@/lib/base-path';
import { dbError, makeClient, type DbClient, type DbResult } from './query';

export function createClient(): DbClient {
  return makeClient(async (req) => {
    const res = await fetch(withBase('/api/db'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
      cache: 'no-store',
    });
    try {
      return (await res.json()) as DbResult<unknown>;
    } catch {
      return { data: null, error: dbError(`GardenRX answered HTTP ${res.status}`, 'HTTP') };
    }
  });
}
