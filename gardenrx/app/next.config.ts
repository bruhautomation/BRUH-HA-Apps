import type { NextConfig } from 'next';

// Inside Home Assistant the app lives under this install's ingress path,
// which nobody knows when the image is built. The image is built with
// GARDENRX_BASE_PATH set to a placeholder, and the add-on writes the real
// path over it at start (gardenrx/gateway/prepare-base.mjs). Unset,
// as in `npm run dev`, the app is served at `/`.
const basePath = process.env.GARDENRX_BASE_PATH || '';

const nextConfig: NextConfig = {
  basePath: basePath || undefined,
  // The add-on runs `node server.js` out of a standalone build rather than
  // carrying node_modules into the image.
  output: 'standalone',
  env: {
    NEXT_PUBLIC_BASE_PATH: basePath,
  },
};

export default nextConfig;
