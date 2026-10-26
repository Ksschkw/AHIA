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
  BoxIcon,
  ChartIcon,
  ChevronDownIcon,
  CloseIcon,
  ExpenseIcon,
  Icon,
  ItemBoxIcon,
  PlusIcon,
  ProductIcon,
  ReceiptIcon,
  SaleIcon,
  SearchIcon,
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
  listCustomerLists,
  listExpenseCategories,
  listExpenses,
  listMembers,
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
  type CustomerList,
  type DailySalesSummary,
  type ExpenseCategory,
  type ExpenseItem,
  type Category,
  type ExpenseCategoryList,
  type Member,
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
import { calculateProfitMetrics } from "@/lib/profit";
import { SalesTimelineChart } from "@/components/SalesTimelineChart";
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

function getSaleDisplayTitle(
  s: SaleSummary,
  user: UserProfile | null,
  members: Member[],
  customerLists: CustomerList[]
): string {
  if (user && s.seller_id === user.id) return "Sale by You";
  const member = members.find((m) => m.user_id === s.seller_id);
  if (member) {
    if (member.full_name) return `Sale by ${member.full_name}`;
    if (member.role_name) return `Sale by ${member.role_name}`;
  }
  const linkedList = customerLists.find(
    (l) =>
      l.id === s.customer_id ||
      s.receipt_number.includes(l.id.slice(0, 8)) ||
      (s.receipt_number.startsWith("PAY-") && s.receipt_number.slice(4).startsWith(l.id.slice(0, 8))) ||
      l.lines.some((line) => line.id === s.id)
  );
  if (linkedList) {
    const cust = linkedList.customer_phone || linkedList.customer_name || "Customer List";
    return `Order: ${cust}`;
  }
  return s.seller_id ? `Sale by Staff (${s.seller_id.slice(0, 8)})` : "Counter Checkout";
}

export default function Dashboard() {
  const router = useRouter();
  const [sessionResolved, setSessionResolved] = useState(false);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
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
  const [customerLists, setCustomerLists] = useState<CustomerList[]>(() => {
    const id = rememberedBusinessId();
    if (!id) return [];
    return cachedRead<CustomerList[]>(`/api/v1/tenants/${id}/requests`) ?? [];
  });
  const [runningOut, setRunningOut] = useState<LowStockProduct[]>([]);
  const [categories, setCategories] = useState<ExpenseCategoryList | null>(null);
  const [expenses, setExpenses] = useState<ExpenseItem[]>([]);
  const [showTimelineChart, setShowTimelineChart] = useState(true);
  const [selectedSaleAudit, setSelectedSaleAudit] = useState<SaleSummary | null>(null);

  // Combine remote expenses with local offline/optimistic expenses
  const allExpenses = useMemo(() => {
    const remote = expenses ?? [];
    if (!businessId || typeof window === "undefined") return remote;
    try {
      const stored = window.localStorage.getItem(`ahia.expenses.${businessId}`);
      if (!stored) return remote;
      const local = JSON.parse(stored) as ExpenseItem[];
      const seen = new Set(remote.map((e) => e.id));
      const combined = [...remote];
      for (const item of local) {
        if (!seen.has(item.id)) {
          combined.push(item);
          seen.add(item.id);
        }
      }
      return combined;
    } catch {
      return remote;
    }
  }, [expenses, businessId]);

  // Merge direct sales with customer list payments, deposits, and confirmed orders
  const allRecentSales = useMemo(() => {
    const list: SaleSummary[] = [...(recentSales ?? [])];
    const seenIds = new Set(list.map((s) => s.id));
    const seenReceipts = new Set(list.map((s) => s.receipt_number));

    // Also load any locally recorded shelf sales
    if (businessId && typeof window !== "undefined") {
      try {
        const stored = window.localStorage.getItem(`ahia.sales.${businessId}`);
        if (stored) {
          const localSales = JSON.parse(stored) as SaleSummary[];
          for (const s of localSales) {
            if (!seenIds.has(s.id) && !seenReceipts.has(s.receipt_number)) {
              list.push(s);
              seenIds.add(s.id);
              seenReceipts.add(s.receipt_number);
            }
          }
        }
      } catch {
        // Non-fatal
      }
    }

    // Synthesize customer list orders and payments
    for (const cl of customerLists) {
      let payments: Array<{ id?: string; amount: string; date?: string; note?: string | null }> = cl.payments || [];
      if (typeof window !== "undefined") {
        try {
          const stored = window.localStorage.getItem(`ahia.list_payments.${cl.id}`);
          if (stored) {
            const parsed = JSON.parse(stored);
            if (Array.isArray(parsed) && parsed.length > 0) {
              payments = parsed;
            }
          }
        } catch {
          // ignore
        }
      }

      const paidAmt = Number(cl.amount_paid || cl.advance_payment || 0);
      if (payments.length === 0 && paidAmt > 0) {
        payments = [
          {
            id: `pay-advance-${cl.id}`,
            amount: paidAmt.toString(),
            date: cl.created_at || new Date().toISOString(),
            note: "Advance Deposit",
          },
        ];
      }

      let paymentsTotal = 0;
      for (const p of payments) {
        const amt = Number(p.amount || 0);
        if (amt <= 0) continue;
        paymentsTotal += amt;
        const pId = `sale-pay-${p.id || cl.id}-${amt}`;
        const pReceipt = `${cl.customer_name || cl.customer_phone || "Customer"}: ${p.note || "Payment"}`;
        if (!seenIds.has(pId) && !seenReceipts.has(pReceipt)) {
          list.push({
            id: pId,
            receipt_number: pReceipt,
            customer_id: null,
            seller_id: user?.id || cl.id,
            total_amount: amt.toFixed(2),
            status: "completed",
            payment_status: "paid",
            occurred_at: p.date || cl.created_at || new Date().toISOString(),
            cancelled_at: null,
          });
          seenIds.add(pId);
          seenReceipts.add(pReceipt);
        }
      }

      if (cl.status === "confirmed" && paymentsTotal === 0) {
        const listTotal = cl.lines.reduce((sum, line) => {
          if (line.note === "heading") return sum;
          const price = Number(line.shop_price || 0);
          const qty = Number(line.quantity || 1);
          return sum + (Number(line.line_total) || price * qty);
        }, 0);

        if (listTotal > 0) {
          const ordId = `sale-ord-${cl.id}`;
          const ordReceipt = `${cl.customer_name || cl.customer_phone || "Order"}: Confirmed Order`;
          if (!seenIds.has(ordId) && !seenReceipts.has(ordReceipt)) {
            list.push({
              id: ordId,
              receipt_number: ordReceipt,
              customer_id: null,
              seller_id: user?.id || cl.id,
              total_amount: listTotal.toFixed(2),
              status: "completed",
              payment_status: "confirmed",
              occurred_at: cl.dispatched_at || cl.created_at || new Date().toISOString(),
              cancelled_at: null,
            });
            seenIds.add(ordId);
            seenReceipts.add(ordReceipt);
          }
        }
      }
    }

    return list.sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime());
  }, [recentSales, customerLists, businessId, user?.id]);

  const todaySalesCountAndRevenue = useMemo(() => {
    const now = new Date();
    const todaySales = allRecentSales.filter((s) => {
      if (s.cancelled_at || s.payment_status === "cancelled") return false;
      const dateStr = s.occurred_at || (s as any).created_at;
      if (!dateStr) return false;
      const d = new Date(dateStr);
      if (Number.isNaN(d.getTime())) return false;
      return (
        d.getFullYear() === now.getFullYear() &&
        d.getMonth() === now.getMonth() &&
        d.getDate() === now.getDate()
      );
    });

    const localRevenue = todaySales.reduce((acc, s) => acc + (Number(s.total_amount) || 0), 0);
    const serverRevenue = Number(today?.total_revenue || "0");
    const serverCount = today?.total_sales ?? 0;

    return {
      revenue: Math.max(localRevenue, serverRevenue).toFixed(2),
      count: Math.max(todaySales.length, serverCount),
    };
  }, [allRecentSales, today]);

  const todayProfitMetrics = useMemo(() => {
    const todayRevenue = Number(todaySalesCountAndRevenue.revenue || 0);
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const todayStr = `${year}-${month}-${day}`;
    return calculateProfitMetrics({
      revenue: todayRevenue,
      products,
      expenses: allExpenses,
      todayStr,
    });
  }, [todaySalesCountAndRevenue.revenue, products, allExpenses]);
  // The product groups, which are a different thing from the spending categories above: these are how
  // the shelf is arranged - Category, Subcategory - and what a list is read under.
  const [productGroups, setProductGroups] = useState<Category[]>([]);
  //: Photos per product, loaded after the shelf and never blocking it. An empty map means "not read
  //: yet", which is why the shelf shows a placeholder rather than nothing while it fills in.
  const [photos, setPhotos] = useState<Record<string, ProductImage[]>>({});
  //: Null until the first photo request answers. False hides every photo affordance, because a
  //: business whose deployment has media switched off should not be shown buttons that cannot work.
  const [photosAvailable, setPhotosAvailable] = useState<boolean | null>(null);
  const [photoProduct, setPhotoProduct] = useState<Product | null>(null);
  const [storefront, setStorefront] = useState<Storefront | null>(null);
  const [shelfQuery, setShelfQuery] = useState("");

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

  const activeBusinessSummary = businesses.find((candidate) => candidate.id === businessId);
  const userRole = (activeBusinessSummary?.role_name ?? "OWNER").toUpperCase();
  const isOwnerOrManager = userRole === "OWNER" || userRole === "MANAGER";

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
    const rememberedLists = cachedRead<CustomerList[]>(`/api/v1/tenants/${tenantId}/requests`);
    if (rememberedProducts) {
      setProducts(rememberedProducts);
      setShelfState("ready");
    }
    if (rememberedStock) {
      setStock(rememberedStock);
    }
    if (rememberedLists) {
      setCustomerLists(rememberedLists);
    }

    const [foundProducts, foundStock, summary, sales, low, expenseCategories, foundLists, foundExpenses, foundMembers] = await Promise.all([
      listProducts(tenantId).catch(() => []),
      listStock(tenantId).catch(() => []),
      dailySales(tenantId).catch(() => null),
      listSales(tenantId, "6").catch(() => []),
      lowStock(tenantId, "5").catch(() => []),
      listExpenseCategories(tenantId).catch(() => null),
      listCustomerLists(tenantId).catch(() => []),
      listExpenses(tenantId).catch(() => []),
      listMembers(tenantId).catch(() => []),
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
    setCustomerLists(foundLists);
    setExpenses(foundExpenses);
    setMembers(foundMembers);
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
      setExpenses([]);
      setPhotos({});
      setStorefront(null);
      // The detail first: it carries the currency, so every amount on the page is rendered in the
      // business's own money rather than in a default that happens to be right for most shops.
      setBusinessDetail(await getBusiness(tenantId).catch(() => null));
      setStorefront(await getStorefront(tenantId).catch(() => null));
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

  // Lists that have not been confirmed yet are the ones the trader still needs to work through.
  const unansweredCount = customerLists.filter((l) => l.status !== "confirmed").length;

  // Shelf search filtering - a single search beats 40 rows of scrolling on a phone.
  const filteredShelf = shelfQuery.trim()
    ? products.filter((p) =>
        p.name.toLowerCase().includes(shelfQuery.trim().toLowerCase()),
      )
    : products;

  // Build a grouped, hierarchical view of the shelf. The trader arranged their stock into
  // categories (and sub-categories, and sub-sub-categories) and the shelf should reflect that
  // arrangement, not ignore it. Products without a category go last under "Uncategorised".
  //
  // The rendering is intentionally flat after the sort: we do not render nested collapsible trees,
  // we render heading -> items -> heading -> items, but the headings are in depth-first order so a
  // subcategory always appears right under its parent heading.
  const categoryById = new Map(productGroups.map((c) => [c.id, c]));
  const depthOf = (id: string | null): number => {
    let depth = 0;
    let cur = id;
    while (cur) {
      const parent = categoryById.get(cur)?.parent_id ?? null;
      if (parent === cur) break; // guard against malformed cycles
      cur = parent;
      depth++;
    }
    return depth;
  };
  // Resolve the full ancestor path for a category so we can sort lexicographically by hierarchy.
  const pathOf = (id: string | null): string => {
    const parts: string[] = [];
    let cur: string | null = id;
    while (cur) {
      const cat = categoryById.get(cur);
      if (!cat) break;
      parts.unshift(cat.name.toLowerCase());
      cur = cat.parent_id ?? null;
    }
    return parts.join("\0"); // null-byte separator keeps the comparison simple
  };

  // Group products by their direct category. When searching, skip the group headings to reduce
  // noise - the search result is already small enough that headings add no value.
  type ShelfGroup = { categoryId: string | null; label: string; depth: number; items: Product[] };
  const shelfGroups: ShelfGroup[] = [];
  if (!shelfQuery.trim()) {
    const grouped = new Map<string | null, Product[]>();
    for (const p of products) {
      const key = p.category_id ?? null;
      const existing = grouped.get(key);
      if (existing) {
        existing.push(p);
      } else {
        grouped.set(key, [p]);
      }
    }
    // Sort groups: root categories first (shallowest), then alphabetically within each depth level.
    const sortedKeys = [...grouped.keys()].sort((a, b) => {
      const depthA = depthOf(a);
      const depthB = depthOf(b);
      if (depthA !== depthB) return depthA - depthB;
      return pathOf(a).localeCompare(pathOf(b));
    });
    for (const key of sortedKeys) {
      const label = key ? (categoryById.get(key)?.name ?? "Unknown") : "Uncategorised";
      const depth = depthOf(key);
      const items = (grouped.get(key) ?? []).sort((a, b) => a.name.localeCompare(b.name));
      shelfGroups.push({ categoryId: key, label, depth, items });
    }
  }

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
        {businessId ? (
          <Link href="/app/lists" className={styles.checkListsBtn}>
            <Icon name="list" size={16} />
            Customer Lists
            {unansweredCount > 0 ? (
              <span className={styles.hoveringBadge}>{unansweredCount}</span>
            ) : null}
          </Link>
        ) : null}
        {isOwnerOrManager || businesses.length === 0 ? (
          <button
            className={styles.addBusiness}
            aria-label="Add another business"
            title="Add another business"
            onClick={() => setSheet("business")}
          >
            + New business
          </button>
        ) : null}
      </div>

      <div className={styles.content}>
        {/* Unanswered lists callout - only when there is something for the trader to action */}
        {unansweredCount > 0 && businessId ? (
          <div className={styles.unansweredCallout}>
            <div className={styles.unansweredCalloutInfo}>
              <span className={styles.unansweredCalloutBadge}>{unansweredCount}</span>
              <div>
                <span className={styles.unansweredCalloutTitle}>
                  {unansweredCount === 1
                    ? "1 customer list waiting"
                    : `${unansweredCount} customer lists waiting`}
                </span>
                <p className={styles.unansweredCalloutSub}>
                  Customers sent orders that have not been confirmed yet.
                </p>
              </div>
            </div>
            <Link href="/app/lists" className={styles.unansweredCalloutAction}>
              Open lists
            </Link>
          </div>
        ) : null}

        <section className={styles.heroRow}>
          {isOwnerOrManager ? (
            <>
              <Stat
                label="Sold today"
                value={formatMoney(todaySalesCountAndRevenue.revenue, currency)}
                hint={`${formatCount(todaySalesCountAndRevenue.count)} sales`}
                tone="good"
              />
              <Stat
                label="Net Profit"
                value={formatMoney(todayProfitMetrics.netProfit.toFixed(2), currency)}
                hint={`${todayProfitMetrics.marginPercent}% margin`}
                tone={todayProfitMetrics.netProfit >= 0 ? "good" : "warn"}
              />
              <Stat
                label="Expenses today"
                value={formatMoney(todayProfitMetrics.expenses.toFixed(2), currency)}
                hint={`${allExpenses.filter((e) => !e.is_reversed && (!e.incurred_at || e.incurred_at.slice(0, 10) === new Date().toISOString().slice(0, 10))).length} logged`}
                tone={todayProfitMetrics.expenses > 0 ? "warn" : "plain"}
              />
            </>
          ) : (
            <Stat
              label="Recent sales"
              value={formatCount(allRecentSales.length)}
              hint="Recorded recently"
              tone="good"
            />
          )}
          <Stat
            label="In stock"
            value={formatCount(products.length)}
            hint={`${stock.filter((entry) => entry.is_out_of_stock).length} out of stock`}
          />
          <Stat
            label="Running out"
            value={formatCount(runningOut.length)}
            hint={runningOut.length > 0 ? "Restock today" : "Nothing urgent"}
            tone={runningOut.length > 0 ? "warn" : "plain"}
          />
          <Stat
            label="Unanswered lists"
            value={formatCount(unansweredCount)}
            hint={unansweredCount > 0 ? "Customer orders waiting" : "All caught up"}
            tone={unansweredCount > 0 ? "warn" : "plain"}
          />
        </section>

        {isOwnerOrManager ? (
          <div style={{ marginBottom: "20px" }}>
            <button
              type="button"
              onClick={() => setShowTimelineChart((prev) => !prev)}
              style={{
                width: "100%",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "12px 18px",
                borderRadius: "12px",
                border: "1px solid var(--line, #2d3830)",
                background: "var(--card, #1e2620)",
                cursor: "pointer",
                marginBottom: showTimelineChart ? "12px" : "0",
                transition: "all 0.15s ease",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <ChartIcon size={20} style={{ color: "var(--leaf, #1aa36a)" }} />
                <div style={{ textAlign: "left" }}>
                  <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--ink, #f0ede6)" }}>
                    Sales & Profit Progress Timeline
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--ink-2, #a8a092)" }}>
                    {showTimelineChart
                      ? "Click to collapse visual charts"
                      : "Click to view 7d / 14d / 30d visual trends & daily performance"}
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "13px", fontWeight: 700, color: "var(--leaf, #1aa36a)" }}>
                <span>{showTimelineChart ? "Hide Chart" : "Show Chart"}</span>
                <ChevronDownIcon size={16} style={{ transform: showTimelineChart ? "rotate(180deg)" : "none", transition: "transform 0.2s ease" }} />
              </div>
            </button>

            {showTimelineChart ? (
              <SalesTimelineChart
                days={today?.days ?? []}
                sales={allRecentSales}
                currency={currency}
                marginRatio={
                  todayProfitMetrics.revenue > 0
                    ? todayProfitMetrics.grossProfit / todayProfitMetrics.revenue
                    : 0.28
                }
              />
            ) : null}
          </div>
        ) : null}

        {/* Quick Actions Bar */}
        <section className={styles.actions} style={{ marginBottom: "20px" }}>
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
          {isOwnerOrManager ? (
            <ActionTile
              label="Record spending"
              hint="Money out"
              glyph="expense"
              onClick={() => setSheet("expense")}
              disabled={!businessId}
            />
          ) : null}
        </section>

        <div className={styles.columns}>
          {/* Left Column: Recent Sales & Online Storefront */}
          <div className={styles.sideColumn}>
            <Card
              title="Recent sales"
              action={
                <button className={styles.linkButton} onClick={() => setSheet("sale")}>
                  + Record Sale
                </button>
              }
            >
              {allRecentSales.length === 0 ? (
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
                  {allRecentSales.map((sale) => (
                    <li key={sale.id} className={styles.row}>
                      <div className={styles.rowMain}>
                        <span
                          className={styles.rowName}
                          style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}
                        >
                          <ReceiptIcon size={16} style={{ color: "var(--leaf)", flexShrink: 0 }} />
                          <span>{getSaleDisplayTitle(sale, user, members, customerLists)}</span>
                        </span>
                        <span className={styles.rowMeta}>
                          {sale.receipt_number} &bull; {((sale as unknown as { payment_method?: string }).payment_method ?? sale.payment_status).toUpperCase()}
                        </span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                        <span className={`${styles.amount} tabular`}>
                          {formatMoney(sale.total_amount, currency)}
                        </span>
                        <button
                          type="button"
                          className={styles.auditBtn}
                          onClick={() => setSelectedSaleAudit(sale)}
                        >
                          Audit &amp; Blame &rsaquo;
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card
              title="Your shop online"
              action={
                storefront?.is_published && isOwnerOrManager ? (
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
                    {isOwnerOrManager ? (
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
                    ) : null}
                  </div>
                </>
              ) : (
                <>
                  <p className={styles.hint}>
                    A page with your products, photos and prices that you can send to a customer.
                    They open it, see what you have, and message you on WhatsApp.
                  </p>
                  {isOwnerOrManager ? (
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
                  ) : null}
                </>
              )}
            </Card>
          </div>

          {/* Right Column: Stock & Inventory Health */}
          <Card
            title="Stock & Inventory Health"
            action={
              <button className={styles.linkButton} onClick={() => setSheet("product")}>
                + Add product
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
              <div>
                {/* 3 Metric Summary Pills */}
                <div className={styles.stockHealthStats}>
                  <div className={styles.stockHealthStat}>
                    <div className={styles.stockHealthVal}>{products.length}</div>
                    <div className={styles.stockHealthLabel}>On Shelf</div>
                  </div>
                  <div className={styles.stockHealthStat}>
                    <div
                      className={styles.stockHealthVal}
                      style={{ color: runningOut.length > 0 ? "var(--clay)" : "var(--ink)" }}
                    >
                      {runningOut.length}
                    </div>
                    <div className={styles.stockHealthLabel}>Low Stock</div>
                  </div>
                  <div className={styles.stockHealthStat}>
                    <div
                      className={styles.stockHealthVal}
                      style={{
                        color:
                          stock.filter((e) => e.is_out_of_stock).length > 0
                            ? "var(--danger)"
                            : "var(--ink)",
                      }}
                    >
                      {stock.filter((e) => e.is_out_of_stock).length}
                    </div>
                    <div className={styles.stockHealthLabel}>Out of Stock</div>
                  </div>
                </div>

                {/* Urgent Low Stock Alert Card */}
                {runningOut.length > 0 && (
                  <div className={styles.urgentAlertCard}>
                    <div className={styles.urgentAlertHeader}>
                      <span>Restock Urgently ({runningOut.length} items low)</span>
                      <button
                        type="button"
                        className={styles.linkButton}
                        style={{ fontSize: "11px", color: "var(--clay)" }}
                        onClick={() => setSheet("stock")}
                      >
                        + Receive stock
                      </button>
                    </div>
                    <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "6px" }}>
                      {runningOut.slice(0, 4).map((item) => (
                        <li key={item.product_id} style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
                          <span style={{ fontWeight: 600, color: "var(--ink)" }}>{item.product_name}</span>
                          <span style={{ color: "var(--clay)", fontWeight: 700 }}>
                            {formatQuantity(item.quantity_on_hand)} left
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Instant Stock Search */}
                <div className={styles.shelfFilterWrap}>
                  <SearchIcon size={16} className={styles.shelfFilterIcon} />
                  <input
                    className={styles.shelfFilterInput}
                    type="search"
                    value={shelfQuery}
                    onChange={(e) => setShelfQuery(e.target.value)}
                    placeholder="Search price & stock of any item..."
                    aria-label="Filter shelf items"
                  />
                  {shelfQuery ? (
                    <button
                      className={styles.shelfFilterClear}
                      onClick={() => setShelfQuery("")}
                      aria-label="Clear filter"
                    >
                      Clear
                    </button>
                  ) : null}
                </div>

                {shelfQuery.trim() ? (
                  filteredShelf.length === 0 ? (
                    <p className={styles.shelfEmptySearch}>
                      No stock matches &ldquo;{shelfQuery}&rdquo;.
                    </p>
                  ) : (
                    <ul className={styles.shelf} style={{ maxHeight: "320px", overflowY: "auto" }}>
                      {filteredShelf.slice(0, 10).map((product) => {
                        const level = levelFor(product.id);
                        const quantity = Number(level?.available_quantity ?? "0");
                        const out = level?.is_out_of_stock ?? false;
                        const cover = coverPhoto(photos[product.id]);
                        return (
                          <ShelfRow
                            key={product.id}
                            product={product}
                            level={level}
                            quantity={quantity}
                            out={out}
                            cover={cover}
                            busy={busy}
                            photosAvailable={photosAvailable}
                            currency={currency}
                            styles={styles}
                            onPhoto={() => setPhotoProduct(product)}
                            onSell={() => {
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
                                if (typeof window !== "undefined" && businessId && receipt?.sale) {
                                  try {
                                    const stored = window.localStorage.getItem(`ahia.sales.${businessId}`);
                                    const parsed = stored ? JSON.parse(stored) : [];
                                    window.localStorage.setItem(`ahia.sales.${businessId}`, JSON.stringify([receipt.sale, ...parsed]));
                                  } catch {
                                    // non-fatal
                                  }
                                }
                                setRecentSales((prev) => [receipt.sale as any, ...prev]);
                                await refresh();
                                setNotice({
                                  message: `Sold one ${product.name} - ${receipt.sale.receipt_number} for ${formatMoney(receipt.sale.total_amount, currency)}`,
                                  tone: "good",
                                });
                              });
                            }}
                            onTogglePublish={() => {
                              void runShop(async () => {
                                if (!businessId) return;
                                const wasPublished = product.is_published;
                                setProducts((current) =>
                                  current.map((c) =>
                                    c.id === product.id ? { ...c, is_published: !wasPublished } : c,
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
                                    current.map((c) =>
                                      c.id === product.id ? { ...c, is_published: wasPublished } : c,
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
                          />
                        );
                      })}
                    </ul>
                  )
                ) : (
                  <div>
                    <p className={styles.hint} style={{ marginBottom: "12px" }}>
                      Manage products, categories, wholesale/retail dual pricing, and stock in the full catalog.
                    </p>
                  </div>
                )}

                {/* Direct Link to Full Catalog */}
                <Link href="/app/items" className={styles.fullCatalogBtn}>
                  <BoxIcon size={16} />
                  <span>Manage Full Shelf &amp; Catalog &rsaquo;</span>
                </Link>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Sale Audit & Blame Modal */}
      {selectedSaleAudit ? (
        <div className={styles.modalOverlay} onClick={() => setSelectedSaleAudit(null)}>
          <div className={styles.modalBox} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div>
                <h3 className={styles.modalTitle}>Sale Audit &amp; Blame</h3>
                <div className={styles.modalSubtitle}>Receipt #{selectedSaleAudit.receipt_number}</div>
              </div>
              <button
                type="button"
                className={styles.closeCircleBtn}
                onClick={() => setSelectedSaleAudit(null)}
                aria-label="Close"
              >
                <CloseIcon size={16} />
              </button>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "14px 16px",
                background: "var(--sand-2)",
                borderRadius: "12px",
                border: "1px solid var(--line)",
              }}
            >
              <div>
                <div
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    color: "var(--ink-2)",
                    textTransform: "uppercase",
                  }}
                >
                  TRANSACTION TOTAL
                </div>
                <div
                  style={{
                    fontSize: "22px",
                    fontWeight: 800,
                    color: selectedSaleAudit.cancelled_at ? "var(--danger)" : "var(--leaf)",
                    marginTop: "2px",
                  }}
                >
                  {formatMoney(selectedSaleAudit.total_amount, currency)}
                </div>
                <div style={{ fontSize: "11px", color: "var(--ink-2)", marginTop: "2px" }}>
                  {new Date(selectedSaleAudit.occurred_at).toLocaleString([], {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <span
                  style={{
                    display: "inline-block",
                    padding: "3px 8px",
                    borderRadius: "999px",
                    fontSize: "10px",
                    fontWeight: 700,
                    background: selectedSaleAudit.cancelled_at
                      ? "var(--danger-soft)"
                      : "var(--leaf-soft)",
                    color: selectedSaleAudit.cancelled_at ? "var(--danger)" : "var(--leaf)",
                    marginBottom: "4px",
                  }}
                >
                  {selectedSaleAudit.cancelled_at
                    ? "RETURNED / VOIDED"
                    : selectedSaleAudit.payment_status.toUpperCase()}
                </span>
                <div style={{ fontSize: "11px", color: "var(--ink-2)", fontWeight: 600 }}>
                  via {((selectedSaleAudit as unknown as { payment_method?: string }).payment_method ?? selectedSaleAudit.payment_status).toUpperCase()}
                </div>
              </div>
            </div>

            {/* Git-Style Blame Box */}
            <div className={styles.blameCard}>
              <div
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  color: "var(--ink-2)",
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                }}
              >
                COMMIT AUTHOR &amp; BLAME
              </div>
              <div className={styles.blameRow}>
                <span className={styles.blameLabel}>Seller / Recorded By:</span>
                <span className={styles.blameValue}>
                  {(() => {
                    const isSelf = user && selectedSaleAudit.seller_id === user.id;
                    const m = members.find((x) => x.user_id === selectedSaleAudit.seller_id);
                    if (isSelf) {
                      return (
                        [user?.first_name, user?.last_name].filter(Boolean).join(" ") ||
                        "You (Account Owner)"
                      );
                    }
                    if (m) {
                      return m.full_name || m.role_name || "Stall Staff";
                    }
                    return selectedSaleAudit.seller_id
                      ? `Staff (${selectedSaleAudit.seller_id.slice(0, 8)})`
                      : "Counter Checkout";
                  })()}
                </span>
              </div>
              <div className={styles.blameRow}>
                <span className={styles.blameLabel}>Role / Permission:</span>
                <span className={styles.blameValue}>
                  {(() => {
                    const isSelf = user && selectedSaleAudit.seller_id === user.id;
                    const m = members.find((x) => x.user_id === selectedSaleAudit.seller_id);
                    if (isSelf) return "Owner / Trader Admin";
                    return m?.role_name || "Sales Representative";
                  })()}
                </span>
              </div>
              <div className={styles.blameRow}>
                <span className={styles.blameLabel}>Seller ID:</span>
                <span
                  className={styles.blameValue}
                  style={{ fontFamily: "monospace", fontSize: "11px" }}
                >
                  {selectedSaleAudit.seller_id || "system"}
                </span>
              </div>
              <div className={styles.blameRow}>
                <span className={styles.blameLabel}>Origin Channel:</span>
                <span className={styles.blameValue}>
                  {(() => {
                    const linked = customerLists.find(
                      (l) =>
                        l.id === selectedSaleAudit.customer_id ||
                        selectedSaleAudit.receipt_number.includes(l.id.slice(0, 8)) ||
                        (selectedSaleAudit.receipt_number.startsWith("PAY-") &&
                          selectedSaleAudit.receipt_number
                            .slice(4)
                            .startsWith(l.id.slice(0, 8))),
                    );
                    if (linked) {
                      return `Customer Order (${linked.customer_phone || linked.customer_name || "Online Request"})`;
                    }
                    return "In-Stall POS Direct Sale";
                  })()}
                </span>
              </div>
            </div>

            <button
              type="button"
              className={styles.fullCatalogBtn}
              onClick={() => setSelectedSaleAudit(null)}
              style={{ marginTop: "4px" }}
            >
              Done &amp; Close Audit
            </button>
          </div>
        </div>
      ) : null}

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
            if (typeof window !== "undefined" && businessId && receipt?.sale) {
              try {
                const stored = window.localStorage.getItem(`ahia.sales.${businessId}`);
                const parsed = stored ? JSON.parse(stored) : [];
                window.localStorage.setItem(`ahia.sales.${businessId}`, JSON.stringify([receipt.sale, ...parsed]));
              } catch {
                // non-fatal
              }
            }
            setRecentSales((prev) => [receipt.sale as any, ...prev]);
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
            const localId = `exp-local-${Date.now()}`;
            const newExp: ExpenseItem = {
              id: localId,
              category: input.category,
              amount: Number(input.amount).toFixed(2),
              payment_method: "CASH",
              description: input.description ?? null,
              incurred_at: new Date().toISOString(),
            };
            if (typeof window !== "undefined") {
              try {
                const stored = window.localStorage.getItem(`ahia.expenses.${businessId}`);
                const parsed = stored ? JSON.parse(stored) : [];
                window.localStorage.setItem(`ahia.expenses.${businessId}`, JSON.stringify([newExp, ...parsed]));
              } catch {
                // non-fatal
              }
            }
            setExpenses((prev) => [newExp, ...prev]);
            try {
              await recordExpense(businessId, input);
              const freshExp = await listExpenses(businessId).catch(() => []);
              setExpenses(freshExp);
            } catch {
              // already saved locally
            }
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

// A single product row in the shelf - extracted so both the grouped view and the flat search
// results view can render it without duplicating the full markup.
function ShelfRow({
  product,
  level,
  quantity,
  out,
  cover,
  busy,
  photosAvailable,
  currency,
  styles,
  onPhoto,
  onSell,
  onTogglePublish,
}: {
  product: Product;
  level: InventoryLevel | undefined;
  quantity: number;
  out: boolean;
  cover: ProductImage | undefined;
  busy: boolean;
  photosAvailable: boolean | null;
  currency: string;
  styles: Record<string, string>;
  onPhoto: () => void;
  onSell: () => void;
  onTogglePublish: () => void;
}) {
  return (
    <li className={styles.shelfRow}>
      {photosAvailable !== false ? (
        <button
          className={styles.shelfThumb}
          onClick={onPhoto}
          aria-label={cover ? `Photos of ${product.name}` : `Add a photo of ${product.name}`}
        >
          {cover?.delivery_url ? (
            // eslint-disable-next-line @next/next/no-img-element
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
          {level ? (
            out ? (
              <span className={styles.shelfOut}>Out</span>
            ) : (
              <span className={quantity <= 3 ? styles.shelfLow : styles.shelfCount}>
                {formatQuantity(level.available_quantity)} left
              </span>
            )
          ) : null}
          <span className={product.is_published ? styles.shelfLive : styles.shelfHidden}>
            {product.is_published ? "In shop" : "Hidden"}
          </span>
        </span>
      </span>

      <span className={styles.shelfActions}>
        <button className={styles.shelfSell} disabled={busy || out} onClick={onSell}>
          Sell one
        </button>
        <button
          className={styles.shelfToggle}
          disabled={busy}
          aria-pressed={product.is_published}
          title={product.is_published ? "Hide this from the public shop" : "Show this in the public shop"}
          onClick={onTogglePublish}
        >
          {product.is_published ? "Hide" : "Show"}
        </button>
      </span>
    </li>
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
  // run of names would make "Subcategory" and "Category" look like siblings when one is inside the other.
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
