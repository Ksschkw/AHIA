/**
 * Reading the API from the server.
 *
 * The public shop is rendered on the server so that a customer, and WhatsApp's link preview, get real
 * HTML: a link that unfurls with the shop's name and what it sells is the whole point of sharing one.
 * That means the fetch happens in this process rather than in the browser, against the API's address
 * directly - the browser-side rewrite in `next.config.ts` is for the signed-in app, which carries a
 * cookie.
 */

/**
 * `||`, not `??`, and that distinction is the bug this line already caused once: the browser-side
 * variable is deliberately the empty string (the app calls its own origin and is proxied), and `??`
 * only falls back on null or undefined. An empty base turns a server-side fetch into a relative URL,
 * which Node refuses - and the shop page answered 404 for a shop that the API was serving happily.
 */
const API_BASE_URL =
  process.env.API_PROXY_TARGET || process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

import type { components } from "./api-schema";

type Schemas = components["schemas"];

// The shapes are the API's own: written by hand they were wrong on the first attempt, and a product
// page rendered "undefined" for a product that plainly existed.
export type PublicProduct = Schemas["PublicProductSchema"];
export type PublicStorefront = Schemas["PublicStorefrontSchema"];
export type PublicProductPage = Schemas["PublicProductPageSchema"];

export async function fetchPublicShop(slug: string): Promise<PublicStorefront | null> {
  return getJson<PublicStorefront>(`/shop/${encodeURIComponent(slug)}`);
}

/** One product, wrapped in the shop's own details so a single request renders the whole page. */
export async function fetchPublicProduct(
  slug: string,
  productSlug: string,
): Promise<PublicProductPage | null> {
  return getJson<PublicProductPage>(
    `/shop/${encodeURIComponent(slug)}/product/${encodeURIComponent(productSlug)}`,
  );
}

async function getJson<T>(path: string): Promise<T | null> {
  try {
    // **Cached at the edge, not fetched on every click.**
    //
    // This was `no-store`, and it is why opening a product took over a second: every navigation made a
    // fresh round trip from the visitor to the web server to the API and back, for a page that changes
    // when the trader edits his shop and not before. Sixty seconds is the compromise - a customer's
    // second click is instant, a price he changed a minute ago is already live, and the shop stays
    // readable even while the API is briefly unwell.
    const response = await fetch(`${API_BASE_URL}${path}`, {
      next: { revalidate: 60, tags: [`shop:${path}`] },
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      // A shop that is closed, or a product that is not published, answers 404 - which is a state the
      // page renders rather than an error a customer should see.
      return null;
    }
    return (await response.json()) as T;
  } catch {
    // The API being unreachable is not something a customer can act on, and a broken shop page says
    // more about the shop than about the network.
    return null;
  }
}

/** The address a customer can open, built from the shop's own slug. */
export function publicShopPath(slug: string): string {
  return `/shop/${slug}`;
}

export function whatsAppLink(phone: string | null, message: string): string | null {
  if (!phone) {
    return null;
  }
  const digits = phone.replace(/[^\d]/g, "");
  if (digits.length < 10) {
    return null;
  }
  return `https://wa.me/${digits}?text=${encodeURIComponent(message)}`;
}
