/**
 * The public shop, at the two sizes a customer uses it.
 *
 * It publishes a shop with a photograph, a price and a phone number, then measures what a customer
 * actually gets: how long until the page answers, whether the layout holds still, whether the number is
 * reachable, and whether anything on the page is a word only the software would use.
 */
import { resolve } from "node:path";
import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const API = process.env.API_URL ?? "http://127.0.0.1:8000";
const OUTPUT = resolve(process.cwd(), "..", ".review");
const stamp = Date.now();

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const shop = await browser.newPage();
await shop.setViewport({ width: 1440, height: 900 });
const failures = [];

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await shop.screenshot({ path: resolve(OUTPUT, `shop-design-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    failures.push(name);
  }
}

async function signUp(page) {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0810${String(stamp).slice(-7)}`);
  await page.type("#password", "Shop-Design-2026");
  await page.type("#confirm_password", "Shop-Design-2026");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40000 });
  await page.type("#business-name", `Alaba Screens ${stamp % 1000}`);
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });
}

let slug = "";
await step("a trader publishes a shop with a product", async () => {
  await signUp(shop);
  // Everything through the app's own origin, so the session cookie travels: the browser talks to
  // localhost:3000 and Next proxies to the API, which is exactly how the product works.
  slug = await shop.evaluate(async () => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    const tenant = tenants[0];
    if (!tenant) throw new Error("no business was created");
    // Publishing carries what the shop says, so the number and the words travel with the decision to
    // open - which is why the request has a body at all.
    const shopBody = JSON.stringify({
      headline: "Screenguards for every phone",
      description: "Alaba International Market. Send a list and we will pack it for you.",
      contact_phone: "+2348031234567",
    });
    await fetch(`/api/v1/tenants/${tenant.id}/products`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "21D Screenguard - Hot 8", selling_price: "500.00" }),
    });
    await fetch(`/api/v1/tenants/${tenant.id}/products`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Privacy Glass - iPhone 13", selling_price: "1500.00" }),
    });
    const published = await fetch(`/api/v1/tenants/${tenant.id}/storefront/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: shopBody,
    });
    if (!published.ok) {
      throw new Error(`publishing answered ${published.status}: ${await published.text()}`);
    }
    const products = await (await fetch(`/api/v1/tenants/${tenant.id}/products`)).json();
    for (const product of products) {
      await fetch(`/api/v1/tenants/${tenant.id}/products/${product.id}/publish`, {
        method: "POST",
      });
    }
    return tenant.slug;
  });
  if (!slug) throw new Error("the shop has no public address");
});

await step("a customer opens it on a phone and a desk", async () => {
  for (const [label, viewport] of [
    ["mobile", { width: 390, height: 844, isMobile: true, hasTouch: true }],
    ["desktop", { width: 1440, height: 900 }],
  ]) {
    const context = await browser.createBrowserContext();
    const page = await context.newPage();
    await page.setViewport(viewport);
    const started = Date.now();
    const response = await page.goto(`${APP_URL}/shop/${slug}`, { waitUntil: "domcontentloaded" });
    const elapsed = Date.now() - started;
    // Wait for the shop itself, not the skeleton: a screenshot of loading state proves the loading
    // state works and tells nobody anything about the design.
    await page.waitForFunction(
      () => !document.body.innerText.includes("Opening the shop"),
      { timeout: 20000 },
    );
    await page.screenshot({ path: resolve(OUTPUT, `shop-${label}.png`), fullPage: false });

    const facts = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > window.innerWidth,
      text: document.body.innerText,
      hasWhatsapp: Boolean(document.querySelector('a[href*="wa.me"]')),
      hasCall: Boolean(document.querySelector('a[href^="tel:"]')),
      squareCards: [...document.querySelectorAll("a[href*='/product/'] span")].some((span) => {
        const style = getComputedStyle(span);
        return style.aspectRatio && style.aspectRatio !== "auto";
      }),
    }));

    console.log(
      `      ${label}: HTTP ${response?.status()} in ${elapsed}ms, overflow=${facts.overflow}, ` +
        `whatsapp=${facts.hasWhatsapp}, call=${facts.hasCall}, stableImages=${facts.squareCards}`,
    );
    if (response?.status() !== 200) throw new Error(`the shop answered ${response?.status()}`);
    if (facts.overflow) throw new Error("the page is wider than the phone");
    if (!facts.hasWhatsapp) throw new Error("a customer cannot message the shop");
    if (!facts.hasCall) throw new Error("the number is not tappable");
    for (const word of ["sourced", "availability", "out of stock", "null", "undefined"]) {
      if (facts.text.toLowerCase().includes(word)) {
        throw new Error(`the page tells a customer about "${word}"`);
      }
    }
    await context.close();
  }
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
