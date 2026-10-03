import * as SQLite from "expo-sqlite";
import {
  type Product,
  type Category,
  type CustomerList,
  type BusinessMembership,
  type TenantSummary,
  type UserProfile,
  type TenantDetails,
  type DailySalesSummary,
  type SaleSummary,
  type ExpenseItem,
  ApiError,
  recordSale,
  createCategory,
  updateCategory,
  deleteCategory,
  createProduct,
  updateProduct,
  deleteProduct,
} from "./api";

/**
 * Local SQLite storage for offline shelf reading, categories, customer lists, and durable sale outbox.
 *
 * Designed for market connectivity: a trader can view cached shelf products and record
 * a "sell one" transaction even when mobile network stalls. Pending transactions are
 * durably queued and flushed when connection returns.
 *
 * All operations are strictly guarded against crashes, thread issues, and profile switches.
 */

let dbInstance: SQLite.SQLiteDatabase | null = null;

function runMigrations(db: SQLite.SQLiteDatabase): void {
  // 1. Create tables if they do not exist
  db.execSync(`
    CREATE TABLE IF NOT EXISTS cached_products (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      name TEXT NOT NULL,
      slug TEXT NOT NULL,
      category_id TEXT,
      selling_price TEXT,
      effective_normal_price TEXT,
      effective_wholesale_price TEXT,
      is_published INTEGER NOT NULL,
      is_active INTEGER NOT NULL,
      image_url TEXT,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cached_categories (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      name TEXT NOT NULL,
      slug TEXT NOT NULL,
      parent_id TEXT,
      position INTEGER NOT NULL DEFAULT 0,
      description TEXT,
      default_normal_price TEXT,
      default_wholesale_price TEXT,
      default_pieces_per_pack INTEGER,
      image_url TEXT,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cached_customer_lists (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      customer_name TEXT,
      customer_phone TEXT,
      status TEXT NOT NULL,
      priced_total TEXT,
      data_json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cached_businesses (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      slug TEXT NOT NULL,
      currency TEXT NOT NULL DEFAULT 'NGN',
      role_name TEXT NOT NULL DEFAULT 'OWNER',
      is_active INTEGER NOT NULL DEFAULT 1,
      logo_url TEXT,
      address TEXT,
      phone TEXT,
      email TEXT,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cached_profile (
      id TEXT PRIMARY KEY,
      first_name TEXT NOT NULL,
      last_name TEXT,
      phone TEXT,
      email TEXT,
      avatar_url TEXT,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cached_business_details (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      slug TEXT NOT NULL,
      phone TEXT,
      address TEXT,
      city TEXT,
      state TEXT,
      logo_url TEXT,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cached_daily_stats (
      tenant_id TEXT PRIMARY KEY,
      date TEXT NOT NULL,
      total_revenue TEXT NOT NULL,
      total_sales INTEGER NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cached_sales (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      data_json TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cached_expenses (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      category TEXT NOT NULL,
      amount TEXT NOT NULL,
      payment_method TEXT NOT NULL,
      description TEXT,
      incurred_at TEXT NOT NULL,
      is_reversed INTEGER NOT NULL DEFAULT 0,
      data_json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS app_settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sale_outbox (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      product_id TEXT NOT NULL,
      product_name TEXT NOT NULL,
      quantity TEXT NOT NULL,
      unit_price TEXT NOT NULL,
      payment_method TEXT NOT NULL,
      created_at TEXT NOT NULL,
      status TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS inventory_deltas (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      product_id TEXT NOT NULL,
      delta_quantity TEXT NOT NULL,
      reason TEXT NOT NULL,
      created_at TEXT NOT NULL,
      status TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sync_conflicts (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      entity_type TEXT NOT NULL,
      entity_id TEXT NOT NULL,
      entity_title TEXT NOT NULL,
      local_data TEXT NOT NULL,
      server_data TEXT NOT NULL,
      created_at TEXT NOT NULL,
      status TEXT NOT NULL,
      resolution TEXT
    );
    CREATE TABLE IF NOT EXISTS catalog_revisions (
      product_id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      server_updated_at TEXT,
      local_updated_at TEXT,
      has_local_edit INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS sync_outbox (
      id TEXT PRIMARY KEY,
      tenant_id TEXT NOT NULL,
      action TEXT NOT NULL,
      entity_type TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
      status TEXT NOT NULL,
      retry_count INTEGER NOT NULL DEFAULT 0
    );
  `);

  // 2. Ensure dynamic schema migration for existing tables on user devices
  const ensureCol = (table: string, column: string, colDef: string) => {
    try {
      const tableInfo = db.getAllSync<{ name: string }>(`PRAGMA table_info(${table})`);
      const exists = tableInfo.some((c) => c.name.toLowerCase() === column.toLowerCase());
      if (!exists) {
        db.execSync(`ALTER TABLE ${table} ADD COLUMN ${column} ${colDef};`);
      }
    } catch {
      // Table may not exist yet or altered previously
    }
  };

  ensureCol("cached_categories", "image_url", "TEXT");
  ensureCol("cached_categories", "description", "TEXT");
  ensureCol("cached_categories", "default_normal_price", "TEXT");
  ensureCol("cached_categories", "default_wholesale_price", "TEXT");
  ensureCol("cached_categories", "default_pieces_per_pack", "INTEGER");

  ensureCol("cached_products", "image_url", "TEXT");
  ensureCol("cached_products", "effective_normal_price", "TEXT");
  ensureCol("cached_products", "effective_wholesale_price", "TEXT");
  ensureCol("cached_products", "description", "TEXT");

  ensureCol("cached_businesses", "logo_url", "TEXT");
  ensureCol("cached_businesses", "currency", "TEXT DEFAULT 'NGN'");
  ensureCol("cached_businesses", "role_name", "TEXT DEFAULT 'OWNER'");
  ensureCol("cached_businesses", "is_active", "INTEGER DEFAULT 1");
  ensureCol("cached_businesses", "address", "TEXT");
  ensureCol("cached_businesses", "phone", "TEXT");
  ensureCol("cached_businesses", "email", "TEXT");
}

function getDb(): SQLite.SQLiteDatabase | null {
  try {
    if (!dbInstance) {
      dbInstance = SQLite.openDatabaseSync("ahia_local.db");
      runMigrations(dbInstance);
    }
    return dbInstance;
  } catch (error) {
    console.warn("[AHIA DB] Error initializing local SQLite:", error);
    return null;
  }
}

/** Clear cached data safely on profile switch or logout. */
export function clearLocalDatabase(): void {
  try {
    const db = getDb();
    if (!db) return;
    db.execSync(`
      DELETE FROM cached_products;
      DELETE FROM cached_categories;
      DELETE FROM cached_customer_lists;
      DELETE FROM cached_businesses;
      DELETE FROM cached_profile;
      DELETE FROM cached_business_details;
      DELETE FROM cached_daily_stats;
      DELETE FROM cached_sales;
      DELETE FROM catalog_revisions;
      DELETE FROM app_settings;
    `);
  } catch {
    // Non-fatal
  }
}

export function cacheProducts(tenantId: string, products: Product[]): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    db.withTransactionSync(() => {
      for (const p of products) {
        db.runSync(
          `INSERT OR REPLACE INTO cached_products
           (id, tenant_id, name, slug, category_id, selling_price, effective_normal_price, effective_wholesale_price, is_published, is_active, image_url, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            p.id,
            tenantId,
            p.name,
            p.slug,
            p.category_id,
            p.selling_price,
            p.effective_normal_price,
            p.effective_wholesale_price,
            p.is_published ? 1 : 0,
            p.is_active ? 1 : 0,
            p.image_url ?? null,
            now,
          ],
        );
      }
    });
  } catch {
    // Non-fatal if local cache write fails
  }
}

export function getCachedProducts(tenantId: string): Product[] {
  try {
    const db = getDb();
    if (!db) return [];
    const rows = db.getAllSync<{
      id: string;
      tenant_id: string;
      name: string;
      slug: string;
      category_id: string | null;
      selling_price: string | null;
      effective_normal_price: string | null;
      effective_wholesale_price: string | null;
      is_published: number;
      is_active: number;
      image_url?: string | null;
    }>(
      "SELECT * FROM cached_products WHERE tenant_id = ? ORDER BY name ASC",
      [tenantId],
    );
    return rows.map((r) => ({
      id: r.id,
      tenant_id: r.tenant_id,
      name: r.name,
      slug: r.slug,
      category_id: r.category_id,
      description: null,
      selling_price: r.selling_price,
      effective_normal_price: r.effective_normal_price,
      effective_wholesale_price: r.effective_wholesale_price,
      is_active: r.is_active === 1,
      is_published: r.is_published === 1,
      image_url: r.image_url ?? null,
    }));
  } catch {
    return [];
  }
}

export function cacheCategories(tenantId: string, categories: Category[]): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    db.withTransactionSync(() => {
      for (const c of categories) {
        db.runSync(
          `INSERT OR REPLACE INTO cached_categories (id, tenant_id, name, slug, parent_id, position, description, default_normal_price, default_wholesale_price, default_pieces_per_pack, image_url, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            c.id,
            tenantId,
            c.name,
            c.slug,
            c.parent_id ?? null,
            c.position ?? 0,
            c.description ?? null,
            c.default_normal_price ?? null,
            c.default_wholesale_price ?? null,
            c.default_pieces_per_pack ?? null,
            c.image_url ?? null,
            now,
          ],
        );
      }
    });
  } catch {
    // Non-fatal if local cache write fails
  }
}

export function getCachedCategories(tenantId: string): Category[] {
  try {
    const db = getDb();
    if (!db) return [];
    const rows = db.getAllSync<{
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
      image_url?: string | null;
    }>(
      "SELECT id, tenant_id, name, slug, parent_id, position, description, default_normal_price, default_wholesale_price, default_pieces_per_pack, image_url FROM cached_categories WHERE tenant_id = ? ORDER BY position ASC, name ASC",
      [tenantId],
    );
    return rows.map((r) => ({
      id: r.id,
      tenant_id: r.tenant_id,
      name: r.name,
      slug: r.slug,
      parent_id: r.parent_id,
      position: r.position,
      description: r.description ?? null,
      default_normal_price: r.default_normal_price ?? null,
      default_wholesale_price: r.default_wholesale_price ?? null,
      default_pieces_per_pack: r.default_pieces_per_pack ?? null,
      image_url: r.image_url ?? null,
    }));
  } catch {
    return [];
  }
}

export function cacheCustomerLists(tenantId: string, lists: CustomerList[]): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    const existing = getCachedCustomerLists(tenantId);
    const existingMap = new Map(existing.map((l) => [l.id, l]));

    db.withTransactionSync(() => {
      for (const l of lists) {
        const prev = existingMap.get(l.id);
        const merged: CustomerList = {
          ...l,
          fulfillment_type: l.fulfillment_type ?? prev?.fulfillment_type,
          payments: (l.payments && l.payments.length > 0) ? l.payments : (prev?.payments ?? []),
          amount_paid: l.amount_paid ?? prev?.amount_paid,
          advance_payment: l.advance_payment ?? prev?.advance_payment,
        };
        db.runSync(
          `INSERT OR REPLACE INTO cached_customer_lists (id, tenant_id, customer_name, customer_phone, status, priced_total, data_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            merged.id,
            tenantId,
            merged.customer_name ?? null,
            merged.customer_phone ?? null,
            merged.status,
            merged.priced_total ?? null,
            JSON.stringify(merged),
            now,
          ],
        );
      }
    });
  } catch {
    // Non-fatal if local cache write fails
  }
}

export function getCachedCustomerLists(tenantId: string): CustomerList[] {
  try {
    const db = getDb();
    if (!db) return [];
    const rows = db.getAllSync<{ data_json: string }>(
      "SELECT data_json FROM cached_customer_lists WHERE tenant_id = ? ORDER BY updated_at DESC",
      [tenantId],
    );
    return rows.map((r) => JSON.parse(r.data_json) as CustomerList);
  } catch {
    return [];
  }
}

export function updateCachedCustomerList(tenantId: string, list: CustomerList): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    db.runSync(
      `INSERT OR REPLACE INTO cached_customer_lists (id, tenant_id, customer_name, customer_phone, status, priced_total, data_json, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        list.id,
        tenantId,
        list.customer_name ?? null,
        list.customer_phone ?? null,
        list.status,
        list.priced_total ?? null,
        JSON.stringify(list),
        now,
      ],
    );
  } catch {
    // Non-fatal
  }
}

export function cacheBusinesses(businesses: Array<BusinessMembership | TenantSummary>): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    db.withTransactionSync(() => {
      for (const b of businesses) {
        const isActiveVal = b.is_active === false ? 0 : 1;
        db.runSync(
          `INSERT OR REPLACE INTO cached_businesses (id, name, slug, currency, role_name, is_active, logo_url, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
          [b.id, b.name, b.slug, b.currency || "NGN", b.role_name || "OWNER", isActiveVal, b.logo_url ?? null, now],
        );
      }
    });
  } catch {
    // Non-fatal
  }
}

export function getCachedBusinesses(): BusinessMembership[] {
  try {
    const db = getDb();
    if (!db) return [];
    const rows = db.getAllSync<{
      id: string;
      name: string;
      slug: string;
      currency?: string | null;
      role_name?: string | null;
      is_active?: number | null;
      logo_url?: string | null;
    }>("SELECT id, name, slug, currency, role_name, is_active, logo_url FROM cached_businesses ORDER BY is_active DESC, updated_at DESC, name ASC");
    return rows.map((r) => ({
      id: r.id,
      name: r.name,
      slug: r.slug,
      currency: r.currency || "NGN",
      role_name: r.role_name || "OWNER",
      is_active: r.is_active !== 0,
      logo_url: r.logo_url ?? null,
    }));
  } catch {
    return [];
  }
}

/** Persistent App Settings (last active stall, preferences). */
export function setAppSetting(key: string, value: string): void {
  try {
    const db = getDb();
    if (!db) return;
    db.runSync(
      "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
      [key, value],
    );
  } catch {
    // Non-fatal
  }
}

export function getAppSetting(key: string): string | null {
  try {
    const db = getDb();
    if (!db) return null;
    const row = db.getFirstSync<{ value: string }>(
      "SELECT value FROM app_settings WHERE key = ?",
      [key],
    );
    return row ? row.value : null;
  } catch {
    return null;
  }
}

/** Cache user profile for offline viewing. */
export function cacheProfile(profile: UserProfile): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    db.runSync(
      `INSERT OR REPLACE INTO cached_profile (id, first_name, last_name, phone, email, avatar_url, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        profile.id,
        profile.first_name,
        profile.last_name ?? null,
        profile.phone ?? null,
        profile.email ?? null,
        profile.avatar_url ?? null,
        now,
      ],
    );
  } catch {
    // Non-fatal
  }
}

export function getCachedProfile(): UserProfile | null {
  try {
    const db = getDb();
    if (!db) return null;
    const row = db.getFirstSync<{
      id: string;
      first_name: string;
      last_name?: string | null;
      phone?: string | null;
      email?: string | null;
      avatar_url?: string | null;
    }>("SELECT id, first_name, last_name, phone, email, avatar_url FROM cached_profile ORDER BY updated_at DESC LIMIT 1");
    if (!row) return null;
    return {
      id: row.id,
      first_name: row.first_name,
      last_name: row.last_name ?? null,
      phone: row.phone ?? null,
      email: row.email ?? null,
      avatar_url: row.avatar_url ?? null,
    };
  } catch {
    return null;
  }
}

/** Cache business details for offline viewing. */
export function cacheBusinessDetails(tenantId: string, details: TenantDetails): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    db.runSync(
      `INSERT OR REPLACE INTO cached_business_details (id, name, slug, phone, address, city, state, logo_url, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        tenantId,
        details.name,
        details.slug,
        details.phone ?? null,
        details.address ?? null,
        details.city ?? null,
        details.state ?? null,
        details.logo_url ?? null,
        now,
      ],
    );
  } catch {
    // Non-fatal
  }
}

export function getCachedBusinessDetails(tenantId: string): TenantDetails | null {
  try {
    const db = getDb();
    if (!db) return null;
    const row = db.getFirstSync<{
      id: string;
      name: string;
      slug: string;
      phone?: string | null;
      address?: string | null;
      city?: string | null;
      state?: string | null;
      logo_url?: string | null;
    }>("SELECT id, name, slug, phone, address, city, state, logo_url FROM cached_business_details WHERE id = ?", [tenantId]);
    if (!row) return null;
    return {
      id: row.id,
      name: row.name,
      slug: row.slug,
      phone: row.phone ?? null,
      address: row.address ?? null,
      city: row.city ?? null,
      state: row.state ?? null,
      logo_url: row.logo_url ?? null,
    };
  } catch {
    return null;
  }
}

/** Cache daily sales stats for offline viewing. */
export function cacheDailyStats(tenantId: string, stats: DailySalesSummary): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    db.runSync(
      `INSERT OR REPLACE INTO cached_daily_stats (tenant_id, date, total_revenue, total_sales, updated_at)
       VALUES (?, ?, ?, ?, ?)`,
      [tenantId, stats.date, stats.total_revenue, stats.total_sales, now],
    );
  } catch {
    // Non-fatal
  }
}

export function getCachedDailyStats(tenantId: string): DailySalesSummary | null {
  try {
    const db = getDb();
    if (!db) return null;
    const row = db.getFirstSync<{
      tenant_id: string;
      date: string;
      total_revenue: string;
      total_sales: number;
    }>("SELECT tenant_id, date, total_revenue, total_sales FROM cached_daily_stats WHERE tenant_id = ?", [tenantId]);
    if (!row) return null;
    return {
      date: row.date,
      total_revenue: row.total_revenue,
      total_sales: row.total_sales,
    };
  } catch {
    return null;
  }
}

/** Cache recent sales for offline viewing. */
export function cacheSales(tenantId: string, sales: SaleSummary[]): void {
  try {
    const db = getDb();
    if (!db) return;
    db.withTransactionSync(() => {
      for (const s of sales) {
        db.runSync(
          `INSERT OR REPLACE INTO cached_sales (id, tenant_id, data_json, created_at)
           VALUES (?, ?, ?, ?)`,
          [s.id, tenantId, JSON.stringify(s), s.created_at],
        );
      }
    });
  } catch {
    // Non-fatal
  }
}

export function getCachedSales(tenantId: string): SaleSummary[] {
  try {
    const db = getDb();
    if (!db) return [];
    const rows = db.getAllSync<{ data_json: string }>(
      "SELECT data_json FROM cached_sales WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 50",
      [tenantId],
    );
    return rows.map((r) => JSON.parse(r.data_json) as SaleSummary);
  } catch {
    return [];
  }
}

/** Cache recent expenses for offline viewing. */
export function cacheExpenses(tenantId: string, expenses: ExpenseItem[]): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    db.withTransactionSync(() => {
      for (const e of expenses) {
        db.runSync(
          `INSERT OR REPLACE INTO cached_expenses (id, tenant_id, category, amount, payment_method, description, incurred_at, is_reversed, data_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            e.id,
            tenantId,
            e.category,
            e.amount,
            e.payment_method,
            e.description ?? null,
            e.incurred_at,
            e.is_reversed ? 1 : 0,
            JSON.stringify(e),
            now,
          ],
        );
      }
    });
  } catch {
    // Non-fatal
  }
}

export function getCachedExpenses(tenantId: string): ExpenseItem[] {
  try {
    const db = getDb();
    if (!db) return [];
    const rows = db.getAllSync<{ data_json: string }>(
      "SELECT data_json FROM cached_expenses WHERE tenant_id = ? ORDER BY incurred_at DESC LIMIT 100",
      [tenantId],
    );
    return rows.map((r) => JSON.parse(r.data_json) as ExpenseItem);
  } catch {
    return [];
  }
}

export function enqueueOfflineSale(sale: {
  tenantId: string;
  productId: string;
  productName: string;
  quantity: string;
  unitPrice: string;
  paymentMethod: string;
}): string {
  const id = `outbox-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  try {
    const db = getDb();
    if (!db) return id;
    const now = new Date().toISOString();
    db.runSync(
      `INSERT INTO sale_outbox (id, tenant_id, product_id, product_name, quantity, unit_price, payment_method, created_at, status)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        id,
        sale.tenantId,
        sale.productId,
        sale.productName,
        sale.quantity,
        sale.unitPrice,
        sale.paymentMethod,
        now,
        "pending",
      ],
    );
  } catch {
    // Fallback if local storage fails
  }
  return id;
}

export function getPendingSalesCount(tenantId: string): number {
  try {
    const db = getDb();
    if (!db) return 0;
    const row = db.getFirstSync<{ count: number }>(
      "SELECT COUNT(*) as count FROM sale_outbox WHERE tenant_id = ? AND status = 'pending'",
      [tenantId],
    );
    return row?.count ?? 0;
  } catch {
    return 0;
  }
}

export async function flushOutbox(tenantId: string): Promise<number> {
  try {
    const db = getDb();
    if (!db) return 0;
    const pending = db.getAllSync<{
      id: string;
      product_id: string;
      quantity: string;
      unit_price: string;
      payment_method: string;
    }>(
      "SELECT id, product_id, quantity, unit_price, payment_method FROM sale_outbox WHERE tenant_id = ? AND status = 'pending'",
      [tenantId],
    );

    let synced = 0;
    for (const item of pending) {
      try {
        await recordSale(tenantId, {
          lines: [
            {
              product_id: item.product_id,
              quantity: item.quantity,
              unit_price: item.unit_price,
            },
          ],
          payment_method: item.payment_method,
        });
        db.runSync("UPDATE sale_outbox SET status = 'synced' WHERE id = ?", [item.id]);
        synced++;
      } catch (err: any) {
        if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
          // Unrecoverable client error (e.g. 400 Bad Request, 404 Not Found, 422 Invalid value)
          // Mark as failed so it does not block the sync queue forever
          db.runSync("UPDATE sale_outbox SET status = 'failed' WHERE id = ?", [item.id]);
          continue;
        }
        // Stays pending if network stalls / 5xx
        break;
      }
    }
    return synced;
  } catch {
    return 0;
  }
}

/** Enqueue a generic mutation into SQLite sync_outbox. */
export function enqueueOutboxMutation(
  tenantId: string,
  action: "CREATE_CATEGORY" | "UPDATE_CATEGORY" | "DELETE_CATEGORY" | "CREATE_PRODUCT" | "UPDATE_PRODUCT" | "DELETE_PRODUCT",
  entityType: "category" | "product",
  payload: Record<string, unknown>,
): string {
  const id = `outbox-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  try {
    const db = getDb();
    if (!db) return id;
    const now = new Date().toISOString();
    db.runSync(
      `INSERT INTO sync_outbox (id, tenant_id, action, entity_type, payload_json, created_at, status, retry_count)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [id, tenantId, action, entityType, JSON.stringify(payload), now, "pending", 0],
    );
  } catch {
    // Non-fatal
  }
  return id;
}

/** Total pending outbox count across sales and catalog mutations. */
export function getPendingOutboxCount(tenantId: string): number {
  try {
    const db = getDb();
    if (!db) return 0;
    const saleRow = db.getFirstSync<{ count: number }>(
      "SELECT COUNT(*) as count FROM sale_outbox WHERE tenant_id = ? AND status = 'pending'",
      [tenantId],
    );
    const syncRow = db.getFirstSync<{ count: number }>(
      "SELECT COUNT(*) as count FROM sync_outbox WHERE tenant_id = ? AND status = 'pending'",
      [tenantId],
    );
    return (saleRow?.count ?? 0) + (syncRow?.count ?? 0);
  } catch {
    return 0;
  }
}

/** Create a category locally first in SQLite and enqueue for sync. */
export function createLocalCategory(
  tenantId: string,
  data: {
    name: string;
    parent_id?: string | null;
    default_normal_price?: string | null;
    default_wholesale_price?: string | null;
    default_pieces_per_pack?: number | null;
    description?: string | null;
    image_url?: string | null;
  },
): Category {
  const tempId = `cat-local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const slug = data.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  const category: Category = {
    id: tempId,
    tenant_id: tenantId,
    name: data.name,
    slug: slug || "category",
    parent_id: data.parent_id ?? null,
    position: 0,
    description: data.description ?? null,
    default_normal_price: data.default_normal_price ?? null,
    default_wholesale_price: data.default_wholesale_price ?? null,
    default_pieces_per_pack: data.default_pieces_per_pack ?? null,
    image_url: data.image_url ?? null,
  };

  try {
    const db = getDb();
    if (db) {
      const now = new Date().toISOString();
      db.runSync(
        `INSERT OR REPLACE INTO cached_categories (id, tenant_id, name, slug, parent_id, position, description, default_normal_price, default_wholesale_price, default_pieces_per_pack, image_url, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [
          category.id,
          tenantId,
          category.name,
          category.slug,
          category.parent_id ?? null,
          0,
          category.description ?? null,
          category.default_normal_price ?? null,
          category.default_wholesale_price ?? null,
          category.default_pieces_per_pack ?? null,
          category.image_url ?? null,
          now,
        ],
      );
    }
  } catch {
    // Non-fatal
  }

  enqueueOutboxMutation(tenantId, "CREATE_CATEGORY", "category", {
    temp_id: tempId,
    name: data.name,
    parent_id: data.parent_id ?? null,
    default_normal_price: data.default_normal_price ?? null,
    default_wholesale_price: data.default_wholesale_price ?? null,
    default_pieces_per_pack: data.default_pieces_per_pack ?? null,
    description: data.description ?? null,
  });

  return category;
}

/** Update a category locally and enqueue for sync. */
export function updateLocalCategory(
  tenantId: string,
  categoryId: string,
  data: {
    name?: string;
    default_normal_price?: string | null;
    default_wholesale_price?: string | null;
    default_pieces_per_pack?: number | null;
    description?: string | null;
    image_url?: string | null;
  },
): void {
  try {
    const db = getDb();
    if (db) {
      if (data.name) {
        db.runSync("UPDATE cached_categories SET name = ? WHERE id = ? AND tenant_id = ?", [
          data.name,
          categoryId,
          tenantId,
        ]);
      }
      if (data.default_normal_price !== undefined) {
        db.runSync(
          "UPDATE cached_categories SET default_normal_price = ? WHERE id = ? AND tenant_id = ?",
          [data.default_normal_price, categoryId, tenantId],
        );
      }
      if (data.default_wholesale_price !== undefined) {
        db.runSync(
          "UPDATE cached_categories SET default_wholesale_price = ? WHERE id = ? AND tenant_id = ?",
          [data.default_wholesale_price, categoryId, tenantId],
        );
      }
      if (data.default_pieces_per_pack !== undefined) {
        db.runSync(
          "UPDATE cached_categories SET default_pieces_per_pack = ? WHERE id = ? AND tenant_id = ?",
          [data.default_pieces_per_pack, categoryId, tenantId],
        );
      }
      if (data.description !== undefined) {
        db.runSync(
          "UPDATE cached_categories SET description = ? WHERE id = ? AND tenant_id = ?",
          [data.description, categoryId, tenantId],
        );
      }
      if (data.image_url !== undefined) {
        db.runSync("UPDATE cached_categories SET image_url = ? WHERE id = ? AND tenant_id = ?", [
          data.image_url,
          categoryId,
          tenantId,
        ]);
      }
    }
  } catch {
    // Non-fatal
  }

  enqueueOutboxMutation(tenantId, "UPDATE_CATEGORY", "category", {
    category_id: categoryId,
    ...data,
  });
}

/** Delete a category locally and enqueue for sync. */
export function deleteLocalCategory(tenantId: string, categoryId: string): void {
  try {
    const db = getDb();
    if (db) {
      db.runSync("DELETE FROM cached_categories WHERE id = ? AND tenant_id = ?", [
        categoryId,
        tenantId,
      ]);
    }
  } catch {
    // Non-fatal
  }

  enqueueOutboxMutation(tenantId, "DELETE_CATEGORY", "category", {
    category_id: categoryId,
  });
}

/** Create a product locally first in SQLite and enqueue for sync. */
export function createLocalProduct(
  tenantId: string,
  data: {
    name: string;
    selling_price?: string | null;
    wholesale_price?: string | null;
    category_id?: string | null;
    description?: string | null;
    image_url?: string | null;
  },
): Product {
  const tempId = `prod-local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const slug = data.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  const product: Product = {
    id: tempId,
    tenant_id: tenantId,
    name: data.name,
    slug: slug || "product",
    category_id: data.category_id ?? null,
    description: data.description ?? null,
    selling_price: data.selling_price ?? null,
    effective_normal_price: data.selling_price ?? null,
    effective_wholesale_price: data.wholesale_price ?? null,
    is_active: true,
    is_published: true,
    image_url: data.image_url ?? null,
  };

  try {
    const db = getDb();
    if (db) {
      const now = new Date().toISOString();
      db.runSync(
        `INSERT OR REPLACE INTO cached_products
         (id, tenant_id, name, slug, category_id, selling_price, effective_normal_price, effective_wholesale_price, is_published, is_active, image_url, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [
          product.id,
          tenantId,
          product.name,
          product.slug,
          product.category_id,
          product.selling_price,
          product.effective_normal_price,
          product.effective_wholesale_price,
          1,
          1,
          product.image_url ?? null,
          now,
        ],
      );
    }
  } catch {
    // Non-fatal
  }

  enqueueOutboxMutation(tenantId, "CREATE_PRODUCT", "product", {
    temp_id: tempId,
    name: data.name,
    selling_price: data.selling_price ?? null,
    wholesale_price: data.wholesale_price ?? null,
    category_id: data.category_id ?? null,
    description: data.description ?? null,
  });

  return product;
}

/** Update a product locally and enqueue for sync. */
export function updateLocalProduct(
  tenantId: string,
  productId: string,
  data: Partial<Product>,
): void {
  try {
    const db = getDb();
    if (db) {
      if (data.name) {
        db.runSync("UPDATE cached_products SET name = ? WHERE id = ? AND tenant_id = ?", [
          data.name,
          productId,
          tenantId,
        ]);
      }
      if (data.selling_price !== undefined) {
        db.runSync("UPDATE cached_products SET selling_price = ? WHERE id = ? AND tenant_id = ?", [
          data.selling_price,
          productId,
          tenantId,
        ]);
      }
      if (data.image_url !== undefined) {
        db.runSync("UPDATE cached_products SET image_url = ? WHERE id = ? AND tenant_id = ?", [
          data.image_url,
          productId,
          tenantId,
        ]);
      }
    }
  } catch {
    // Non-fatal
  }

  enqueueOutboxMutation(tenantId, "UPDATE_PRODUCT", "product", {
    product_id: productId,
    ...data,
  });
}

/** Delete a product locally and enqueue for sync. */
export function deleteLocalProduct(tenantId: string, productId: string): void {
  try {
    const db = getDb();
    if (db) {
      db.runSync("DELETE FROM cached_products WHERE id = ? AND tenant_id = ?", [
        productId,
        tenantId,
      ]);
    }
  } catch {
    // Non-fatal
  }

  enqueueOutboxMutation(tenantId, "DELETE_PRODUCT", "product", {
    product_id: productId,
  });
}

/** Flush both sales outbox and catalog mutation outbox. */
export async function flushSyncOutbox(tenantId: string): Promise<{ sales: number; mutations: number }> {
  const salesCount = await flushOutbox(tenantId);
  let mutationsCount = 0;

  try {
    const db = getDb();
    if (!db) return { sales: salesCount, mutations: 0 };

    const pending = db.getAllSync<{
      id: string;
      action: string;
      entity_type: string;
      payload_json: string;
    }>(
      "SELECT id, action, entity_type, payload_json FROM sync_outbox WHERE tenant_id = ? AND status = 'pending' ORDER BY created_at ASC",
      [tenantId],
    );

    for (const item of pending) {
      try {
        const payload = JSON.parse(item.payload_json);

        if (item.action === "CREATE_CATEGORY") {
          const created = await createCategory(tenantId, {
            name: payload.name,
            parent_id: payload.parent_id,
            default_normal_price: payload.default_normal_price,
            default_wholesale_price: payload.default_wholesale_price,
          });
          // Replace temp id in local cache
          db.runSync("UPDATE cached_categories SET id = ? WHERE id = ?", [
            created.id,
            payload.temp_id,
          ]);
        } else if (item.action === "UPDATE_CATEGORY") {
          await updateCategory(tenantId, payload.category_id, {
            name: payload.name,
            default_normal_price: payload.default_normal_price,
            default_wholesale_price: payload.default_wholesale_price,
          });
        } else if (item.action === "DELETE_CATEGORY") {
          await deleteCategory(tenantId, payload.category_id);
        } else if (item.action === "CREATE_PRODUCT") {
          const created = await createProduct(tenantId, {
            name: payload.name,
            selling_price: payload.selling_price,
            wholesale_price: payload.wholesale_price,
            category_id: payload.category_id,
            description: payload.description,
          });
          // Replace temp id in local cache
          db.runSync("UPDATE cached_products SET id = ? WHERE id = ?", [
            created.id,
            payload.temp_id,
          ]);
        } else if (item.action === "UPDATE_PRODUCT") {
          await updateProduct(tenantId, payload.product_id, {
            name: payload.name,
            selling_price: payload.selling_price,
            wholesale_price: payload.wholesale_price,
            category_id: payload.category_id,
          });
        } else if (item.action === "DELETE_PRODUCT") {
          await deleteProduct(tenantId, payload.product_id);
        }

        db.runSync("UPDATE sync_outbox SET status = 'synced' WHERE id = ?", [item.id]);
        mutationsCount++;
      } catch (err: any) {
        if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
          // Unrecoverable client error - mark as failed so it does not block the sync queue forever
          db.runSync("UPDATE sync_outbox SET status = 'failed' WHERE id = ?", [item.id]);
          continue;
        }
        // Stop on first failure (network stall / offline) - remaining mutations stay pending
        break;
      }
    }
  } catch {
    // Non-fatal
  }

  return { sales: salesCount, mutations: mutationsCount };
}


/* ---------------------------------------------------------------------------
 * Hybrid Offline Conflict Resolution Strategy
 * ------------------------------------------------------------------------- */

export interface SyncConflict {
  id: string;
  tenant_id: string;
  entity_type: string;
  entity_id: string;
  entity_title: string;
  local_data: string;
  server_data: string;
  created_at: string;
  status: "unresolved" | "resolved";
  resolution: string | null;
}

/** Record an inventory decrement delta for commutative smart merging. */
export function enqueueInventoryDelta(
  tenantId: string,
  productId: string,
  deltaQuantity: string,
  reason: string = "sale",
): string {
  const id = `delta-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  try {
    const db = getDb();
    if (!db) return id;
    const now = new Date().toISOString();
    db.runSync(
      `INSERT INTO inventory_deltas (id, tenant_id, product_id, delta_quantity, reason, created_at, status)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [id, tenantId, productId, deltaQuantity, reason, now, "pending"],
    );
  } catch {
    // Non-fatal
  }
  return id;
}

/** Last-Write-Wins (LWW) catalog reconciliation. */
export function applyCatalogLWW(tenantId: string, serverProducts: Product[]): Product[] {
  try {
    const db = getDb();
    if (!db) return serverProducts;
    const localProducts = getCachedProducts(tenantId);
    const localMap = new Map(localProducts.map((p) => [p.id, p]));

    const reconciled: Product[] = [];
    for (const sp of serverProducts) {
      const lp = localMap.get(sp.id);
      if (!lp) {
        reconciled.push(sp);
        continue;
      }

      // Check if local device had an un-synced edit
      const revision = db.getFirstSync<{ has_local_edit: number }>(
        "SELECT has_local_edit FROM catalog_revisions WHERE product_id = ?",
        [sp.id],
      );

      if (revision && revision.has_local_edit === 1) {
        // Local edit takes precedence until synced (LWW local)
        reconciled.push(lp);
      } else {
        // Server is canonical
        reconciled.push(sp);
      }
    }

    cacheProducts(tenantId, reconciled);
    return reconciled;
  } catch {
    return serverProducts;
  }
}

/** Record a conflict for human user decision. */
export function recordConflict(conflict: {
  tenantId: string;
  entityType: string;
  entityId: string;
  entityTitle: string;
  localData: unknown;
  serverData: unknown;
}): string {
  const id = `conflict-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  try {
    const db = getDb();
    if (!db) return id;
    const now = new Date().toISOString();
    db.runSync(
      `INSERT INTO sync_conflicts (id, tenant_id, entity_type, entity_id, entity_title, local_data, server_data, created_at, status)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        id,
        conflict.tenantId,
        conflict.entityType,
        conflict.entityId,
        conflict.entityTitle,
        JSON.stringify(conflict.localData),
        JSON.stringify(conflict.serverData),
        now,
        "unresolved",
      ],
    );
  } catch {
    // Non-fatal
  }
  return id;
}

/** Get all pending conflicts that require human trader decision. */
export function getUnresolvedConflicts(tenantId: string): SyncConflict[] {
  try {
    const db = getDb();
    if (!db) return [];
    return db.getAllSync<SyncConflict>(
      "SELECT * FROM sync_conflicts WHERE tenant_id = ? AND status = 'unresolved' ORDER BY created_at DESC",
      [tenantId],
    );
  } catch {
    return [];
  }
}

/** Resolve a conflict based on user's direct choice. */
export function resolveConflict(
  conflictId: string,
  resolution: "keep_local" | "keep_server" | "merged",
): void {
  try {
    const db = getDb();
    if (!db) return;
    db.runSync(
      "UPDATE sync_conflicts SET status = 'resolved', resolution = ? WHERE id = ?",
      [resolution, conflictId],
    );
  } catch {
    // Non-fatal
  }
}


/** Update cached business logo or details locally. */
export function updateCachedBusiness(
  tenantId: string,
  data: { name?: string; logo_url?: string | null },
): void {
  try {
    const db = getDb();
    if (!db) return;
    if (data.name) {
      db.runSync("UPDATE cached_businesses SET name = ? WHERE id = ?", [data.name, tenantId]);
    }
    if (data.logo_url !== undefined) {
      db.runSync("UPDATE cached_businesses SET logo_url = ? WHERE id = ?", [data.logo_url, tenantId]);
    }
  } catch {
    // Non-fatal
  }
}
