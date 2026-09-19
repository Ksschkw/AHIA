/**
 * A customer builds a list as a cart, and sends it as a picture.
 *
 * What the product owner described: search the shop, add what is needed, ask for what is not there with
 * the price blank, read it under the trader's own headings, and send it as an image rather than a wall
 * of text - because a typed list arrives truncated and cannot be forwarded as a list.
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
const trader = await browser.newPage();
await trader.setViewport({ width: 1440, height: 900 });
let current = trader;
const failures = [];

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await current.screenshot({ path: resolve(OUTPUT, `cart-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    failures.push(name);
  }
}

let shop = { slug: "", tenantId: "" };

await step("a shop with headings and stock", async () => {
  await trader.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await trader.waitForSelector("#first_name", { timeout: 40000 });
  await trader.type("#first_name", "Ada");
  await trader.type("#last_name", "Obi");
  await trader.type("#phone", `0819${String(stamp).slice(-7)}`);
  await trader.type("#password", "Cart-Check-2026");
  await trader.type("#confirm_password", "Cart-Check-2026");
  await trader.click('button[type="submit"]');
  await trader.waitForSelector("#business-name", { timeout: 40000 });
  await trader.type("#business-name", `Alaba Cart ${stamp % 1000}`);
  await trader.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await trader.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });

  shop = await trader.evaluate(async () => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    const tenant = tenants[0];
    // A grade, with models under it - the way a screenguard shelf is arranged.
    const group = await (
      await fetch(`/api/v1/tenants/${tenant.id}/categories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "21D" }),
      })
    ).json();
    for (const [name, price] of [
      ["Screenguard - Hot 8", "500.00"],
      ["Screenguard - Camon 30", "400.00"],
      ["Privacy Glass - iPhone 13", "1500.00"],
    ]) {
      const created = await fetch(`/api/v1/tenants/${tenant.id}/products`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          selling_price: price,
          ...(name.startsWith("Screenguard") ? { category_id: group.id } : {}),
        }),
      });
      if (!created.ok) throw new Error(`creating ${name}: ${await created.text()}`);
      const product = await created.json();
      await fetch(`/api/v1/tenants/${tenant.id}/inventory/${product.id}/receipts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quantity: "50.000", note: "Opening" }),
      });
      // Published, or the shop's catalogue is empty and the customer has nothing to search.
      const published = await fetch(
        `/api/v1/tenants/${tenant.id}/products/${product.id}/publish`,
        { method: "POST" },
      );
      if (!published.ok) throw new Error(`publishing ${name}: ${await published.text()}`);
    }
    await fetch(`/api/v1/tenants/${tenant.id}/storefront/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ headline: "Screenguards", contact_phone: "+2348031234567" }),
    });
    return { slug: tenant.slug, tenantId: tenant.id };
  });
});

await step("the customer searches, adds, and asks for the rest", async () => {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  current = page;
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  await page.goto(`${APP_URL}/list/${shop.slug}`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#list_search", { timeout: 20000 });

  await page.type("#list_search", "21D");
  await page.waitForFunction(() => document.body.innerText.includes("Screenguard - Hot 8"), {
    timeout: 10000,
  });
  await page.evaluate(() => {
    const control = [...document.querySelectorAll("button")].find(
      (candidate) => candidate.getAttribute("aria-label") === "Add Screenguard - Hot 8",
    );
    control?.click();
  });

  await page.type("#list_search", "Privacy");
  await page.waitForFunction(() => document.body.innerText.includes("Privacy Glass"), {
    timeout: 10000,
  });
  await page.evaluate(() => {
    const control = [...document.querySelectorAll("button")].find(
      (candidate) => candidate.getAttribute("aria-label") === "Add Privacy Glass - iPhone 13",
    );
    control?.click();
  });

  // **The walk down the tree**, which is the shape the product owner described: pick the kind, see what
  // it prices differently, and type anything else under that kind so it takes the kind's price.
  await page.evaluate(() => {
    const chip = [...document.querySelectorAll("button")].find(
      (candidate) => candidate.textContent?.trim() === "Screenguard",
    );
    chip?.click();
  });
  await page.waitForFunction(() => document.body.innerText.includes("21D"), { timeout: 10000 });
  await page.evaluate(() => {
    const chip = [...document.querySelectorAll("button")].find(
      (candidate) => candidate.textContent?.trim() === "21D",
    );
    chip?.click();
  });
  const walked = await page.evaluate(() => document.body.innerText);
  console.log(`      the walk shows: ${walked.match(/21D[^\n]*/)?.[0] ?? "(nothing)"}`);
  if (!walked.includes("Everything")) throw new Error("the headings are not offered");
  await page.screenshot({ path: resolve(OUTPUT, "cart-tree-mobile.png") });

  // Something the shop has not got, with no price - the line that sends people back to paper.
  await page.type("#list_asked", "Universal metal frame, any brand");
  // The Add beside the box that was typed into, not the first Add on the page: the headings added their
  // own Add buttons, and "the first one whose text is Add" stopped meaning what it used to.
  await page.evaluate(() => {
    const input = document.querySelector("#list_asked");
    const row = input?.parentElement;
    const control = [...(row?.querySelectorAll("button") ?? [])].find(
      (candidate) => candidate.textContent?.trim() === "Add",
    );
    control?.click();
  });

  await page.screenshot({ path: resolve(OUTPUT, "cart-mobile.png") });
  const text = await page.evaluate(() => document.body.innerText);
  console.log(`      grouped under: ${text.includes("21D") ? "21D" : "(no heading)"}`);
  console.log(`      reads: ${text.match(/\\d+ items on your list/)?.[0] ?? "(no count)"} | ${text.match(/[₦][^\\n]*/)?.[0] ?? ""}`);
  if (!text.includes("price to be confirmed")) {
    throw new Error("a line the shop has not got does not say its price is to be confirmed");
  }
  if (!text.includes("3 items on your list")) throw new Error("the list does not count three items");

  await page.type("#list_phone", "08029876543");
  await page.type("#list_name", "Toba");
  await page.evaluate(() => {
    const control = [...document.querySelectorAll("button")].find((candidate) =>
      candidate.textContent?.trim().startsWith("Send my list"),
    );
    control?.click();
  });
  await page.waitForFunction(() => document.body.innerText.includes("has reached"), {
    timeout: 30000,
  });
  await page.screenshot({ path: resolve(OUTPUT, "cart-sent.png") });

  // The picture, which is what actually gets sent.
  const drawn = await page.evaluate(() => {
    const image = document.querySelector("img[alt='Your list']");
    return image ? image.src : "";
  });
  if (!drawn.startsWith("blob:")) throw new Error("no picture of the list was produced");
  const hasShare = await page.evaluate(() =>
    [...document.querySelectorAll("button")].some((candidate) =>
      candidate.textContent?.includes("Send the list on WhatsApp"),
    ),
  );
  if (!hasShare) throw new Error("no way to send the picture");
  console.log(`      picture produced: ${drawn.slice(0, 12)}...`);
  current = trader;
  await context.close();
});

await step("the trader receives the counts and the heading", async () => {
  const list = await trader.evaluate(async (tenantId) => {
    const response = await fetch(`/api/v1/tenants/${tenantId}/requests`);
    return response.json();
  }, shop.tenantId);
  const first = list[0];
  if (!first) throw new Error("the shop received no list");
  console.log(
    `      received: ${first.lines.length} lines, unpriced=${first.unpriced_line_count}, ` +
      `phone=${first.customer_phone}, headings=${JSON.stringify(first.lines.map((l) => l.note))}`,
  );
  if (first.lines.length !== 3) throw new Error(`expected 3 lines, got ${first.lines.length}`);
  if (first.customer_phone !== "+2348029876543") throw new Error("the number was not canonicalised");
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
