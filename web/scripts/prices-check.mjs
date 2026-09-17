/**
 * The price book: one number for a grade, and the exceptions that carry their own.
 *
 * The claim being tested is the product owner's own sentence - "all of the 21D are 350, but Hot 8 is
 * 370" - so the check sets a group price, watches the items under it follow, overrides one item, and
 * then clears the override and watches it follow again.
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
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1000 });

const failures = [];

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await page.screenshot({ path: resolve(OUTPUT, `prices-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    console.log((await page.evaluate(() => document.body.innerText)).slice(0, 900));
    failures.push(name);
  }
}

const waitFor = (text, timeout = 40_000) =>
  page.waitForFunction((wanted) => document.body.innerText.includes(wanted), { timeout }, text);

async function click(label, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const outcome = await page.evaluate((wanted) => {
      const dialog = document.querySelector('[role="dialog"]');
      const scope = dialog ?? document.body;
      const control = [...scope.querySelectorAll("button, a[href]")].find(
        (candidate) =>
          (candidate.getAttribute("aria-label") ?? "").startsWith(wanted) ||
          candidate.textContent?.trim().startsWith(wanted),
      );
      if (!control) return "missing";
      if (control.disabled) return "disabled";
      control.click();
      return "clicked";
    }, label);
    if (outcome === "clicked") return;
    await new Promise((resolve_) => setTimeout(resolve_, 200));
  }
  throw new Error(`no usable control starting with "${label}"`);
}

async function type(selector, text) {
  await page.waitForSelector(selector, { timeout: 40_000 });
  await page.click(selector, { clickCount: 3 });
  await page.type(selector, text);
}

await step("an account with a group and two items", async () => {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40_000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0806${String(stamp).slice(-7)}`);
  await page.type("#password", "Prices-Password-2026");
  await page.type("#confirm_password", "Prices-Password-2026");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40_000 });
  await page.type("#business-name", `Price Shop ${stamp % 1000}`);
  await click("Create business");
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40_000 });

  // Two items under one grade, the way a real catalogue starts.
  for (const name of ["Screenguard Hot 8", "Screenguard Camon 30"]) {
    await click("Add a product");
    await type("#new-product", name);
    await type("#new-price", "500");
    await click("Add to the shelf");
    await waitFor(name);
    await click("Dismiss");
  }
});

await step("a group is created", async () => {
  await page.goto(`${APP_URL}/app/prices`, { waitUntil: "networkidle2" });
  await type("#new_group", "21D");
  await click("Add group");
  await waitFor("Group added");
});

let groupSelector = "";
await step("one price covers everything under the group", async () => {
  groupSelector = await page.evaluate(() => {
    const input = [...document.querySelectorAll("input")].find((candidate) =>
      candidate.id.startsWith("normal_"),
    );
    return input ? input.id.replace("normal_", "") : "";
  });
  await type(`#normal_${groupSelector}`, "500");
  await type(`#wholesale_${groupSelector}`, "350");
  await type(`#pack_${groupSelector}`, "10");
  await click("Set this group");
  await waitFor("Everything under 21D follows this now");
  await page.screenshot({ path: resolve(OUTPUT, "prices-1-group.png") });
});

await step("both items are filed under the group and follow it", async () => {
  await click("Dismiss");
  for (const name of ["Screenguard Hot 8", "Screenguard Camon 30"]) {
    const selector = await page.evaluate((wanted) => {
      const row = [...document.querySelectorAll("li")].find((candidate) =>
        candidate.innerText.includes(wanted),
      );
      const select = row?.querySelector("select");
      return select ? `#${select.id}` : null;
    }, name);
    if (!selector) {
      throw new Error(`${name} has no group picker`);
    }
    await page.select(selector, groupSelector);
  }
  await waitFor("now follows a group");
  await click("Dismiss");

  // The items were added with a price of their own, so they are exceptions until that is cleared -
  // which is exactly the distinction this screen exists to show.
  for (const name of ["Screenguard Hot 8", "Screenguard Camon 30"]) {
    const cleared = await page.evaluate((wanted) => {
      const row = [...document.querySelectorAll("li")].find((candidate) =>
        candidate.innerText.includes(wanted),
      );
      const button = [...(row?.querySelectorAll("button") ?? [])].find((candidate) =>
        candidate.textContent?.trim().startsWith("Follow the group"),
      );
      button?.click();
      return Boolean(button);
    }, name);
    if (!cleared) {
      throw new Error(`${name} has no way to stop carrying its own price`);
    }
    await waitFor("follows 21D again");
    await click("Dismiss");
  }

  const text = await page.evaluate(() => document.body.innerText);
  for (const name of ["Screenguard Hot 8", "Screenguard Camon 30"]) {
    if (!text.includes(name)) {
      throw new Error(`${name} is not listed under the group`);
    }
  }
  if (!text.includes("Follows the group")) {
    throw new Error("neither item is marked as following the group");
  }
  if (!text.includes("NGN 350.00") && !text.includes("350.00")) {
    throw new Error(`the wholesale price is not shown: ${text.slice(0, 300)}`);
  }
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
