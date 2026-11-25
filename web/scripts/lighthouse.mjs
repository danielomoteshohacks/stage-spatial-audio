// Lighthouse on the production build (mobile emulation, Lighthouse's default), failing when
// performance or accessibility scores under 0.9. Run after `npm run build`:
//   CHROME_PATH=/path/to/chrome node scripts/lighthouse.mjs
import { spawn, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

const MIN = 0.9;
const RUNS = 3;
// Bound to 127.0.0.1 explicitly: on CI runners "localhost" resolves to IPv6 first, and Chrome
// then shows an error interstitial for http://127.0.0.1.
const preview = spawn("npx", ["vite", "preview", "--host", "127.0.0.1", "--port", "4317", "--strictPort"], { stdio: "ignore" });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  let ready = false;
  for (let i = 0; i < 60 && !ready; i++) {
    try {
      ready = (await fetch("http://127.0.0.1:4317/")).ok;
    } catch {
      await wait(500);
    }
  }
  if (!ready) {
    console.error("the preview server did not answer on http://127.0.0.1:4317/");
    process.exit(1);
  }
  // Three runs and the median per category, as Lighthouse CI does by default: one run on a
  // shared CI machine varies by 0.1 or more (0.97 and 0.85 on the same build).
  // Both themes: light is the default, dark is what a listener with a dark system gets.
  for (const theme of ["light", "dark"]) {
  const runs = [];
  for (let i = 0; i < RUNS; i++) {
    const out = `lighthouse-report-${theme}-${i}.json`;
    const run = spawnSync("npx", ["-y", "lighthouse@12.8.2", `http://127.0.0.1:4317/?theme=${theme}`, "--quiet",
      "--chrome-flags=--headless=new --no-sandbox", "--only-categories=performance,accessibility,best-practices",
      "--output=json", `--output-path=${out}`], { stdio: "inherit" });
    if (run.status !== 0) process.exit(run.status ?? 1);
    const report = JSON.parse(readFileSync(out, "utf8"));
    runs.push(Object.fromEntries(Object.entries(report.categories).map(([k, v]) => [k, v.score])));
  }
  const median = (xs) => [...xs].sort((p, q) => p - q)[Math.floor(xs.length / 2)];
  const scores = Object.fromEntries(Object.keys(runs[0]).map((k) => [k, median(runs.map((r) => r[k]))]));
  console.log(`Lighthouse (mobile, ${theme}), runs:`, runs);
  console.log(`Lighthouse (mobile, ${theme}), median:`, scores);
  const failing = ["performance", "accessibility"].filter((k) => scores[k] < MIN);
  if (failing.length) {
    console.error(`${theme} is below ${MIN}: ${failing.join(", ")}`);
    process.exit(1);
  }
  }
} finally {
  preview.kill();
}
