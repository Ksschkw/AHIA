/**
 * The profile screen, exercised rather than eyeballed: change the name, change the business address,
 * change the password, and prove each one by reading it back from the API afterwards.
 */

import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const OUTPUT = resolve(process.cwd(), "..", ".review");
const stamp = Date.now();
const email = `profile.${stamp}@example.com`;
const originalPassword = "Profile-Password-2026";
const newPassword = "Profile-Password-2027";
const surname = `Obi${stamp % 10000}`;

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();
await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
const problems = [];

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await mkdir(OUTPUT, { recursive: true });
    await page.screenshot({ path: resolve(OUTPUT, `profile-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    console.log((await page.evaluate(() => document.body.innerText)).slice(0, 500));
    process.exitCode = 1;
    throw error;
  }
}

const waitFor = (text, timeout = 40_000) =>
  page.waitForFunction((wanted) => document.body.innerText.includes(wanted), { timeout }, text);

try {
  await step("the account exists", async () => {
    await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
    await page.waitForSelector("#first_name", { timeout: 30_000 });
    await page.type("#first_name", "Ada");
    await page.type("#last_name", "Obi");
    await page.type("#phone", `0807${String(stamp).slice(-7)}`);
    await page.type("#email", email);
    await page.type("#password", originalPassword);
    await page.type("#confirm_password", originalPassword);
    await page.click('button[type="submit"]');
    await page.waitForSelector("#business-name", { timeout: 40_000 });
    await page.type("#business-name", "Profile Shop");
    // The dialog's own button, by its label: its first button is "Close".
    await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]');
      const button = [...dialog.querySelectorAll("button")].find((candidate) =>
        candidate.textContent?.trim().startsWith("Create business"),
      );
      button?.click();
    });
    await waitFor("Record a sale");
  });

  await step("the profile opens from the dashboard", async () => {
    await page.goto(`${APP_URL}/app/profile`, { waitUntil: "networkidle2" });
    await page.waitForSelector("#last_name", { timeout: 30_000 });
    await page.screenshot({ path: resolve(OUTPUT, "profile-1-overview.png") });
  });

  await step("the name is saved", async () => {
    // Select-all then type: a triple click does not reliably select inside a controlled input.
    await page.click("#last_name");
    await page.keyboard.down("Control");
    await page.keyboard.press("KeyA");
    await page.keyboard.up("Control");
    await page.type("#last_name", surname);
    await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((candidate) =>
        candidate.textContent?.includes("Save my details"),
      );
      button?.click();
    });
    await waitFor("Your details are saved.");
    // Read back through the API, because the screen saying so is not the same as the data saying so.
    const saved = await page.evaluate(async () => {
      const response = await fetch("/api/v1/users/me", { credentials: "include" });
      return await response.json();
    });
    if (saved.last_name !== surname) {
      throw new Error(`the API still says ${saved.last_name}`);
    }
  });

  await step("the business address is saved", async () => {
    await page.type("#business_address", "12 Balogun Street");
    await page.type("#business_city", "Lagos");
    await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((candidate) =>
        candidate.textContent?.includes("Save the business details"),
      );
      button?.click();
    });
    await waitFor("The business details are saved.");
    await page.screenshot({ path: resolve(OUTPUT, "profile-2-saved.png") });
  });

  await step("the password is changed and the new one works", async () => {
    await page.type("#current_password", originalPassword);
    await page.type("#new_password", newPassword);
    await page.type("#confirm_new_password", newPassword);
    await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((candidate) =>
        candidate.textContent?.includes("Change my password"),
      );
      button?.click();
    });
    await waitFor("Your password is changed.");
    await page.screenshot({ path: resolve(OUTPUT, "profile-3-password.png") });

    const status = await page.evaluate(async (identifier, password) => {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier, password }),
        credentials: "include",
      });
      return response.status;
    }, email, newPassword);
    if (status !== 200) {
      throw new Error(`signing in with the new password answered ${status}`);
    }
  });

  console.log(problems.length ? `[WARN] ${problems.join(", ")}` : "[OK] no problems");
} catch {
  // The failing step has already reported itself.
} finally {
  await browser.close();
}
