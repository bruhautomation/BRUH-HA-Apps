import { defineConfig } from "astro/config";
import preact from "@astrojs/preact";

// Static build only — the FastAPI server serves the bundle, no Astro SSR.
export default defineConfig({
  integrations: [preact()],
  output: "static",
  build: {
    assets: "assets",
  },
  vite: {
    build: {
      // Inline assets below this size into the HTML so the FastAPI mount
      // surface stays simple. Bigger assets go to /assets/.
      assetsInlineLimit: 4096,
    },
  },
});
