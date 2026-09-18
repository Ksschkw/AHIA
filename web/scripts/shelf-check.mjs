/**
 * The shelf, with stock on it.
 *
 * The screen a trader uses twenty times a day, judged on what it has to do: let him recognise his own
 * goods, read a price and a count without hunting, and act with a thumb. It is photographed at the two
 * sizes his day happens at, and every row is measured rather than eyeballed.
 */
import { resolve } from "node:path";
import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const OUTPUT = resolve(process.cwd(), "..", ".review");
const stamp = Date.now();

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
const failures = [];

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await page.screenshot({ path: resolve(OUTPUT, `shelf-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    failures.push(name);
  }
}

await step("a shelf with things on it", async () => {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0818${String(stamp).slice(-7)}`);
  await page.type("#password", "Shelf-Check-2026");
  await page.type("#confirm_password", "Shelf-Check-2026");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40000 });
  await page.type("#business-name", `Alaba Shelf ${stamp % 1000}`);
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });

  await page.evaluate(async () => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    const tenant = tenants[0];
    const catalogue = [
      ["21D Screenguard - Hot 8", "500.00", "40.000"],
      ["Privacy Glass - iPhone 13 Pro Max", "1500.00", "12.000"],
      ["Ceramic Matte - Camon 30", "400.00", "3.000"],
      ["Charging cord - Type C braided 2m", "1200.00", "0.000"],
      ["Camera glass - Samsung A54", "350.00", "25.000"],
    ];
    for (const [name, price, quantity] of catalogue) {
      const created = await fetch(`/api/v1/tenants/${tenant.id}/products`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, selling_price: price }),
      });
      // **Every step asserts its own answer.** The previous version ignored all of this, so a wrong
      // stock path answered 404 in silence and the check went on to photograph an empty shelf and call
      // it a shelf. A setup that cannot fail is a setup that proves nothing.
      if (!created.ok) {
        throw new Error(`creating ${name} answered ${created.status}: ${await created.text()}`);
      }
      const product = await created.json();
      if (Number(quantity) > 0) {
        const received = await fetch(
          `/api/v1/tenants/${tenant.id}/inventory/${product.id}/receipts`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ quantity, note: "Opening stock" }),
          },
        );
        if (!received.ok) {
          throw new Error(`stocking ${name} answered ${received.status}: ${await received.text()}`);
        }
      }
    }
    // And the shelf is only judged once the API agrees there is something on it.
    const shelf = await (await fetch(`/api/v1/tenants/${tenant.id}/products`)).json();
    if (shelf.length !== catalogue.length) {
      throw new Error(`the catalogue holds ${shelf.length} of ${catalogue.length} products`);
    }
    return tenant.id;
  });
});

await step("every size shows the same shelf", async () => {
  for (const [label, viewport] of [
    ["mobile", { width: 390, height: 844, isMobile: true, hasTouch: true }],
    ["desktop", { width: 1440, height: 900 }],
  ]) {
    await page.setViewport(viewport);
    await page.goto(`${APP_URL}/app`, { waitUntil: "networkidle2" });
    await page.waitForFunction(() => document.body.innerText.includes("21D Screenguard"), {
      timeout: 30000,
    });
    await page.screenshot({ path: resolve(OUTPUT, `shelf-${label}.png`) });

    const facts = await page.evaluate(() => {
      const rows = [...document.querySelectorAll("ul li")].filter((row) =>
        row.textContent?.includes("Screenguard"),
      );
      const row = rows[0];
      const controls = [...(row?.querySelectorAll("button") ?? [])];
      const box = row?.getBoundingClientRect();
      const short = controls
        .map((control) => control.getBoundingClientRect().height)
        .filter((height) => height > 0);
      return {
        rowHeight: box ? Math.round(box.height) : 0,
        controls: controls.length,
        shortestControl: short.length ? Math.round(Math.min(...short)) : 0,
        hasPhotoSlot: Boolean(row?.querySelector("img, span")),
        overflow: document.documentElement.scrollWidth > window.innerWidth,
        text: row?.innerText.replace(/\n/g, " | ") ?? "",
      };
    });
    console.log(
      `      ${label}: row ${facts.rowHeight}px, ${facts.controls} controls, ` +
        `smallest ${facts.shortestControl}px, overflow=${facts.overflow}`,
    );
    console.log(`        reads: ${facts.text}`);

    // The order a phone user actually experiences: the shelf he works from every day must come before
    // the tiles, not after them. A trader should not scroll past what he touches least.
    const order = await page.evaluate(() => {
      const heading = [...document.querySelectorAll("h2, h3, div")].find(
        (node) => node.textContent?.trim().startsWith("The shelf"),
      );
      const tile = [...document.querySelectorAll("button")].find((node) =>
        node.textContent?.includes("Record a sale"),
      );
      if (!heading || !tile) return null;
      return {
        shelfTop: Math.round(heading.getBoundingClientRect().top + window.scrollY),
        tileTop: Math.round(tile.getBoundingClientRect().top + window.scrollY),
      };
    });
    if (!order) throw new Error("could not find the shelf or the tiles to compare");
    console.log(`        shelf at ${order.shelfTop}px, tiles at ${order.tileTop}px`);
    if (order.shelfTop > order.tileTop) {
      throw new Error("the shelf is below the tiles");
    }
    if (facts.overflow) throw new Error("the shelf is wider than the phone");
    if (facts.shortestControl < 36) {
      throw new Error(`a control is only ${facts.shortestControl}px tall, too small for a thumb`);
    }
    if (facts.controls < 3) {
      throw new Error("a row does not offer the photo, the sale and the shop toggle");
    }
  }
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
