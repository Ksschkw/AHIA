/**
 * Two businesses on one account.
 *
 * A trader with a shop and a second stall should not need two accounts: the businesses are separate
 * worlds - their own products, stock, sales, money and public address - and switching between them
 * must not leak one into the other.
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
await page.setViewport({ width: 1280, height: 900 });
const problems = [];
page.on("pageerror", (error) => problems.push(error.message.slice(0, 160)));

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await page.screenshot({ path: resolve(OUTPUT, `businesses-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    process.exitCode = 1;
    throw error;
  }
}

const waitFor = (text, timeout = 40_000) =>
  page.waitForFunction((wanted) => document.body.innerText.includes(wanted), { timeout }, text);

async function click(label, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const outcome = await page.evaluate((wanted) => {
      const dialog = document.querySelector('[role="dialog"]');
      const scope = dialog ?? document.body;
      const control = [...scope.querySelectorAll("button, a[href]")].find(
        (candidate) =>
          (candidate.getAttribute("aria-label") ?? "").startsWith(wanted) ||
          candidate.textContent?.trim().startsWith(wanted),
      );
      if (!control) return "missing";
      if (control.disabled) return "disabled";
      control.click();
      return "clicked";
    }, label);
    if (outcome === "clicked") return;
    await new Promise((resolve_) => setTimeout(resolve_, 200));
  }
  throw new Error(`no usable control starting with "${label}"`);
}

const createBusiness = async (name) => {
  await click("Add another business");
  await page.waitForSelector("#business-name", { timeout: 30_000 });
  await page.type("#business-name", name);
  await click("Create business");
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40_000 });
};

try {
  await step("an account with one business", async () => {
    await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
    await page.waitForSelector("#first_name", { timeout: 30_000 });
    await page.type("#first_name", "Ada");
    await page.type("#last_name", "Obi");
    await page.type("#phone", `0804${String(stamp).slice(-7)}`);
    await page.type("#password", "Businesses-2026");
    await page.type("#confirm_password", "Businesses-2026");
    await page.click('button[type="submit"]');
    await page.waitForSelector("#business-name", { timeout: 40_000 });
    await page.type("#business-name", `Main Shop ${stamp % 1000}`);
    await click("Create business");
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40_000 });
  });

  await step("a second business is created from the top bar", async () => {
    await createBusiness(`Second Shop ${stamp % 1000}`);
    await page.waitForFunction(
      () => [...document.querySelectorAll("select option")].length === 2,
      { timeout: 40_000 },
    );
  });

  await step("each business keeps its own shelf", async () => {
    await click("Add a product");
    await page.waitForSelector("#new-product", { timeout: 30_000 });
    await page.type("#new-product", "Item only in the second shop");
    await page.type("#new-price", "5000.00");
    await click("Add to the shelf");
    await waitFor("Item only in the second shop");
    // The confirmation stays on screen for a few seconds, and it carries the product's name: reading
    // the page while it is up would report the toast rather than the shelf.
    await click("Dismiss");

    // Switch to the first business and prove the item is not there.
    const first = await page.evaluate(() => {
      const select = document.querySelector("select");
      const option = [...select.options].find((candidate) => candidate.text.startsWith("Main Shop"));
      if (!option) return false;
      select.value = option.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    });
    if (!first) {
      throw new Error("the first business was not in the picker");
    }
    await waitFor("Main Shop");
    await new Promise((resolve_) => setTimeout(resolve_, 2500));
    const body = await page.evaluate(() => document.body.innerText);
    if (body.includes("Item only in the second shop")) {
      throw new Error("the second shop's product appeared in the first shop");
    }
    await page.screenshot({ path: resolve(OUTPUT, "businesses-1-switched.png") });
  });

  console.log(problems.length ? `[WARN] ${problems.join(", ")}` : "[OK] no problems");
} catch {
  // Each failing step has reported itself.
} finally {
  await browser.close();
}
