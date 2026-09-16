/**
 * Drives the console in a real browser: create an account, open a business, add a product, stock it,
 * record a sale, and screenshot each step.
 *
 * This exists because the only proof that a frontend works is a browser doing what a person does. It
 * is a script rather than a test framework on purpose: it writes screenshots to `.review/` and exits
 * non-zero when a step failed, which is enough to see the loop end to end without another test suite.
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
const password = "Browser-Password-2026";

const steps = [];

/**
 * Click the first button whose label starts with `text`, once it is enabled.
 *
 * Waiting for enabled matters: the button is disabled while a request is in flight, and a click on a
 * disabled button is silently dropped - which looks exactly like a broken page.
 */
async function clickByText(page, text, { timeout = 20_000 } = {}) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const outcome = await page.evaluate((wanted) => {
      const button = [...document.querySelectorAll("button")].find((candidate) =>
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

async function diagnose(page, step, error) {
  await mkdir(OUTPUT, { recursive: true });
  await page.screenshot({ path: resolve(OUTPUT, `failure-${step}.png`) });
  const body = await page.evaluate(() => document.body.innerText);
  await writeFile(resolve(OUTPUT, `failure-${step}.txt`), body, "utf8");
  throw new Error(`${step}: ${error.message}\n--- page said ---\n${body}`);
}

async function waitForText(page, text, timeout = 20_000) {
  await page.waitForFunction(
    (wanted) => document.body.innerText.includes(wanted),
    { timeout },
    text,
  );
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
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });

  try {
    await page.goto(APP_URL, { waitUntil: "networkidle2" });
    await waitForText(page, "Open an account").catch((e) => diagnose(page, "1-account", e));
    await shot(page, "web-1-account");

    await page.type("#email", email);
    await page.type("#password", password);
    await clickByText(page, "Create account");
    await waitForText(page, "2. Business").catch((e) => diagnose(page, "2-signed-in", e));
    await waitForText(page, "No business on this account yet.").catch((e) =>
      diagnose(page, "2-empty-list", e),
    );
    await shot(page, "web-2-signed-in");

    await page.type("#business", "Obi Electronics");
    await clickByText(page, "Create business");
    await waitForText(page, "Product and stock").catch((e) => diagnose(page, "3-business", e));
    await shot(page, "web-3-business");

    await page.type("#product", "Rice 50kg");
    await clickByText(page, "Add product");
    await waitForText(page, "Rice 50kg").catch((e) => diagnose(page, "4-product", e));
    await shot(page, "web-4-product");

    await clickByText(page, "+ 10.000");
    await waitForText(page, "Stocked").catch((e) => diagnose(page, "5-stock", e));
    await shot(page, "web-5-stock");

    await clickByText(page, "Sell 1.000");
    await waitForText(page, "Sale OBI-").catch((e) => diagnose(page, "6-sale", e));
    await shot(page, "web-6-sale");

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
