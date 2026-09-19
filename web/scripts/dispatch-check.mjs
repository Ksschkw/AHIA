/**
 * The trader sends a list, from his phone.
 *
 * A customer's list is priced and confirmed, and then the trader writes down who is carrying it, the waybill
 * number, what the trip cost and where to follow it - and the list reads it back. That is the journey this
 * checks, at 390x844, because that is where he does it.
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
    await page.screenshot({ path: resolve(OUTPUT, `dispatch-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    failures.push(name);
  }
}

/** Put a value in a field the way React hears it, and press a control by its id. */
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

await step("a shop with a confirmed list", async () => {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0826${String(stamp).slice(-7)}`);
  await page.type("#password", "Dispatch-2026");
  await page.type("#confirm_password", "Dispatch-2026");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40000 });
  await page.type("#business-name", `Alaba Send ${stamp % 1000}`);
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
        lines: [{ free_text: "21D for Hot 8", quantity: "20" }],
      }),
    });
    const lists = await (await fetch(`/api/v1/tenants/${tenant.id}/requests`)).json();
    const list = lists[0];
    await fetch(`/api/v1/tenants/${tenant.id}/requests/${list.id}/lines/${list.lines[0].id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: "buy_it", cost_price: "280.00", shop_price: "350.00" }),
    });
    await fetch(`/api/v1/tenants/${tenant.id}/requests/${list.id}/confirm`, { method: "POST" });
    return { tenantId: tenant.id, requestId: list.id };
  });
});

await step("the waybill is written down and read back", async () => {
  await page.goto(`${APP_URL}/app/lists`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => document.body.innerText.includes("Work this list"), {
    timeout: 30000,
  });
  // Open the list: the control that expands it is the only button reading "Work this list".
  await page.evaluate(() => {
    const control = [...document.querySelectorAll("button")].find((candidate) =>
      candidate.textContent?.trim().startsWith("Work this list"),
    );
    control?.click();
  });
  await page.waitForFunction(() => document.body.innerText.includes("Send it"), { timeout: 20000 });

  await fill(`#transporter_${ids.requestId}`, "Emeka Motors");
  await fill(`#waybill_${ids.requestId}`, "WB-4471");
  await fill(`#dispatch_cost_${ids.requestId}`, "1500.00");
  await fill(`#tracking_${ids.requestId}`, "https://track.example/WB-4471");
  await pressById(`#dispatch_${ids.requestId}`);

  // The list reads it back, which is the whole point of writing it down.
  await page.waitForFunction(() => document.body.innerText.includes("How it went"), {
    timeout: 30000,
  });
  const readBack = await page.evaluate(() => {
    const text = document.body.innerText;
    const line = text.match(/[^\n]*Emeka Motors[^\n]*/)?.[0] ?? "(no line)";
    return { line, hasCost: text.includes("1,500") };
  });
  console.log(`      the list reads back: ${readBack.line}`);
  if (!readBack.line.includes("WB-4471")) throw new Error("the waybill number is not on the list");
  if (!readBack.hasCost) throw new Error("what the trip cost is not on the list");
  await page.screenshot({ path: resolve(OUTPUT, "dispatch-sent.png") });
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
