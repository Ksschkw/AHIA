"use client";

/**
 * The trader's home screen.
 *
 * Today's money at the top, the actions they take all day in the middle, and the shelf at the bottom.
 * Everything on it came from the API: the revenue is the day's report, the stock column is the
 * inventory projection, and the sale sheet writes a real sale.
 *
 * The session is a cookie the page never sees. On load the app asks `/users/me`; if the API answers,
 * somebody is signed in, and if it answers 401 they are not. There is no token in `localStorage` to
 * get out of step with the server, and no header for a call site to forget.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Brand, Wordmark } from "@/components/brand";
import {
  ExpenseIcon,
  ProductIcon,
  SaleIcon,
  StockIcon,
} from "@/components/icons";
import { Button, Card, Empty, Field, Pill, Select, Sheet, Stat, Toast } from "@/components/ui";
import {
  ApiError,
  createBusiness,
  createProduct,
  currentUser,
  dailySales,
  listBusinesses,
  listExpenseCategories,
  listProducts,
  listSales,
  listStock,
  lowStock,
  receiveStock,
  recordExpense,
  recordSale,
  signOut,
  type DailySalesSummary,
  type ExpenseCategory,
  type ExpenseCategoryList,
  type PaymentMethod,
  type InventoryLevel,
  type LowStockProduct,
  type Product,
  type SaleCreate,
  type SaleSummary,
  type Tenant,
  type UserProfile,
} from "@/lib/api";
import { formatCount, formatMoney, formatQuantity } from "@/lib/format";
import styles from "./dashboard.module.css";

type Notice = { message: string; tone: "good" | "bad" };
type SheetName = "sale" | "product" | "stock" | "expense" | "business" | null;

const STORAGE_KEY = "ahia.business";

//: The API's own payment vocabulary. A client that invented "CARD" would be refused by the schema,
//: which is the contract doing its job rather than a limitation to work around.
const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: "CASH", label: "Cash" },
  { value: "BANK_TRANSFER", label: "Transfer" },
  { value: "OTHER", label: "Other" },
];

export default function Dashboard() {
  const router = useRouter();
  const [sessionResolved, setSessionResolved] = useState(false);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [businesses, setBusinesses] = useState<Tenant[]>([]);
  const [businessId, setBusinessId] = useState<string | null>(null);
  //: Whether the list has been read yet. "No business" is a fact about the data, not an event
  //: that can be missed while a screen is mounting - which is exactly how a trader ends up on a
  //: dashboard with no business and no way to name one.
  const [businessesLoaded, setBusinessesLoaded] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [stock, setStock] = useState<InventoryLevel[]>([]);
  const [today, setToday] = useState<DailySalesSummary | null>(null);
  const [recentSales, setRecentSales] = useState<SaleSummary[]>([]);
  const [runningOut, setRunningOut] = useState<LowStockProduct[]>([]);
  const [categories, setCategories] = useState<ExpenseCategoryList | null>(null);

  //: Which action is in flight, if any. A boolean would disable every control on the screen for
  //: the length of any request, which on a slow connection is a frozen interface.
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const busy = busyAction !== null;
  const [notice, setNotice] = useState<Notice | null>(null);
  const [sheet, setSheet] = useState<SheetName>(null);

  const business = useMemo(
    () => businesses.find((candidate) => candidate.id === businessId) ?? null,
    [businesses, businessId],
  );
  //: Derived, not toggled: while there is no business, the sheet that asks for one is open.
  const needsBusiness = Boolean(user) && businessesLoaded && businesses.length === 0 && !businessId;
  const currency = business?.currency ?? "NGN";

  const report = useCallback((error: unknown) => {
    if (error instanceof ApiError) {
      setNotice({ message: `${error.code}: ${error.describe()}`, tone: "bad" });
      return;
    }
    setNotice({
      message: error instanceof Error ? error.message : "Something went wrong.",
      tone: "bad",
    });
  }, []);

  const loadBusiness = useCallback(async (tenantId: string) => {
    const [foundProducts, foundStock, summary, sales, low, expenseCategories] = await Promise.all([
      listProducts(tenantId),
      listStock(tenantId),
      dailySales(tenantId),
      listSales(tenantId, "6"),
      lowStock(tenantId, "5"),
      listExpenseCategories(tenantId),
    ]);
    setProducts(foundProducts);
    setStock(foundStock);
    setToday(summary);
    setRecentSales(sales);
    setRunningOut(low);
    setCategories(expenseCategories);
  }, []);

  const selectBusiness = useCallback(
    async (tenantId: string) => {
      setBusinessId(tenantId);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, tenantId);
      }
      await loadBusiness(tenantId);
    },
    [loadBusiness],
  );

  const refreshBusinessList = useCallback(async () => {
    const found = await listBusinesses();
    setBusinesses(found);
    setBusinessesLoaded(true);
    if (found.length === 0) {
      return found;
    }
    const remembered =
      typeof window === "undefined" ? null : window.localStorage.getItem(STORAGE_KEY);
    const chosen = found.find((candidate) => candidate.id === remembered) ?? found[0];
    await selectBusiness(chosen.id);
    return found;
  }, [selectBusiness]);

  const refresh = useCallback(async () => {
    if (businessId) {
      await loadBusiness(businessId);
    }
  }, [businessId, loadBusiness]);

  // Bootstrap: the cookie decides, and the API is the only thing that can answer.
  // A page that needs a session asks once, and either renders or sends the person to sign in. It
  // never shows a message about checking: a screen whose only content is "wait" is a screen that
  // looks broken whenever the network is slow, and this one resolves in milliseconds when it is not.
  useEffect(() => {
    void (async () => {
      try {
        setUser(await currentUser());
      } catch {
        router.replace("/start");
      } finally {
        setSessionResolved(true);
      }
    })();
  }, [router]);

  // The dashboard loads its own data as soon as there is a session, rather than being a continuation
  // of whatever signed the person in. A screen that loads itself works the same way after a refresh,
  // after a sign-in, and after a session cookie is restored - three paths that would otherwise need
  // three chances to remember to fetch.
  useEffect(() => {
    if (!user || businessesLoaded) {
      return;
    }
    void (async () => {
      try {
        await refreshBusinessList();
      } catch (error) {
        report(error);
      }
    })();
  }, [user, businessesLoaded, refreshBusinessList, report]);

  const run = useCallback(
    async (action: () => Promise<void>, actionKey = "global") => {
      setBusyAction(actionKey);
      try {
        await action();
      } catch (error) {
        report(error);
      } finally {
        setBusyAction(null);
      }
    },
    [report],
  );

  const runProduct = useCallback(
    (action: () => Promise<void>) => run(action, "product"),
    [run],
  );
  const runSale = useCallback((action: () => Promise<void>) => run(action, "sale"), [run]);
  const runStock = useCallback((action: () => Promise<void>) => run(action, "stock"), [run]);
  const runExpense = useCallback((action: () => Promise<void>) => run(action, "expense"), [run]);

  const levelFor = (productId: string) => stock.find((entry) => entry.product_id === productId);

  // No holding screen: a person sees the sign-in card at once, and the dashboard replaces it if the
  // session cookie turns out to be valid. A probe that is slow, or a backend that is unreachable,
  // delays nothing and blocks nothing.
  if (!user) {
    return (
      <main className={styles.page}>
        <header className={styles.topbar}>
          <Brand>
            <span className={styles.brandStack}>
              <Wordmark />
              <span className={styles.brandSub}>
                {sessionResolved ? "Signing you in" : "Loading"}
              </span>
            </span>
          </Brand>
        </header>
        <div className={styles.content}>
          <section className={styles.heroRow}>
            <span className={styles.skeleton} />
            <span className={styles.skeleton} />
            <span className={styles.skeleton} />
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <Brand>
            <span className={styles.brandStack}>
              <Wordmark />
              <span className={styles.brandSub}>
                {business ? business.name : "No business yet"}
              </span>
            </span>
          </Brand>
        </div>
        <div className={styles.account}>
          <select
            className={styles.businessPicker}
            value={businessId ?? ""}
            onChange={(event) => {
              void run(() => selectBusiness(event.target.value));
            }}
          >
            {businesses.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.name}
              </option>
            ))}
          </select>
          <span className={styles.who}>
            {user.first_name} {user.last_name}
          </span>
          <button
            className={styles.linkButton}
            onClick={() => {
              void run(async () => {
                await signOut();
                setUser(null);
                setBusinesses([]);
                setBusinessesLoaded(false);
                setBusinessId(null);
                if (typeof window !== "undefined") {
                  window.localStorage.removeItem(STORAGE_KEY);
                }
                router.replace("/");
              });
            }}
          >
            Sign out
          </button>
        </div>
      </header>

      <div className={styles.content}>
        <section className={styles.heroRow}>
          <Stat
            label="Sold today"
            value={formatMoney(today?.total_revenue ?? "0.00", currency)}
            hint={`${formatCount(today?.total_sales ?? 0)} sales`}
            tone="good"
          />
          <Stat
            label="On the shelves"
            value={formatCount(products.length)}
            hint={`${stock.filter((entry) => entry.is_out_of_stock).length} out of stock`}
          />
          <Stat
            label="Running out"
            value={formatCount(runningOut.length)}
            hint={runningOut.length > 0 ? "Restock today" : "Nothing needs attention"}
            tone={runningOut.length > 0 ? "warn" : "plain"}
          />
        </section>

        <section className={styles.actions}>
          <ActionTile
            label="Record a sale"
            hint="Money in"
            glyph="sale"
            onClick={() => setSheet("sale")}
            disabled={!businessId || products.length === 0}
          />
          <ActionTile
            label="Add a product"
            hint="New line on the shelf"
            glyph="product"
            onClick={() => setSheet("product")}
            disabled={!businessId}
          />
          <ActionTile
            label="Stock in"
            hint="Goods received"
            glyph="stock"
            onClick={() => setSheet("stock")}
            disabled={!businessId || products.length === 0}
          />
          <ActionTile
            label="Record spending"
            hint="Money out"
            glyph="expense"
            onClick={() => setSheet("expense")}
            disabled={!businessId}
          />
        </section>

        <div className={styles.columns}>
          <Card
            title="The shelf"
            action={
              <button className={styles.linkButton} onClick={() => setSheet("product")}>
                Add product
              </button>
            }
          >
            {!businessId ? (
              <Empty>
                Name your business first -{" "}
                <button className={styles.linkButton} onClick={() => setSheet("business")}>
                  choose a name
                </button>
                .
              </Empty>
            ) : products.length === 0 ? (
              <Empty>No products yet. Add the first thing you sell.</Empty>
            ) : (
              <ul className={styles.list}>
                {products.map((product) => {
                  const level = levelFor(product.id);
                  const quantity = Number(level?.available_quantity ?? "0");
                  const out = level?.is_out_of_stock ?? true;
                  return (
                    <li key={product.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span className={styles.rowName}>{product.name}</span>
                        <span className={`${styles.rowMeta} tabular`}>
                          {formatMoney(product.selling_price, currency)}
                        </span>
                      </div>
                      <div className={styles.rowEnd}>
                        {out ? (
                          <Pill tone="bad">Out</Pill>
                        ) : quantity <= 3 ? (
                          <Pill tone="warn">
                            {formatQuantity(level?.available_quantity ?? "0")} left
                          </Pill>
                        ) : (
                          <Pill tone="good">
                            {formatQuantity(level?.available_quantity ?? "0")} in stock
                          </Pill>
                        )}
                        <button
                          className={styles.rowAction}
                          disabled={busy || out}
                          onClick={() => {
                            void run(async () => {
                              if (!businessId) return;
                              const receipt = await recordSale(businessId, {
                                discount_amount: "0.00",
                                lines: [
                                  {
                                    product_id: product.id,
                                    quantity: "1.000",
                                    discount_amount: "0.00",
                                  },
                                ],
                                payments: [{ amount: product.selling_price, method: "CASH" }],
                              });
                              await refresh();
                              setNotice({
                                message: `Sold one ${product.name} - ${receipt.sale.receipt_number} for ${formatMoney(receipt.sale.total_amount, currency)}`,
                                tone: "good",
                              });
                            });
                          }}
                        >
                          Sell one
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          <div className={styles.sideColumn}>
            <Card title="Recent sales">
              {recentSales.length === 0 ? (
                <Empty>Nothing sold yet.</Empty>
              ) : (
                <ul className={styles.list}>
                  {recentSales.map((sale) => (
                    <li key={sale.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span className={styles.rowName}>{sale.receipt_number}</span>
                        <span className={styles.rowMeta}>{sale.payment_status}</span>
                      </div>
                      <span className={`${styles.amount} tabular`}>
                        {formatMoney(sale.total_amount, currency)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Running out">
              {runningOut.length === 0 ? (
                <Empty>Everything is stocked.</Empty>
              ) : (
                <ul className={styles.list}>
                  {runningOut.map((entry) => (
                    <li key={entry.product_id} className={styles.row}>
                      <span className={styles.rowName}>{entry.product_name}</span>
                      <Pill tone={entry.is_out_of_stock ? "bad" : "warn"}>
                        {formatQuantity(entry.quantity_on_hand)} left
                      </Pill>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      </div>

      <SaleSheet
        open={sheet === "sale"}
        busy={busyAction === "sale"}
        products={products}
        stock={stock}
        currency={currency}
        onClose={() => setSheet(null)}
        onSubmit={(input) =>
          runSale(async () => {
            if (!businessId) return;
            const receipt = await recordSale(businessId, input);
            setSheet(null);
            await refresh();
            setNotice({
              message: `${receipt.sale.receipt_number} recorded: ${formatMoney(receipt.sale.total_amount, currency)} ${receipt.sale.payment_status}`,
              tone: "good",
            });
          })
        }
      />

      <ProductSheet
        open={sheet === "product"}
        busy={busyAction === "product"}
        currency={currency}
        onClose={() => setSheet(null)}
        onSubmit={(name, price) =>
          runProduct(async () => {
            if (!businessId) return;
            await createProduct(businessId, { name, selling_price: price });
            setSheet(null);
            await refresh();
            setNotice({ message: `${name} added to the shelf.`, tone: "good" });
          })
        }
      />

      <StockSheet
        open={sheet === "stock"}
        busy={busyAction === "sale"}
        products={products}
        onClose={() => setSheet(null)}
        onSubmit={(productId, quantity) =>
          runStock(async () => {
            if (!businessId) return;
            await receiveStock(businessId, productId, quantity);
            setSheet(null);
            await refresh();
            setNotice({ message: `Stocked ${formatQuantity(quantity)}.`, tone: "good" });
          })
        }
      />

      <ExpenseSheet
        open={sheet === "expense"}
        busy={busyAction === "expense"}
        currency={currency}
        categories={categories}
        onClose={() => setSheet(null)}
        onSubmit={(input) =>
          runExpense(async () => {
            if (!businessId) return;
            await recordExpense(businessId, input);
            setSheet(null);
            setNotice({
              message: `Spending recorded: ${formatMoney(input.amount, currency)}`,
              tone: "good",
            });
          })
        }
      />

      <BusinessSheet
        open={sheet === "business" || needsBusiness}
        busy={busy}
        closable={businesses.length > 0}
        onClose={() => setSheet(null)}
        onSubmit={(name) =>
          run(async () => {
            try {
              const created = await createBusiness({ name });
              setSheet(null);
              const found = await listBusinesses();
              setBusinesses(found);
              await selectBusiness(created.id);
              setNotice({ message: `${created.name} is ready.`, tone: "good" });
            } catch (error) {
              if (error instanceof ApiError && error.code === "CONFLICT") {
                throw new Error("That name is already taken. Try a different one.");
              }
              throw error;
            }
          })
        }
      />

      {notice ? (
        <Toast message={notice.message} tone={notice.tone} onDismiss={() => setNotice(null)} />
      ) : null}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Action tiles
// ---------------------------------------------------------------------------

function ActionTile({
  label,
  hint,
  glyph,
  onClick,
  disabled,
}: {
  label: string;
  hint: string;
  glyph: "sale" | "product" | "stock" | "expense";
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button className={styles.tile} onClick={onClick} disabled={disabled} aria-label={label}>
      <span className={`${styles.tileGlyph} ${styles[`glyph_${glyph}`]}`} aria-hidden>
        {glyph === "sale" ? (
          <SaleIcon />
        ) : glyph === "product" ? (
          <ProductIcon />
        ) : glyph === "stock" ? (
          <StockIcon />
        ) : (
          <ExpenseIcon />
        )}
      </span>
      <span className={styles.tileLabel}>{label}</span>
      <span className={styles.tileHint}>{hint}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Sheets
// ---------------------------------------------------------------------------

function SaleSheet({
  open,
  busy,
  products,
  stock,
  currency,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  products: Product[];
  stock: InventoryLevel[];
  currency: string;
  onClose: () => void;
  onSubmit: (input: SaleCreate) => void;
}) {
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState("1.000");
  const [method, setMethod] = useState<PaymentMethod>("CASH");

  const product = products.find((candidate) => candidate.id === productId) ?? products[0];
  const level = stock.find((entry) => entry.product_id === (product?.id ?? ""));
  const total = (Number(product?.selling_price ?? "0") * Number(quantity || "0")).toFixed(2);

  return (
    <Sheet open={open} title="Record a sale" onClose={onClose}>
      {products.length === 0 ? (
        <Empty>Add a product first.</Empty>
      ) : (
        <>
          <Select
            label="What did you sell?"
            id="sale-product"
            value={product?.id ?? ""}
            options={products.map((candidate) => ({
              value: candidate.id,
              label: `${candidate.name} - ${formatMoney(candidate.selling_price, currency)}`,
            }))}
            onChange={setProductId}
          />
          <div className={styles.inlineFields}>
            <Field
              label="How many?"
              id="sale-quantity"
              value={quantity}
              onChange={setQuantity}
              inputMode="decimal"
            />
            <Select
              label="Paid with"
              id="sale-method"
              value={method}
              options={PAYMENT_METHODS}
              onChange={(value) => setMethod(value as PaymentMethod)}
            />
          </div>
          <div className={styles.totalLine}>
            <span>Total</span>
            <strong className="tabular">{formatMoney(total, currency)}</strong>
          </div>
          {level ? (
            <p className={styles.hint}>
              {formatQuantity(level.available_quantity)} in stock before this sale.
            </p>
          ) : null}
          <Button
            full
            busy={busy}
            disabled={!product || Number(quantity) <= 0}
            onClick={() => {
              if (!product) return;
              onSubmit({
                discount_amount: "0.00",
                lines: [{ product_id: product.id, quantity, discount_amount: "0.00" }],
                payments: [{ amount: total, method }],
              });
            }}
          >
            Record {formatMoney(total, currency)}
          </Button>
        </>
      )}
    </Sheet>
  );
}

function ProductSheet({
  open,
  busy,
  currency,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  currency: string;
  onClose: () => void;
  onSubmit: (name: string, price: string) => void;
}) {
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");

  return (
    <Sheet open={open} title="Add a product" onClose={onClose}>
      <Field
        label="Product name"
        id="new-product"
        value={name}
        onChange={setName}
        placeholder="Rice 50kg"
      />
      <Field
        label={`Selling price (${currency})`}
        id="new-price"
        value={price}
        onChange={setPrice}
        inputMode="decimal"
        placeholder="45000.00"
      />
      <Button
        full
        busy={busy}
        disabled={name.trim().length < 2 || Number(price) <= 0}
        onClick={() => onSubmit(name.trim(), Number(price).toFixed(2))}
      >
        Add to the shelf
      </Button>
    </Sheet>
  );
}

function StockSheet({
  open,
  busy,
  products,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  products: Product[];
  onClose: () => void;
  onSubmit: (productId: string, quantity: string) => void;
}) {
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState("10.000");
  const product = products.find((candidate) => candidate.id === productId) ?? products[0];

  return (
    <Sheet open={open} title="Stock in" onClose={onClose}>
      <Select
        label="What arrived?"
        id="stock-product"
        value={product?.id ?? ""}
        options={products.map((candidate) => ({ value: candidate.id, label: candidate.name }))}
        onChange={setProductId}
      />
      <Field
        label="How many?"
        id="stock-quantity"
        value={quantity}
        onChange={setQuantity}
        inputMode="decimal"
      />
      <Button
        full
        busy={busy}
        disabled={!product || Number(quantity) <= 0}
        onClick={() => product && onSubmit(product.id, quantity)}
      >
        Add to stock
      </Button>
    </Sheet>
  );
}

function ExpenseSheet({
  open,
  busy,
  currency,
  categories,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  currency: string;
  categories: ExpenseCategoryList | null;
  onClose: () => void;
  onSubmit: (input: {
    category: ExpenseCategory["value"];
    amount: string;
    payment_method: PaymentMethod;
    description?: string;
  }) => void;
}) {
  const options: ExpenseCategory[] = categories?.categories ?? [];
  const [category, setCategory] = useState<ExpenseCategory["value"] | null>(null);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("CASH");
  const chosen = category ?? options[0]?.value ?? null;

  return (
    <Sheet open={open} title="Record spending" onClose={onClose}>
      <Select
        label="What did you spend on?"
        id="expense-category"
        value={chosen ?? ""}
        options={options.map((option) => ({ value: option.value, label: option.label }))}
        onChange={(value) => setCategory(value as ExpenseCategory["value"])}
      />
      <Field
        label={`How much? (${currency})`}
        id="expense-amount"
        value={amount}
        onChange={setAmount}
        inputMode="decimal"
        placeholder="15000.00"
      />
      <Select
        label="Paid with"
        id="expense-method"
        value={method}
        options={PAYMENT_METHODS}
        onChange={(value) => setMethod(value as PaymentMethod)}
      />
      <Field
        label="Note (optional)"
        id="expense-description"
        value={description}
        onChange={setDescription}
        placeholder="Generator fuel"
      />
      <Button
        full
        busy={busy}
        disabled={!chosen || Number(amount) <= 0}
        onClick={() =>
          onSubmit({
            category: chosen,
            amount: Number(amount).toFixed(2),
            payment_method: method,
            description: description.trim() || undefined,
          })
        }
      >
        Record spending
      </Button>
    </Sheet>
  );
}

function BusinessSheet({
  open,
  busy,
  closable,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  closable: boolean;
  onClose: () => void;
  onSubmit: (name: string) => void;
}) {
  const [name, setName] = useState("");

  return (
    <Sheet open={open} title="Name your business" onClose={closable ? onClose : () => {}}>
      <p className={styles.hint}>
        This is the name your customers see. You can add more businesses later.
      </p>
      <Field
        label="Business name"
        id="business-name"
        value={name}
        onChange={setName}
        placeholder="Obi Electronics"
      />
      <Button
        full
        busy={busy}
        disabled={name.trim().length < 2}
        onClick={() => onSubmit(name.trim())}
      >
        Create business
      </Button>
    </Sheet>
  );
}
