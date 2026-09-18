/**
 * The list at its own address.
 *
 * The page the customer keeps and the trader opens. It has to be a page (not JSON), it has to show the
 * customer's own view - their lines, the shop's prices, and nothing about what the goods cost the trader
 * - and it has to notice when the trader prices something, because two people are working on it.
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
    await trader.screenshot({ path: resolve(OUTPUT, `list-page-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    failures.push(name);
  }
}

let shop = { slug: "", tenantId: "", path: "", requestId: "", lineId: "" };

await step("a shop, and a list a customer sent", async () => {
  await trader.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await trader.waitForSelector("#first_name", { timeout: 40000 });
  await trader.type("#first_name", "Ada");
  await trader.type("#last_name", "Obi");
  await trader.type("#phone", `0821${String(stamp).slice(-7)}`);
  await trader.type("#password", "ListPage-2026");
  await trader.type("#confirm_password", "ListPage-2026");
  await trader.click('button[type="submit"]');
  await trader.waitForSelector("#business-name", { timeout: 40000 });
  await trader.type("#business-name", `Alaba Page ${stamp % 1000}`);
  await trader.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await trader.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });

  const created = await trader.evaluate(async () => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    const tenant = tenants[0];
    await fetch(`/api/v1/tenants/${tenant.id}/storefront/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ headline: "Screenguards", contact_phone: "+2348031234567" }),
    });
    const accepted = await (
      await fetch(`/shop/${tenant.slug}/requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_phone: "08029876543",
          customer_name: "Toba",
          lines: [
            { free_text: "21D for Hot 8", quantity: "20" },
            { free_text: "Universal metal frame", quantity: "5" },
          ],
        }),
      })
    ).json();
    const lists = await (await fetch(`/api/v1/tenants/${tenant.id}/requests`)).json();
    return {
      slug: tenant.slug,
      tenantId: tenant.id,
      path: accepted.list_path,
      requestId: lists[0].id,
      lineId: lists[0].lines[0].id,
    };
  });
  shop = created;
  if (!shop.path) throw new Error("the list has no address");
  console.log(`      address: ${shop.path.slice(0, 32)}...`);
});

await step("the customer opens it, at both sizes", async () => {
  for (const [label, viewport] of [
    ["mobile", { width: 390, height: 844, isMobile: true, hasTouch: true }],
    ["desktop", { width: 1440, height: 900 }],
  ]) {
    const context = await browser.createBrowserContext();
    const page = await context.newPage();
    await page.setViewport(viewport);
    const response = await page.goto(`${APP_URL}${shop.path}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("Alaba Page"), {
      timeout: 20000,
    });
    await page.screenshot({ path: resolve(OUTPUT, `list-page-${label}.png`) });

    const contentType = response?.headers()["content-type"] ?? "";
    if (!contentType.includes("text/html")) {
      throw new Error(`the list answered ${contentType} instead of a page`);
    }
    const facts = await page.evaluate(() => {
      const text = document.body.innerText;
      return {
        overflow: document.documentElement.scrollWidth > window.innerWidth,
        text,
        hasLines: text.includes("21D for Hot 8") && text.includes("Universal metal frame"),
        honestTotal: text.includes("Nothing priced yet") || text.includes("still to be priced"),
        leaks: ["margin", "It cost me", "you make", "cost_price"].filter((word) =>
          text.toLowerCase().includes(word.toLowerCase()),
        ),
        updatesItself: text.includes("updates"),
      };
    });
    console.log(
      `      ${label}: html=true, lines=${facts.hasLines}, honestTotal=${facts.honestTotal}, ` +
        `selfUpdating=${facts.updatesItself}, overflow=${facts.overflow}, leaks=${facts.leaks.length}`,
    );
    if (!facts.hasLines) throw new Error("the customer's lines are not on the page");
    if (!facts.honestTotal) throw new Error("the page does not say the list is not priced yet");
    if (facts.leaks.length) throw new Error(`the page leaks the trader's numbers: ${facts.leaks}`);
    if (facts.overflow) throw new Error("the page is wider than the phone");
    await context.close();
  }
});

await step("the trader prices a line, and the page notices", async () => {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  await page.goto(`${APP_URL}${shop.path}`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("21D for Hot 8"), {
    timeout: 20000,
  });

  // The trader prices it and marks it as bought in, with the API - as his own screen does.
  const priced = await trader.evaluate(
    async ([tenantId, requestId, lineId]) => {
      const response = await fetch(
        `/api/v1/tenants/${tenantId}/requests/${requestId}/lines/${lineId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ state: "buy_it", cost_price: "280.00", shop_price: "350.00" }),
        },
      );
      return response.ok;
    },
    [shop.tenantId, shop.requestId, shop.lineId],
  );
  if (!priced) throw new Error("the trader could not price the line");

  // The page updates itself; the customer does not have to know to refresh.
  await page.waitForFunction(
    () => document.body.innerText.includes("350") && document.body.innerText.includes("finding it"),
    { timeout: 40000 },
  );
  await page.screenshot({ path: resolve(OUTPUT, "list-page-updated.png") });
  const text = await page.evaluate(() => document.body.innerText);
  console.log(`      after the shop priced it: ${text.match(/[^\n]*Finding it[^\n]*|the shop is finding it/)?.[0] ?? "state shown"}`);
  if (text.toLowerCase().includes("you make") || text.includes("280")) {
    throw new Error("the customer can see what the goods cost the trader");
  }
  await context.close();
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
