/**
 * What a person actually reads when they get their password wrong.
 *
 * The API's own error is a code, a safe message and a correlation ID, which is the right shape for an
 * engineer and unreadable for a trader. This drives the real screen and prints the words that appear,
 * so the copy is verified rather than assumed.
 */

import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

try {
  await page.goto(`${APP_URL}/start`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#identifier", { timeout: 30_000 });
  await page.type("#identifier", `nobody.${Date.now()}@example.com`);
  await page.type("#password", "Wrong-Password-2026");
  // The submit button specifically: the tab above it is also called "Sign in", and clicking that one
  // only switches mode.
  await page.evaluate(() => {
    const submit = document.querySelector('button[type="submit"]');
    if (submit) {
      submit.click();
    }
  });
  // Wait for the alert itself, whatever it turns out to say: asserting the exact copy here would
  // make the check fail for the wrong reason when the copy is the thing being reviewed.
  await page.waitForSelector('[role="alert"]', { timeout: 30_000 });
  const message = await page.evaluate(() => {
    const alert = document.querySelector('[role="alert"]');
    return alert ? alert.innerText : "(no alert rendered)";
  });
  console.log("--- what the person reads ---");
  console.log(message);
  await page.screenshot({ path: `${process.env.REVIEW_DIR ?? "../.review"}/web-wrong-password.png` });
} catch (error) {
  console.log(`[FAIL] ${error.message}`);
  console.log((await page.evaluate(() => document.body.innerText)).slice(0, 400));
  process.exitCode = 1;
} finally {
  await browser.close();
}
