/**
 * Where the app is mounted.
 *
 * Home Assistant serves an add-on's panel under `/api/hassio_ingress/<token>/`,
 * and the token is this install's, so it cannot be known when the image is
 * built. The image is built with a placeholder in its place (Next's
 * `basePath` and this variable), and the add-on's start script writes this
 * install's ingress path over the placeholder before the server starts —
 * see gardenrx/gateway/prepare-base.mjs. Outside Home Assistant
 * (`npm run dev`) both are empty and the app is served at `/`.
 *
 * Next's <Link> and router add the base path themselves; a plain `fetch`,
 * `<a href>` or `<img src>` does not, which is what `withBase` is for.
 */

export const BASE_PATH: string = process.env.NEXT_PUBLIC_BASE_PATH ?? '';

export function withBase(path: string): string {
  return path.startsWith('/') && !path.startsWith('//') ? BASE_PATH + path : path;
}
