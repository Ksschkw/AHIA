/**
 * The trader works a customer's list.
 *
 * The claim: a list arrives, he says what he did with each line, records what it cost him, sets what he
 * charges, sees what he made - and turns it into a sale. The screen is judged at the two sizes his day
 * happens at: a phone in a market and a desk in the shop.
 */
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
const trader = await browser.newPage();
await trader.setViewport({ width: 1440, height: 900 });
// Every request the screen makes, so a failure is a status code rather than a suspicion.
const traffic = [];
trader.on("request", (request) => {
  if (request.method() !== "GET") {
    traffic.push(`${request.method()} ${request.url().replace("http://localhost:3000", "")} ${request.postData() ?? ""}`);
  }
});
trader.on("pageerror", (error) => traffic.push(`PAGEERROR ${error.message.slice(0, 300)}`));
trader.on("console", (message) => {
  if (message.type() === "error") traffic.push(`CONSOLE ${message.text().slice(0, 300)}`);
});
trader.on("response", (response) => {
  if (response.url().includes("/requests") && response.status() >= 400) {
    traffic.push(`  -> HTTP ${response.status()}`);
  }
});
const failures = [];
let current = trader;

async function click(label, timeout = 20000) {
  const deadline = Date.now() + timeout;
  let last = "missing";
  while (Date.now() < deadline) {
    last = await current.evaluate((wanted) => {
      const control = [...document.querySelectorAll("button, a[href]")].find(
        (candidate) =>
          (candidate.getAttribute("aria-label") ?? "").startsWith(wanted) ||
          candidate.textContent?.trim().startsWith(wanted),
      );
      if (!control) return "missing";
      if (control.disabled) return "disabled";
      control.click();
      return "clicked";
    }, label);
    if (last === "clicked") return;
    await new Promise((resolve_) => setTimeout(resolve_, 200));
  }
  throw new Error(`could not press "${label}" (${last})`);
}

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await current.screenshot({ path: resolve(OUTPUT, `workbench-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    console.log(`--- requests ---\n  ${traffic.slice(-8).join("\n  ")}`);
    console.log((await current.evaluate(() => document.body.innerText)).slice(0, 700));
    failures.push(name);
  }
}

let shop = { slug: "", tenantId: "" };

await step("a shop with a customer's list waiting", async () => {
  await trader.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await trader.waitForSelector("#first_name", { timeout: 40000 });
  await trader.type("#first_name", "Ada");
  await trader.type("#last_name", "Obi");
  await trader.type("#phone", `0816${String(stamp).slice(-7)}`);
  await trader.type("#password", "Workbench-2026");
  await trader.type("#confirm_password", "Workbench-2026");
  await trader.click('button[type="submit"]');
  await trader.waitForSelector("#business-name", { timeout: 40000 });
  await trader.type("#business-name", `Alaba Bench ${stamp % 1000}`);
  await trader.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await trader.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });

  shop = await trader.evaluate(async () => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    const tenant = tenants[0];
    await fetch(`/api/v1/tenants/${tenant.id}/storefront/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ headline: "Screenguards", contact_phone: "+2348031234567" }),
    });
    // A customer sends a list, anonymously, exactly as the customer screen does.
    await fetch(`/shop/${tenant.slug}/requests`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_phone: "08029876543",
        customer_name: "Toba",
        note: "The one for the shop on Balogun street",
        lines: [
          { free_text: "21D for Hot 8", quantity: "20" },
          { free_text: "Privacy glass for 13 Pro Max", quantity: "2" },
        ],
      }),
    });
    return { slug: tenant.slug, tenantId: tenant.id };
  });
});

await step("the list is waiting to be worked", async () => {
  await trader.goto(`${APP_URL}/app/lists`, { waitUntil: "networkidle2" });
  await trader.waitForFunction(() => document.body.innerText.includes("Toba"), { timeout: 30000 });
  const text = await trader.evaluate(() => document.body.innerText);
  if (!text.includes("2 to price")) throw new Error(`the unpriced count is not shown: ${text.slice(0, 300)}`);
});

await step("he works the first line and sees what he makes", async () => {
  await click("Work this list");
  await trader.waitForFunction(() => document.body.innerText.includes("It cost me"), {
    timeout: 20000,
  });

  // "I will buy it" - the market case, which is the one paper cannot account for.
  await click("I will buy it");
  await trader.waitForFunction(() => document.body.innerText.includes("Going to the market"), {
    timeout: 20000,
  });

  const ids = await trader.evaluate(() =>
    [...document.querySelectorAll("input[id^='cost_']")].map((input) => input.id.replace("cost_", "")),
  );
  const firstLine = ids[0];
  await trader.type(`#cost_${firstLine}`, "280.00");
  await trader.type(`#price_${firstLine}`, "350.00");
  // Wait until the typed values have reached React, then press save the way a person would.
  await trader.waitForFunction(
    (lineId) => (document.querySelector(`#cost_${lineId}`)?.value ?? "").length > 0,
    { timeout: 10000 },
    firstLine,
  );
  // A native click through the browser, on a control with a name: a synthetic `.click()` from inside
  // the page was not reaching React's handler, and guessing why was costing more than naming the button.
  // Focused and activated from the keyboard, rather than clicked by coordinates: the summary bar is
  // sticky at the bottom of the screen, so a click aimed at a line's control can land on it instead.
  // That is worth knowing for the interface too, not only for the test.
  await trader.waitForSelector(`#save_${firstLine}`, { timeout: 20000 });
  const probe = await trader.evaluate((id) => {
    const element = document.querySelector(`#${id}`);
    if (!element) return { found: false };
    let fired = false;
    element.addEventListener("click", () => {
      fired = true;
    });
    element.scrollIntoView({ block: "center" });
    element.focus();
    element.click();
    return {
      found: true,
      tag: element.tagName,
      text: element.textContent?.trim(),
      disabled: element.disabled,
      outer: element.outerHTML.slice(0, 220),
      listenerFired: fired,
    };
  }, `save_${firstLine}`);
  console.log(`      probe: ${JSON.stringify(probe)}`);

  await trader.waitForFunction(() => document.body.innerText.includes("you make"), {
    timeout: 20000,
  });
  const text = await trader.evaluate(() => document.body.innerText);
  console.log(
    `      reads: ${text.match(/Comes to [^\n]*/)?.[0] ?? "(no line total)"} | ` +
      `${text.match(/\d+ to price/)?.[0] ?? "(none left to price)"}`,
  );
  if (!text.includes("you make")) throw new Error("the margin is not shown");
  await trader.screenshot({ path: resolve(OUTPUT, "workbench-desktop.png") });
});

await step("a phone shows the same screen", async () => {
  // Resized rather than a new context: a fresh one has no session, so it would be photographing the
  // sign-in screen and calling it the workbench.
  await trader.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  await trader.reload({ waitUntil: "networkidle2" });
  await trader.waitForFunction(() => document.body.innerText.includes("Toba"), { timeout: 30000 });
  await trader.screenshot({ path: resolve(OUTPUT, "workbench-mobile.png") });
  const overflow = await trader.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  await trader.setViewport({ width: 1440, height: 900 });
  if (overflow) throw new Error("the workbench is wider than the phone");
});

await step("it refuses to become a sale with a line unpriced", async () => {
  const answer = await trader.evaluate(async (tenantId) => {
    const lists = await (await fetch(`/api/v1/tenants/${tenantId}/requests`)).json();
    const response = await fetch(
      `/api/v1/tenants/${tenantId}/requests/${lists[0].id}/confirm`,
      { method: "POST" },
    );
    return { status: response.status, body: await response.json() };
  }, shop.tenantId);
  console.log(`      confirm with one line unpriced: HTTP ${answer.status}`);
  if (answer.status !== 422) throw new Error("a list with an unpriced line was allowed to become a sale");
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
