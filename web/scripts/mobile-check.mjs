/**
 * The whole journey on a phone, which is the device this product is actually for.
 *
 * "Responsive" is not an opinion here: the check fails if any screen is wider than the viewport, which
 * is the one thing that makes a mobile page feel broken - a form you have to drag sideways to read.
 * It walks the same flow as the desktop check and screenshots every step at 390x844, the shape of the
 * phones a market trader carries.
 */

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUTPUT = resolve(HERE, "..", "..", ".review");
const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const CHROME = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";

const stamp = Date.now();
const email = `mobile.${stamp}@example.com`;
const password = "Mobile-Password-2026";
const businessName = `Mobile Shop ${stamp}`;

const overflows = [];
const apiFailures = [];

async function shot(page, name) {
  await mkdir(OUTPUT, { recursive: true });
  const path = resolve(OUTPUT, `mobile-${name}.png`);
  await page.screenshot({ path, fullPage: false });
  const wide = await page.evaluate(() => {
    const document_ = document.documentElement;
    return {
      scrollWidth: document_.scrollWidth,
      clientWidth: document_.clientWidth,
      offenders: [...document_.querySelectorAll("*")]
        .filter((element) => element.getBoundingClientRect().right > document_.clientWidth + 1)
        .slice(0, 4)
        .map((element) => `${element.tagName.toLowerCase()}.${String(element.className).split(" ")[0] ?? ""}`),
    };
  });
  if (wide.scrollWidth > wide.clientWidth + 1) {
    overflows.push(`${name}: page is ${wide.scrollWidth}px wide in a ${wide.clientWidth}px viewport (${wide.offenders.join(", ")})`);
  }
  console.log(`${name}: ${wide.scrollWidth}/${wide.clientWidth}px`);
}

async function clickByText(page, text, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const outcome = await page.evaluate((wanted) => {
      const roots = [document.querySelector('[role="dialog"]'), document.body].filter(Boolean);
      const controls = roots.flatMap((root) => [...root.querySelectorAll("button, a[href]")]);
      const found = controls.find(
        (candidate) =>
          (candidate.getAttribute("aria-label") ?? "").startsWith(wanted) ||
          candidate.textContent?.trim().startsWith(wanted),
      );
      if (!found) return "missing";
      if (found instanceof HTMLButtonElement && found.disabled) return "disabled";
      found.click();
      return "clicked";
    }, text);
    if (outcome === "clicked") return;
    await new Promise((resolve_) => setTimeout(resolve_, 200));
  }
  throw new Error(`no usable control starting with "${text}"`);
}

const waitForText = (page, text, timeout = 40_000) =>
  page.waitForFunction((wanted) => document.body.innerText.includes(wanted), { timeout }, text);

async function step(page, name, action) {
  try {
    await action();
  } catch (error) {
    await mkdir(OUTPUT, { recursive: true });
    await page.screenshot({ path: resolve(OUTPUT, `mobile-failure-${name}.png`) });
    const body = await page.evaluate(() => document.body.innerText);
    await writeFile(resolve(OUTPUT, `mobile-failure-${name}.txt`), body, "utf8");
    throw new Error(`${name}: ${error.message}\n--- api ---\n${apiFailures.join("\n")}\n--- page ---\n${body.slice(0, 600)}`);
  }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();
await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
page.on("response", (response) => {
  if (response.url().includes("/api/") && response.status() >= 400) {
    apiFailures.push(`${response.status()} ${response.request().method()} ${response.url()}`);
  }
});

try {
  await step(page, "1-landing", async () => {
    await page.goto(APP_URL, { waitUntil: "networkidle2" });
    await waitForText(page, "in your pocket");
    await shot(page, "1-landing");
  });

  await step(page, "2-signup", async () => {
    await clickByText(page, "Open your shop");
    await page.waitForSelector("#first_name", { timeout: 30_000 });
    await shot(page, "2-signup-empty");
    await page.type("#first_name", "Ada");
    await page.type("#last_name", "Obi");
    await page.type("#identifier", email);
    await page.type("#password", password);
    await page.type("#confirm_password", password);
    await shot(page, "3-signup-filled");
    await clickByText(page, "Create my account");
  });

  await step(page, "3-business", async () => {
    await page.waitForSelector("#business-name", { timeout: 40_000 });
    await shot(page, "4-business");
    await page.type("#business-name", businessName);
    await clickByText(page, "Create business");
  });

  await step(page, "4-dashboard", async () => {
    await waitForText(page, businessName);
    await shot(page, "5-dashboard");
  });

  await step(page, "5-product", async () => {
    await clickByText(page, "Add a product");
    await page.waitForSelector("#new-product", { timeout: 30_000 });
    await page.type("#new-product", "Rice 50kg");
    await page.type("#new-price", "45000.00");
    await shot(page, "6-product-sheet");
    await clickByText(page, "Add to the shelf");
    await waitForText(page, "Rice 50kg");
  });

  await step(page, "6-stock", async () => {
    await clickByText(page, "Stock in");
    await page.waitForSelector("#stock-quantity", { timeout: 30_000 });
    await clickByText(page, "Add to stock");
    await waitForText(page, "in stock");
    await shot(page, "7-stocked");
  });

  await step(page, "7-sale", async () => {
    await clickByText(page, "Record a sale");
    await page.waitForSelector("#sale-quantity", { timeout: 30_000 });
    await shot(page, "8-sale-sheet");
    await clickByText(page, "Record ");
    await waitForText(page, "recorded:");
    await shot(page, "9-sale-recorded");
  });


  await step(page, "8-photo", async () => {
    await clickByText(page, "Add a photo of Rice 50kg");
    await page.waitForSelector('input[type="file"]', { timeout: 30_000 });
    await shot(page, "10-photo-sheet-empty");
    const input = await page.$('input[type="file"]');
    await input.uploadFile(resolve(HERE, "..", "..", ".review", "ahia-test-photo.png"));
    // The upload goes to the object storage provider and comes back with a delivery URL, so the wait
    // has to allow for a real round trip to a real service.
    await waitForText(page, "Cover", 60_000);
    // The bytes come from Cloudinary, so "the row exists" is not "the picture is on the screen".
    await page.waitForFunction(
      () => [...document.images].every((image) => image.complete && image.naturalWidth > 0),
      { timeout: 40_000 },
    );
    await shot(page, "11-photo-added");
    await clickByText(page, "Close");
  });

  console.log(overflows.length ? `\n[FAIL] ${overflows.length} screen(s) overflow the viewport:\n  ${overflows.join("\n  ")}` : "\n[OK] no screen is wider than the phone viewport");
  if (apiFailures.length) {
    console.log(`[WARN] api failures:\n  ${apiFailures.join("\n  ")}`);
  }
  process.exitCode = overflows.length ? 1 : 0;
} catch (error) {
  console.log(`[FAIL] ${error.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
