/**
 * The Home Assistant API's credential.
 *
 * The add-on writes a random token to a file both it and Home Assistant can
 * read (`/config/.gardenrx/api_token`, root-only) and the `gardenrx`
 * integration sends it as a bearer token. The panel's own screens never use
 * this API — they arrive through ingress, which is Home Assistant's login —
 * so a request here without the token is refused, whoever sent it. No token
 * file at all (`npm run dev`) refuses everything rather than nothing.
 */

import fs from 'node:fs';
import crypto from 'node:crypto';

let cached: { file: string; mtimeMs: number; token: string } | null = null;

function expectedToken(): string | null {
  const file = process.env.GARDENRX_HA_TOKEN_FILE;
  if (!file) return null;
  let fd: number | null = null;
  try {
    // Stat and read the same open file, so the token read is the one whose
    // mtime was checked.
    fd = fs.openSync(/*turbopackIgnore: true*/ file, 'r');
    const st = fs.fstatSync(fd);
    if (cached && cached.file === file && cached.mtimeMs === st.mtimeMs) return cached.token;
    const token = fs.readFileSync(fd, 'utf8').trim();
    if (token.length < 32) return null;
    cached = { file, mtimeMs: st.mtimeMs, token };
    return token;
  } catch {
    return null;
  } finally {
    if (fd !== null) fs.closeSync(fd);
  }
}

export function authorized(request: Request): boolean {
  const want = expectedToken();
  if (!want) return false;
  const header = request.headers.get('authorization') ?? '';
  const got = header.startsWith('Bearer ') ? header.slice(7).trim() : '';
  const a = Buffer.from(got);
  const b = Buffer.from(want);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
