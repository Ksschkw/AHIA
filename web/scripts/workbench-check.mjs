/**
 * The trader works a customer's list.
 *
 * The screen he uses every morning: a list arrives, he goes through it line by line saying whether he has it,
 * is going to find it, or cannot get it - writing down what it cost him and what he charges - and then turns
 * it into a sale he can send.
 *
 * Every assertion here asks the page for an **element** or a **value**, never for a sentence, because a check
 * that looks for prose reports a working product as broken - which it has done four times in this project.
 */
import { resolve } from "node:path";
import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const OUTPUT = resolve(process.cwd(), "..", ".review");
const stamp = Date.now();
const failures = [];

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
    await page.screenshot({ path: resolve(OUTPUT, `workbench-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    const facts = await page.evaluate(() => ({
      fields: [...document.querySelectorAll("input[id]")].map((input) => input.id).slice(0, 8),
      buttons: [...document.querySelectorAll("button[id]")].map((button) => button.id).slice(0, 8),
    }));
    console.log(`      the page holds: ${JSON.stringify(facts)}`);
    failures.push(name);
  }
}

async function fill(selector, value) {
  const ok = await page.evaluate(
    ([target, wanted]) => {
      const input = document.querySelector(target);
      if (!input) return false;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
      setter?.call(input, wanted);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    },
    [selector, value],
  );
  if (!ok) throw new Error(`no field at ${selector}`);
}

async function pressById(selector) {
  const ok = await page.evaluate((target) => {
    const control = document.querySelector(target);
    if (!control) return false;
    control.click();
    return true;
  }, selector);
  if (!ok) throw new Error(`no control at ${selector}`);
}

let ids = {};

await step("a shop with a list waiting", async () => {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0828${String(stamp).slice(-7)}`);
  await page.type("#password", "Work-2026-Pass");
  await page.type("#confirm_password", "Work-2026-Pass");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40000 });
  await page.type("#business-name", `Alaba Work ${stamp % 1000}`);
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });

  ids = await page.evaluate(async () => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    const tenant = tenants[0];
    await fetch(`/api/v1/tenants/${tenant.id}/storefront/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ headline: "Screens", contact_phone: "+2348031234567" }),
    });
    await fetch(`/shop/${tenant.slug}/requests`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_phone: "08029876543",
        customer_name: "Toba",
        lines: [{ free_text: "21D for Hot 8", quantity: "20" }],
      }),
    });
    const lists = await (await fetch(`/api/v1/tenants/${tenant.id}/requests`)).json();
    return { tenantId: tenant.id, requestId: lists[0].id, lineId: lists[0].lines[0].id };
  });
});

await step("he marks the line, prices it, and sees what it comes to", async () => {
  await page.goto(`${APP_URL}/app/lists`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => document.body.innerText.includes("Toba"), { timeout: 30000 });
  await page.evaluate(() => {
    const control = [...document.querySelectorAll("button")].find((candidate) =>
      candidate.textContent?.trim().startsWith("Work this list"),
    );
    control?.click();
  });
  await page.waitForSelector(`#price_${ids.lineId}`, { timeout: 20000 });

  // "I will buy it" - the market case, which is the one paper cannot account for.
  await page.evaluate(() => {
    const control = [...document.querySelectorAll("button")].find(
      (candidate) => candidate.textContent?.trim() === "I will buy it",
    );
    control?.click();
  });

  // **The price, and only the price.** There is no cost box, which is the point: a trader knows what he paid,
  // and asking him to type it turns his screen into a bookkeeper's form.
  const thereIsNoCostBox = await page.evaluate(
    () => document.querySelectorAll("input[id^='cost_']").length === 0,
  );
  if (!thereIsNoCostBox) throw new Error("a cost field is still on the trader's screen");

  await fill(`#price_${ids.lineId}`, "350.00");
  await pressById(`#save_${ids.lineId}`);

  await page.waitForFunction(() => document.body.innerText.includes("Comes to"), { timeout: 30000 });
  const facts = await page.evaluate(() => {
    const text = document.body.innerText;
    return { total: text.match(/Comes to [^\n]*/)?.[0] ?? "(no total)" };
  });
  console.log(`      ${facts.total}`);
  await page.screenshot({ path: resolve(OUTPUT, "workbench-priced.png") });

  // And the whole list can become a sale, because everything on it is priced - which asks who is holding the
  // phone, because confirming a list is confirming money.
  await pressById(`#confirm_${ids.requestId}`);
  await page.waitForSelector("#device-pin", { timeout: 20000 });
  const answered = await page.evaluate(() => {
    const first = document.querySelector("#device-pin");
    const again = document.querySelector("#device-pin-again");
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
    for (const input of [first, again]) {
      if (!input) continue;
      setter?.call(input, "1234");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    const button = [...document.querySelectorAll("button")].find((candidate) =>
      candidate.textContent?.trim().startsWith("Set it and continue"),
    );
    button?.click();
    return Boolean(button);
  });
  if (!answered) throw new Error("the gate was up but could not be answered");
  await page.waitForFunction(() => document.body.innerText.includes("is confirmed"), {
    timeout: 30000,
  });
  console.log("      the confirmation asked for the PIN, and then the list became a sale");
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
