// Screenshots at the two sizes the product is judged at, after signing in.
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

async function signUp(page) {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0809${String(stamp).slice(-7)}`);
  await page.type("#password", "Shots-Password-2026");
  await page.type("#confirm_password", "Shots-Password-2026");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40000 });
  await page.type("#business-name", `Shot Shop ${stamp % 1000}`);
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });
}

// One account, two sizes: registering twice trips the local auth rate limit, and the point here is
// the frame at two widths rather than two accounts.
const context = await browser.createBrowserContext();
const page = await context.newPage();
await page.setViewport({ width: 1440, height: 900 });
await signUp(page);

for (const [label, viewport] of [
  ["mobile", { width: 390, height: 844, isMobile: true, hasTouch: true }],
  ["desktop", { width: 1440, height: 900 }],
]) {
  await page.setViewport(viewport);
  await page.goto(`${APP_URL}/app`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => document.body.innerText.includes("Record a sale"), {
    timeout: 40000,
  });
  await page.screenshot({ path: resolve(OUTPUT, `shell-${label}.png`), fullPage: false });

  const navigation = await page.evaluate(() => {
    const links = [...document.querySelectorAll("nav a")].map((a) => a.textContent?.trim());
    const current = [...document.querySelectorAll('nav a[aria-current="page"]')].map((a) =>
      a.textContent?.trim(),
    );
    const overflow = document.documentElement.scrollWidth > window.innerWidth;
    const bar = document.querySelector("nav[aria-label='Sections']:last-of-type");
    const barVisible = bar ? getComputedStyle(bar).display !== "none" : false;
    return { count: links.length, current: current.join("|"), overflow, barVisible };
  });
  console.log(
    `${label}: ${navigation.count} destinations, current=${navigation.current}, overflow=${navigation.overflow}, bottombar=${navigation.barVisible}`,
  );

  if (label === "mobile") {
    // Everything must be reachable from the bar, and the choice of what is pinned must stick.
    const opened = await page.evaluate(() => {
      const more = [...document.querySelectorAll("button")].find((b) =>
        b.textContent?.trim().startsWith("More"),
      );
      more?.click();
      return Boolean(more);
    });
    if (!opened) {
      throw new Error("the phone's bar has no way to reach the rest");
    }
    await page.waitForFunction(() => document.body.innerText.includes("Everything"), {
      timeout: 10000,
    });
    await page.screenshot({ path: resolve(OUTPUT, "shell-mobile-more.png") });
    const listed = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]');
      return dialog ? dialog.innerText.split("\n").length : 0;
    });
    console.log(`mobile: the More sheet lists ${listed} lines`);
  }
}

await context.close();
await browser.close();
