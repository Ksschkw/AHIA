/**
 * The same journey, in Firefox.
 *
 * A frontend that only works in the browser the developer happens to use is not a frontend. This
 * drives the real Firefox through the sign-up flow and reports what the page did, so "the button does
 * nothing" is a fact with a cause rather than a report.
 */

import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const FIREFOX = process.env.FIREFOX_PATH ?? "/usr/bin/firefox";

const browser = await puppeteer.launch({
  browser: "firefox",
  executablePath: FIREFOX,
  headless: true,
});

const page = await browser.newPage();
const problems = [];
page.on("console", (message) => {
  if (message.type() === "error") problems.push(`console: ${message.text().slice(0, 200)}`);
});
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message.slice(0, 200)}`));
page.on("requestfailed", (request) => {
  if (request.url().includes("_next") || request.url().includes("/api/")) {
    problems.push(`failed: ${request.url().replace(APP_URL, "")} (${request.failure()?.errorText})`);
  }
});

const click = async (text) =>
  page.evaluate((wanted) => {
    const controls = [...document.querySelectorAll("button, a[href]")];
    const found = controls.find(
      (candidate) =>
        (candidate.getAttribute("aria-label") ?? "").startsWith(wanted) ||
        candidate.textContent?.trim().startsWith(wanted),
    );
    if (!found) return "missing";
    found.click();
    return "clicked";
  }, text);

const waitFor = (text, timeout = 40_000) =>
  page.waitForFunction((wanted) => document.body.innerText.includes(wanted), { timeout }, text);

try {
  await page.goto(APP_URL, { waitUntil: "networkidle2", timeout: 60_000 });
  await waitFor("Keep your shop in your pocket");
  console.log("[OK] landing page rendered");

  console.log("    click 'Open your shop':", await click("Open your shop"));
  await waitFor("Create account");
  console.log("[OK] reached the sign-in screen");

  console.log("    click 'Create account' tab:", await click("Create account"));
  await page.waitForSelector("#first_name", { timeout: 20_000 });
  console.log("[OK] the create-account form switched");

  await page.type("#first_name", "Ada");
  await page.type("#identifier", `firefox.${Date.now()}@example.com`);
  await page.type("#password", "Firefox-Password-2026");
  console.log("    click 'Create my shop':", await click("Create my shop"));

  await page.waitForSelector("#business-name", { timeout: 40_000 });
  console.log("[OK] account created and the business sheet opened");

  const state = await page.evaluate(() => document.body.innerText);
  console.log(problems.length ? `[WARN] problems:\n  ${problems.join("\n  ")}` : "[OK] no console or network problems");
  console.log(state.slice(0, 120).replace(/\n+/g, " | "));
} catch (error) {
  console.log(`[FAIL] ${error.message}`);
  console.log("--- page said ---");
  console.log((await page.evaluate(() => document.body.innerText)).slice(0, 400));
  console.log(problems.length ? `--- problems ---\n  ${problems.join("\n  ")}` : "--- no console problems ---");
  process.exitCode = 1;
} finally {
  await browser.close();
}
