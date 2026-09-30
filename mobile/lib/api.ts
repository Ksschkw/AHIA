import { currentAccessToken, forgetSession, readRefreshToken, rememberSession } from "./session";

/**
 * The same API the web app calls, from a phone.
 *
 * **Nothing about the backend changes for mobile.** It already accepts an `Authorization` header before it
 * looks for a session cookie - its own docstring says so, and names a mobile client as the reason - and its
 * sign-in and refresh endpoints already return both tokens in the body. What follows is the client side of
 * that: hold the access token in memory, keep the refresh token in the keychain, and refresh in exactly one
 * place when a call comes back 401.
 *
 * The base address comes from the environment so a build points at whichever API it was built for, rather than
 * carrying a hostname that happens to be right today.
 */

const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "https://p01--ahia-api--qw5xhkblp8hy.code.run";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function refreshOnce(): Promise<boolean> {
  const refreshToken = await readRefreshToken();
  if (!refreshToken) return false;
  const response = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) {
    // The refresh token is gone, expired or revoked: there is no session left to rescue, and pretending
    // otherwise would leave a screen that looks signed in and cannot do anything.
    await forgetSession();
    return false;
  }
  await rememberSession(await response.json());
  return true;
}

/**
 * Call the API, refreshing once if the access token has expired.
 *
 * One retry, never a loop: an endpoint that answers 401 twice in a row is not a stale token, it is a refusal,
 * and retrying would turn a clear answer into a delay.
 */
export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const send = async (): Promise<Response> => {
    const token = currentAccessToken();
    return fetch(`${BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
    });
  };

  let response = await send();
  if (response.status === 401 && (await refreshOnce())) {
    response = await send();
  }
  const payload = (await response.json().catch(() => null)) as
    | { error?: { message?: string } }
    | null;
  if (!response.ok) {
    throw new ApiError(response.status, payload?.error?.message ?? "That did not work. Try again.");
  }
  return payload as T;
}

/**
 * Sign in and keep the session where a phone keeps secrets.
 *
 * The field is **`identifier`**, not `phone`: one field for whichever a trader remembers, phone or email, and
 * the service decides which it is. The schema forbids extra fields, so sending `phone` is refused with
 * `INVALID_REQUEST` before anything is looked up - which is exactly what happened the first time this app was
 * opened on a phone.
 */
export async function signIn(identifier: string, password: string): Promise<void> {
  const session = await request<{ access_token: string; refresh_token: string }>("/api/v1/auth/login", {
    method: "POST",
    body: { identifier, password },
  });
  await rememberSession(session);
}

/** Create an account, and be signed in with it. */
export async function registerAccount(details: {
  firstName: string;
  lastName: string;
  phone: string;
  password: string;
}): Promise<void> {
  const session = await request<{ access_token: string; refresh_token: string }>("/api/v1/auth/register", {
    method: "POST",
    body: {
      first_name: details.firstName,
      ...(details.lastName.trim() ? { last_name: details.lastName } : {}),
      phone: details.phone,
      password: details.password,
    },
  });
  await rememberSession(session);
}

export interface TenantSummary {
  id: string;
  name: string;
  slug: string;
}

export interface Category {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  parent_id: string | null;
  position: number;
}

export interface Product {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  category_id: string | null;
  description: string | null;
  selling_price: string | null;
  effective_normal_price: string | null;
  effective_wholesale_price: string | null;
  is_active: boolean;
  is_published: boolean;
}

export interface CustomerListLine {
  id: string;
  product_id: string | null;
  product_name: string | null;
  group_name: string | null;
  free_text: string | null;
  note: string | null;
  quantity: string;
  unit: string;
  pieces_per_pack: number | null;
  pieces: string | null;
  shop_price: string | null;
  cost_price: string | null;
  line_total: string | null;
  state: "somewhere" | "have_it" | "buy_it" | "cannot_get";
}

export interface CustomerList {
  id: string;
  tenant_id: string;
  customer_phone: string;
  customer_name: string | null;
  status: "received" | "quoted" | "confirmed" | "cancelled";
  created_at: string;
  priced_total: string | null;
  lines: CustomerListLine[];
}

export function listBusinesses(): Promise<TenantSummary[]> {
  return request<TenantSummary[]>("/api/v1/tenants");
}

export function listCategories(tenantId: string): Promise<Category[]> {
  return request<Category[]>(`/api/v1/tenants/${tenantId}/categories`);
}

export function listProducts(tenantId: string): Promise<Product[]> {
  return request<Product[]>(`/api/v1/tenants/${tenantId}/products`);
}

export function publishProduct(tenantId: string, productId: string): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products/${productId}/publish`, {
    method: "POST",
  });
}

export function unpublishProduct(tenantId: string, productId: string): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products/${productId}/unpublish`, {
    method: "POST",
  });
}

export function copyProducts(
  tenantId: string,
  productIds: string[],
  targetCategoryId: string | null = null,
): Promise<Product[]> {
  return request<Product[]>(`/api/v1/tenants/${tenantId}/products/copy`, {
    method: "POST",
    body: {
      product_ids: productIds,
      target_category_id: targetCategoryId,
    },
  });
}

export function recordSale(
  tenantId: string,
  sale: {
    lines: Array<{ product_id: string; quantity: string; unit_price: string }>;
    payment_method: string;
  },
): Promise<{ id: string; total_amount: string }> {
  return request<{ id: string; total_amount: string }>(`/api/v1/tenants/${tenantId}/sales`, {
    method: "POST",
    body: sale,
  });
}

export function sellOneProduct(tenantId: string, product: Product): Promise<{ id: string; total_amount: string }> {
  const price = product.effective_normal_price ?? product.selling_price ?? "0";
  return recordSale(tenantId, {
    lines: [{ product_id: product.id, quantity: "1.000", unit_price: price }],
    payment_method: "cash",
  });
}

export function listCustomerLists(tenantId: string): Promise<CustomerList[]> {
  return request<CustomerList[]>(`/api/v1/tenants/${tenantId}/requests`);
}

export function workListLine(
  tenantId: string,
  listId: string,
  lineId: string,
  updates: {
    shop_price?: string;
    state?: string;
  },
): Promise<CustomerList> {
  return request<CustomerList>(`/api/v1/tenants/${tenantId}/requests/${listId}/lines/${lineId}`, {
    method: "PATCH",
    body: updates,
  });
}

export function createProduct(
  tenantId: string,
  data: {
    name: string;
    selling_price?: string | null;
    wholesale_price?: string | null;
    category_id?: string | null;
    description?: string | null;
  },
): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products`, {
    method: "POST",
    body: data,
  });
}

export function updateProduct(
  tenantId: string,
  productId: string,
  data: {
    name?: string;
    selling_price?: string | null;
    wholesale_price?: string | null;
    category_id?: string | null;
    is_published?: boolean;
  },
): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products/${productId}`, {
    method: "PATCH",
    body: data,
  });
}

export function deleteCustomerList(tenantId: string, listId: string): Promise<void> {
  return request<void>(`/api/v1/tenants/${tenantId}/requests/${listId}`, {
    method: "DELETE",
  });
}

export function confirmCustomerList(tenantId: string, listId: string): Promise<CustomerList> {
  return request<CustomerList>(`/api/v1/tenants/${tenantId}/requests/${listId}/confirm`, {
    method: "POST",
  });
}

export function createCategory(
  tenantId: string,
  data: {
    name: string;
    parent_id?: string | null;
  },
): Promise<Category> {
  return request<Category>(`/api/v1/tenants/${tenantId}/categories`, {
    method: "POST",
    body: data,
  });
}

export interface SaleSummary {
  id: string;
  receipt_number: string;
  total_amount: string;
  payment_method: string;
  payment_status: string;
  created_at: string;
}

export function listSales(tenantId: string, limit: string = "50"): Promise<SaleSummary[]> {
  return request<SaleSummary[]>(`/api/v1/tenants/${tenantId}/sales?limit=${limit}`);
}

export interface DailySalesSummary {
  date: string;
  total_revenue: string;
  total_sales: number;
}

export function dailySales(tenantId: string): Promise<DailySalesSummary> {
  return request<DailySalesSummary>(`/api/v1/tenants/${tenantId}/reports/daily-sales`);
}

export interface ExpenseCategory {
  id: string;
  name: string;
}

export function listExpenseCategories(tenantId: string): Promise<{ categories: ExpenseCategory[] }> {
  return request<{ categories: ExpenseCategory[] }>(`/api/v1/tenants/${tenantId}/expenses/categories`);
}

export function recordExpense(
  tenantId: string,
  data: {
    category_id: string;
    amount: string;
    description?: string | null;
    payment_method: string;
  },
): Promise<{ id: string; amount: string }> {
  return request<{ id: string; amount: string }>(`/api/v1/tenants/${tenantId}/expenses`, {
    method: "POST",
    body: data,
  });
}

export function receiveStock(
  tenantId: string,
  productId: string,
  quantity: string,
): Promise<{ id: string; product_id: string; quantity_on_hand: string }> {
  return request<{ id: string; product_id: string; quantity_on_hand: string }>(
    `/api/v1/tenants/${tenantId}/inventory/${productId}/receive`,
    {
      method: "POST",
      body: { quantity },
    },
  );
}

export type MemberRole = "ADMIN" | "SALES" | "INVENTORY";

export interface Member {
  id: string;
  user_id: string;
  role: MemberRole;
  status: "active" | "invited" | "suspended" | "removed";
  first_name: string;
  last_name: string | null;
  phone: string | null;
  email: string | null;
  joined_at: string;
}

export interface MembershipInvitation {
  id: string;
  tenant_id: string;
  role: MemberRole;
  phone: string | null;
  email: string | null;
  token?: string;
  status: "pending" | "accepted" | "expired" | "revoked";
  created_at: string;
}

export function listMembers(tenantId: string): Promise<Member[]> {
  return request<Member[]>(`/api/v1/tenants/${tenantId}/members`);
}

export function listInvitations(tenantId: string): Promise<MembershipInvitation[]> {
  return request<MembershipInvitation[]>(`/api/v1/tenants/${tenantId}/invitations`);
}

export function inviteMember(
  tenantId: string,
  data: {
    role: MemberRole;
    phone?: string;
    email?: string;
  },
): Promise<MembershipInvitation> {
  return request<MembershipInvitation>(`/api/v1/tenants/${tenantId}/invitations`, {
    method: "POST",
    body: data,
  });
}

export function removeMember(tenantId: string, memberId: string): Promise<void> {
  return request<void>(`/api/v1/tenants/${tenantId}/members/${memberId}`, {
    method: "DELETE",
  });
}

export interface UserProfile {
  id: string;
  first_name: string;
  last_name: string | null;
  phone: string | null;
  email: string | null;
}

export function currentUser(): Promise<UserProfile> {
  return request<UserProfile>("/api/v1/users/me");
}

export function updateProfile(data: {
  first_name?: string;
  last_name?: string;
  phone?: string;
  email?: string;
}): Promise<UserProfile> {
  return request<UserProfile>("/api/v1/users/me", {
    method: "PATCH",
    body: data,
  });
}

export interface TenantDetails {
  id: string;
  name: string;
  slug: string;
  phone?: string | null;
  address?: string | null;
  city?: string | null;
  state?: string | null;
}

export function getBusiness(tenantId: string): Promise<TenantDetails> {
  return request<TenantDetails>(`/api/v1/tenants/${tenantId}`);
}

export function updateBusiness(
  tenantId: string,
  data: {
    name?: string;
    phone?: string | null;
    address?: string | null;
    city?: string | null;
    state?: string | null;
  },
): Promise<TenantDetails> {
  return request<TenantDetails>(`/api/v1/tenants/${tenantId}`, {
    method: "PATCH",
    body: data,
  });
}
