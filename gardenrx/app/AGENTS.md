<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Local preview & screenshots (for visual/UI work)

To see the app rendered with **real data** (the UI lives in the data-filled
screens, not the empty shell), run it locally against the production Supabase and
screenshot `localhost`. Hitting the public Vercel URL through a sandboxed agent
proxy does **not** work for a headless browser (the proxy re-terminates TLS and
rejects browser/HTTP-2 traffic — `ERR_CONNECTION_CLOSED`). `localhost` bypasses
the proxy, so that's the path that works.

### 1. Get the public Supabase creds

`NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` are public and
inlined into the production JS bundle. Extract them (don't hardcode the key in
git) and write `.env.local` (already git-ignored):

```bash
html=$(curl -s https://garden-rx.vercel.app/)
for c in $(echo "$html" | grep -oE '/_next/static/[^"]+\.js' | sort -u); do
  body=$(curl -s "https://garden-rx.vercel.app$c")
  echo "$body" | grep -oE 'https://[a-z0-9]+\.supabase\.co' | head -1
  echo "$body" | grep -oE 'sb_publishable_[A-Za-z0-9_-]+' | head -1   # or eyJ... legacy anon JWT
done
# write src .env.local:
#   NEXT_PUBLIC_SUPABASE_URL=...
#   NEXT_PUBLIC_SUPABASE_ANON_KEY=...
```

### 2. Run the dev server so its server-side Supabase fetches traverse the proxy

Node's built-in fetch needs `NODE_USE_ENV_PROXY=1` (Node ≥ 22.21) and must trust
the proxy CA via `NODE_EXTRA_CA_CERTS`:

```bash
NODE_USE_ENV_PROXY=1 NODE_EXTRA_CA_CERTS=/root/.ccr/ca-bundle.crt npm run dev
# verify: curl -s localhost:3000/ | grep -o 'verdict'   (expect data, not an error)
```

### 3. Screenshot localhost with the pre-installed Chromium

Use the global Playwright (`/opt/node22/lib/node_modules/playwright`) + the
pre-installed browser. Launch with **no proxy** (localhost is direct):

```js
import pkg from '/opt/node22/lib/node_modules/playwright/index.js';
const { chromium } = pkg;
const b = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox'],
});
const page = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
await page.goto('http://127.0.0.1:3000/', { waitUntil: 'networkidle' });
await page.screenshot({ path: 'shot.png', fullPage: true });
```

### Tips & gotchas

- **Themes:** there are three — `light`, `medium` (neutral gray), `dark`. Toggle
  in a screenshot via `page.evaluate(t => document.documentElement.setAttribute('data-theme', t), 'dark')`.
- **Garden map:** the `<canvas>` is sized at runtime from its container and does
  **not** paint in a headless screenshot (it stays the default 300×150) — this is
  a headless-capture artifact, not a production bug. Don't "fix" the working map
  based on a blank screenshot.
- **`position: fixed` elements** (e.g. the mobile bottom nav) render at their
  initial position in a `fullPage` screenshot — not a real overlap. The mobile
  nav already reserves space via `.page { padding-bottom }` + `safe-area-inset`.
- **Routes:** `/` (Today), `/crops`, `/crops/<id>`, `/garden`, `/weather`,
  `/products`, `/inventory`, `/harvest`, `/tank`.
