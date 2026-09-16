"use client";

/**
 * The trader console: the product's core loop, in one screen.
 *
 * Sign in, open a business, add a product, stock it, record a sale and watch the stock move. It
 * exists to prove the loop against the real API rather than against fixtures - every number on this
 * page came back from the backend, and an error shows the correlation ID a support ticket should
 * quote.
 */

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  createBusiness,
  createProduct,
  listBusinesses,
  listProducts,
  listStock,
  receiveStock,
  recordSale,
  registerAccount,
  signIn,
  type AuthenticatedSession,
  type InventoryLevel,
  type Product,
  type Tenant,
} from "@/lib/api";
import styles from "./page.module.css";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const STORAGE_KEY = "ahia.session";

type StoredSession = {
  accessToken: string;
  email: string;
  tenantId: string | null;
};

function readStoredSession(): StoredSession | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as StoredSession;
  } catch {
    return null;
  }
}

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.describe()}`;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

export default function Console() {
  const [session, setSession] = useState<StoredSession | null>(null);
  const [businesses, setBusinesses] = useState<Tenant[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [stock, setStock] = useState<InventoryLevel[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [productName, setProductName] = useState("");
  const [productPrice, setProductPrice] = useState("45000.00");
  const [stockQuantity, setStockQuantity] = useState("10.000");
  const [saleQuantity, setSaleQuantity] = useState("1.000");

  const remember = useCallback((next: StoredSession | null) => {
    setSession(next);
    if (typeof window !== "undefined") {
      if (next) {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    }
  }, []);

  useEffect(() => {
    setSession(readStoredSession());
  }, []);

  const run = useCallback(
    async (action: () => Promise<void>) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        await action();
      } catch (caught) {
        setError(describe(caught));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const refreshBusinesses = useCallback(
    async (token: string) => {
      const found = await listBusinesses(token);
      setBusinesses(found);
      return found;
    },
    [],
  );

  const refreshCatalogue = useCallback(async (token: string, tenantId: string) => {
    const [foundProducts, foundStock] = await Promise.all([
      listProducts(token, tenantId),
      listStock(token, tenantId),
    ]);
    setProducts(foundProducts);
    setStock(foundStock);
  }, []);

  useEffect(() => {
    if (!session) {
      return;
    }
    void run(async () => {
      await refreshBusinesses(session.accessToken);
      if (session.tenantId) {
        await refreshCatalogue(session.accessToken, session.tenantId);
      }
    });
  }, [session, refreshBusinesses, refreshCatalogue, run]);

  const onAuthenticated = (result: AuthenticatedSession, mode: "registered" | "signed in") =>
    run(async () => {
      const stored: StoredSession = {
        accessToken: result.access_token,
        email: result.user.email ?? email,
        tenantId: null,
      };
      remember(stored);
      const found = await refreshBusinesses(stored.accessToken);
      setNotice(`Account ${mode}. ${found.length} business(es) on this account.`);
    });

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>AHIA</h1>
        <span className={styles.connection}>
          API {API_BASE_URL}
          {session ? ` | signed in as ${session.email}` : " | not signed in"}
        </span>
      </header>

      {!session ? (
        <section className={styles.panel}>
          <h2 className={styles.panelTitle}>1. Open an account</h2>
          <div className={styles.row}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="email">
                Email
              </label>
              <input
                id="email"
                className={styles.input}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="ada@example.com"
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="password">
                Password
              </label>
              <input
                id="password"
                className={styles.input}
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="at least 8 characters"
              />
            </div>
            <button
              className={styles.button}
              disabled={busy || !email || password.length < 8}
              onClick={() => {
                void run(async () => {
                  const first = email.split("@")[0].replace(/[^a-zA-Z]/g, "") || "Trader";
                  const created = await registerAccount({
                    first_name: first.slice(0, 20),
                    last_name: "Owner",
                    email,
                    password,
                  });
                  const stored: StoredSession = {
                    accessToken: created.access_token,
                    email: created.user.email ?? email,
                    tenantId: null,
                  };
                  remember(stored);
                  const found = await refreshBusinesses(stored.accessToken);
                  setNotice(`Account created. ${found.length} business(es) on this account.`);
                });
              }}
            >
              Create account
            </button>
            <button
              className={styles.buttonQuiet}
              disabled={busy || !email || !password}
              onClick={() => {
                void run(async () => {
                  const opened = await signIn({ identifier: email, password });
                  const stored: StoredSession = {
                    accessToken: opened.access_token,
                    email: opened.user.email ?? email,
                    tenantId: null,
                  };
                  remember(stored);
                  const found = await refreshBusinesses(stored.accessToken);
                  setNotice(`Signed in. ${found.length} business(es) on this account.`);
                });
              }}
            >
              Sign in
            </button>
          </div>
        </section>
      ) : null}

      {session ? (
        <section className={styles.panel}>
          <h2 className={styles.panelTitle}>2. Business</h2>
          <div className={styles.row}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="business">
                New business name
              </label>
              <input
                id="business"
                className={styles.input}
                value={businessName}
                onChange={(event) => setBusinessName(event.target.value)}
                placeholder="Obi Electronics"
              />
            </div>
            <button
              className={styles.button}
              disabled={busy || businessName.trim().length < 2}
              onClick={() => {
                void run(async () => {
                  const created = await createBusiness(session.accessToken, { name: businessName.trim() });
                  remember({ ...session, tenantId: created.id });
                  await refreshBusinesses(session.accessToken);
                  await refreshCatalogue(session.accessToken, created.id);
                  setNotice(`Business "${created.name}" created.`);
                  setBusinessName("");
                });
              }}
            >
              Create business
            </button>
            <button
              className={styles.buttonQuiet}
              disabled={busy}
              onClick={() => {
                void run(async () => {
                  remember(null);
                  setBusinesses([]);
                  setProducts([]);
                  setStock([]);
                });
              }}
            >
              Sign out
            </button>
          </div>

          {businesses.length === 0 ? (
            <p className={styles.empty}>No business on this account yet.</p>
          ) : (
            <div className={styles.choices}>
              {businesses.map((business) => (
                <button
                  key={business.id}
                  className={
                    business.id === session.tenantId ? styles.choiceActive : styles.choice
                  }
                  onClick={() => {
                    void run(async () => {
                      remember({ ...session, tenantId: business.id });
                      await refreshCatalogue(session.accessToken, business.id);
                    });
                  }}
                >
                  {business.name} ({business.slug})
                </button>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {session?.tenantId ? (
        <section className={styles.panel}>
          <h2 className={styles.panelTitle}>3. Product and stock</h2>
          <div className={styles.row}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="product">
                Product
              </label>
              <input
                id="product"
                className={styles.input}
                value={productName}
                onChange={(event) => setProductName(event.target.value)}
                placeholder="Rice 50kg"
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="price">
                Selling price
              </label>
              <input
                id="price"
                className={styles.input}
                value={productPrice}
                onChange={(event) => setProductPrice(event.target.value)}
              />
            </div>
            <button
              className={styles.button}
              disabled={busy || productName.trim().length < 2}
              onClick={() => {
                void run(async () => {
                  const created = await createProduct(session.accessToken, session.tenantId!, {
                    name: productName.trim(),
                    selling_price: productPrice,
                  });
                  await refreshCatalogue(session.accessToken, session.tenantId!);
                  setNotice(`Product "${created.name}" added.`);
                  setProductName("");
                });
              }}
            >
              Add product
            </button>
          </div>

          {products.length === 0 ? (
            <p className={styles.empty}>No product in this business yet.</p>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className={styles.numeric}>Price</th>
                  <th className={styles.numeric}>In stock</th>
                  <th className={styles.numeric}>Received</th>
                  <th className={styles.numeric}>Sold</th>
                </tr>
              </thead>
              <tbody>
                {products.map((product) => {
                  const level = stock.find((entry) => entry.product_id === product.id);
                  return (
                    <tr key={product.id}>
                      <td>{product.name}</td>
                      <td className={styles.numeric}>{product.selling_price}</td>
                      <td className={styles.numeric}>{level?.quantity_on_hand ?? "-"}</td>
                      <td className={styles.numeric}>
                        <button
                          className={styles.choice}
                          disabled={busy}
                          onClick={() => {
                            void run(async () => {
                              await receiveStock(
                                session.accessToken,
                                session.tenantId!,
                                product.id,
                                stockQuantity,
                              );
                              await refreshCatalogue(session.accessToken, session.tenantId!);
                              setNotice(`Stocked ${stockQuantity} of ${product.name}.`);
                            });
                          }}
                        >
                          + {stockQuantity}
                        </button>
                      </td>
                      <td className={styles.numeric}>
                        <button
                          className={styles.choice}
                          disabled={busy}
                          onClick={() => {
                            void run(async () => {
                              const receipt = await recordSale(session.accessToken, session.tenantId!, {
                                discount_amount: "0.00",
                                lines: [
                                  {
                                    product_id: product.id,
                                    quantity: saleQuantity,
                                    discount_amount: "0.00",
                                  },
                                ],
                                payments: [
                                  {
                                    amount: (Number(product.selling_price) * Number(saleQuantity)).toFixed(2),
                                    method: "CASH",
                                  },
                                ],
                              });
                              await refreshCatalogue(session.accessToken, session.tenantId!);
                              setNotice(
                                `Sale ${receipt.sale.receipt_number}: ${receipt.sale.total_amount} ` +
                                  `${receipt.sale.payment_status}`,
                              );
                            });
                          }}
                        >
                          Sell {saleQuantity}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          <div className={styles.row} style={{ marginTop: 14 }}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="stock-qty">
                Quantity to receive
              </label>
              <input
                id="stock-qty"
                className={styles.input}
                value={stockQuantity}
                onChange={(event) => setStockQuantity(event.target.value)}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="sale-qty">
                Quantity per sale
              </label>
              <input
                id="sale-qty"
                className={styles.input}
                value={saleQuantity}
                onChange={(event) => setSaleQuantity(event.target.value)}
              />
            </div>
          </div>
        </section>
      ) : null}

      {error ? <p className={`${styles.message} ${styles.error}`}>{error}</p> : null}
      {notice ? <p className={`${styles.message} ${styles.success}`}>{notice}</p> : null}

      <p className={styles.footnote}>
        Every number on this page came from the API at {API_BASE_URL}. The API documentation is at{" "}
        <a href={`${API_BASE_URL}/docs`}>/docs</a>.
      </p>
    </div>
  );
}
