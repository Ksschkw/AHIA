import * as SQLite from "expo-sqlite";
import {
  type Product,
  type Category,
  type CustomerList,
  type BusinessMembership,
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

function getDb(): SQLite.SQLiteDatabase | null {
  try {
    if (!dbInstance) {
      dbInstance = SQLite.openDatabaseSync("ahia_local.db");
      dbInstance.execSync(`
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
          updated_at TEXT NOT NULL
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
    }
    return dbInstance;
  } catch {
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
      DELETE FROM catalog_revisions;
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
          `INSERT OR REPLACE INTO cached_categories (id, tenant_id, name, slug, parent_id, position, image_url, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
          [c.id, tenantId, c.name, c.slug, c.parent_id ?? null, c.position ?? 0, c.image_url ?? null, now],
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
      image_url?: string | null;
    }>(
      "SELECT id, tenant_id, name, slug, parent_id, position, image_url FROM cached_categories WHERE tenant_id = ? ORDER BY position ASC, name ASC",
      [tenantId],
    );
    return rows.map((r) => ({
      id: r.id,
      tenant_id: r.tenant_id,
      name: r.name,
      slug: r.slug,
      parent_id: r.parent_id,
      position: r.position,
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
    db.withTransactionSync(() => {
      for (const l of lists) {
        db.runSync(
          `INSERT OR REPLACE INTO cached_customer_lists (id, tenant_id, customer_name, customer_phone, status, priced_total, data_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            l.id,
            tenantId,
            l.customer_name ?? null,
            l.customer_phone ?? null,
            l.status,
            l.priced_total ?? null,
            JSON.stringify(l),
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

export function cacheBusinesses(businesses: BusinessMembership[]): void {
  try {
    const db = getDb();
    if (!db) return;
    const now = new Date().toISOString();
    db.withTransactionSync(() => {
      for (const b of businesses) {
        db.runSync(
          `INSERT OR REPLACE INTO cached_businesses (id, name, slug, currency, role_name, is_active, logo_url, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
          [b.id, b.name, b.slug, b.currency || "NGN", b.role_name || "OWNER", b.is_active ? 1 : 0, b.logo_url ?? null, now],
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
      currency: string;
      role_name: string;
      is_active: number;
      logo_url?: string | null;
    }>("SELECT id, name, slug, currency, role_name, is_active, logo_url FROM cached_businesses WHERE is_active = 1 ORDER BY name ASC");
    return rows.map((r) => ({
      id: r.id,
      name: r.name,
      slug: r.slug,
      currency: r.currency,
      role_name: r.role_name,
      is_active: Boolean(r.is_active),
      logo_url: r.logo_url ?? null,
    }));
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
      } catch {
        // Stays pending if network fails
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
    default_normal_price: data.default_normal_price ?? null,
    default_wholesale_price: data.default_wholesale_price ?? null,
    image_url: data.image_url ?? null,
  };

  try {
    const db = getDb();
    if (db) {
      const now = new Date().toISOString();
      db.runSync(
        `INSERT OR REPLACE INTO cached_categories (id, tenant_id, name, slug, parent_id, position, image_url, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        [category.id, tenantId, category.name, category.slug, category.parent_id, 0, category.image_url ?? null, now],
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
      } catch {
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
