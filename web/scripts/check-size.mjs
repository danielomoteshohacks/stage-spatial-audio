// Fails the build when the first load exceeds the budget, gzipped: index.html, every script,
// stylesheet and asset it references, and the woff2 fonts those stylesheets reference (the
// browser fetches them for the first paint). Lazy chunks (stage view, blind test, palette) are
// listed but not counted. Gzip rather than brotli: every host serves it, so the number is the
// conservative one.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const BUDGET_BYTES = 250 * 1024;
const dist = new URL("../dist/", import.meta.url).pathname;
const html = readFileSync(join(dist, "index.html"), "utf8");
const refs = new Set(["index.html"]);
for (const m of html.matchAll(/(?:src|href)="\/?([^"?#]+)"/g)) {
  const ref = m[1];
  if (/^(https?:)?\/\//.test(ref)) continue;
  try {
    if (statSync(join(dist, ref)).isFile()) refs.add(ref);
  } catch {
    // A reference to something not in dist (an external link) is not part of the first load.
  }
}
for (const ref of [...refs].filter((r) => r.endsWith(".css"))) {
  const css = readFileSync(join(dist, ref), "utf8");
  for (const m of css.matchAll(/url\(\/?([^)]+\.woff2)\)/g)) refs.add(m[1].replace(/^\.\//, "assets/"));
}
let total = 0;
for (const ref of refs) {
  const size = gzipSync(readFileSync(join(dist, ref)), { level: 9 }).length;
  total += size;
  console.log(`${(size / 1024).toFixed(1).padStart(8)} KB  ${ref}`);
}
for (const f of readdirSync(join(dist, "assets")).filter((f) => f.endsWith(".js") && !refs.has(`assets/${f}`))) {
  const size = gzipSync(readFileSync(join(dist, "assets", f)), { level: 9 }).length;
  console.log(`${(size / 1024).toFixed(1).padStart(8)} KB  assets/${f} (lazy, not counted)`);
}
const verdict = total <= BUDGET_BYTES ? "within" : "OVER";
console.log(`${(total / 1024).toFixed(1).padStart(8)} KB  first load, gzipped (${verdict} the ${BUDGET_BYTES / 1024} KB budget)`);
if (total > BUDGET_BYTES) process.exit(1);
