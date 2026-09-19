/**
 * The gate's own journey, walked the way a trader would.
 *
 * The claim M25.2 makes: changing a price asks who is holding the phone, a phone with no PIN sets one the
 * first time, a wrong PIN does not go through, and the right one does. A gate nobody has walked through is a
 * gate nobody knows is locked, so this walks it.
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
    await page.screenshot({ path: resolve(OUTPUT, `pin-gate-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    failures.push(name);
  }
}

/**
 * Put a value in a price field, replacing what is there.
 *
 * Typing appends, and a price that has been appended to is a number the API refuses - which is how the
 * first run of this check reported a gate that did not let the action through, when the gate was fine and
 * the number was not.
 */
async function setPriceTo(value) {
  const cleared = await page.evaluate(() => {
    const input = document.querySelector("input[id^='normal_']");
    if (!input) return false;
    input.focus();
    input.setSelectionRange(0, input.value.length);
    return true;
  });
  if (!cleared) throw new Error("no price field to change");
  await page.keyboard.press("Backspace");
  await page.type("input[id^='normal_']", value);
}

async function press(label) {
  const clicked = await page.evaluate((wanted) => {
    const control = [...document.querySelectorAll("button")].find(
      (candidate) => candidate.textContent?.trim().startsWith(wanted),
    );
    if (!control) return false;
    control.click();
    return true;
  }, label);
  if (!clicked) throw new Error(`could not find a control starting with "${label}"`);
}

await step("a shop with a group to price", async () => {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0823${String(stamp).slice(-7)}`);
  await page.type("#password", "Pin-2026-Pass");
  await page.type("#confirm_password", "Pin-2026-Pass");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40000 });
  await page.type("#business-name", `Alaba Pin ${stamp % 1000}`);
  await press("Create business");
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });
  await page.evaluate(async () => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    await fetch(`/api/v1/tenants/${tenants[0].id}/categories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "21D", default_normal_price: "350.00" }),
    });
  });
});

await step("the first price change asks for a PIN to be set", async () => {
  await page.goto(`${APP_URL}/app/prices`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => document.body.innerText.includes("21D"), { timeout: 30000 });
  await setPriceTo("360");
  await press("Set this group");
  await page.waitForFunction(
    () => document.body.innerText.includes("Set a PIN for this phone"),
    { timeout: 20000 },
  );
  await page.screenshot({ path: resolve(OUTPUT, "pin-gate-first.png") });
  console.log("      the gate reads: Set a PIN for this phone");
  await page.type("#device-pin", "1234");
  await page.type("#device-pin-again", "1234");
  await press("Set it and continue");
  await page.waitForFunction(
    () => document.body.innerText.includes("follows this now"),
    { timeout: 30000 },
  );
  console.log("      and the change went through after the PIN was set");
});

await step("a wrong PIN does not move a price", async () => {
  await page.goto(`${APP_URL}/app/prices`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => document.body.innerText.includes("21D"), { timeout: 30000 });
  await setPriceTo("361");
  console.log(
    `      stored before the second change: ${await page.evaluate(() =>
      JSON.stringify({ digest: Boolean(window.localStorage.getItem("ahia.pin.digest")) }),
    )}`,
  );
  await press("Set this group");
  await new Promise((resolve_) => setTimeout(resolve_, 3000));
  console.log(
    `      after pressing, the screen says: ${(await page.evaluate(() => document.body.innerText))
      .replace(/\n+/g, " | ")
      .slice(0, 220)}`,
  );
  await page.waitForFunction(() => document.body.innerText.includes("Enter your PIN"), {
    timeout: 20000,
  });
  await page.type("#device-pin", "9999");
  await press("Continue");
  await page.waitForFunction(() => document.body.innerText.includes("not the PIN for this phone"), {
    timeout: 20000,
  });
  await page.screenshot({ path: resolve(OUTPUT, "pin-gate-wrong.png") });
  const stillAsking = await page.evaluate(() =>
    document.body.innerText.includes("Enter your PIN"),
  );
  if (!stillAsking) throw new Error("the wrong PIN closed the gate instead of refusing");
  console.log("      refused, and the gate stayed open");

  await page.type("#device-pin", "1234");
  await press("Continue");
  await page.waitForFunction(() => document.body.innerText.includes("follows this now"), {
    timeout: 30000,
  });
  console.log("      then the right PIN let it through");
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
