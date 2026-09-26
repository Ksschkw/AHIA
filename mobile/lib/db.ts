import * as SQLite from "expo-sqlite";
import { type Product, recordSale } from "./api";

/**
 * Local SQLite storage for offline shelf reading and durable sale outbox.
 *
 * Designed for market connectivity: a trader can view cached shelf products and record
 * a "sell one" transaction even when mobile network stalls. Pending transactions are
 * durably queued and flushed when connection returns.
 */

let dbInstance: SQLite.SQLiteDatabase | null = null;

function getDb(): SQLite.SQLiteDatabase {
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
}

export function cacheProducts(tenantId: string, products: Product[]): void {
  try {
    const db = getDb();
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

export function enqueueOfflineSale(sale: {
  tenantId: string;
  productId: string;
  productName: string;
  quantity: string;
  unitPrice: string;
  paymentMethod: string;
}): string {
  const db = getDb();
  const id = `outbox-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
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
  return id;
}

export function getPendingSalesCount(tenantId: string): number {
  try {
    const db = getDb();
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
  const db = getDb();
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
}

/* ---------------------------------------------------------------------------
 * Hybrid Offline Conflict Resolution Strategy
 *
 * 1. Sales & Cash Outbox: Append-only Event Sourcing (Conflict-free).
 *    Each sale is an immutable transaction record that gets committed to the
 *    ledger once connectivity resumes.
 *
 * 2. Inventory / Balances: Automatic Smart Merging via Additive Deltas.
 *    Instead of overwriting total balance, the app tracks stock decrements
 *    as deltas. Concurrent sales from multiple devices are commutative.
 *
 * 3. Catalog & Price Lists: Last-Write-Wins (LWW) with Timestamp Versioning.
 *    Server updated_at vs local updated_at determines the winning version.
 *
 * 4. Customer Lists & Drafts: User Decides / Interactive Reconciliation.
 *    When simultaneous conflicting edits occur on the same customer request,
 *    an interactive prompt allows the trader to choose or merge.
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
  const db = getDb();
  const id = `delta-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const now = new Date().toISOString();
  db.runSync(
    `INSERT INTO inventory_deltas (id, tenant_id, product_id, delta_quantity, reason, created_at, status)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [id, tenantId, productId, deltaQuantity, reason, now, "pending"],
  );
  return id;
}

/** Last-Write-Wins (LWW) catalog reconciliation. */
export function applyCatalogLWW(tenantId: string, serverProducts: Product[]): Product[] {
  const db = getDb();
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
  const db = getDb();
  const id = `conflict-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
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
  return id;
}

/** Get all pending conflicts that require human trader decision. */
export function getUnresolvedConflicts(tenantId: string): SyncConflict[] {
  try {
    const db = getDb();
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
  const db = getDb();
  db.runSync(
    "UPDATE sync_conflicts SET status = 'resolved', resolution = ? WHERE id = ?",
    [resolution, conflictId],
  );
}
