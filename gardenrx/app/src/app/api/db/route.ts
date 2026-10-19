import { NextResponse } from 'next/server';
import { runRequest } from '@/lib/db/server';
import { dbError, type DbRequest } from '@/lib/db/query';

// The browser half of the query builder posts here. Every request is validated
// against the schema inside `execute` — the table, every column, every filter
// — and every value is bound, so what arrives is data and never SQL.
export const dynamic = 'force-dynamic';

const MAX_BODY = 2_000_000;

export async function POST(request: Request) {
  const text = await request.text();
  if (text.length > MAX_BODY) {
    return NextResponse.json({ data: null, error: dbError('request too large') }, { status: 413 });
  }
  let req: DbRequest;
  try {
    req = JSON.parse(text) as DbRequest;
  } catch {
    return NextResponse.json({ data: null, error: dbError('not JSON') }, { status: 400 });
  }
  const result = runRequest(req);
  return NextResponse.json(result, { status: result.error ? (result.status ?? 400) : 200 });
}
