// Fails the build when the first load (index.html plus every script, stylesheet and preloaded
// asset it references) exceeds the budget, gzipped. Gzip rather than brotli because it is the
// encoding every host serves, so the number is the conservative one.
import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const BUDGET_BYTES = 500 * 1024;
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
let total = 0;
for (const ref of refs) {
  const size = gzipSync(readFileSync(join(dist, ref)), { level: 9 }).length;
  total += size;
  console.log(`${(size / 1024).toFixed(1).padStart(8)} KB  ${ref}`);
}
const verdict = total <= BUDGET_BYTES ? "within" : "OVER";
console.log(`${(total / 1024).toFixed(1).padStart(8)} KB  first load, gzipped (${verdict} the ${BUDGET_BYTES / 1024} KB budget)`);
if (total > BUDGET_BYTES) process.exit(1);
