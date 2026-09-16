/**
 * The typed client for the AHIA API.
 *
 * The types are generated from the API's own OpenAPI document (`npm run api:types`), so a field this
 * client sends or reads cannot drift from what the backend validates without the type check failing.
 * Hand-written request and response types would be a second, silently diverging contract.
 */

import type { components, paths } from "./api-schema";

type Schemas = components["schemas"];

export type AuthenticatedSession = Schemas["AuthenticatedSessionSchema"];
export type Tenant = Schemas["TenantResponseSchema"];
export type Product = Schemas["ProductResponseSchema"];
export type InventoryLevel = Schemas["InventoryLevelResponseSchema"];
export type SaleCreation = Schemas["SaleCreationResponseSchema"];
export type SaleCreate = Schemas["SaleCreateSchema"];

/** The API's own default. Overridable in `.env.local` for a deployed backend. */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

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
    return this.correlationId ? `${this.message} (correlation id ${this.correlationId})` : this.message;
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  accessToken?: string | null;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.accessToken) {
    headers.Authorization = `Bearer ${options.accessToken}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: "no-store",
  });

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
 * The login endpoint takes one `identifier`, not an email field: a trader types whichever they
 * remember and the service decides which it is. The failure response is identical either way.
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

export function listBusinesses(accessToken: string): Promise<Tenant[]> {
  return request<Tenant[]>("/api/v1/tenants", { accessToken });
}

/**
 * Currency and timezone are the business's own, not the deployment's: they are sent explicitly so
 * the choice is a decision rather than an accident of whatever the server defaults to.
 */
export function createBusiness(
  accessToken: string,
  input: { name: string; country?: string; currency?: string; timezone?: string },
): Promise<Tenant> {
  return request<Tenant>("/api/v1/tenants", {
    method: "POST",
    accessToken,
    body: {
      name: input.name,
      country: input.country ?? "NG",
      currency: input.currency ?? "NGN",
      timezone: input.timezone ?? "Africa/Lagos",
    } satisfies Schemas["TenantCreateSchema"],
  });
}

export function listProducts(accessToken: string, tenantId: string): Promise<Product[]> {
  return request<Product[]>(`/api/v1/tenants/${tenantId}/products`, { accessToken });
}

export function createProduct(
  accessToken: string,
  tenantId: string,
  input: { name: string; selling_price: string },
): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products`, {
    method: "POST",
    accessToken,
    body: input satisfies Schemas["ProductCreateSchema"],
  });
}

export function listStock(accessToken: string, tenantId: string): Promise<InventoryLevel[]> {
  return request<InventoryLevel[]>(`/api/v1/tenants/${tenantId}/inventory`, { accessToken });
}

export function receiveStock(
  accessToken: string,
  tenantId: string,
  productId: string,
  quantity: string,
): Promise<unknown> {
  return request<unknown>(`/api/v1/tenants/${tenantId}/inventory/${productId}/receipts`, {
    method: "POST",
    accessToken,
    body: { quantity } satisfies Schemas["StockReceiveSchema"],
  });
}

export function recordSale(
  accessToken: string,
  tenantId: string,
  input: SaleCreate,
): Promise<SaleCreation> {
  return request<SaleCreation>(`/api/v1/tenants/${tenantId}/sales`, {
    method: "POST",
    accessToken,
    body: input,
  });
}

/** The paths type is exported so a future page can use the generated operation shapes directly. */
export type ApiPaths = paths;
