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

import type { components, paths } from "./api-schema";

type Schemas = components["schemas"];

export type AuthenticatedSession = Schemas["AuthenticatedSessionSchema"];
export type UserProfile = Schemas["UserResponseSchema"];
export type Tenant = Schemas["TenantResponseSchema"];
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

  return payload as T;
}

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------

export function registerAccount(input: {
  first_name: string;
  last_name: string;
  email: string;
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
export function currentUser(): Promise<UserProfile> {
  return request<UserProfile>("/api/v1/users/me");
}

// ---------------------------------------------------------------------------
// The business
// ---------------------------------------------------------------------------

export function listBusinesses(): Promise<Tenant[]> {
  return request<Tenant[]>("/api/v1/tenants");
}

export function createBusiness(input: {
  name: string;
  country?: string;
  currency?: string;
  timezone?: string;
}): Promise<Tenant> {
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
  input: { name: string; selling_price: string },
): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products`, {
    method: "POST",
    body: input satisfies Schemas["ProductCreateSchema"],
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

/** Exported so a page can use the generated operation shapes directly when it needs to. */
export type ApiPaths = paths;
