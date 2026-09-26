/**
 * The typed client for the AHIA API.
 *
 * Two things matter here.
 *
 * **The session lives in a cookie, not in JavaScript.** Every request is sent with
 * `credentials: "include"`, and the browser attaches the HttpOnly session cookie by itself. No
 * component holds a token, no call site has to remember a header, and an injected script cannot read
 * the session. A bearer token is still accepted by the API for scripts and mobile clients, which is
 * why the headers below keep that option.
 *
 * **The types are generated from the API's own document** (`npm run api:types`), so a field this
 * client sends or reads cannot drift from what the backend validates without `tsc` failing.
 */

import { normaliseImage } from "@/lib/images";
import type { components, paths } from "./api-schema";

type Schemas = components["schemas"];

export type AuthenticatedSession = Schemas["AuthenticatedSessionSchema"];
export type UserProfile = Schemas["UserResponseSchema"];
export type Tenant = Schemas["TenantResponseSchema"];
export type TenantSummary = Schemas["TenantSummarySchema"];
export type Product = Schemas["ProductResponseSchema"];
export type InventoryLevel = Schemas["InventoryLevelResponseSchema"];
export type SaleCreation = Schemas["SaleCreationResponseSchema"];
export type SaleCreate = Schemas["SaleCreateSchema"];
export type SaleSummary = Schemas["SaleSummaryResponseSchema"];
export type DailySalesSummary = Schemas["DailySalesSummarySchema"];
export type LowStockProduct = Schemas["LowStockProductSchema"];
export type ExpenseCategoryList = Schemas["ExpenseCategoryListSchema"];
export type ExpenseCategory = Schemas["ExpenseCategorySchema"];
export type PaymentMethod = Schemas["PaymentMethod"];
export type ExpenseCreate = Schemas["ExpenseCreateSchema"];
export type ProductImage = Schemas["ProductImageResponseSchema"];
export type Storefront = Schemas["StorefrontResponseSchema"];
export type Member = Schemas["MembershipResponseSchema"];
export type CustomerList = Schemas["RequestResponseSchema"];
export type CustomerListLine = Schemas["RequestLineResponseSchema"];
export type CustomerListSummary = Schemas["CustomerListSummarySchema"];
export type CustomerListLineItem = Schemas["CustomerListLineItemSchema"];
export type ListLineState = Schemas["RequestLineWorkSchema"]["state"];
export type MembershipInvitation = Schemas["InvitationResponseSchema"];
export type PendingInvitation = Schemas["PendingInvitationSchema"];
export type AcceptedInvitation = Schemas["AcceptedInvitationSchema"];
export type MemberRole = Schemas["MembershipRoleUpdateSchema"]["role_name"];
export type MemberStatus = Schemas["MembershipStatusUpdateSchema"]["status"];
export type ProductShareSheet = Schemas["ProductShareSheetSchema"];

/**
 * Empty by default, so every call goes to this app's own origin and is proxied to the API by the
 * rewrite in `next.config.ts`. Set `NEXT_PUBLIC_API_BASE_URL` only for a client that talks to the API
 * directly - a mobile build, for instance - and remember that a browser then needs CORS and a
 * cross-site cookie policy.
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

/**
 * No request may hang the interface.
 *
 * The backend is reachable over a network that can stall, and a database can be suspended. A `fetch`
 * with no bound waits for as long as the socket does, which means a screen that spins forever and a
 * person who cannot tell whether the app is broken or the network is. Twenty-five seconds is longer
 * than any healthy call and shorter than anybody's patience.
 */
const REQUEST_TIMEOUT_MS = 25_000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId: string | null;

  constructor(status: number, code: string, message: string, correlationId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
  }

  /** What a support ticket should quote: the identifier an engineer can grep for. */
  describe(): string {
    return this.correlationId
      ? `${this.message} (correlation id ${this.correlationId})`
      : this.message;
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  accessToken?: string | null;
  query?: Record<string, string>;
};

/**
 * What has already been fetched, so a screen does not ask twice.
 *
 * Kept in memory and mirrored into local storage: the memory copy makes a second visit instant within
 * a session, and the stored copy means the first paint after a reload has something to show instead of
 * an empty shelf. A read cache is only safe if it cannot outlive the change that invalidates it, so
 * **every write clears all of it** - a shop's own edit must never be answered from a stale copy of
 * before that edit.
 *
 * This is deliberately small and boring. It is not a data layer; it is the difference between a screen
 * that answers and a screen that makes somebody wait for something it already knew.
 */

declare global {
  interface Window {
    /** How many requests this tab has in flight. Read by the progress line in the frame. */
    __ahiaInFlight?: number;
  }
}

const CACHE_PREFIX = "ahia.cache.";
const READ_CACHE = new Map<string, { at: number; value: unknown }>();

function cacheKey(path: string, search: string): string {
  return `${path}${search}`;
}

function recall<T>(key: string): { at: number; value: T } | null {
  const held = READ_CACHE.get(key);
  if (held) {
    return held as { at: number; value: T };
  }
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(`${CACHE_PREFIX}${key}`);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as { at: number; value: T };
    READ_CACHE.set(key, parsed);
    return parsed;
  } catch {
    return null;
  }
}

function remember(key: string, value: unknown): void {
  const entry = { at: Date.now(), value };
  READ_CACHE.set(key, entry);
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(`${CACHE_PREFIX}${key}`, JSON.stringify(entry));
  } catch {
    // A full or unavailable store is not a reason to fail a read.
  }
}

/** Forget everything. Called after any write, because a write is the only thing that invalidates a read. */
export function forgetEverythingFetched(): void {
  forgetResolution();
  READ_CACHE.clear();
  if (typeof window === "undefined") {
    return;
  }
  try {
    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith(CACHE_PREFIX)) {
        window.localStorage.removeItem(key);
      }
    }
  } catch {
    // As above: nothing here is worth breaking a screen over.
  }
}

/**
 * Tell the frame that something is in flight.
 *
 * A window event rather than a store the shell subscribes to, because the shell is a client component
 * and this module is imported by everything: a counter plus an event is the whole contract, and it
 * cannot be forgotten by a new caller the way a per-page loading flag can.
 */
/**
 * Trade the refresh cookie for a new session, silently.
 *
 * The access token lives fifteen minutes; the refresh cookie lives a year. Only the first one was ever
 * being used, so every quarter of an hour the application behaved as if the person had signed out -
 * which is the single most annoying thing a product can do, and the opposite of how WhatsApp or GitHub
 * feel. This is the whole fix: when something answers 401, ask once for a new session, then do the
 * original thing again. The person sees their screen, not a login form.
 *
 * A direct `fetch` rather than `request`, because this is called from inside `request` and a recursive
 * refresh on a failing refresh would loop.
 */
let refreshInFlight: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // The body is optional on the API, because the refresh token travels in its own cookie.
        body: "{}",
        credentials: "include",
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      return response.ok;
    } catch {
      return false;
    } finally {
      // Cleared on the next tick so concurrent callers share one attempt rather than racing.
      setTimeout(() => {
        refreshInFlight = null;
      }, 0);
    }
  })();
  return refreshInFlight;
}

/** The paths that must never trigger a refresh: signing in is how a session is created, not renewed. */
function isSessionPath(path: string): boolean {
  return path.startsWith("/api/v1/auth/");
}

function announceInFlight(delta: number): void {
  if (typeof window === "undefined") {
    return;
  }
  const current = Number(window.__ahiaInFlight ?? 0) + delta;
  window.__ahiaInFlight = Math.max(0, current);
  window.dispatchEvent(new CustomEvent("ahia:inflight", { detail: window.__ahiaInFlight }));
}

/** Read what has been cached without asking the server, for a first paint. */
/** The business this device last chose, readable before anything is fetched. */
export function rememberedBusinessId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("ahia.business");
}

/** What a screen should show on its very first frame: the cache, or nothing. */
export function firstPaint<T>(tenantId: string | null, path: (tenantId: string) => string): T | null {
  if (!tenantId) return null;
  return cachedRead<T>(path(tenantId));
}

export function cachedRead<T>(path: string, query?: Record<string, string>): T | null {
  const search = query ? `?${new URLSearchParams(query).toString()}` : "";
  return recall<T>(cacheKey(path, search))?.value ?? null;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.accessToken) {
    headers.Authorization = `Bearer ${options.accessToken}`;
  }
  const search = options.query ? `?${new URLSearchParams(options.query).toString()}` : "";
  const method = options.method ?? "GET";
  const key = cacheKey(path, search);

  // **The cache seeds the first paint; it never replaces the network.**
  //
  // This used to answer a read made in the last thirty seconds from memory and skip the request
  // entirely, which looked like a win and was a lie: a trader who added a product and came back to the
  // dashboard within half a minute was shown his old shelf, and the screen had no way to discover
  // otherwise. The screens already paint from `cachedRead` before they ask (see the dashboard), so
  // removing the shortcut costs nothing visible and guarantees the answer is always current.
  if (method !== "GET") {
    // A write invalidates everything: the only reliable moment to know a read is stale is right after
    // something changed.
    forgetEverythingFetched();
  }

  const send = () =>
    fetch(`${API_BASE_URL}${path}${search}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "include",
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

  let response: Response;
  announceInFlight(1);
  try {
    response = await send();
  } catch (error) {
    // One retry, and only for a read. A shop's connection drops in and out all day, and a screen
    // that gives up on the first blip is a screen that shows an empty shelf to somebody who has
    // stock. A write is never retried here: retrying a sale is how a sale happens twice.
    if (method !== "GET") {
      throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
    try {
      response = await send();
    } catch (retryError) {
      throw new ApiError(
        0,
        "UNREACHABLE",
        "The server did not answer. Check the connection and try again.",
        null,
      );
    }
  }

  announceInFlight(-1);

  // A session that has quietly expired, restored without the person noticing.
  if (response.status === 401 && !isSessionPath(path)) {
    if (await refreshSession()) {
      response = await send();
    }
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const payload = (await response.json().catch(() => null)) as
    | { error?: { code?: string; message?: string; correlation_id?: string } }
    | null;

  if (!response.ok) {
    const error = payload?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "UNKNOWN",
      error?.message ?? `The API answered ${response.status}.`,
      error?.correlation_id ?? null,
    );
  }

  if (method === "GET") {
    remember(key, payload);
  }
  return payload as T;
}

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------

export function registerAccount(input: {
  first_name: string;
  last_name: string;
  /** One of these two is required; the API refuses a registration with neither. */
  email?: string;
  phone?: string;
  password: string;
}): Promise<AuthenticatedSession> {
  return request<AuthenticatedSession>("/api/v1/auth/register", {
    method: "POST",
    body: input satisfies Schemas["RegisterUserSchema"],
  });
}

/**
 * One `identifier`, not an email field: a trader types whichever they remember - a phone number or an
 * address - and the service decides which it is. The failure response is identical either way.
 */
export function signIn(input: {
  identifier: string;
  password: string;
}): Promise<AuthenticatedSession> {
  return request<AuthenticatedSession>("/api/v1/auth/login", {
    method: "POST",
    body: input satisfies Schemas["LoginSchema"],
  });
}

/** Clears the session cookies server-side, so the browser cannot keep looking signed in. */
export function signOut(): Promise<Schemas["LogoutSchema"]> {
  return request<Schemas["LogoutSchema"]>("/api/v1/auth/logout", { method: "POST", body: {} });
}

/**
 * The session bootstrap. There is no token to inspect in the browser, so the only honest way to know
 * whether somebody is signed in is to ask the API with the cookie attached.
 */
/**
 * Who is signed in, remembered for as long as they are.
 *
 * **This and the two below were the real cause of every tap feeling like a reload.** Each screen asked for the
 * user, then the businesses, then the business detail, and only then its own data - four round trips before a
 * spinner could stop, on a page the browser already had everything for. A session does not change between two
 * taps, so it is asked for once.
 */
let signedInUser: UserProfile | null = null;
let businessesForSession: TenantSummary[] | null = null;
const businessDetails = new Map<string, Tenant>();

/** Forget what was resolved: for a sign-out, a failed refresh, or a business just created. */
export function forgetResolution(): void {
  signedInUser = null;
  businessesForSession = null;
  businessDetails.clear();
}

export function currentUser(): Promise<UserProfile> {
  if (signedInUser) return Promise.resolve(signedInUser);
  return request<UserProfile>("/api/v1/users/me").then((user) => {
    signedInUser = user;
    return user;
  });
}

// ---------------------------------------------------------------------------
// The business
// ---------------------------------------------------------------------------

export function listBusinesses(): Promise<TenantSummary[]> {
  if (businessesForSession) return Promise.resolve(businessesForSession);
  return request<TenantSummary[]>("/api/v1/tenants").then((businesses) => {
    businessesForSession = businesses;
    return businesses;
  });
}

export function getBusiness(tenantId: string): Promise<Tenant> {
  const known = businessDetails.get(tenantId);
  if (known) return Promise.resolve(known);
  return request<Tenant>(`/api/v1/tenants/${tenantId}`).then((business) => {
    businessDetails.set(tenantId, business);
    return business;
  });
}

/** The business's own details: its name, where it is, and what it trades in. */
export function updateBusiness(
  tenantId: string,
  changes: {
    name?: string;
    business_type?: string;
    phone?: string;
    email?: string;
    address?: string;
    city?: string;
    state?: string;
  },
): Promise<Tenant> {
  return request<Tenant>(`/api/v1/tenants/${tenantId}`, {
    method: "PATCH",
    body: changes satisfies Schemas["TenantUpdateSchema"],
  });
}

// ---------------------------------------------------------------------------
// The person's own profile
// ---------------------------------------------------------------------------

export function updateProfile(changes: {
  first_name?: string;
  last_name?: string;
  email?: string;
  phone?: string;
}): Promise<UserProfile> {
  return request<UserProfile>("/api/v1/users/me", {
    method: "PATCH",
    body: changes satisfies Schemas["UserProfileUpdateSchema"],
  });
}

export function changePassword(input: {
  current_password: string;
  new_password: string;
}): Promise<Schemas["PasswordChangedSchema"]> {
  return request<Schemas["PasswordChangedSchema"]>("/api/v1/auth/password", {
    method: "POST",
    body: input satisfies Schemas["ChangePasswordSchema"],
  });
}

export function createBusiness(input: {
  name: string;
  country?: string;
  currency?: string;
  timezone?: string;
}): Promise<Tenant> {
  // The list this session remembers is now one short, so it is forgotten rather than corrected: the next read
  // asks, and asking is the only way to be sure.
  businessesForSession = null;
  return request<Tenant>("/api/v1/tenants", {
    method: "POST",
    body: {
      name: input.name,
      country: input.country ?? "NG",
      currency: input.currency ?? "NGN",
      timezone: input.timezone ?? "Africa/Lagos",
    } satisfies Schemas["TenantCreateSchema"],
  });
}

// ---------------------------------------------------------------------------
// Products and stock
// ---------------------------------------------------------------------------

export function listProducts(tenantId: string): Promise<Product[]> {
  return request<Product[]>(`/api/v1/tenants/${tenantId}/products`);
}

export function createProduct(
  tenantId: string,
  input: {
    name: string;
    selling_price?: string | null;
    category_id?: string | null;
    wholesale_price?: string | null;
    pieces_per_pack?: number | null;
  },
): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products`, {
    method: "POST",
    body: input satisfies Schemas["ProductCreateSchema"],
  });
}

export type Category = Schemas["CategoryResponseSchema"];

export function listCategories(tenantId: string): Promise<Category[]> {
  return request<Category[]>(`/api/v1/tenants/${tenantId}/categories`);
}

export function createCategory(
  tenantId: string,
  input: {
    name: string;
    parent_id?: string | null;
    default_normal_price?: string | null;
    default_wholesale_price?: string | null;
    default_pieces_per_pack?: number | null;
  },
): Promise<Category> {
  return request<Category>(`/api/v1/tenants/${tenantId}/categories`, {
    method: "POST",
    body: input satisfies Schemas["CategoryCreateSchema"],
  });
}

/**
 * Set what a group costs.
 *
 * One request for all three, because they answer one question: what do the items under this heading
 * cost. Every item that has no price of its own follows this immediately, which is what makes "all of
 * the 21D are 350" a single action rather than twenty.
 */
export function setGroupPrices(
  tenantId: string,
  categoryId: string,
  prices: {
    default_normal_price?: string | null;
    default_wholesale_price?: string | null;
    default_pieces_per_pack?: number | null;
  },
): Promise<Category> {
  return request<Category>(`/api/v1/tenants/${tenantId}/categories/${categoryId}`, {
    method: "PATCH",
    body: prices satisfies Schemas["CategoryUpdateSchema"],
  });
}

/**
 * Set an item's own prices, or clear them back to following its group.
 *
 * `null` is the meaningful value here: it removes the override, and the item goes back to whatever
 * its group says. That is the difference between "this model costs 370" and "this model costs the same
 * as the rest of the 21D".
 */
export function setItemPrices(
  tenantId: string,
  productId: string,
  prices: {
    selling_price?: string | null;
    wholesale_price?: string | null;
    pieces_per_pack?: number | null;
  },
): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products/${productId}`, {
    method: "PATCH",
    body: prices satisfies Schemas["ProductUpdateSchema"],
  });
}

/** File an item under a group, or take it out of one, so a group's price can reach it. */
export function moveItemToGroup(
  tenantId: string,
  productId: string,
  categoryId: string | null,
): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products/${productId}`, {
    method: "PATCH",
    body: { category_id: categoryId } satisfies Schemas["ProductUpdateSchema"],
  });
}

/**
 * Publication is its own operation, not a field on an edit: a product that appears in the public shop
 * is a decision, and it is recorded as one.
 */
export function publishProduct(tenantId: string, productId: string): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products/${productId}/publish`, {
    method: "POST",
    body: {},
  });
}

export function unpublishProduct(tenantId: string, productId: string): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products/${productId}/unpublish`, {
    method: "POST",
    body: {},
  });
}

export function listStock(tenantId: string): Promise<InventoryLevel[]> {
  return request<InventoryLevel[]>(`/api/v1/tenants/${tenantId}/inventory`);
}

export function receiveStock(
  tenantId: string,
  productId: string,
  quantity: string,
  note?: string,
): Promise<unknown> {
  return request<unknown>(`/api/v1/tenants/${tenantId}/inventory/${productId}/receipts`, {
    method: "POST",
    body: { quantity, note } satisfies Schemas["StockReceiveSchema"],
  });
}

// ---------------------------------------------------------------------------
// Selling, spending and the day's numbers
// ---------------------------------------------------------------------------

export function recordSale(tenantId: string, input: SaleCreate): Promise<SaleCreation> {
  return request<SaleCreation>(`/api/v1/tenants/${tenantId}/sales`, {
    method: "POST",
    body: input,
  });
}

export function listSales(tenantId: string, limit = "10"): Promise<SaleSummary[]> {
  return request<SaleSummary[]>(`/api/v1/tenants/${tenantId}/sales`, { query: { limit } });
}

export function recordExpense(tenantId: string, input: ExpenseCreate): Promise<unknown> {
  return request<unknown>(`/api/v1/tenants/${tenantId}/expenses`, {
    method: "POST",
    body: input,
  });
}

export function listExpenseCategories(tenantId: string): Promise<ExpenseCategoryList> {
  return request<ExpenseCategoryList>(`/api/v1/tenants/${tenantId}/expenses/categories`);
}

export function dailySales(tenantId: string): Promise<DailySalesSummary> {
  return request<DailySalesSummary>(`/api/v1/tenants/${tenantId}/reports/daily-sales`);
}

export function lowStock(tenantId: string, limit = "5"): Promise<LowStockProduct[]> {
  return request<LowStockProduct[]>(`/api/v1/tenants/${tenantId}/reports/low-stock`, {
    query: { limit },
  });
}

// ---------------------------------------------------------------------------
// Product photos
// ---------------------------------------------------------------------------

export function listProductImages(tenantId: string, productId: string): Promise<ProductImage[]> {
  return request<ProductImage[]>(`/api/v1/tenants/${tenantId}/products/${productId}/images`);
}

/**
 * Upload one photo.
 *
 * The API takes the image as the raw request body with its own content type, rather than as a
 * multipart form: the bytes are the body, and the type is a claim the server checks by decoding them.
 * Nothing here trusts the browser's word for it - the pipeline does, and refuses a mismatch.
 */
export async function uploadProductImage(
  tenantId: string,
  productId: string,
  chosen: File,
  isPrimary: boolean,
): Promise<ProductImage> {
  // Whatever the camera produced is turned into what we want to store before it leaves the browser:
  // a phone's HEIC, or a twelve-megabyte portrait, becomes a 1600-pixel WebP. The API keeps its own
  // allowlist and checks the bytes, because this runs in a browser and a browser is the client's.
  const { file } = await normaliseImage(chosen);
  const query = isPrimary ? "?is_primary=true" : "";
  const response = await fetch(
    `${API_BASE_URL}/api/v1/tenants/${tenantId}/products/${productId}/images${query}`,
    {
      method: "POST",
      headers: { "Content-Type": file.type },
      body: file,
      credentials: "include",
      signal: AbortSignal.timeout(60_000),
    },
  );
  const payload = (await response.json().catch(() => null)) as
    | ProductImage
    | { error?: { code?: string; message?: string; correlation_id?: string } };
  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string; correlation_id?: string } })
      .error;
    throw new ApiError(
      response.status,
      error?.code ?? "UNKNOWN",
      error?.message ?? `The photo could not be uploaded (${response.status}).`,
      error?.correlation_id ?? null,
    );
  }
  return payload as ProductImage;
}

export function makeProductImagePrimary(
  tenantId: string,
  productId: string,
  imageId: string,
): Promise<ProductImage> {
  return request<ProductImage>(
    `/api/v1/tenants/${tenantId}/products/${productId}/images/${imageId}/primary`,
    { method: "POST" },
  );
}

export function removeProductImage(
  tenantId: string,
  productId: string,
  imageId: string,
): Promise<{ image_id: string; storage_released: boolean }> {
  return request<{ image_id: string; storage_released: boolean }>(
    `/api/v1/tenants/${tenantId}/products/${productId}/images/${imageId}`,
    { method: "DELETE" },
  );
}

// ---------------------------------------------------------------------------
// The public shop
// ---------------------------------------------------------------------------

export function getStorefront(tenantId: string): Promise<Storefront> {
  return request<Storefront>(`/api/v1/tenants/${tenantId}/storefront`);
}

export function publishStorefront(
  tenantId: string,
  details: { headline?: string | null; description?: string | null; contact_phone?: string | null },
): Promise<Storefront> {
  return request<Storefront>(`/api/v1/tenants/${tenantId}/storefront/publish`, {
    method: "POST",
    body: details satisfies Schemas["StorefrontPublishSchema"],
  });
}

export function unpublishStorefront(tenantId: string): Promise<Storefront> {
  return request<Storefront>(`/api/v1/tenants/${tenantId}/storefront/unpublish`, {
    method: "POST",
    body: {},
  });
}

/**
 * Turn a text box into a value the API accepts.
 *
 * An empty string is not a headline: the field's smallest valid value is one character, so clearing
 * one has to be sent as null. The service reads null as "set it to nothing" and an omitted field as
 * "leave it alone", which is exactly the difference a person means when they delete what was there.
 */
function clearedOrText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function updateStorefront(
  tenantId: string,
  changes: { headline?: string | null; description?: string | null; contact_phone?: string | null },
): Promise<Storefront> {
  return request<Storefront>(`/api/v1/tenants/${tenantId}/storefront`, {
    method: "PATCH",
    body: changes satisfies Schemas["StorefrontUpdateSchema"],
  });
}

/** The public URL, the QR payload and the WhatsApp link for one product. */
export function productShareSheet(tenantId: string, productId: string): Promise<ProductShareSheet> {
  return request<ProductShareSheet>(
    `/api/v1/tenants/${tenantId}/products/${productId}/share-sheet`,
  );
}

// ---------------------------------------------------------------------------
// The team
// ---------------------------------------------------------------------------

/** The four roles the product ships with, in the order a shop thinks about them. */
export const MEMBER_ROLES: { value: MemberRole; label: string; description: string }[] = [
  { value: "MANAGER", label: "Manager", description: "Runs the shop day to day, and reports" },
  { value: "SALES", label: "Sales", description: "Records sales and takes payment" },
  { value: "INVENTORY", label: "Inventory", description: "Receives, counts and adjusts stock" },
  { value: "OWNER", label: "Owner", description: "Everything, including staff" },
];

export function listMembers(tenantId: string): Promise<Member[]> {
  return request<Member[]>(`/api/v1/tenants/${tenantId}/members`);
}

/**
 * Invite somebody.
 *
 * The answer carries the token, which is the only moment it exists: the API stores a digest, so it
 * cannot be read back later. That is why the screen shows the link immediately and offers to send it
 * on WhatsApp - there is no email sender in this deployment, and there does not need to be one.
 */
export function inviteMember(
  tenantId: string,
  invitation: { role_name: MemberRole; email?: string; phone?: string },
): Promise<MembershipInvitation> {
  return request<MembershipInvitation>(`/api/v1/tenants/${tenantId}/members`, {
    method: "POST",
    body: invitation satisfies Schemas["MembershipInviteSchema"],
  });
}

export function listIssuedInvitations(tenantId: string): Promise<MembershipInvitation[]> {
  return request<MembershipInvitation[]>(`/api/v1/tenants/${tenantId}/invitations`);
}

export function changeMemberRole(
  tenantId: string,
  membershipId: string,
  roleName: MemberRole,
): Promise<Member> {
  return request<Member>(`/api/v1/tenants/${tenantId}/members/${membershipId}`, {
    method: "PATCH",
    body: { role_name: roleName } satisfies Schemas["MembershipRoleUpdateSchema"],
  });
}

export function changeMemberStatus(
  tenantId: string,
  membershipId: string,
  status: MemberStatus,
): Promise<Member> {
  return request<Member>(`/api/v1/tenants/${tenantId}/members/${membershipId}`, {
    method: "PATCH",
    body: { status } satisfies Schemas["MembershipStatusUpdateSchema"],
  });
}

export function removeMember(tenantId: string, membershipId: string): Promise<void> {
  return request<void>(`/api/v1/tenants/${tenantId}/members/${membershipId}`, {
    method: "DELETE",
  });
}

/** Invitations addressed to the signed-in person, waiting to be accepted. */
export function listMyInvitations(): Promise<PendingInvitation[]> {
  return request<PendingInvitation[]>("/api/v1/invitations");
}

export function acceptInvitation(token: string): Promise<AcceptedInvitation> {
  return request<AcceptedInvitation>("/api/v1/invitations/accept", {
    method: "POST",
    body: { token } satisfies Schemas["AcceptInvitationSchema"],
  });
}

// ---------------------------------------------------------------------------
// The lists customers send
// ---------------------------------------------------------------------------

/** What the three buttons mean, in the trader's own words rather than the machine's. */
export const LINE_STATES: { value: NonNullable<ListLineState>; label: string; hint: string }[] = [
  { value: "have_it", label: "I have it", hint: "It is on the shelf" },
  { value: "buy_it", label: "I will buy it", hint: "Go and find it in the market" },
  { value: "cannot_get", label: "Cannot get it", hint: "Not available anywhere today" },
];

/** Every list this business has been sent, newest first, with its lines. */
export function listCustomerLists(tenantId: string): Promise<CustomerList[]> {
  return request<CustomerList[]>(`/api/v1/tenants/${tenantId}/requests`);
}

/** Lists a returning customer has previously sent to this shop, for quick reordering. */
export function getCustomerPastLists(slug: string, phone: string): Promise<CustomerListSummary[]> {
  return request<CustomerListSummary[]>(
    `/shop/${encodeURIComponent(slug)}/customer-lists`,
    { query: { phone: phone.trim() } },
  );
}

/**
 * Say what was done with one line: where it came from, what it cost, what it is sold for.
 *
 * One call for the whole decision, because that is one action at a counter - and because the connection
 * in a market is the reason the trader is standing there with a phone in his hand.
 */
export function workListLine(
  tenantId: string,
  requestId: string,
  lineId: string,
  changes: {
    state?: NonNullable<ListLineState>;
    cost_price?: string | null;
    shop_price?: string | null;
  },
): Promise<CustomerList> {
  return request<CustomerList>(
    `/api/v1/tenants/${tenantId}/requests/${requestId}/lines/${lineId}`,
    { method: "PATCH", body: changes satisfies Schemas["RequestLineWorkSchema"] },
  );
}

/** Record how a list was sent: who carried it, under what number, what it cost, where to follow it. */
export function dispatchCustomerList(
  tenantId: string,
  requestId: string,
  details: {
    transporter_name?: string | null;
    transporter_phone?: string | null;
    waybill_number?: string | null;
    dispatch_cost?: string | null;
    tracking_url?: string | null;
  },
): Promise<CustomerList> {
  return request<CustomerList>(
    `/api/v1/tenants/${tenantId}/requests/${requestId}/dispatch`,
    { method: "POST", body: details satisfies Schemas["DispatchSchema"] },
  );
}

/** Turn a list into a sale. The API refuses while any line is unpriced, and says so. */
export function confirmCustomerList(tenantId: string, requestId: string): Promise<CustomerList> {
  return request<CustomerList>(`/api/v1/tenants/${tenantId}/requests/${requestId}/confirm`, {
    method: "POST",
    body: {},
  });
}

/** Exported so a page can use the generated operation shapes directly when it needs to. */
export type ApiPaths = paths;
