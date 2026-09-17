/**
 * The public shop, as a customer sees it - and as WhatsApp's link preview would.
 *
 * The page is rendered on the server with no session, so this check uses a fresh browser with no
 * cookies at all. It opens the shop, opens a product, and asserts that the metadata a link preview
 * reads is real: a page that renders for a human but unfurls as a blank link is half a feature.
 */

import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const OUTPUT = resolve(process.cwd(), "..", ".review");
const stamp = Date.now();
const email = `shop.${stamp}@example.com`;
const password = "Shop-Password-2026";

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
    await mkdir(OUTPUT, { recursive: true });
    await page.screenshot({ path: resolve(OUTPUT, `shop-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    console.log((await page.evaluate(() => document.body.innerText)).slice(0, 400));
    process.exitCode = 1;
    throw error;
  }
}

const waitFor = (text, timeout = 40_000) =>
  page.waitForFunction((wanted) => document.body.innerText.includes(wanted), { timeout }, text);

const clickInDialog = (label) =>
  page.evaluate((wanted) => {
    const dialog = document.querySelector('[role="dialog"]');
    const scope = dialog ?? document.body;
    // The accessible name as well as the text: the photo button shows a picture, not a word.
    const button = [...scope.querySelectorAll("button")].find(
      (candidate) =>
        (candidate.getAttribute("aria-label") ?? "").startsWith(wanted) ||
        candidate.textContent?.trim().startsWith(wanted),
    );
    button?.click();
  }, label);

try {
  await step("a shop exists with something in it", async () => {
    await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
    await page.waitForSelector("#first_name", { timeout: 30_000 });
    await page.type("#first_name", "Ada");
    await page.type("#last_name", "Obi");
    await page.type("#phone", `0809${String(stamp).slice(-7)}`);
    await page.type("#password", password);
    await page.type("#confirm_password", password);
    await page.click('button[type="submit"]');
    await page.waitForSelector("#business-name", { timeout: 40_000 });
    await page.type("#business-name", `Alaba Shop ${stamp % 10000}`);
    await clickInDialog("Create business");
    // The dashboard's own text is behind the sheet, so waiting for a word proves nothing: wait for
    // the sheet to be gone, which is the business having been created.
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40_000 });

    await clickInDialog("Add a product");
    await page.waitForSelector("#new-product", { timeout: 30_000 });
    await page.type("#new-product", "Standing Fan 18 inch");
    await page.type("#new-price", "38000.00");
    await clickInDialog("Add to the shelf");
    await waitFor("Standing Fan 18 inch");

    // A product starts hidden: showing it in the public shop is a decision the trader makes.
    await clickInDialog("Hidden");
    await waitFor("In shop");

    await clickInDialog("Add a photo of Standing Fan 18 inch");
    await page.waitForSelector('input[type="file"]', { timeout: 30_000 });
    const input = await page.$('input[type="file"]');
    await input.uploadFile(resolve(OUTPUT, "ahia-test-photo.png"));
    await waitFor("Cover", 60_000);
    await clickInDialog("Close");
  });

  let slug = "";

  await step("the shop is published", async () => {
    await clickInDialog("Open my shop");
    // "Your shop online" is the card's title and is there whether or not it is open. The link itself
    // is the proof that the publish landed.
    await waitFor("Copy link");
    slug = await page.evaluate(() => {
      const element = [...document.querySelectorAll("p")].find((candidate) =>
        candidate.textContent?.includes("/shop/"),
      );
      return element?.textContent?.split("/shop/")[1]?.trim() ?? "";
    });
    if (!slug) {
      throw new Error("the shop link was not on the page");
    }
    console.log(`      shop address: /shop/${slug}`);

    // The number customers message: without it the shop is a catalogue nobody can ask about.
    await clickInDialog("Edit");
    await page.waitForSelector("#shop_phone", { timeout: 30_000 });
    await page.type("#shop_phone", "08031234567");
    await page.type("#shop_headline", "Electronics and appliances in Alaba");
    await clickInDialog("Save the shop page");
    await waitFor("Your shop page is updated.");
    await page.screenshot({ path: resolve(OUTPUT, "shop-0-dashboard.png") });
  });

  await step("a customer with no account can open it", async () => {
    const anonymous = await browser.createBrowserContext();
    const visitor = await anonymous.newPage();
    await visitor.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
    await visitor.goto(`${APP_URL}/shop/${slug}`, { waitUntil: "networkidle2" });
    const body = await visitor.evaluate(() => document.body.innerText);
    if (!body.includes("Standing Fan 18 inch")) {
      throw new Error(`the catalogue did not render: ${body.slice(0, 200)}`);
    }
    const title = await visitor.title();
    if (!title.includes("Alaba Shop")) {
      throw new Error(`the page title is ${title}, which WhatsApp's preview would show`);
    }
    await visitor.screenshot({ path: resolve(OUTPUT, "shop-1-catalogue.png") });

    await visitor.click("a[href*='/product/']");
    await visitor.waitForFunction(
      () => document.body.innerText.includes("Standing Fan 18 inch"),
      { timeout: 30_000 },
    );
    // "undefined" is what a payload mismatch looks like on screen, so it is asserted against.
    const productBody = await visitor.evaluate(() => document.body.innerText);
    if (productBody.includes("undefined")) {
      throw new Error(`the product page rendered a missing field: ${productBody.slice(0, 200)}`);
    }
    await visitor.waitForFunction(() => document.body.innerText.includes("Ask on WhatsApp"), {
      timeout: 30_000,
    });
    await visitor.screenshot({ path: resolve(OUTPUT, "shop-2-product.png") });
    await anonymous.close();
  });

  console.log("[OK] no problems");
} catch {
  // Each failing step has already reported itself.
} finally {
  await browser.close();
}
