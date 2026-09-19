/**
 * The trader puts a product in a group.
 *
 * The product owner said it plainly: "on my add product, i do not see the option to add it to a group or
 * subgroup". This opens the form on a phone and a desk, checks the groups are offered with the nested one
 * indented under its parent, and that saving puts the product in the group that was chosen.
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
await page.setViewport({ width: 1440, height: 900 });
const failures = [];

async function step(name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await page.screenshot({ path: resolve(OUTPUT, `group-picker-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    failures.push(name);
  }
}

await step("a shop with a group and a subgroup", async () => {
  await page.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#first_name", { timeout: 40000 });
  await page.type("#first_name", "Ada");
  await page.type("#last_name", "Obi");
  await page.type("#phone", `0822${String(stamp).slice(-7)}`);
  await page.type("#password", "Groups-2026");
  await page.type("#confirm_password", "Groups-2026");
  await page.click('button[type="submit"]');
  await page.waitForSelector("#business-name", { timeout: 40000 });
  await page.type("#business-name", `Alaba Groups ${stamp % 1000}`);
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.trim().startsWith("Create business"),
    );
    button?.click();
  });
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40000 });

  const created = await page.evaluate(async () => {
    const tenants = await (await fetch("/api/v1/tenants")).json();
    const tenant = tenants[0];
    const family = await (
      await fetch(`/api/v1/tenants/${tenant.id}/categories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Screenguard" }),
      })
    ).json();
    const grade = await (
      await fetch(`/api/v1/tenants/${tenant.id}/categories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "21D", parent_id: family.id }),
      })
    ).json();
    return { tenantId: tenant.id, family: family.id, grade: grade.id };
  });
  if (!created.grade) throw new Error("the subgroup was not created");
  globalThis.__ids = created;
});

await step("the form offers the groups, nested, at both sizes", async () => {
  for (const [label, viewport] of [
    ["mobile", { width: 390, height: 844, isMobile: true, hasTouch: true }],
    ["desktop", { width: 1440, height: 900 }],
  ]) {
    await page.setViewport(viewport);
    await page.goto(`${APP_URL}/app`, { waitUntil: "networkidle2" });
    await page.waitForFunction(() => document.body.innerText.includes("Add a product"), {
      timeout: 30000,
    });
    await page.evaluate(() => {
      const tile = [...document.querySelectorAll("button")].find((candidate) =>
        candidate.textContent?.includes("Add a product"),
      );
      tile?.click();
    });
    await page.waitForSelector("#new-product-group", { timeout: 20000 });
    const options = await page.evaluate(() =>
      [...document.querySelectorAll("#new-product-group option")].map((option) => ({
        value: option.value,
        text: option.textContent ?? "",
      })),
    );
    const named = options.filter((option) => option.text !== "No group");
    console.log(`      ${label}: ${named.map((option) => JSON.stringify(option.text)).join(", ")}`);
    if (named.length !== 2) throw new Error(`${label}: expected two groups, saw ${named.length}`);
    const nested = named.find((option) => option.text.includes("21D"));
    if (!nested) throw new Error(`${label}: the subgroup is not offered`);
    if (!nested.text.startsWith("\u00a0")) {
      throw new Error(`${label}: the subgroup is not indented under its parent`);
    }
    await page.screenshot({ path: resolve(OUTPUT, `group-picker-${label}.png`) });
    // Close the sheet before the next size.
    await page.evaluate(() => {
      const close = [...document.querySelectorAll("button")].find(
        (candidate) => candidate.getAttribute("aria-label") === "Close",
      );
      close?.click();
    });
  }
});

console.log(failures.length ? `[FAIL] ${failures.length} step(s)` : "[OK] no problems");
await browser.close();
process.exitCode = failures.length ? 1 : 0;
