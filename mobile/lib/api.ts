import {
  currentAccessToken,
  forgetSession,
  readRefreshToken,
  readStoredAccessToken,
  rememberSession,
} from "./session";

/**
 * The same API the web app calls, from a phone.
 *
 * Persists session credentials securely on device and automatically restores
 * sessions on app startup.
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
  try {
    const response = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) {
      await forgetSession();
      return false;
    }
    await rememberSession(await response.json());
    return true;
  } catch {
    return false;
  }
}

/** Check if there is an active session on device and restore it. */
export async function restoreSession(): Promise<boolean> {
  const refreshToken = await readRefreshToken();
  if (!refreshToken) return false;
  await readStoredAccessToken();
  if (currentAccessToken()) {
    return true;
  }
  return await refreshOnce();
}

/**
 * Call the API, refreshing once if the access token has expired.
 */
export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const send = async (): Promise<Response> => {
    let token = currentAccessToken();
    if (!token) {
      token = await readStoredAccessToken();
    }
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
  role_name?: string;
  public_path?: string;
  is_active?: boolean;
}

export interface Category {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  parent_id: string | null;
  position: number;
  description?: string | null;
  default_normal_price?: string | null;
  default_wholesale_price?: string | null;
  default_pieces_per_pack?: number | null;
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
  note?: string | null;
  created_at: string;
  priced_total: string | null;
  unpriced_line_count?: number;
  transporter_name?: string | null;
  transporter_phone?: string | null;
  waybill_number?: string | null;
  dispatch_cost?: string | null;
  tracking_url?: string | null;
  dispatched_at?: string | null;
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
    shop_price?: string | null;
    cost_price?: string | null;
    state?: "somewhere" | "have_it" | "buy_it" | "cannot_get" | string;
  },
): Promise<CustomerList> {
  return request<CustomerList>(`/api/v1/tenants/${tenantId}/requests/${listId}/lines/${lineId}`, {
    method: "PATCH",
    body: updates,
  });
}

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
  return request<CustomerList>(`/api/v1/tenants/${tenantId}/requests/${requestId}/dispatch`, {
    method: "POST",
    body: details,
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

export interface PublicRequestLine {
  product_slug?: string | null;
  free_text?: string | null;
  quantity: string;
  unit?: string;
  note?: string | null;
  parent_position?: number | null;
}

export interface PublicRequestPayload {
  customer_phone: string;
  customer_name?: string | null;
  lines: PublicRequestLine[];
}

export function submitCustomerList(
  tenantSlug: string,
  payload: PublicRequestPayload,
): Promise<{ request_id: string; line_count: number; message: string; list_path: string }> {
  return request<{ request_id: string; line_count: number; message: string; list_path: string }>(
    `/shop/${encodeURIComponent(tenantSlug)}/requests`,
    {
      method: "POST",
      body: payload,
    },
  );
}

export function createCategory(
  tenantId: string,
  data: {
    name: string;
    parent_id?: string | null;
    default_normal_price?: string | null;
    default_wholesale_price?: string | null;
    default_pieces_per_pack?: number | null;
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
  cancelled_at?: string | null;
}

export function listSales(tenantId: string, limit: string = "50"): Promise<SaleSummary[]> {
  return request<SaleSummary[]>(`/api/v1/tenants/${tenantId}/sales?limit=${limit}`);
}

export function cancelSale(tenantId: string, saleId: string, reason: string): Promise<void> {
  return request<void>(`/api/v1/tenants/${tenantId}/sales/${saleId}/cancel`, {
    method: "POST",
    body: { reason },
  });
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
  description?: string | null;
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

export type MemberRole = "OWNER" | "MANAGER" | "SALES" | "INVENTORY" | "ADMIN";

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

export function changeMemberRole(
  tenantId: string,
  memberId: string,
  role: MemberRole,
): Promise<Member> {
  return request<Member>(`/api/v1/tenants/${tenantId}/members/${memberId}`, {
    method: "PATCH",
    body: { role_name: role },
  });
}

export function changeMemberStatus(
  tenantId: string,
  memberId: string,
  status: "active" | "suspended",
): Promise<Member> {
  return request<Member>(`/api/v1/tenants/${tenantId}/members/${memberId}`, {
    method: "PATCH",
    body: { status },
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

export function updateCategory(
  tenantId: string,
  categoryId: string,
  data: {
    name?: string;
    description?: string | null;
    parent_id?: string | null;
    default_normal_price?: string | null;
    default_wholesale_price?: string | null;
    default_pieces_per_pack?: number | null;
  },
): Promise<Category> {
  return request<Category>(`/api/v1/tenants/${tenantId}/categories/${categoryId}`, {
    method: "PATCH",
    body: data,
  });
}

export interface StorefrontDetails {
  id: string;
  tenant_id: string;
  headline: string | null;
  description: string | null;
  contact_phone: string | null;
  theme_color: string | null;
  theme_bg_color: string | null;
  theme_bg_image: string | null;
  closing_statement: string | null;
  is_published: boolean;
}

export function getStorefront(tenantId: string): Promise<StorefrontDetails> {
  return request<StorefrontDetails>(`/api/v1/tenants/${tenantId}/storefront`);
}

export function updateStorefront(
  tenantId: string,
  data: {
    headline?: string | null;
    description?: string | null;
    contact_phone?: string | null;
    theme_color?: string | null;
    theme_bg_color?: string | null;
    theme_bg_image?: string | null;
    closing_statement?: string | null;
  },
): Promise<StorefrontDetails> {
  return request<StorefrontDetails>(`/api/v1/tenants/${tenantId}/storefront`, {
    method: "PATCH",
    body: data,
  });
}

export function publishStorefront(
  tenantId: string,
  details: { headline?: string | null; description?: string | null; contact_phone?: string | null },
): Promise<StorefrontDetails> {
  return request<StorefrontDetails>(`/api/v1/tenants/${tenantId}/storefront/publish`, {
    method: "POST",
    body: details,
  });
}

export function unpublishStorefront(tenantId: string): Promise<StorefrontDetails> {
  return request<StorefrontDetails>(`/api/v1/tenants/${tenantId}/storefront/unpublish`, {
    method: "POST",
    body: {},
  });
}

export interface ProductImage {
  id: string;
  product_id: string;
  delivery_url: string;
  is_primary: boolean;
  position: number;
}

export function listProductImages(tenantId: string, productId: string): Promise<ProductImage[]> {
  return request<ProductImage[]>(`/api/v1/tenants/${tenantId}/products/${productId}/images`);
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
): Promise<void> {
  return request<void>(
    `/api/v1/tenants/${tenantId}/products/${productId}/images/${imageId}`,
    { method: "DELETE" },
  );
}

export function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  return request<void>("/api/v1/auth/password", {
    method: "POST",
    body: {
      current_password: currentPassword,
      new_password: newPassword,
    },
  });
}

export interface PendingInvitation {
  id: string;
  tenant_id: string;
  tenant_name: string;
  role: MemberRole;
  role_name: string;
  invited_phone: string | null;
  invited_email: string | null;
  created_at: string;
}

export interface AcceptedInvitation {
  membership_id: string;
  tenant_id: string;
  tenant_name: string;
  role: MemberRole;
  role_name: string;
}

export function listMyInvitations(): Promise<PendingInvitation[]> {
  return request<PendingInvitation[]>("/api/v1/invitations");
}

export function acceptInvitation(token: string): Promise<AcceptedInvitation> {
  return request<AcceptedInvitation>("/api/v1/invitations/accept", {
    method: "POST",
    body: { token },
  });
}

export function deleteProduct(
  tenantId: string,
  productId: string,
): Promise<Product> {
  return request<Product>(`/api/v1/tenants/${tenantId}/products/${productId}`, {
    method: "DELETE",
  });
}

export function deleteCategory(
  tenantId: string,
  categoryId: string,
  strategy: "move_up" | "cascade" | "restrict" = "move_up",
): Promise<void> {
  return request<void>(`/api/v1/tenants/${tenantId}/categories/${categoryId}?strategy=${encodeURIComponent(strategy)}`, {
    method: "DELETE",
  });
}

export function moveCategory(
  tenantId: string,
  categoryId: string,
  newParentId: string | null,
): Promise<Category> {
  return request<Category>(`/api/v1/tenants/${tenantId}/categories/${categoryId}/move`, {
    method: "POST",
    body: { new_parent_id: newParentId },
  });
}

export interface ProductShareSheet {
  product_name: string;
  public_url: string;
  qr_payload: string;
  whatsapp_url: string | null;
  whatsapp_unavailable_reason: string | null;
}

export function productShareSheet(tenantId: string, productId: string): Promise<ProductShareSheet> {
  return request<ProductShareSheet>(
    `/api/v1/tenants/${tenantId}/products/${productId}/share-sheet`,
  );
}

export interface LowStockProduct {
  product_id: string;
  product_name: string;
  quantity_on_hand: string;
  low_stock_threshold?: string | null;
}

export function lowStock(tenantId: string, limit = "5"): Promise<LowStockProduct[]> {
  return request<LowStockProduct[]>(`/api/v1/tenants/${tenantId}/reports/low-stock?limit=${limit}`);
}
