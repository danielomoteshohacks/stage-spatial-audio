import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [svelte()],
  build: {
    target: "es2020",
    // The size budget is checked on the gzipped output by scripts/check-size.mjs.
    reportCompressedSize: true,
  },
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
