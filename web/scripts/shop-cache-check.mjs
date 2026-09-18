/**
 * What a shop link is to everything that is not a browser.
 *
 * M24.1 claims the storefront is edge-cached with share cards that look like a shop. Both of those are
 * facts about the response, not about the React in the file, so they are checked on the response: the
 * content type, the Open Graph tags a messaging app reads to build the preview, and the cache headers
 * that decide whether a customer waits for a server on another continent.
 *
 * No browser needed, so it runs in about a second.
 */
const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const failures = [];

function check(name, condition, detail) {
  if (condition) {
    console.log(`[OK] ${name}`);
    return;
  }
  console.log(`[FAIL] ${name}: ${detail}`);
  failures.push(name);
}

function meta(html, property) {
  const doubleQuoted = new RegExp(`<meta[^>]+(?:property|name)="${property}"[^>]+content="([^"]*)"`, "i");
  const reversed = new RegExp(`<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="${property}"`, "i");
  return (html.match(doubleQuoted) ?? html.match(reversed))?.[1] ?? null;
}

// **The slug must exist**, and that is the first assertion: pointed at a shop that is not there, every
// other check here passes for the wrong reason - a not-found page has no share card and is never cached,
// which is exactly what the first run of this script reported while looking like four real failures.
const slug = process.env.SHOP_SLUG;
if (!slug) {
  console.log("[FAIL] no shop to check: set SHOP_SLUG to a published shop's address");
  process.exit(1);
}
const response = await fetch(`${APP_URL}/shop/${slug}`);
if (response.status !== 200) {
  console.log(`[FAIL] the shop at /shop/${slug} answered ${response.status}`);
  process.exit(1);
}
const html = await response.text();
const contentType = response.headers.get("content-type") ?? "";
const cache = response.headers.get("cache-control") ?? "";

check("the link is a page", contentType.includes("text/html"), `got ${contentType || "nothing"}`);
const title = meta(html, "og:title");
const description = meta(html, "og:description");
check("the card has a title", Boolean(title), `og:title was ${title}`);
check("the card says what the shop is", Boolean(description), `og:description was ${description}`);
console.log(`      card reads: ${title} - ${description}`);
console.log(`      cache: ${cache || "(none)"}`);
// Edge caching is a property of the platform, not of the code: the deployed site is behind a CDN that
// reads `s-maxage`, while a local server answers `no-cache, must-revalidate` for every page it renders.
// Reporting that as a failure would be reporting the absence of a CDN, so it is skipped with the reason
// said out loud - a check that cannot tell "not cached" from "cannot be judged here" is a check that
// teaches people to ignore it.
const isDeployed = !APP_URL.includes("localhost") && !APP_URL.includes("127.0.0.1");
if (/s-maxage|stale-while-revalidate/.test(cache)) {
  console.log("[OK] the page can be cached at the edge");
} else if (isDeployed) {
  console.log(`[FAIL] the page can be cached at the edge: cache-control was "${cache}"`);
  failures.push("edge caching");
} else {
  console.log(`[SKIP] edge caching: a local server sent "${cache}"; this is asserted against the deployment`);
}
const canonical = (html.match(/<link rel="canonical" href="([^"]+)"/) ?? [])[1];
check("the page has one address", Boolean(canonical), "no canonical link");

console.log(failures.length ? `[FAIL] ${failures.length} problem(s)` : "[OK] no problems");
process.exitCode = failures.length ? 1 : 0;
