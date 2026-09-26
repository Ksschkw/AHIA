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
           (id, tenant_id, name, slug, category_id, selling_price, effective_normal_price, is_published, is_active, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            p.id,
            tenantId,
            p.name,
            p.slug,
            p.category_id,
            p.selling_price,
            p.effective_normal_price,
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
      effective_wholesale_price: null,
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
