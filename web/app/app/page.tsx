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

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Brand, Wordmark } from "@/components/brand";
import {
  ExpenseIcon,
  ProductIcon,
  SaleIcon,
  StockIcon,
} from "@/components/icons";
import { EmptySalesIllustration, EmptyShelfIllustration } from "@/components/illustrations";
import {
  Button,
  Card,
  Empty,
  Field,
  Loading,
  Pill,
  Select,
  Sheet,
  Stat,
  Toast,
} from "@/components/ui";
import {
  ApiError,
  createBusiness,
  getBusiness,
  getStorefront,
  listCategories,
  productShareSheet,
  publishProduct,
  publishStorefront,
  unpublishProduct,
  unpublishStorefront,
  updateStorefront,
  createProduct,
  currentUser,
  dailySales,
  firstPaint,
  listBusinesses,
  listExpenseCategories,
  listProductImages,
  cachedRead,
  rememberedBusinessId,
  listProducts,
  listSales,
  listStock,
  lowStock,
  makeProductImagePrimary,
  receiveStock,
  recordExpense,
  recordSale,
  removeProductImage,
  uploadProductImage,
  signOut,
  type DailySalesSummary,
  type ExpenseCategory,
  type Category,
  type ExpenseCategoryList,
  type PaymentMethod,
  type InventoryLevel,
  type LowStockProduct,
  type Product,
  type ProductImage,
  type SaleCreate,
  type Storefront,
  type SaleSummary,
  type Tenant,
  type TenantSummary,
  type UserProfile,
} from "@/lib/api";
import { formatCount, formatMoney, formatMoneyOrOnRequest, formatQuantity } from "@/lib/format";
import styles from "./dashboard.module.css";

type Notice = { message: string; tone: "good" | "bad" };
type SheetName = "sale" | "product" | "stock" | "expense" | "business" | "shop" | null;

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
  const [businesses, setBusinesses] = useState<TenantSummary[]>([]);
  const [businessDetail, setBusinessDetail] = useState<Tenant | null>(null);
  const [businessId, setBusinessId] = useState<string | null>(() => rememberedBusinessId());
  //: Whether the list has been read yet. "No business" is a fact about the data, not an event
  //: that can be missed while a screen is mounting - which is exactly how a trader ends up on a
  //: dashboard with no business and no way to name one.
  const [businessesLoaded, setBusinessesLoaded] = useState(false);
  const [products, setProducts] = useState<Product[]>(() =>
    firstPaint<Product[]>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}/products`) ?? [],
  );
  //: "loading" until the first answer arrives, so an empty shelf is never asserted before it is known.
  const [shelfState, setShelfState] = useState<"loading" | "ready">(() =>
    rememberedBusinessId() && cachedRead(`/api/v1/tenants/${rememberedBusinessId()}/products`)
      ? "ready"
      : "loading",
  );
  const [stock, setStock] = useState<InventoryLevel[]>([]);
  const [today, setToday] = useState<DailySalesSummary | null>(null);
  const [recentSales, setRecentSales] = useState<SaleSummary[]>([]);
  const [runningOut, setRunningOut] = useState<LowStockProduct[]>([]);
  const [categories, setCategories] = useState<ExpenseCategoryList | null>(null);
  // The product groups, which are a different thing from the spending categories above: these are how
  // the shelf is arranged - Screenguard, 21D - and what a list is read under.
  const [productGroups, setProductGroups] = useState<Category[]>([]);
  //: Photos per product, loaded after the shelf and never blocking it. An empty map means "not read
  //: yet", which is why the shelf shows a placeholder rather than nothing while it fills in.
  const [photos, setPhotos] = useState<Record<string, ProductImage[]>>({});
  //: Null until the first photo request answers. False hides every photo affordance, because a
  //: business whose deployment has media switched off should not be shown buttons that cannot work.
  const [photosAvailable, setPhotosAvailable] = useState<boolean | null>(null);
  const [photoProduct, setPhotoProduct] = useState<Product | null>(null);
  const [storefront, setStorefront] = useState<Storefront | null>(null);

  //: Which action is in flight, if any. A boolean would disable every control on the screen for
  //: the length of any request, which on a slow connection is a frozen interface.
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const busy = busyAction !== null;
  const [notice, setNotice] = useState<Notice | null>(null);
  const [sheet, setSheet] = useState<SheetName>(null);

  const business = businessDetail;
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
    // **Everything already known is painted first, before a single request is made.** This is the
    // difference the trader was describing: before, a refresh showed an empty shelf while the same
    // data sat in local storage, and the screen looked like it had forgotten his shop. What follows
    // replaces it if anything changed, silently - no spinner, because there is something to show.
    const rememberedProducts = cachedRead<Product[]>(
      `/api/v1/tenants/${tenantId}/products`,
    );
    const rememberedStock = cachedRead<InventoryLevel[]>(`/api/v1/tenants/${tenantId}/inventory`);
    if (rememberedProducts) {
      setProducts(rememberedProducts);
      setShelfState("ready");
    }
    if (rememberedStock) {
      setStock(rememberedStock);
    }

    const [foundProducts, foundStock, summary, sales, low, expenseCategories] = await Promise.all([
      listProducts(tenantId),
      listStock(tenantId),
      dailySales(tenantId),
      listSales(tenantId, "6"),
      lowStock(tenantId, "5"),
      listExpenseCategories(tenantId),
    ]);
    setProducts(foundProducts);
    // Ready only now: everything above this line is a request in flight, and a shelf that says it is
    // empty while one is in flight is telling the trader something it does not know.
    setShelfState("ready");
    setStock(foundStock);
    void loadPhotos(
      tenantId,
      foundProducts.map((product) => product.id),
    );
    setToday(summary);
    setRecentSales(sales);
    setRunningOut(low);
    setCategories(expenseCategories);
  }, []);

  /**
   * Read every product's photos, after the shelf has rendered.
   *
   * Deliberately not part of the page's critical path: a shop with forty products would otherwise wait
   * for forty round trips before showing anything. The shelf draws immediately and the pictures arrive.
   */
  const loadPhotos = useCallback(async (tenantId: string, productIds: string[]) => {
    if (productIds.length === 0) {
      setPhotos({});
      return;
    }
    try {
      const entries = await Promise.all(
        productIds.map(async (productId) => {
          const images = await listProductImages(tenantId, productId);
          return [productId, images] as const;
        }),
      );
      setPhotos(Object.fromEntries(entries));
      setPhotosAvailable(true);
    } catch (error) {
      // A 404 here means the deployment has media switched off, which is a configuration fact and not
      // a failure to report to a trader: the buttons simply do not appear.
      setPhotosAvailable(!(error instanceof ApiError && error.status === 404));
    }
  }, []);

  const refreshPhotos = useCallback(
    async (productId: string) => {
      if (!businessId) return;
      const images = await listProductImages(businessId, productId);
      setPhotos((current) => ({ ...current, [productId]: images }));
    },
    [businessId],
  );

  const selectBusiness = useCallback(
    async (tenantId: string) => {
      setBusinessId(tenantId);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, tenantId);
      }
      const rememberedProducts = cachedRead<Product[]>(`/api/v1/tenants/${tenantId}/products`);
      if (rememberedProducts) {
        setProducts(rememberedProducts);
        setShelfState("ready");
      } else {
        setProducts([]);
        setShelfState("loading");
      }
      setStock([]);
      setToday(null);
      setRecentSales([]);
      setRunningOut([]);
      setPhotos({});
      setStorefront(null);
      // The detail first: it carries the currency, so every amount on the page is rendered in the
      // business's own money rather than in a default that happens to be right for most shops.
      setBusinessDetail(await getBusiness(tenantId));
      setStorefront(await getStorefront(tenantId));
      // A failure here leaves the form without a group picker rather than blocking the shelf: a trader
      // who cannot pick a group can still add the thing and group it later.
      setProductGroups(await listCategories(tenantId).catch(() => []));
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
  const runPhoto = useCallback((action: () => Promise<void>) => run(action, "photo"), [run]);
  const runShop = useCallback((action: () => Promise<void>) => run(action, "shop"), [run]);
  const runBusiness = useCallback(
    (action: () => Promise<void>) => run(action, "business"),
    [run],
  );

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
      {/* The shell owns the frame now: the brand, the business switcher and the way to the profile
          all live there, so this page carries only what is particular to it - and the one action the
          frame cannot offer, which is starting another business. */}
      <div className={styles.pageActions}>
        <button
          className={styles.addBusiness}
          aria-label="Add another business"
          title="Add another business"
          onClick={() => setSheet("business")}
        >
          + New business
        </button>
      </div>

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
            ) : shelfState === "loading" ? (
              // "No products yet" before the answer arrives is a lie, and the trader caught it: he
              // added something, and the screen had already told him it was not there. An empty list
              // and a list nobody has fetched are different states and have to read differently.
              <Loading label="Fetching your shelf..." />
            ) : products.length === 0 ? (
              <Empty
                illustration={<EmptyShelfIllustration size={100} />}
                action={
                  <button className={styles.linkButton} onClick={() => setSheet("product")}>
                    + Add First Product
                  </button>
                }
              >
                No products yet. Add the first thing you sell.
              </Empty>
            ) : (
              <ul className={styles.shelf}>
                {products.map((product) => {
                  const level = levelFor(product.id);
                  const quantity = Number(level?.available_quantity ?? "0");
                  const out = level?.is_out_of_stock ?? true;
                  const cover = coverPhoto(photos[product.id]);
                  return (
                    <li key={product.id} className={styles.shelfRow}>
                      {/* The photograph is the anchor of the row: a trader recognises his stock by
                          sight long before he reads a name, and a shelf of photographs is a shelf
                          somebody can scan while a customer waits. */}
                      {photosAvailable !== false ? (
                        <button
                          className={styles.shelfThumb}
                          onClick={() => setPhotoProduct(product)}
                          aria-label={
                            cover ? `Photos of ${product.name}` : `Add a photo of ${product.name}`
                          }
                        >
                          {cover?.delivery_url ? (
                            /* eslint-disable-next-line @next/next/no-img-element */
                            <img src={cover.delivery_url} alt="" className={styles.shelfThumbImage} />
                          ) : (
                            <span className={styles.shelfThumbEmpty}>+</span>
                          )}
                        </button>
                      ) : null}

                      <span className={styles.shelfMain}>
                        <span className={styles.shelfName}>{product.name}</span>
                        <span className={styles.shelfFacts}>
                          <span className={`${styles.shelfPrice} tabular`}>
                            {formatMoneyOrOnRequest(product.selling_price, currency)}
                          </span>
                          {out ? (
                            <span className={styles.shelfOut}>Out</span>
                          ) : (
                            <span className={quantity <= 3 ? styles.shelfLow : styles.shelfCount}>
                              {formatQuantity(level?.available_quantity ?? "0")} left
                            </span>
                          )}
                          <span className={product.is_published ? styles.shelfLive : styles.shelfHidden}>
                            {product.is_published ? "In shop" : "Hidden"}
                          </span>
                        </span>
                      </span>

                      <span className={styles.shelfActions}>
                        <button
                          className={styles.shelfSell}
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
                                payments: [
                                  {
                                    amount: product.effective_normal_price ?? "0.00",
                                    method: "CASH",
                                  },
                                ],
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
                        <button
                          className={styles.shelfToggle}
                          disabled={busy}
                          aria-pressed={product.is_published}
                          title={
                            product.is_published
                              ? "Hide this from the public shop"
                              : "Show this in the public shop"
                          }
                          onClick={() => {
                            void runShop(async () => {
                              if (!businessId) return;
                              // **The switch moves first, the request follows.** Hiding something is a
                              // decision the trader has already made, with a customer possibly standing
                              // in front of him; waiting for a round trip to another continent to see his
                              // own decision is what makes a product feel broken. If it fails, the change
                              // comes back and the notice says so.
                              const wasPublished = product.is_published;
                              setProducts((current) =>
                                current.map((candidate) =>
                                  candidate.id === product.id
                                    ? { ...candidate, is_published: !wasPublished }
                                    : candidate,
                                ),
                              );
                              try {
                                if (wasPublished) {
                                  await unpublishProduct(businessId, product.id);
                                } else {
                                  await publishProduct(businessId, product.id);
                                }
                              } catch (error) {
                                setProducts((current) =>
                                  current.map((candidate) =>
                                    candidate.id === product.id
                                      ? { ...candidate, is_published: wasPublished }
                                      : candidate,
                                  ),
                                );
                                throw error;
                              }
                              await refresh();
                              setNotice({
                                message: product.is_published
                                  ? `${product.name} is hidden from the shop.`
                                  : `${product.name} is now in your shop.`,
                                tone: "good",
                              });
                            });
                          }}
                        >
                          {product.is_published ? "Hide" : "Show"}
                        </button>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          <div className={styles.sideColumn}>
            <Card title="Recent sales">
              {recentSales.length === 0 ? (
                <Empty
                  illustration={<EmptySalesIllustration size={90} />}
                  action={
                    <button className={styles.linkButton} onClick={() => setSheet("sale")}>
                      + Record Sale
                    </button>
                  }
                >
                  Nothing sold yet today.
                </Empty>
              ) : (
                <ul className={styles.list}>
                  {recentSales.map((sale) => (
                    <li key={sale.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span
                          className={styles.rowName}
                          style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}
                        >
                          <SaleIcon size={15} style={{ color: "var(--leaf)", flexShrink: 0 }} />
                          <span>{sale.receipt_number}</span>
                        </span>
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

            <Card
              title="Your shop online"
              action={
                storefront?.is_published ? (
                  <button className={styles.linkButton} onClick={() => setSheet("shop")}>
                    Edit
                  </button>
                ) : null
              }
            >
              {storefront?.is_published ? (
                <>
                  <p className={styles.hint}>
                    Anyone with this link can see your shelf and what it costs.
                  </p>
                  <p className={styles.shopLink}>{publicShopUrl(business?.slug ?? "")}</p>
                  <div className={styles.shopActions}>
                    <button
                      className={styles.rowAction}
                      onClick={() => {
                        void runShop(async () => {
                          await copyToClipboard(publicShopUrl(business?.slug ?? ""));
                          setNotice({ message: "Shop link copied.", tone: "good" });
                        });
                      }}
                    >
                      Copy link
                    </button>
                    <a
                      className={styles.rowAction}
                      href={whatsAppShareUrl(
                        `Come and see what we have: ${publicShopUrl(business?.slug ?? "")}`,
                      )}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      Share on WhatsApp
                    </a>
                    <button
                      className={styles.linkButton}
                      onClick={() =>
                        runShop(async () => {
                          if (!businessId) return;
                          setStorefront(await unpublishStorefront(businessId));
                          setNotice({ message: "Your shop is closed. The link is kept.", tone: "good" });
                        })
                      }
                    >
                      Close it for now
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <p className={styles.hint}>
                    A page with your products, photos and prices that you can send to a customer.
                    They open it, see what you have, and message you on WhatsApp.
                  </p>
                  <Button
                    busy={busyAction === "shop"}
                    onClick={() =>
                      runShop(async () => {
                        if (!businessId) return;
                        setStorefront(await publishStorefront(businessId, {}));
                        setNotice({ message: "Your shop is open.", tone: "good" });
                      })
                    }
                  >
                    Open my shop
                  </Button>
                </>
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
        categories={productGroups}
        onSubmit={(name, price, groupId) =>
          runProduct(async () => {
            if (!businessId) return;
            await createProduct(businessId, {
              name,
              selling_price: price,
              category_id: groupId,
            });
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

      <PhotoSheet
        product={photoProduct}
        images={photoProduct ? (photos[photoProduct.id] ?? []) : []}
        busy={busyAction === "photo"}
        onClose={() => setPhotoProduct(null)}
        onUpload={(file) =>
          runPhoto(async () => {
            if (!businessId || !photoProduct) return;
            const isFirst = (photos[photoProduct.id] ?? []).length === 0;
            await uploadProductImage(businessId, photoProduct.id, file, isFirst);
            await refreshPhotos(photoProduct.id);
            setNotice({ message: `${photoProduct.name}: photo added.`, tone: "good" });
          })
        }
        onMakeCover={(imageId) =>
          runPhoto(async () => {
            if (!businessId || !photoProduct) return;
            await makeProductImagePrimary(businessId, photoProduct.id, imageId);
            await refreshPhotos(photoProduct.id);
            setNotice({ message: "That is now the cover photo.", tone: "good" });
          })
        }
        onRemove={(imageId) =>
          runPhoto(async () => {
            if (!businessId || !photoProduct) return;
            const outcome = await removeProductImage(businessId, photoProduct.id, imageId);
            await refreshPhotos(photoProduct.id);
            setNotice({
              message: outcome.storage_released
                ? "Photo removed."
                : "Photo removed from the product; the file is still being cleared from storage.",
              tone: "good",
            });
          })
        }
      />

      <ShopSheet
        open={sheet === "shop"}
        busy={busyAction === "shop"}
        storefront={storefront}
        slug={business?.slug ?? ""}
        onClose={() => setSheet(null)}
        onSubmit={(details) =>
          runShop(async () => {
            if (!businessId) return;
            setStorefront(await updateStorefront(businessId, details));
            setSheet(null);
            setNotice({ message: "Your shop page is updated.", tone: "good" });
          })
        }
      />

      <BusinessSheet
        open={sheet === "business" || needsBusiness}
        busy={busyAction === "business"}
        firstOne={businesses.length === 0}
        closable={businesses.length > 0}
        onClose={() => setSheet(null)}
        onSubmit={(name) =>
          runBusiness(async () => {
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
              label: `${candidate.name} - ${formatMoneyOrOnRequest(candidate.selling_price, currency)}`,
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

/**
 * Every group, with how deep it sits, so a select can show a heading and what hangs under it.
 *
 * Depth is worked out by walking up to the root, with a bound on how far it will go: a catalogue is not
 * nested thirty levels deep, and a tree damaged elsewhere should not hang the form that adds a product.
 */
function orderGroups(categories: Category[]): { category: Category; depth: number }[] {
  const byId = new Map(categories.map((category) => [category.id, category]));
  const depthOf = (category: Category): number => {
    let depth = 0;
    let parentId = category.parent_id ?? null;
    while (parentId !== null && depth < 16) {
      const parent = byId.get(parentId);
      if (!parent) break;
      depth += 1;
      parentId = parent.parent_id ?? null;
    }
    return depth;
  };
  return categories
    .map((category) => ({ category, depth: depthOf(category) }))
    .sort((left, right) =>
      left.depth === right.depth
        ? left.category.name.localeCompare(right.category.name)
        : left.depth - right.depth,
    );
}

function ProductSheet({
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
  categories: Category[];
  onClose: () => void;
  onSubmit: (name: string, price: string, groupId: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [groupId, setGroupId] = useState("");

  // The groups, in the order a person reads them: a heading, then what hangs under it, indented. A flat
  // run of names would make "21D" and "Screenguard" look like siblings when one is inside the other.
  const ordered = orderGroups(categories);

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
      {categories.length > 0 ? (
        <label className={styles.selectField}>
          <span className={styles.selectLabel}>Which group?</span>
          <select
            className={styles.select}
            id="new-product-group"
            value={groupId}
            onChange={(event) => setGroupId(event.target.value)}
          >
            <option value="">No group</option>
            {ordered.map((entry) => (
              <option key={entry.category.id} value={entry.category.id}>
                {`${"\u00a0\u00a0".repeat(entry.depth)}${entry.category.name}`}
              </option>
            ))}
          </select>
          <span className={styles.selectHint}>
            A group carries a price for everything under it, so a model that is the same as the rest does
            not need its own.
          </span>
        </label>
      ) : null}
      <Button
        full
        busy={busy}
        disabled={name.trim().length < 2 || Number(price) <= 0}
        onClick={() => onSubmit(name.trim(), Number(price).toFixed(2), groupId || null)}
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

/** Where a customer opens this business's shop. Built from the browser's own address. */
function publicShopUrl(slug: string): string {
  if (!slug) {
    return "";
  }
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return `${origin}/shop/${slug}`;
}

function whatsAppShareUrl(message: string): string {
  return `https://wa.me/?text=${encodeURIComponent(message)}`;
}

/** An empty text box means "clear it", which the API expresses as null rather than "". */
function clearedOrText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

async function copyToClipboard(value: string): Promise<void> {
  if (!value) {
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    // A browser that refuses the clipboard (an insecure origin, or a refused permission) still has
    // the link on screen, which is enough to copy by hand.
  }
}

/**
 * What the shop says about itself.
 *
 * The address is not editable: it is on links that customers already have, so a business that wants a
 * different one is a different decision from a profile edit.
 */
function ShopSheet({
  open,
  busy,
  storefront,
  slug,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  storefront: Storefront | null;
  slug: string;
  onClose: () => void;
  onSubmit: (details: {
    headline: string | null;
    description: string | null;
    contact_phone: string | null;
  }) => void;
}) {
  const [headline, setHeadline] = useState(storefront?.headline ?? "");
  const [description, setDescription] = useState(storefront?.description ?? "");
  const [contactPhone, setContactPhone] = useState(storefront?.contact_phone ?? "");

  // Redrawn from what the shop says now, so reopening it never shows a stale edit.
  useEffect(() => {
    if (open) {
      setHeadline(storefront?.headline ?? "");
      setDescription(storefront?.description ?? "");
      setContactPhone(storefront?.contact_phone ?? "");
    }
  }, [open, storefront]);

  return (
    <Sheet open={open} title="Your shop page" onClose={onClose}>
      <p className={styles.hint}>
        Your address is <strong>{publicShopUrl(slug)}</strong>. It stays the same.
      </p>
      <Field
        label="One line about the business"
        id="shop_headline"
        value={headline}
        onChange={setHeadline}
        placeholder="Electronics and home appliances in Alaba"
      />
      <Field
        label="What you want customers to know"
        id="shop_description"
        value={description}
        onChange={setDescription}
        placeholder="We sell and install. Delivery within Lagos on the same day."
      />
      <Field
        label="Number customers should message"
        id="shop_phone"
        value={contactPhone}
        onChange={setContactPhone}
        inputMode="tel"
        hint="This is the number the WhatsApp button opens."
      />
      <Button
        full
        busy={busy}
        onClick={() =>
          onSubmit({
            headline: clearedOrText(headline),
            description: clearedOrText(description),
            contact_phone: clearedOrText(contactPhone),
          })
        }
      >
        Save the shop page
      </Button>
    </Sheet>
  );
}

/** The picture that stands for a product: the chosen cover, or the first one there is. */
function coverPhoto(images: ProductImage[] | undefined): ProductImage | undefined {
  if (!images || images.length === 0) {
    return undefined;
  }
  return images.find((image) => image.is_primary) ?? images[0];
}

/**
 * One product's photos.
 *
 * A phone is a camera and a trader's catalogue is their shop window, so this is where the storefront
 * gets its pictures. Upload takes the file straight from the picker - `capture` asks a phone for the
 * camera - and nothing is cropped or reordered on the client: the server decodes, resizes, strips
 * metadata and stores it, so there is one implementation of that and it is not in two places.
 */
function PhotoSheet({
  product,
  images,
  busy,
  onClose,
  onUpload,
  onMakeCover,
  onRemove,
}: {
  product: Product | null;
  images: ProductImage[];
  busy: boolean;
  onClose: () => void;
  onUpload: (file: File) => void;
  onMakeCover: (imageId: string) => void;
  onRemove: (imageId: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);

  return (
    <Sheet open={product !== null} title={product ? `Photos of ${product.name}` : "Photos"} onClose={onClose}>
      <input
        ref={input}
        type="file"
        // Anything the device has. The browser converts it below, so the trader is never asked to
        // know what a WebP is, and an iPhone photograph can simply be chosen.
        accept="image/*"
        className={styles.fileInput}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) {
            onUpload(file);
          }
          // Cleared so choosing the same file twice still fires a change event.
          event.target.value = "";
        }}
      />
      <Button full busy={busy} onClick={() => input.current?.click()}>
        {images.length === 0 ? "Add a photo" : "Add another photo"}
      </Button>
      <p className={styles.hint}>
        A clear picture of the item. Taken with your phone camera here, or chosen from the gallery.
      </p>

      {images.length === 0 ? (
        <Empty>No photos yet. The first thing a customer looks at is the picture.</Empty>
      ) : (
        <ul className={styles.gallery}>
          {images.map((image) => (
            <li key={image.id} className={styles.galleryItem}>
              {image.delivery_url ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img src={image.delivery_url} alt="" className={styles.galleryImage} />
              ) : (
                <span className={styles.galleryImage} />
              )}
              <div className={styles.galleryActions}>
                {image.is_primary ? (
                  <Pill tone="good">Cover</Pill>
                ) : (
                  <button className={styles.linkButton} onClick={() => onMakeCover(image.id)}>
                    Make cover
                  </button>
                )}
                <button className={styles.linkButton} onClick={() => onRemove(image.id)}>
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  );
}

function BusinessSheet({
  open,
  busy,
  closable,
  firstOne,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  closable: boolean;
  firstOne: boolean;
  onClose: () => void;
  onSubmit: (name: string) => void;
}) {
  const [name, setName] = useState("");

  // Empty every time it opens: the field is for the business about to be created, not the last one.
  useEffect(() => {
    if (open) {
      setName("");
    }
  }, [open]);

  return (
    <Sheet
      open={open}
      title={firstOne ? "Name your business" : "Another business"}
      onClose={closable ? onClose : () => {}}
    >
      <p className={styles.hint}>
        This is the name your customers see.{" "}
        {firstOne
          ? "You can add more businesses later, and keep them apart."
          : "It gets its own products, stock, sales and public shop address."}
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
