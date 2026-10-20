import type { NextConfig } from 'next';

// Inside Home Assistant the app lives under this install's ingress path,
// which nobody knows when the image is built. The image is built with
// GARDENRX_BASE_PATH set to a placeholder, and the add-on writes the real
// path over it at start (gardenrx/gateway/prepare-base.mjs). Unset,
// as in `npm run dev`, the app is served at `/`.
const basePath = process.env.GARDENRX_BASE_PATH || '';

const nextConfig: NextConfig = {
  basePath: basePath || undefined,
  // Home Assistant answers an ingress panel only under `<ingress path>/...`:
  // the path with no slash after the token is a 404 from Core, before it
  // ever reaches the add-on. With no trailing slash every Link to `/` (the
  // Today page) pointed at exactly that path. So every page URL Next writes
  // ends in a slash, and neither form is redirected to the other: `/api/*`
  // is called without one, by the browser and by the integration, and a
  // 308 there would be a second round trip on every call.
  trailingSlash: true,
  skipTrailingSlashRedirect: true,
  // The add-on runs `node server.js` out of a standalone build rather than
  // carrying node_modules into the image.
  output: 'standalone',
  env: {
    NEXT_PUBLIC_BASE_PATH: basePath,
  },
};

export default nextConfig;
