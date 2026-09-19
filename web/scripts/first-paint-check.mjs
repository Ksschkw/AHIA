/**
 * The first paint comes from the cache, not from the network.
 *
 * M24.5's second half claims the authenticated app paints what it already knows before it asks anybody. That is
 * a claim about *timing*, so it is measured rather than read: the products request is delayed by several
 * seconds, and the screen is asked whether the shelf is already on it.
 *
 * If the content appears while the reply is still in flight, the first paint came from the cache. If it appears
 * only after, it came from the server and the claim is false - and no amount of reading the code would have
 * settled it.
 */
import { resolve } from "node:path";
import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const OUTPUT = resolve(process.cwd(), "..", ".review");
const stamp = Date.now();
const failures = [];
const PRODUCT = `Cached Screenguard ${stamp % 1000}`;

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();
await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await page.screenshot({ path: resolve(OUTPUT, `first-paint-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    failures.push(name);
  }
}

await step("a shop with something on the shelf", async () => {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0829${String(stamp).slice(-7)}`);
  await page.type("#password", "Paint-2026-Pass");
  await page.type("#confirm_password", "Paint-2026-Pass");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40000 });
  await page.type("#business-name", `Alaba Paint ${stamp % 1000}`);
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });

  const created = await page.evaluate(async (name) => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    const tenant = tenants[0];
    const response = await fetch(`/api/v1/tenants/${tenant.id}/products`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, selling_price: "500.00" }),
    });
    if (!response.ok) throw new Error(await response.text());
    return tenant.id;
  }, PRODUCT);
  if (!created) throw new Error("the product was not created");
});

await step("the shelf is on screen, and the cache is written", async () => {
  await page.goto(`${APP_URL}/app`, { waitUntil: "networkidle2" });
  await page.waitForFunction((name) => document.body.innerText.includes(name), { timeout: 30000 }, PRODUCT);
  const cached = await page.evaluate(() =>
    Object.keys(window.localStorage).filter((key) => key.startsWith("ahia.cache.")),
  );
  console.log(`      cache keys written: ${cached.length}`);
  if (cached.length === 0) throw new Error("nothing was written to the cache");
});

await step("on a reload with a slow network, the shelf is there before the reply", async () => {
  // The measurement: every products request is held for five seconds.
  await page.setRequestInterception(true);
  let heldBack = 0;
  page.on("request", async (request) => {
    if (request.url().includes("/products")) {
      heldBack += 1;
      await new Promise((resolve_) => setTimeout(resolve_, 5000));
    }
    await request.continue().catch(() => {});
  });

  const started = Date.now();
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction((name) => document.body.innerText.includes(name), { timeout: 4500 }, PRODUCT);
  const elapsed = Date.now() - started;
  await page.screenshot({ path: resolve(OUTPUT, "first-paint.png") });
  console.log(
    `      the shelf was on screen ${elapsed}ms after the reload, with ${heldBack} request(s) held for 5s`,
  );
  if (heldBack === 0) throw new Error("no request was delayed, so nothing was measured");
  if (elapsed > 4000) {
    throw new Error("the shelf appeared only after the network answered, so the first paint waited for it");
  }
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
