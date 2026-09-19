/**
 * A pressed control cannot be pressed again while it is working.
 *
 * Removing somebody from the team runs a request. The control is disabled while it runs - and that claim is
 * about behaviour under a fast double press, so it is measured by counting the requests a double press causes.
 * One request, not two: two is how somebody repeats a removal they believe failed.
 */
import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const stamp = Date.now();
const failures = [];

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});
const page = await browser.newPage();
await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });

const removals = [];
page.on("request", (request) => {
  if (request.method() !== "GET" && /memberships|members\//.test(request.url())) {
    removals.push(`${request.method()} ${request.url().split("/api/v1/")[1]}`);
  }
});

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    console.log(`[FAIL] ${name}: ${error.message}`);
    failures.push(name);
  }
}

await step("a team with somebody on it", async () => {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0830${String(stamp).slice(-7)}`);
  await page.type("#password", "Team-2026-Pass");
  await page.type("#confirm_password", "Team-2026-Pass");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40000 });
  await page.type("#business-name", `Alaba Team ${stamp % 1000}`);
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });

  const invited = await page.evaluate(async () => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    const tenant = tenants[0];
    // The path and the body the app itself uses: `/members`, with a role and a phone. The first version of
    // this asked for `/invitations`, which answered nothing useful, so the setup quietly measured a guard
    // against whoever was already there instead of somebody it had added.
    const response = await fetch(`/api/v1/tenants/${tenant.id}/members`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: "08111111111", role_name: "SALES" }),
    });
    if (!response.ok) return `the invitation was refused: ${response.status} ${await response.text()}`;
    const invitation = await response.json();
    return Boolean(invitation.id ?? invitation.token);
  });
  if (invited !== true) {
    throw new Error(typeof invited === "string" ? invited : "nobody was invited");
  }
  console.log("      somebody is on the team to remove");
});

await step("a double press sends one request, not two", async () => {
  await page.goto(`${APP_URL}/app/team`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => document.querySelectorAll("button[id^='member_remove_']").length > 0, {
    timeout: 30000,
  });

  // **Only the request count is measured, and the reason is worth keeping.** Reading `disabled` in the same
  // tick as the click always reports `false`: React applies the attribute on the next render, which is why the
  // attribute was never the guard. Counting the requests a double press causes is a fact about behaviour; the
  // attribute is a fact about a moment that has not happened yet.
  await page.evaluate(() => {
    const control = document.querySelector("button[id^='member_remove_']");
    control.click();
    control.click();
  });
  await new Promise((resolve_) => setTimeout(resolve_, 3000));
  const after = await page.evaluate(() => {
    const control = document.querySelector("button[id^='member_remove_']");
    return control ? control.disabled : null;
  });
  console.log(`      requests caused by a double press: ${removals.length}`);
  console.log(`      and the control ends up disabled: ${after}`);
  if (removals.length !== 1) {
    throw new Error(`a double press caused ${removals.length} requests; it must cause one`);
  }
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
