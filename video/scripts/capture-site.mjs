// Capture the receipt site's real pages for the video: full-page screenshots at 2x and the
// boxes of every section, card, table, paper receipt, badge and diff, so scenes can push in
// on real UI instead of re-drawing it.
// Usage, from video/: node scripts/capture-site.mjs ../build/site public/captures/site
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [siteDir, outDir] = process.argv.slice(2);
if (!siteDir || !outDir) {
  console.error("usage: node scripts/capture-site.mjs SITE_DIR OUT_DIR");
  process.exit(2);
}

const pages = {
  index: "index.html",
  featured_run: "run/pyfilesystem__pyfilesystem2-462.html",
  featured_receipt: "receipt/pyfilesystem__pyfilesystem2-462.html",
  cold_open_run: "run/azure__walinuxagent-638.html",
};

const SELECTORS = "section, .card, table, .paper, .badge, pre.diff, .comparison, .metrics, h1, h2, h3";

await mkdir(outDir, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
for (const [name, path] of Object.entries(pages)) {
  const page = await context.newPage();
  await page.goto(pathToFileURL(resolve(siteDir, path)).href, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: resolve(outDir, `${name}.png`), fullPage: true });
  const boxes = await page.$$eval(SELECTORS, (elements) =>
    elements.map((el, index) => {
      const r = el.getBoundingClientRect();
      return {
        index,
        tag: el.tagName.toLowerCase(),
        className: el.className || "",
        text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 120),
        x: r.x + window.scrollX,
        y: r.y + window.scrollY,
        width: r.width,
        height: r.height,
      };
    }),
  );
  const size = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }));
  await writeFile(resolve(outDir, `${name}.json`), JSON.stringify({ page: path, scale: 2, size, boxes }, null, 2) + "\n");
  console.log(`${name}: ${size.width}x${size.height} css px, ${boxes.length} boxes`);
  await page.close();
}
await browser.close();
