/**
 * The home-screen icons, rendered from the mark the product already has.
 *
 * The first version of these was an **invented glyph** - a letter A drawn by hand - which is a second brand
 * mark nobody asked for, sitting beside the one in `app/icon.svg` that every screen already shows. The lesson
 * is the one this project keeps teaching: look for the thing that exists before making a new one.
 *
 * Chrome renders the SVG, so the icons are the real mark at size and a build needs no design tool.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import puppeteer from "puppeteer-core";

// The mark carries its own 24px size, which is right in a header and wrong when it is being scaled up: left
// as it is, it renders as a small tile in the corner of a large canvas - which is exactly what the first
// render produced.
const mark = readFileSync(resolve("app", "icon.svg"), "utf8")
  .replace(/width="[^"]*"/, 'width="100%"')
  .replace(/height="[^"]*"/, 'height="100%"');
const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();

/**
 * Draw the mark at a size.
 *
 * `inset` is the fraction of the canvas kept clear around it, which is what a **maskable** icon needs: a
 * launcher crops it to a shape of its own choosing, and anything outside the safe zone can be cut off.
 */
async function draw(size, inset, background, path) {
  await page.setViewport({ width: size, height: size, deviceScaleFactor: 1 });
  await page.setContent(`
    <html><body style="margin:0;width:${size}px;height:${size}px;background:${background};
      display:flex;align-items:center;justify-content:center">
      <div style="width:${(size * (1 - inset * 2)).toFixed(2)}px;height:${(size * (1 - inset * 2)).toFixed(2)}px">
        ${mark}
      </div>
    </body></html>
  `);
  const bytes = await page.screenshot({ omitBackground: background === "transparent" });
  writeFileSync(path, bytes);
  console.log(`      ${path} at ${size}px, inset ${inset}`);
}

await draw(192, 0, "transparent", resolve("public", "icon-192.png"));
await draw(512, 0, "transparent", resolve("public", "icon-512.png"));
// Maskable: the product's own green fills the tile, and the mark sits inside the safe zone.
await draw(512, 0.14, "#0b5d3b", resolve("public", "icon-maskable-512.png"));

await browser.close();
