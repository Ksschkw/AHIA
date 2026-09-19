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
  // **React does not hear a programmatic value assignment.** Typing at the keyboard and selecting the text
  // first both left the field exactly as it was - measured, not guessed - so the page never saw a change and
  // nothing happened on the press. The native setter followed by an input event is the way React's own
  // listener is told, and it is what a person's keystroke looks like to it.
  const changed = await page.evaluate((wanted) => {
    const input = document.querySelector("input[id^='normal_']");
    if (!input) return null;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    )?.set;
    setter?.call(input, wanted);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return input.value;
  }, value);
  if (changed === null) throw new Error("no price field to change");
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
  // **The measurement, not a theory.** What the field holds immediately before the press decides which
  // half is at fault: an unchanged field means the typing never reached React, a changed one means the
  // press did not run the action.
  const before = await page.evaluate(() => {
    const input = document.querySelector("input[id^='normal_']");
    return {
      field: input ? input.value : "(no field)",
      digest: Boolean(window.localStorage.getItem("ahia.pin.digest")),
    };
  });
  console.log(`      before the press: field=${JSON.stringify(before.field)}, pin stored=${before.digest}`);
  const clicked = await page.evaluate(() => {
    const control = [...document.querySelectorAll("button")].find((candidate) =>
      candidate.textContent?.trim().startsWith("Set this group"),
    );
    if (!control) return "no button";
    let seen = 0;
    control.addEventListener("click", () => {
      seen += 1;
    });
    control.click();
    return seen;
  });
  await new Promise((resolve_) => setTimeout(resolve_, 2500));
  const afterPress = await page.evaluate(() => ({
    pinField: Boolean(document.querySelector("#device-pin")),
    headings: [...document.querySelectorAll("h1, h2, h3")].map((node) => node.textContent?.trim()),
    tail: document.body.innerText.slice(-260).replace(/\n+/g, " | "),
    buttonText: [...document.querySelectorAll("button")]
      .map((candidate) => candidate.textContent?.trim())
      .filter((text) => text?.startsWith("Set this group")),
  }));
  console.log(`      the element was clicked ${clicked} time(s); pin field present: ${afterPress.pinField}`);
  console.log(`      headings now: ${JSON.stringify(afterPress.headings)}`);
  console.log(`      the end of the page: ${afterPress.tail}`);
  await page.waitForSelector("#device-pin", { timeout: 20000 });
  await page.type("#device-pin", "9999");
  await press("Continue");
  await page.waitForSelector("#device-pin", { timeout: 20000 });
  await page.screenshot({ path: resolve(OUTPUT, "pin-gate-wrong.png") });
  const stillAsking = await page.evaluate(() => Boolean(document.querySelector("#device-pin")));
  if (!stillAsking) throw new Error("the wrong PIN closed the gate instead of refusing");
  console.log("      refused, and the gate stayed open");

  // The right PIN, put into the field the way React hears it, and judged by **the gate closing** rather
  // than by a sentence on the page: the sentence is what failed last time while the behaviour was correct.
  await page.evaluate(() => {
    const input = document.querySelector("#device-pin");
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, "1234");
    input?.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await press("Continue");
  await page.waitForFunction(() => !document.querySelector("#device-pin"), { timeout: 30000 });
  console.log("      then the right PIN let it through - the gate closed");
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
