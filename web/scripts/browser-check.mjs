/**
 * Drives the console in a real browser: create an account, name a business, add a product, stock it,
 * record a sale from the sheet, and screenshot every step.
 *
 * This exists because the only proof a frontend works is a browser doing what a person does. It is a
 * script rather than a test framework on purpose: it writes screenshots to `.review/`, and exits
 * non-zero with the page's own words when a step does not appear.
 *
 *     node scripts/browser-check.mjs
 */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUTPUT = resolve(HERE, "..", "..", ".review");
const CHROME = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";
const APP_URL = process.env.APP_URL ?? "http://localhost:3000";

const stamp = Date.now();
const email = `browser.${stamp}@example.com`;
const businessName = `Obi Electronics ${stamp}`;
const password = "Browser-Password-2026";

//: Generous on purpose: the backend talks to a database in another region, so a correct screen can
//: take seconds to appear. This script is about whether the flow works, not how fast it is.
const STEP_TIMEOUT_MS = 45_000;

const steps = [];

/** Every API answer this run saw, so a failure is diagnosable instead of merely reported. */
const apiTraffic = [];

async function diagnose(page, step, error) {
  await mkdir(OUTPUT, { recursive: true });
  await page.screenshot({ path: resolve(OUTPUT, `failure-${step}.png`) });
  const body = await page.evaluate(() => document.body.innerText);
  await writeFile(resolve(OUTPUT, `failure-${step}.txt`), body, "utf8");
  const traffic = apiTraffic.map((line) => `  ${line}`).join("\n") || "  (none)";
  throw new Error(`${step}: ${error.message}\n--- api traffic ---\n${traffic}\n--- page said ---\n${body}`);
}

async function waitForText(page, text, timeout = STEP_TIMEOUT_MS) {
  await page.waitForFunction((wanted) => document.body.innerText.includes(wanted), { timeout }, text);
}

/**
 * Click the first button whose label starts with `text`, once it is enabled.
 *
 * Waiting for enabled matters: a button is disabled while a request is in flight, and a click on a
 * disabled button is silently dropped - which looks exactly like a broken page.
 */
async function clickByText(page, text, { timeout = STEP_TIMEOUT_MS } = {}) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const outcome = await page.evaluate((wanted) => {
      // A dialog owns the interaction while it is open, so its buttons are searched first: the tiles
      // behind it are still in the document, and "Record " matches both the sheet's submit and the
      // "Record a sale" tile behind the scrim.
      const roots = [document.querySelector('[role="dialog"]'), document.body].filter(Boolean);
      const buttons = roots.flatMap((root) => [...root.querySelectorAll("button")]);
      const button = buttons.find(
        (candidate) =>
          // The accessible name first: a tile renders its glyph before its label, so matching raw
          // text would need to know the decoration. `aria-label` is what a screen reader reads.
          (candidate.getAttribute("aria-label") ?? "").startsWith(wanted) ||
          candidate.textContent?.trim().startsWith(wanted),
      );
      if (!button) {
        return "missing";
      }
      if (button.disabled) {
        return "disabled";
      }
      button.click();
      return "clicked";
    }, text);
    if (outcome === "clicked") {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`no enabled button starting with "${text}"`);
}

/**
 * Run one step, and on failure leave everything needed to diagnose it: a screenshot, the page's own
 * words, and every API answer the run saw. A step that fails without evidence costs another run.
 */
async function step(page, name, action) {
  try {
    await action();
  } catch (error) {
    await diagnose(page, name, error);
  }
}

async function shot(page, name) {
  await mkdir(OUTPUT, { recursive: true });
  const path = resolve(OUTPUT, `${name}.png`);
  await page.screenshot({ path, fullPage: false });
  steps.push(`${name}: ${path}`);
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  const consoleErrors = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/")) {
      apiTraffic.push(`${response.status()} ${response.request().method()} ${response.url().replace(APP_URL, "")}`);
    }
  });
  page.on("requestfailed", (request) => {
    if (request.url().includes("/api/")) {
      apiTraffic.push(`FAILED ${request.method()} ${request.url().replace(APP_URL, "")} (${request.failure()?.errorText ?? "unknown"})`);
    }
  });
  page.on("pageerror", (error) => {
    consoleErrors.push(`pageerror: ${error.message}`);
  });
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });

  try {
    await step(page, "1-welcome", async () => {
      await page.goto(APP_URL, { waitUntil: "networkidle2" });
      await waitForText(page, "Create account");
      await shot(page, "web-1-welcome");
    });

    await step(page, "2-create-account", async () => {
      await clickByText(page, "Create account");
      await page.waitForSelector("#first_name", { timeout: STEP_TIMEOUT_MS });
      await page.type("#first_name", "Ada");
      await page.type("#identifier", email);
      await page.type("#password", password);
      await shot(page, "web-2-create-account");
      await clickByText(page, "Create my account");
    });

    await step(page, "3-name-business", async () => {
      // The element, not the words: the dashboard's empty state also says "Name your business",
      // so waiting for the text raced ahead of the sheet that actually has the field.
      await page.waitForSelector("#business-name", { timeout: STEP_TIMEOUT_MS });
      await shot(page, "web-3-name-business");
      await page.type("#business-name", businessName);
      await clickByText(page, "Create business");
    });

    await step(page, "4-dashboard", async () => {
      await waitForText(page, businessName);
      await shot(page, "web-4-dashboard");
    });

    await step(page, "5-add-product", async () => {
      await clickByText(page, "Add a product");
      await page.waitForSelector("#new-product", { timeout: STEP_TIMEOUT_MS });
      await page.type("#new-product", "Rice 50kg");
      await page.type("#new-price", "45000.00");
      await shot(page, "web-5-add-product");
      await clickByText(page, "Add to the shelf");
      await waitForText(page, "Rice 50kg");
      await shot(page, "web-6-product-added");
    });

    await step(page, "6-stock-in", async () => {
      await clickByText(page, "Stock in");
      await page.waitForSelector("#stock-quantity", { timeout: STEP_TIMEOUT_MS });
      await shot(page, "web-7-stock-in");
      await clickByText(page, "Add to stock");
      await waitForText(page, "in stock");
      await shot(page, "web-8-stocked");
    });

    await step(page, "7-record-sale", async () => {
      await clickByText(page, "Record a sale");
      await page.waitForSelector("#sale-quantity", { timeout: STEP_TIMEOUT_MS });
      await shot(page, "web-9-sale-sheet");
      await clickByText(page, "Record ");
      await waitForText(page, "recorded:");
      await shot(page, "web-10-sale-recorded");
    });

    const state = await page.evaluate(() => document.body.innerText);
    await writeFile(resolve(OUTPUT, "web-console.txt"), state, "utf8");
    steps.push(`text: ${resolve(OUTPUT, "web-console.txt")}`);

    console.log(steps.join("\n"));
    if (consoleErrors.length > 0) {
      console.log(`[WARN] browser console errors:\n  ${consoleErrors.join("\n  ")}`);
    }
    console.log("[OK] the console completed the loop in a real browser");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`[FAIL] ${error.message}`);
  process.exit(1);
});
