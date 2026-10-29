import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    // Component tests opt into a DOM with `// @vitest-environment happy-dom`.
    environment: "node",
  },
});
