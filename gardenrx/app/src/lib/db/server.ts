/**
 * The database, for server components and route handlers.
 *
 * Same builder the browser gets (`./client`), executed in-process against the
 * SQLite file. `createClient` stays async because every caller was written
 * against `@supabase/ssr`'s, which is.
 */

import { makeClient, type DbClient, type DbRequest } from './query';
import { execute, getDatabase } from './sqlite';

export function runRequest(req: DbRequest) {
  return execute(getDatabase(), req);
}

export async function createClient(): Promise<DbClient> {
  return makeClient(async (req) => runRequest(req));
}
