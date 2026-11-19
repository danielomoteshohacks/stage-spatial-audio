import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

// GitHub Pages serves the site from /<repo>/. The deploy workflow sets BASE_PATH;
// local dev and tests run from the root.
export default defineConfig({
  base: process.env.BASE_PATH ?? "/",
  plugins: [svelte()],
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
