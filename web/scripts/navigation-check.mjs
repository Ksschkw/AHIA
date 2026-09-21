/**
 * Tapping a page should not cost a session.
 *
 * Every screen used to resolve the user, the business list and the business detail before asking for its own
 * data - four round trips, and a spinner until the last one landed. This counts what a tap actually costs now,
 * and how long the page takes to show something.
 */
import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const stamp = Date.now();
const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();
await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });

let calls = [];
page.on("request", (request) => {
  if (request.method() === "GET" && request.url().includes("/api/v1/")) {
    calls.push(request.url().replace(/^.*\/api\/v1\//, ""));
  }
});

await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
await page.waitForSelector("#first_name", { timeout: 40000 });
await page.type("#first_name", "Tap");
await page.type("#last_name", "Test");
await page.type("#phone", `0835${String(stamp).slice(-7)}`);
await page.type("#password", "Tap-2026-Pass");
await page.type("#confirm_password", "Tap-2026-Pass");
await page.click('button[type="submit"]');
await page.waitForSelector("#business-name", { timeout: 40000 });
await page.type("#business-name", `Tap Shop ${stamp % 1000}`);
await page.evaluate(() => {
  const button = [...document.querySelectorAll("button")].find((b) =>
    b.textContent?.trim().startsWith("Create business"),
  );
  button?.click();
});
await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });

// Warm: visit both pages once, as a person would.
for (const path of ["/app", "/app/sales"]) {
  await page.goto(`${APP_URL}${path}`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => !document.body.innerText.includes("Opening"), { timeout: 20000 });
}

// **The measurement.** Reset the counter, then tap the way a person taps.
calls = [];
const started = Date.now();
await Promise.all([
  page.waitForFunction(() => window.location.pathname === "/app/sales", { timeout: 15000 }),
  page.evaluate(() => {
    const link = [...document.querySelectorAll("a")].find((a) =>
      a.getAttribute("href") === "/app/sales",
    );
    link?.click();
  }),
]);
await page.waitForFunction(() => document.body.innerText.includes("Sales"), { timeout: 15000 });
const elapsed = Date.now() - started;
console.log(`      tapping Sales cost ${calls.length} request(s): ${JSON.stringify(calls)}`);
console.log(`      and it showed its content ${elapsed}ms after the tap`);

// A soft word on the goal, not a hard gate: the point is that it is no longer four.
if (calls.length > 2) {
  console.log(`[FAIL] a tap still costs ${calls.length} requests`);
  process.exitCode = 1;
} else {
  console.log("[OK] a tap costs the page's own data and nothing else");
}
await browser.close();
