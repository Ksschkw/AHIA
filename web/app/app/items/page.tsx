"use client";

/**
 * Everything on the shelf.
 *
 * The fourth destination, and the other one that led to a 404. It shows the whole catalogue with a search box,
 * because the dashboard's shelf is for the dozen things he touches every day and this is for finding the one
 * thing he sold once in March.
 *
 * Like the sales page, it paints what the browser already holds before it asks for anything.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { Card, Empty, Loading, Pill } from "@/components/ui";
import {
  cachedRead,
  currentUser,
  getBusiness,
  listBusinesses,
  listProducts,
  listStock,
  type InventoryLevel,
  type Product,
  type Tenant,
} from "@/lib/api";
import { formatMoneyOrOnRequest, formatQuantity } from "@/lib/format";
import styles from "../dashboard.module.css";

export default function Items() {
  const [products, setProducts] = useState<Product[] | null>(null);
  const [stock, setStock] = useState<InventoryLevel[]>([]);
  const [currency, setCurrency] = useState("NGN");
  const [query, setQuery] = useState("");
  const [state, setState] = useState<"loading" | "ready">("loading");

  const load = useCallback(async (tenantId: string) => {
    const [foundProducts, foundStock] = await Promise.all([
      listProducts(tenantId),
      listStock(tenantId),
    ]);
    setProducts(foundProducts);
    setStock(foundStock);
    setState("ready");
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await currentUser();
        const businesses = await listBusinesses();
        const remembered =
          typeof window === "undefined" ? null : window.localStorage.getItem("ahia.business");
        const chosen = businesses.find((candidate) => candidate.id === remembered) ?? businesses[0];
        if (!chosen) return;
        const detail = await getBusiness(chosen.id);
        setCurrency(detail.currency);
        const rememberedProducts = cachedRead<Product[]>(`/api/v1/tenants/${chosen.id}/products`);
        if (rememberedProducts) {
          setProducts(rememberedProducts);
          setState("ready");
        }
        await load(chosen.id);
      } catch {
        // The frame sends a signed-out visitor to sign in; a failed load leaves what is on screen alone.
      }
    })();
  }, [load]);

  const level = (productId: string) => stock.find((entry) => entry.product_id === productId);
  const shown = useMemo(() => {
    const wanted = query.trim().toLowerCase();
    const all = products ?? [];
    if (wanted.length === 0) return all;
    return all.filter((product) => product.name.toLowerCase().includes(wanted));
  }, [products, query]);

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Items</h1>
      <p className={styles.lede}>Everything on the shelf. {products ? `${products.length} lines` : ""}</p>

      <input
        className={styles.shelfSearch}
        id="items_search"
        value={query}
        placeholder="Search your shelf"
        aria-label="Search your shelf"
        onChange={(event) => setQuery(event.target.value)}
      />

      {state === "loading" ? <Loading label="Fetching your shelf..." /> : null}
      {state === "ready" && (products ?? []).length === 0 ? (
        <Empty>Nothing on the shelf yet. Add the first thing you sell.</Empty>
      ) : null}

      {shown.length > 0 ? (
        <Card title={`${shown.length} of ${products?.length ?? 0}`}>
          <ul className={styles.shelf}>
            {shown.map((product) => {
              const current = level(product.id);
              return (
                <li key={product.id} className={styles.shelfRow}>
                  <span className={styles.shelfMain}>
                    <span className={styles.shelfName}>{product.name}</span>
                    <span className={styles.shelfFacts}>
                      <span className={styles.shelfPrice}>
                        {formatMoneyOrOnRequest(product.effective_normal_price, currency)}
                      </span>
                      <span className={styles.shelfCount}>
                        {formatQuantity(current?.available_quantity ?? "0")} in stock
                      </span>
                    </span>
                  </span>
                  <span className={styles.shelfActions}>
                    <Pill tone={product.is_published ? "good" : "warn"}>
                      {product.is_published ? "In shop" : "Hidden"}
                    </Pill>
                  </span>
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}

      {state === "ready" && (products ?? []).length > 0 && shown.length === 0 ? (
        <Empty>Nothing on your shelf matches that.</Empty>
      ) : null}
    </main>
  );
}
