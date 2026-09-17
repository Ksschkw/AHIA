/**
 * Getting a salesperson into the business.
 *
 * The flow this proves is the one the product actually uses: the owner invites a phone number, the API
 * hands back a link exactly once, the owner sends it on WhatsApp, the person opens it in a browser with
 * no account and no cookies, signs up, and lands inside the business with the role they were given.
 * Then the owner changes that role and removes them.
 */

import { resolve } from "node:path";

import puppeteer from "puppeteer-core";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const OUTPUT = resolve(process.cwd(), "..", ".review");
const stamp = Date.now();
const ownerPhone = `0803${String(stamp).slice(-7)}`;
const staffPhone = `0805${String(stamp).slice(-7)}`;
// The API stores a number in one canonical form, so the invitation list shows this rather than the
// way it was typed - which is the whole point: one person, one number, whichever way it is written.
const staffPhoneStored = `+234${staffPhone.slice(1)}`;

/** Every API answer, so a failure is a status code rather than a guess. */
const apiTraffic = [];

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox", "--disable-gpu"],
});

async function step(page, name, action) {
  try {
    await action();
    console.log(`[OK] ${name}`);
  } catch (error) {
    await page.screenshot({ path: resolve(OUTPUT, `team-failure-${name}.png`) });
    console.log(`[FAIL] ${name}: ${error.message}`);
    console.log(apiTraffic.length ? `--- api ---\n  ${apiTraffic.join("\n  ")}` : "--- no api failures ---");
    // The end of the page as well as the start: a toast lives at the end of the document, and the
    // members list is what the failing step was reading.
    const text = await page.evaluate(() => document.body.innerText);
    console.log(`--- page (${text.length} chars) ---`);
    console.log(text.slice(-800));
    process.exitCode = 1;
    throw error;
  }
}

const waitFor = (page, text, timeout = 40_000) =>
  page.waitForFunction((wanted) => document.body.innerText.includes(wanted), { timeout }, text);

async function click(page, label, timeout = 30_000) {
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

const owner = await browser.newPage();
await owner.setViewport({ width: 1280, height: 900 });
owner.on("response", (response) => {
  if (response.url().includes("/api/") && response.status() >= 400) {
    apiTraffic.push(`${response.status()} ${response.request().method()} ${response.url()}`);
  }
});
let inviteLink = "";

try {
  await step(owner, "the owner signs up", async () => {
    await owner.goto(`${APP_URL}/start?intent=create`, { waitUntil: "networkidle2" });
    await owner.waitForSelector("#first_name", { timeout: 40_000 });
    await owner.type("#first_name", "Ada");
    await owner.type("#last_name", "Obi");
    await owner.type("#phone", ownerPhone);
    await owner.type("#password", "Owner-Password-2026");
    await owner.type("#confirm_password", "Owner-Password-2026");
    await owner.click('button[type="submit"]');
    await owner.waitForSelector("#business-name", { timeout: 40_000 });
    await owner.type("#business-name", `Team Shop ${stamp % 1000}`);
    await click(owner, "Create business");
    await owner.waitForFunction(() => !document.querySelector('[role="dialog"]'), { timeout: 40_000 });
  });

  await step(owner, "the salesperson is invited by phone", async () => {
    await owner.goto(`${APP_URL}/app/team`, { waitUntil: "networkidle2" });
    await owner.waitForSelector("#invite_phone", { timeout: 40_000 });
    await owner.type("#invite_phone", staffPhone);
    await click(owner, "Create an invitation");
    await waitFor(owner, "Invitation created.");
    inviteLink = await owner.evaluate(() => {
      const element = [...document.querySelectorAll("span")].find((candidate) =>
        candidate.textContent?.includes("/join/"),
      );
      return element?.textContent?.trim() ?? "";
    });
    if (!inviteLink.includes("/join/")) {
      throw new Error("no invitation link was shown, and the token cannot be read back later");
    }
    console.log(`      invite link: ${inviteLink.replace(APP_URL, "")}`);
    await owner.screenshot({ path: resolve(OUTPUT, "team-1-owner.png") });
  });

  await step(owner, "the invitation is listed as waiting", async () => {
    // The number that was invited, in the list of invitations the business has issued.
    await waitFor(owner, staffPhoneStored);
    await waitFor(owner, "Waiting");
  });

  let staff;
  await step(owner, "the salesperson opens the link with no account", async () => {
    const context = await browser.createBrowserContext();
    staff = await context.newPage();
    await staff.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
    await staff.goto(inviteLink, { waitUntil: "networkidle2" });
    // No session, so the invitation link sends them through sign-up and comes back to itself.
    await staff.waitForSelector("#first_name", { timeout: 40_000 });
    await staff.screenshot({ path: resolve(OUTPUT, "team-2-join-signup.png") });
    await staff.type("#first_name", "Nwa");
    await staff.type("#last_name", "Boy");
    await staff.type("#phone", staffPhone);
    await staff.type("#password", "Staff-Password-2026");
    await staff.type("#confirm_password", "Staff-Password-2026");
    await staff.click('button[type="submit"]');
  });

  await step(staff, "they land inside the business", async () => {
    // The invitee's own screen, which is where a failure belongs: it is their browser that has to end
    // up inside the business.
    await waitFor(staff, "You are in", 60_000);
    const body = await staff.evaluate(() => document.body.innerText);
    if (!body.includes("SALES")) {
      throw new Error(`the role was not the one invited: ${body.slice(0, 200)}`);
    }
    await staff.screenshot({ path: resolve(OUTPUT, "team-3-joined.png") });
    await click(staff, "Open the shop");
    await waitFor(staff, "Record a sale", 40_000);
  });

  await step(owner, "the owner sees them on the team", async () => {
    await owner.reload({ waitUntil: "networkidle2" });
    await waitFor(owner, "Nwa Boy", 40_000);
    await waitFor(owner, "Working");
    await owner.screenshot({ path: resolve(OUTPUT, "team-4-members.png") });
  });

  await step(owner, "the owner promotes them and then removes them", async () => {
    // Scoped to the salesperson's own row: picking the first role select on the page would try to
    // demote the owner, which the API refuses - correctly, because a business with no owner is a
    // business nobody can administer.
    const roleSelector = await owner.evaluate(() => {
      const row = [...document.querySelectorAll("li")].find((candidate) =>
        candidate.innerText.includes("Nwa Boy"),
      );
      const select = row?.querySelector("select[id^='role_']");
      return select ? `#${select.id}` : null;
    });
    if (!roleSelector) {
      throw new Error("the salesperson's role control was not on the page");
    }
    // `page.select` rather than setting the value and dispatching: it drives the control the way a
    // person does, so React's own change handling is what runs.
    await owner.select(roleSelector, "MANAGER");
    await waitFor(owner, "is now MANAGER");
    await owner.screenshot({ path: resolve(OUTPUT, "team-5-promoted.png") });

    await owner.evaluate(() => {
      const row = [...document.querySelectorAll("li")].find((candidate) =>
        candidate.innerText.includes("Nwa Boy"),
      );
      const button = [...(row?.querySelectorAll("button") ?? [])].find((candidate) =>
        candidate.textContent?.trim().startsWith("Remove"),
      );
      button?.click();
    });
    // The row leaves the list of people. The confirmation carries the name, so it is dismissed
    // first - otherwise the page still contains it and the assertion is about the toast.
    await waitFor(owner, "no longer has access");
    await click(owner, "Dismiss");
    await owner.waitForFunction(() => !document.body.innerText.includes("Nwa Boy"), {
      timeout: 40_000,
    });
    await owner.screenshot({ path: resolve(OUTPUT, "team-6-removed.png") });
  });

  console.log("[OK] no problems");
} catch {
  // Each failing step has already reported itself.
} finally {
  await browser.close();
}
