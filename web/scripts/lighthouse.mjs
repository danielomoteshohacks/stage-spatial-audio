// Lighthouse on the production build (mobile emulation, Lighthouse's default), failing when
// performance or accessibility scores under 0.9. Run after `npm run build`:
//   CHROME_PATH=/path/to/chrome node scripts/lighthouse.mjs
import { spawn, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

const MIN = 0.9;
const preview = spawn("npx", ["vite", "preview", "--port", "4317", "--strictPort"], { stdio: "ignore" });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  for (let i = 0; i < 30; i++) {
    try {
      if ((await fetch("http://127.0.0.1:4317/")).ok) break;
    } catch {
      await wait(500);
    }
  }
  const out = "lighthouse-report.json";
  const run = spawnSync("npx", ["-y", "lighthouse@12.8.2", "http://127.0.0.1:4317/", "--quiet",
    "--chrome-flags=--headless=new --no-sandbox", "--only-categories=performance,accessibility,best-practices",
    "--output=json", `--output-path=${out}`], { stdio: "inherit" });
  if (run.status !== 0) process.exit(run.status ?? 1);
  const report = JSON.parse(readFileSync(out, "utf8"));
  const scores = Object.fromEntries(Object.entries(report.categories).map(([k, v]) => [k, v.score]));
  console.log("Lighthouse (mobile):", scores);
  const failing = ["performance", "accessibility"].filter((k) => scores[k] < MIN);
  if (failing.length) {
    console.error(`below ${MIN}: ${failing.join(", ")}`);
    process.exit(1);
  }
} finally {
  preview.kill();
}
