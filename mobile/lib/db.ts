import * as SQLite from "expo-sqlite";
import { type Product, type Category, type CustomerList, recordSale } from "./api";

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
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cached_categories (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          name TEXT NOT NULL,
          slug TEXT NOT NULL,
          parent_id TEXT,
          position INTEGER NOT NULL DEFAULT 0,
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
           (id, tenant_id, name, slug, category_id, selling_price, effective_normal_price, effective_wholesale_price, is_published, is_active, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
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
          `INSERT OR REPLACE INTO cached_categories (id, tenant_id, name, slug, parent_id, position, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)`,
          [c.id, tenantId, c.name, c.slug, c.parent_id ?? null, c.position ?? 0, now],
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
    }>(
      "SELECT id, tenant_id, name, slug, parent_id, position FROM cached_categories WHERE tenant_id = ? ORDER BY position ASC, name ASC",
      [tenantId],
    );
    return rows.map((r) => ({
      id: r.id,
      tenant_id: r.tenant_id,
      name: r.name,
      slug: r.slug,
      parent_id: r.parent_id,
      position: r.position,
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
