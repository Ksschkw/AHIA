/**
 * A customer builds a list and sends it.
 *
 * The claim being tested is the product's whole reason to exist: a list that would take twenty minutes
 * of "bring Hot 8 five, bring XR five" across a counter is built here in one sitting, arrives at the
 * shop, and is priced by the shop rather than guessed at by the customer.
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
const failures = [];

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    // Whichever page is in front of us is the one worth looking at, and a screenshot of the trader's
    // screen when the customer's failed is a picture of the wrong thing entirely.
    const pages = await browser.pages();
    const visible = pages[pages.length - 1] ?? trader;
    await visible.screenshot({ path: resolve(OUTPUT, `list-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    console.log((await visible.evaluate(() => document.body.innerText)).slice(0, 700));
    failures.push(name);
  }
}

let shop = { slug: "", tenantId: "" };

await step("a shop is open with items on the shelf", async () => {
  await trader.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await trader.waitForSelector("#first_name", { timeout: 40000 });
  await trader.type("#first_name", "Ada");
  await trader.type("#last_name", "Obi");
  await trader.type("#phone", `0813${String(stamp).slice(-7)}`);
  await trader.type("#password", "List-Check-2026");
  await trader.type("#confirm_password", "List-Check-2026");
  await trader.click('button[type="submit"]');
  await trader.waitForSelector("#business-name", { timeout: 40000 });
  await trader.type("#business-name", `Alaba Lists ${stamp % 1000}`);
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
    await fetch(`/api/v1/tenants/${tenant.id}/storefront/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ headline: "Screenguards", contact_phone: "+2348031234567" }),
    });
    for (const [name, price] of [
      ["21D Screenguard - Hot 8", "500.00"],
      ["Privacy Glass - iPhone 13", "1500.00"],
      ["Ceramic - Camon 30", "400.00"],
    ]) {
      const created = await (
        await fetch(`/api/v1/tenants/${tenant.id}/products`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, selling_price: price }),
        })
      ).json();
      await fetch(`/api/v1/tenants/${tenant.id}/products/${created.id}/publish`, {
        method: "POST",
      });
    }
    return { slug: tenant.slug, tenantId: tenant.id };
  });
  if (!shop.slug) throw new Error("the shop has no address");
});

await step("a customer builds the list", async () => {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  await page.goto(`${APP_URL}/list/${shop.slug}`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => document.body.innerText.includes("How many of each?"), {
    timeout: 20000,
  });

  // Twenty of one, two of another - the counts a customer actually says out loud.
  const raise = async (itemName, times) => {
    for (let index = 0; index < times; index += 1) {
      const clicked = await page.evaluate((wanted) => {
        const row = [...document.querySelectorAll("li")].find((candidate) =>
          candidate.innerText.includes(wanted),
        );
        const button = [...(row?.querySelectorAll("button") ?? [])].find((candidate) =>
          (candidate.getAttribute("aria-label") ?? "").startsWith("One more"),
        );
        button?.click();
        return Boolean(button);
      }, itemName);
      if (!clicked) throw new Error(`no stepper for ${itemName}`);
    }
  };

  await raise("21D Screenguard - Hot 8", 20);
  await raise("Privacy Glass - iPhone 13", 2);

  // Then something the shop does not list, which is the case that sends people back to paper.
  await page.type("input[placeholder*='21D screenguard for iPhone 15']", "Universal metal frame, any brand");
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find(
      (candidate) => candidate.textContent?.trim() === "Add",
    );
    button?.click();
  });

  const counted = await page.evaluate(() => document.body.innerText);
  if (!counted.includes("3 items on your list")) {
    throw new Error(`the list does not read three items: ${counted.slice(-300)}`);
  }
  console.log(`      counts read: ${counted.match(/\\d+ items on your list/)?.[0]}`);

  await page.type("#list_phone", "08029876543");
  await page.type("#list_name", "Toba");
  await page.screenshot({ path: resolve(OUTPUT, "list-mobile.png") });
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((candidate) =>
      candidate.textContent?.trim().startsWith("Send my list"),
    );
    button?.click();
  });
  await page.waitForFunction(() => document.body.innerText.includes("has reached"), {
    timeout: 30000,
  });
  await page.screenshot({ path: resolve(OUTPUT, "list-sent.png") });
  await context.close();
});

await step("the trader sees the counts, unpriced", async () => {
  const list = await trader.evaluate(async (tenantId) => {
    const response = await fetch(`/api/v1/tenants/${tenantId}/requests`);
    return response.json();
  }, shop.tenantId);
  const first = list[0];
  if (!first) throw new Error("the shop received no list");
  const quantities = first.lines.map((line) => Number(line.pieces));
  const expected = [20, 2, 1];
  const sorted = [...quantities].sort((a, b) => b - a);
  console.log(
    `      received: ${first.lines.length} lines, pieces=${JSON.stringify(quantities)}, ` +
      `unpriced=${first.unpriced_line_count}, total=${first.priced_total}, ` +
      `phone=${first.customer_phone}`,
  );
  if (first.lines.length !== 3) throw new Error(`expected 3 lines, got ${first.lines.length}`);
  if (JSON.stringify(sorted) !== JSON.stringify(expected)) {
    throw new Error(`the counts did not survive: ${JSON.stringify(quantities)}`);
  }
  if (first.customer_phone !== "+2348029876543") {
    throw new Error(`the number was not canonicalised: ${first.customer_phone}`);
  }
  if (first.priced_total !== null || first.unpriced_line_count !== 3) {
    throw new Error("a list nobody has priced must report no total, and say how many are unpriced");
  }
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
