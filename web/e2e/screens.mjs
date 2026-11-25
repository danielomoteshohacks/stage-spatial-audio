// Screenshots of every screen in both themes, on a phone profile and one desktop size, against the
// mock backend and a production build:
//   (cd web && npm run build) && node e2e/mock-server.mjs & node e2e/screens.mjs
// Writes JPEGs to ../docs/screens. Remote cover art is blocked, so the tiles show their gradients
// (the same ones used whenever art cannot be read). The phone profile is a mid-range Android: 412 x
// 915 CSS pixels at 2x. Separately, `--profile` loads the home screen under 4x CPU slowdown and a
// slow-4G network and prints the paint timings, which is the mobile check of decision 0029.
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const here = dirname(fileURLToPath(import.meta.url));
const OUT = join(here, "..", "..", "docs", "screens");
const FIX = join(here, "fixture");
const PORT = 4318;
mkdirSync(OUT, { recursive: true });

const preview = spawn("npx", ["vite", "preview", "--host", "127.0.0.1", "--port", String(PORT), "--strictPort"], { cwd: join(here, ".."), stdio: "ignore" });
const base = `http://127.0.0.1:${PORT}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
for (let i = 0; i < 60; i++) {
  try { if ((await fetch(base)).ok) break; } catch { await sleep(500); }
}

const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const profile = process.argv.includes("--profile");

async function newPage(theme, size) {
  const ctx = await browser.newContext({
    viewport: size,
    deviceScaleFactor: size.width < 600 ? 2 : 1.5,
    isMobile: size.width < 600,
    hasTouch: size.width < 600,
    userAgent: size.width < 600 ? "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36" : undefined,
    colorScheme: theme,
  });
  const page = await ctx.newPage();
  await page.route(/api\.openverse\.org|jamendo\.com|archive\.org/, (r) => r.abort());
  return { ctx, page };
}

const shot = (page, theme, name) => page.screenshot({ path: join(OUT, `${theme}-${name}.jpg`), type: "jpeg", quality: 82 });

async function run(theme, size, tag) {
  const { ctx, page } = await newPage(theme, size);
  const go = async (path = "") => {
    await page.goto(`${base}/${path}${path.includes("?") ? "&" : "?"}theme=${theme}`, { waitUntil: "networkidle" });
  };
  await go();
  await page.waitForSelector(".shelf", { timeout: 15000 });
  await shot(page, theme, `${tag}-home`);

  await page.getByRole("button", { name: "Browse" }).first().click();
  await page.waitForSelector(".genre");
  await shot(page, theme, `${tag}-browse`);
  await page.locator(".genre").nth(1).click();
  await page.waitForSelector(".rows li");
  await shot(page, theme, `${tag}-genre`);

  await page.getByRole("button", { name: "Create" }).first().click();
  await shot(page, theme, `${tag}-create`);
  await page.locator('input[type="file"]').setInputFiles(join(FIX, "original.wav"));
  await page.waitForSelector(".form");
  await shot(page, theme, `${tag}-create-options`);

  // A catalogue track: play it and wait until the whole render has arrived.
  await page.getByRole("button", { name: "Home" }).first().click();
  await page.waitForSelector(".shelf");
  await page.locator(".shelf .card").first().click();
  await page.waitForSelector(".np");
  await page.waitForFunction(() => /SoundStage spatial render|Spatial is rendering/.test(document.querySelector(".status")?.textContent || ""), null, { timeout: 20000 });
  await sleep(3500);
  await shot(page, theme, `${tag}-player`);
  await page.getByRole("tab", { name: "Queue" }).click();
  await shot(page, theme, `${tag}-player-queue`);
  await page.getByRole("tab", { name: "About" }).click();
  await shot(page, theme, `${tag}-player-about`);
  await page.getByRole("tab", { name: "Stage" }).click();
  await page.getByRole("button", { name: "Original", exact: true }).click();
  await sleep(300);
  await shot(page, theme, `${tag}-player-original`);

  await page.getByRole("button", { name: "Fit to my ears" }).click();
  await page.getByRole("button", { name: "Start" }).waitFor();
  await shot(page, theme, `${tag}-calibration`);
  await page.getByRole("button", { name: "Close" }).last().click();
  await page.getByRole("button", { name: "Close the player" }).click();

  await page.getByRole("button", { name: "Library" }).first().click();
  await sleep(500);
  await shot(page, theme, `${tag}-library`);

  await page.getByRole("button", { name: "Credits" }).first().click().catch(async () => {
    await page.getByRole("button", { name: "Home" }).first().click();
  });
  await sleep(300);
  await shot(page, theme, `${tag}-credits`);

  // The blind test, with the reference slot. The song played above is still in memory.
  await page.getByRole("button", { name: "Listening test" }).click();
  await page.waitForSelector(".test");
  await sleep(300);
  await shot(page, theme, `${tag}-listening-test`);
  await ctx.close();
}

async function measure() {
  const { ctx, page } = await newPage("light", { width: 412, height: 915 });
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
  await page.addInitScript(() => {
    window.__lcp = 0;
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lcp = e.startTime; }).observe({ type: "largest-contentful-paint", buffered: true });
    window.__long = 0;
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__long += Math.max(0, e.duration - 50); }).observe({ type: "longtask", buffered: true });
  });
  const t0 = Date.now();
  await page.goto(`${base}/`, { waitUntil: "load" });
  await page.waitForSelector(".shelf", { timeout: 60000 });
  const shelfMs = Date.now() - t0;
  await sleep(1500);
  const m = await page.evaluate(() => ({
    fcp: Math.round(performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? 0),
    lcp: Math.round(window.__lcp),
    tbt: Math.round(window.__long),
    transferKB: Math.round(performance.getEntriesByType("resource").reduce((a, r) => a + (r.transferSize || 0), 0) / 1024),
  }));
  console.log(JSON.stringify({ profile: "mid-range Android, 4x CPU, slow 4G", ...m, shelvesVisibleMs: shelfMs }));
  await ctx.close();
}

try {
  if (profile) await measure();
  else {
    for (const theme of ["light", "dark"]) {
      await run(theme, { width: 412, height: 915 }, "phone");
      await run(theme, { width: 1280, height: 800 }, "desktop");
    }
    console.log("screens written to docs/screens");
  }
} finally {
  await browser.close();
  preview.kill();
}
