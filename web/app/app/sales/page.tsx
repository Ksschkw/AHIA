"use client";

/**
 * What has been sold and spent: the daily trading ledger.
 *
 * Matches the mobile app's Trading tab identically:
 * - Two sub-tabs: "Sales" and "Expenses"
 * - Sales timeline progress chart (revenue vs profit)
 * - Search past transactions and filter by All / Paid / Returned
 * - Transaction Audit drawer showing who sold it, waybill, and lines
 * - Business expenses tracker with category breakdown and "+ Log Expense" sheet
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SaleIcon, SearchIcon, PlusIcon, TruckIcon } from "@/components/icons";
import { EmptySalesIllustration } from "@/components/illustrations";
import { Card, Empty, Field, Loading, Pill, Select, Sheet, Toast } from "@/components/ui";
import {
  cachedRead,
  firstPaint,
  rememberedBusinessId,
  currentUser,
  dailySales,
  getBusiness,
  listBusinesses,
  listCustomerLists,
  listExpenses,
  listExpenseCategories,
  listProducts,
  listSales,
  recordExpense,
  type CustomerList,
  type DailySalesSummary,
  type ExpenseCategory,
  type ExpenseCategoryCode,
  type ExpenseItem,
  type Product,
  type SaleSummary,
  type Tenant,
  type UserProfile,
} from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { calculateProfitMetrics } from "@/lib/profit";
import { SalesTimelineChart } from "@/components/SalesTimelineChart";
import styles from "../dashboard.module.css";

export default function Sales() {
  const [business, setBusiness] = useState<Tenant | null>(null);
  const [sales, setSales] = useState<SaleSummary[] | null>(() =>
    firstPaint<SaleSummary[]>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}/sales`),
  );
  const [expenses, setExpenses] = useState<ExpenseItem[]>([]);
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>([]);
  const [dailySummary, setDailySummary] = useState<DailySalesSummary | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [customerLists, setCustomerLists] = useState<CustomerList[]>([]);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [currency, setCurrency] = useState("NGN");
  const [state, setState] = useState<"loading" | "ready">(() =>
    rememberedBusinessId() ? "ready" : "loading",
  );
  const [notice, setNotice] = useState<string | null>(null);

  // Trading Sub-tabs
  const [tradingTab, setTradingTab] = useState<"sales" | "expenses">("sales");

  // Search & Filter state for old sales and staff accountability audit
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "paid" | "returned">("all");
  const [selectedSaleAudit, setSelectedSaleAudit] = useState<SaleSummary | null>(null);

  // Log Expense modal
  const [showExpenseModal, setShowExpenseModal] = useState(false);
  const [expenseAmount, setExpenseAmount] = useState("");
  const [expenseCategory, setExpenseCategory] = useState<ExpenseCategoryCode>("STOCK_PURCHASE");
  const [expenseDescription, setExpenseDescription] = useState("");
  const [savingExpense, setSavingExpense] = useState(false);

  const load = useCallback(async (tenantId: string) => {
    const [found, expList, expCats, summary, prods, lists] = await Promise.all([
      listSales(tenantId, "50"),
      listExpenses(tenantId).catch(() => []),
      listExpenseCategories(tenantId).then((res) => res.categories).catch(() => []),
      dailySales(tenantId).catch(() => null),
      listProducts(tenantId).catch(() => []),
      listCustomerLists(tenantId).catch(() => []),
    ]);
    setSales(found);
    setExpenses(expList);
    setExpenseCategories(expCats);
    setDailySummary(summary);
    setProducts(prods);
    setCustomerLists(lists);
    setState("ready");
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const me = await currentUser().catch(() => null);
        if (me) setUserProfile(me);
        const businesses = await listBusinesses();
        const remembered =
          typeof window === "undefined" ? null : window.localStorage.getItem("ahia.business");
        const chosen = businesses.find((candidate) => candidate.id === remembered) ?? businesses[0];
        if (!chosen) return;
        const detail = await getBusiness(chosen.id);
        setBusiness(detail);
        setCurrency(detail.currency);
        // What the browser already holds, painted before anything is asked for.
        const rememberedSales = cachedRead<SaleSummary[]>(`/api/v1/tenants/${chosen.id}/sales`);
        const rememberedExpenses = cachedRead<ExpenseItem[]>(`/api/v1/tenants/${chosen.id}/expenses`);
        const rememberedLists = cachedRead<CustomerList[]>(`/api/v1/tenants/${chosen.id}/requests`);
        if (rememberedSales) {
          setSales(rememberedSales);
          setState("ready");
        }
        if (rememberedExpenses) {
          setExpenses(rememberedExpenses);
        }
        if (rememberedLists) {
          setCustomerLists(rememberedLists);
        }
        await load(chosen.id);
      } catch (error) {
        setNotice("We could not fetch your sales. Pull down to try again.");
      }
    })();
  }, [load]);

  // Combine remote expenses with local offline/optimistic expenses
  const allExpenses = useMemo(() => {
    const remote = expenses ?? [];
    if (!business?.id || typeof window === "undefined") return remote;
    try {
      const stored = window.localStorage.getItem(`ahia.expenses.${business.id}`);
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
  }, [expenses, business?.id]);

  // Merge direct sales with customer list payments, deposits, and confirmed orders
  const allSales = useMemo(() => {
    const list: SaleSummary[] = [...(sales ?? [])];
    const seenIds = new Set(list.map((s) => s.id));
    const seenReceipts = new Set(list.map((s) => s.receipt_number));

    // Also load any locally recorded shelf sales
    if (business?.id && typeof window !== "undefined") {
      try {
        const stored = window.localStorage.getItem(`ahia.sales.${business.id}`);
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
      // 1. Check for itemized payments (from list.payments or localStorage)
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

      // If no payments array but amount_paid / advance_payment > 0
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

      // Add each payment as a sale transaction
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
            seller_id: userProfile?.id || cl.id,
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

      // 2. Confirmed customer lists that have no payments recorded yet
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
              seller_id: userProfile?.id || cl.id,
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

    // Sort newest to oldest
    return list.sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime());
  }, [sales, customerLists, business?.id, userProfile?.id]);

  const total = useMemo(
    () => allSales.reduce((running, sale) => running + (sale.cancelled_at ? 0 : Number(sale.total_amount ?? "0")), 0),
    [allSales],
  );

  const totalExpenses = useMemo(
    () => allExpenses.reduce((running, exp) => running + (exp.is_reversed ? 0 : Number(exp.amount ?? "0")), 0),
    [allExpenses],
  );

  const profitMetrics = useMemo(
    () => calculateProfitMetrics({ revenue: total, products, expenses: allExpenses }),
    [total, products, allExpenses],
  );

  const handleLogExpense = async () => {
    if (!business) return;
    const amt = expenseAmount.trim();
    if (!amt || Number(amt) <= 0) {
      setNotice("Please enter a valid expense amount.");
      return;
    }
    setSavingExpense(true);

    const localId = `exp-local-${Date.now()}`;
    const newExp: ExpenseItem = {
      id: localId,
      category: expenseCategory,
      amount: Number(amt).toFixed(2),
      payment_method: "CASH",
      description: expenseDescription.trim() || null,
      incurred_at: new Date().toISOString(),
    };

    if (typeof window !== "undefined") {
      try {
        const existingStored = window.localStorage.getItem(`ahia.expenses.${business.id}`);
        const parsed = existingStored ? JSON.parse(existingStored) : [];
        window.localStorage.setItem(`ahia.expenses.${business.id}`, JSON.stringify([newExp, ...parsed]));
      } catch {
        // Non-fatal
      }
    }
    setExpenses((prev) => [newExp, ...prev]);

    try {
      await recordExpense(business.id, {
        category: expenseCategory,
        amount: Number(amt).toFixed(2),
        description: expenseDescription.trim() || undefined,
        payment_method: "CASH",
      });
      setShowExpenseModal(false);
      setExpenseAmount("");
      setExpenseDescription("");
      setNotice("Expense logged successfully!");
      void load(business.id);
    } catch {
      setShowExpenseModal(false);
      setExpenseAmount("");
      setExpenseDescription("");
      setNotice("Expense saved locally and will sync when connected.");
    } finally {
      setSavingExpense(false);
    }
  };

  return (
    <main className={styles.page}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", flexWrap: "wrap", gap: "10px" }}>
        <div>
          <h1 className={styles.title} style={{ marginBottom: "2px" }}>Daily Trading</h1>
          <p className={styles.lede} style={{ margin: 0 }}>
            Daily revenue, expenses, and staff transaction audit.
          </p>
        </div>

        {/* Sub-tab Pill Switcher matching Mobile App identically */}
        <div style={{ display: "flex", gap: "6px", background: "var(--card, #fff)", padding: "4px", borderRadius: "10px", border: "1px solid var(--line, #e5e7eb)" }}>
          <button
            type="button"
            onClick={() => setTradingTab("sales")}
            style={{
              padding: "6px 16px",
              borderRadius: "8px",
              border: "none",
              fontSize: "13px",
              fontWeight: 700,
              cursor: "pointer",
              background: tradingTab === "sales" ? "var(--leaf, #238636)" : "transparent",
              color: tradingTab === "sales" ? "#ffffff" : "var(--ink, #111)",
              transition: "all 0.15s ease",
            }}
          >
            Sales {state === "loading" && allSales.length === 0 ? "" : `(${allSales.length})`}
          </button>
          <button
            type="button"
            onClick={() => setTradingTab("expenses")}
            style={{
              padding: "6px 16px",
              borderRadius: "8px",
              border: "none",
              fontSize: "13px",
              fontWeight: 700,
              cursor: "pointer",
              background: tradingTab === "expenses" ? "var(--leaf, #238636)" : "transparent",
              color: tradingTab === "expenses" ? "#ffffff" : "var(--ink, #111)",
              transition: "all 0.15s ease",
            }}
          >
            Expenses {state === "loading" && allExpenses.length === 0 ? "" : `(${allExpenses.length})`}
          </button>
        </div>
      </div>

      {state === "loading" ? <Loading label="Fetching your records..." /> : null}

      {/* SALES TAB */}
      {tradingTab === "sales" ? (
        <>
          {state === "ready" && allSales.length === 0 ? (
            <Empty
              illustration={<EmptySalesIllustration size={110} />}
              action={
                <Link
                  href="/app"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "8px 16px",
                    borderRadius: "999px",
                    background: "var(--leaf)",
                    color: "#fff",
                    fontWeight: 700,
                    fontSize: "12px",
                    textDecoration: "none",
                  }}
                >
                  <SaleIcon size={14} /> Record First Sale on Shelf
                </Link>
              }
            >
              No sales recorded yet.
              <br />
              Record customer sales directly from your shelf to track your daily revenue.
            </Empty>
          ) : null}

          {allSales.length > 0 ? (
            <>
              <SalesTimelineChart
                days={dailySummary?.days ?? []}
                sales={allSales}
                currency={currency}
                marginRatio={
                  profitMetrics.revenue > 0 ? profitMetrics.grossProfit / profitMetrics.revenue : 0.28
                }
              />
              <Card title={`${allSales.length} sales`}>
                <p className={styles.totalPreview}>
                  {formatMoney(total.toFixed(2), currency)} in total | Est. Profit:{" "}
                  <strong style={{ color: "var(--leaf, #238636)" }}>
                    {formatMoney(profitMetrics.grossProfit.toFixed(2), currency)}
                  </strong>{" "}
                  ({profitMetrics.marginPercent}%)
                </p>

                {/* Search & Filter Controls to track past sales and staff audit */}
                <div style={{ display: "flex", gap: "10px", alignItems: "center", margin: "14px 0", flexWrap: "wrap" }}>
                  <div style={{ flex: 1, minWidth: "220px", position: "relative" }}>
                    <input
                      type="text"
                      placeholder="Search sales by receipt, customer, amount, date..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "8px 12px 8px 32px",
                        borderRadius: "8px",
                        border: "1px solid var(--border, #e5e7eb)",
                        background: "var(--paper, #fff)",
                        color: "var(--ink, #111)",
                        fontSize: "13px",
                      }}
                    />
                    <span style={{ position: "absolute", left: "10px", top: "50%", transform: "translateY(-50%)", color: "#8a928e" }}>
                      <SearchIcon size={14} />
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: "6px" }}>
                    {(["all", "paid", "returned"] as const).map((filter) => {
                      const count =
                        filter === "all"
                          ? allSales.length
                          : filter === "paid"
                          ? allSales.filter((s) => !s.cancelled_at).length
                          : allSales.filter((s) => Boolean(s.cancelled_at)).length;
                      return (
                        <button
                          key={filter}
                          type="button"
                          onClick={() => setStatusFilter(filter)}
                          style={{
                            padding: "6px 12px",
                            borderRadius: "999px",
                            fontSize: "12px",
                            fontWeight: 600,
                            border: statusFilter === filter ? "1px solid #238636" : "1px solid var(--border, #e5e7eb)",
                            background: statusFilter === filter ? "#238636" : "var(--paper, #fff)",
                            color: statusFilter === filter ? "#fff" : "var(--ink, #111)",
                            cursor: "pointer",
                          }}
                        >
                          {filter === "all" ? `All (${count})` : filter === "paid" ? `Paid (${count})` : `Returned (${count})`}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {(() => {
                  const filteredSales = allSales.filter((s) => {
                    if (statusFilter === "paid" && s.cancelled_at) return false;
                    if (statusFilter === "returned" && !s.cancelled_at) return false;
                    if (!searchQuery.trim()) return true;
                    const q = searchQuery.toLowerCase();
                    const receipt = (s.receipt_number || "").toLowerCase();
                    const amt = (s.total_amount || "").toLowerCase();
                    const date = new Date(s.occurred_at).toLocaleString().toLowerCase();
                    return receipt.includes(q) || amt.includes(q) || date.includes(q);
                  });

                  if (filteredSales.length === 0) {
                    return (
                      <p style={{ textAlign: "center", color: "var(--ink-secondary, #6b7280)", padding: "20px 0" }}>
                        No matching sales found for &ldquo;{searchQuery}&rdquo;.
                      </p>
                    );
                  }

                  return (
                    <ul className={styles.list}>
                      {filteredSales.map((sale) => (
                        <li
                          key={sale.id}
                          className={styles.row}
                          onClick={() => setSelectedSaleAudit(sale)}
                          style={{ cursor: "pointer", transition: "background 0.15s ease" }}
                          title="Click to view staff audit and waybill details"
                        >
                          <span className={styles.rowMain}>
                            <span
                              className={styles.rowName}
                              style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}
                            >
                              <SaleIcon size={16} style={{ color: "var(--leaf)", flexShrink: 0 }} />
                              <span>{sale.receipt_number}</span>
                            </span>
                            <span className={styles.rowMeta}>
                              {new Date(sale.occurred_at).toLocaleString()}
                              {sale.payment_status ? ` - ${sale.payment_status.toLowerCase()}` : ""}
                              <span style={{ color: "var(--leaf, #238636)", marginLeft: "8px", fontWeight: 600 }}>
                                Audit Staff &rsaquo;
                              </span>
                            </span>
                          </span>
                          <span className={styles.rowEnd}>
                            <Pill tone={sale.cancelled_at ? "bad" : "good"}>
                              {formatMoney(sale.total_amount, currency)}
                            </Pill>
                          </span>
                        </li>
                      ))}
                    </ul>
                  );
                })()}
            </Card>
          </>
        ) : null}
      </>
    ) : (
      /* EXPENSES TAB */
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <div>
            <h2 style={{ fontSize: "16px", fontWeight: 800, margin: 0 }}>Logged Business Expenses</h2>
            <p style={{ fontSize: "13px", color: "var(--ink-secondary)", margin: "2px 0 0" }}>
              Total Expenses: <strong>{formatMoney(totalExpenses.toFixed(2), currency)}</strong>
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowExpenseModal(true)}
            style={{
              padding: "8px 16px",
              borderRadius: "8px",
              border: "none",
              background: "var(--leaf, #238636)",
              color: "#fff",
              fontWeight: 700,
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            + Log Expense
          </button>
        </div>

        {allExpenses.length === 0 ? (
          <Empty>No expenses recorded yet. Tap "+ Log Expense" to record rent, transport, or fuel.</Empty>
        ) : (
          <Card title={`${allExpenses.length} expenses`}>
            <ul className={styles.list}>
              {allExpenses.map((exp) => (
                <li key={exp.id} className={styles.row}>
                  <span className={styles.rowMain}>
                    <span className={styles.rowName}>
                      {exp.category.replace(/_/g, " ")}
                    </span>
                    <span className={styles.rowMeta}>
                      {exp.description ? `${exp.description} \u2022 ` : ""}
                      {new Date(exp.incurred_at).toLocaleString()} via {(exp.payment_method || "CASH").toUpperCase()}
                    </span>
                  </span>
                  <span className={styles.rowEnd}>
                    <Pill tone={exp.is_reversed ? "bad" : "warn"}>
                      {exp.is_reversed ? "REVERSED" : formatMoney(exp.amount, currency)}
                    </Pill>
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    )}

      {/* Sale Detail & Audit Sheet Dialog */}
      <Sheet
        open={selectedSaleAudit !== null}
        title={selectedSaleAudit ? `Transaction Audit - #${selectedSaleAudit.receipt_number}` : "Sale Audit"}
        onClose={() => setSelectedSaleAudit(null)}
      >
        {selectedSaleAudit ? (() => {
          const isCancelled = Boolean(selectedSaleAudit.cancelled_at);
          const linkedList = customerLists.find(
            (l) =>
              l.id === selectedSaleAudit.receipt_number.replace(/^RCP-/, "") ||
              selectedSaleAudit.receipt_number.includes(l.id.slice(0, 8)) ||
              (selectedSaleAudit.receipt_number.startsWith("PAY-") && selectedSaleAudit.receipt_number.slice(4).startsWith(l.id.slice(0, 8))) ||
              l.lines.some((line) => line.id === selectedSaleAudit.id)
          );

          const authorName = [userProfile?.first_name, userProfile?.last_name].filter(Boolean).join(" ") || "Account Owner / Staff";
          const authorPhone = userProfile?.phone || userProfile?.email || "Terminal Device";

          return (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {/* Total & Status Box */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "16px",
                  borderRadius: "12px",
                  border: isCancelled ? "1px solid #f87171" : "1px solid #238636",
                  background: isCancelled ? "rgba(248,113,113,0.08)" : "rgba(35,134,54,0.08)",
                }}
              >
                <div>
                  <div style={{ fontSize: "11px", fontWeight: 700, color: "var(--ink-secondary, #6b7280)", letterSpacing: "0.5px" }}>
                    TOTAL AMOUNT
                  </div>
                  <div style={{ fontSize: "24px", fontWeight: 800, color: isCancelled ? "#f87171" : "var(--leaf, #238636)", marginTop: "4px" }}>
                    {formatMoney(selectedSaleAudit.total_amount, currency)}
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--ink-secondary, #6b7280)", marginTop: "2px" }}>
                    {new Date(selectedSaleAudit.occurred_at).toLocaleString()}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <Pill tone={isCancelled ? "bad" : "good"}>
                    {isCancelled ? "RETURNED / VOIDED" : selectedSaleAudit.payment_status.toUpperCase()}
                  </Pill>
                </div>
              </div>

              {/* Staff Accountability & Confirmation Section */}
              <div
                style={{
                  padding: "14px",
                  borderRadius: "10px",
                  border: "1px solid var(--border, #e5e7eb)",
                  background: "var(--paper, #fff)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", fontWeight: 800, color: "var(--ink, #111)", marginBottom: "10px", letterSpacing: "0.5px" }}>
                  <SearchIcon size={14} /> STAFF & CONFIRMATION AUDIT
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border, #f3f4f6)", fontSize: "13px" }}>
                  <span style={{ color: "var(--ink-secondary, #6b7280)" }}>Recorded / Sold By</span>
                  <span style={{ fontWeight: 700, color: "#1f6feb" }}>{authorName} ({authorPhone})</span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border, #f3f4f6)", fontSize: "13px" }}>
                  <span style={{ color: "var(--ink-secondary, #6b7280)" }}>Confirmed By</span>
                  <span style={{ fontWeight: 700, color: "#238636" }}>
                    {linkedList?.status === "confirmed" ? "Owner / Manager (PIN Verified)" : "Direct Register Sale"}
                  </span>
                </div>

                {linkedList ? (
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border, #f3f4f6)", fontSize: "13px" }}>
                    <span style={{ color: "var(--ink-secondary, #6b7280)" }}>Customer</span>
                    <span style={{ fontWeight: 700, color: "var(--ink, #111)" }}>
                      {linkedList.customer_name || linkedList.customer_phone || "Customer"} ({linkedList.customer_phone || "No phone"})
                    </span>
                  </div>
                ) : null}

                {isCancelled ? (
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", fontSize: "13px" }}>
                    <span style={{ color: "#cf222e" }}>Voided / Returned At</span>
                    <span style={{ fontWeight: 700, color: "#cf222e" }}>
                      {new Date(selectedSaleAudit.cancelled_at!).toLocaleString()}
                    </span>
                  </div>
                ) : null}
              </div>

              {/* Waybill & Logistics Section (if available) */}
              {linkedList && (linkedList.waybill_number || linkedList.transporter_name) ? (
                <div
                  style={{
                    padding: "14px",
                    borderRadius: "10px",
                    border: "1px solid var(--border, #e5e7eb)",
                    background: "var(--paper, #fff)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", fontWeight: 800, color: "#d97706", marginBottom: "10px", letterSpacing: "0.5px" }}>
                    <TruckIcon size={14} /> WAYBILL & LOGISTICS DISPATCH
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
                    <span style={{ color: "var(--ink-secondary, #6b7280)" }}>Carrier / Transporter</span>
                    <span style={{ fontWeight: 700 }}>{linkedList.transporter_name || "Motor Carrier / Courier"}</span>
                  </div>

                  {linkedList.transporter_phone ? (
                    <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
                      <span style={{ color: "var(--ink-secondary, #6b7280)" }}>Carrier Contact</span>
                      <a href={`tel:${linkedList.transporter_phone}`} style={{ fontWeight: 700, color: "#1f6feb", textDecoration: "none" }}>
                        {linkedList.transporter_phone} (Call)
                      </a>
                    </div>
                  ) : null}

                  <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
                    <span style={{ color: "var(--ink-secondary, #6b7280)" }}>Waybill / Receipt #</span>
                    <span style={{ fontWeight: 700, color: "#238636" }}>{linkedList.waybill_number || "Pending receipt"}</span>
                  </div>

                  {linkedList.dispatch_cost ? (
                    <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
                      <span style={{ color: "var(--ink-secondary, #6b7280)" }}>Waybill Cost</span>
                      <span style={{ fontWeight: 700 }}>{formatMoney(linkedList.dispatch_cost, currency)}</span>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {/* Sold Lines Breakdown */}
              {linkedList && linkedList.lines && linkedList.lines.filter((l) => l.note !== "heading").length > 0 ? (
                <div
                  style={{
                    padding: "14px",
                    borderRadius: "10px",
                    border: "1px solid var(--border, #e5e7eb)",
                    background: "var(--paper, #fff)",
                  }}
                >
                  <div style={{ fontSize: "12px", fontWeight: 800, color: "var(--ink, #111)", marginBottom: "8px", letterSpacing: "0.5px" }}>
                    SOLD ITEMS & QUANTITIES
                  </div>
                  {linkedList.lines
                    .filter((l) => l.note !== "heading")
                    .map((line, lIdx) => (
                      <div
                        key={line.id || lIdx}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          padding: "6px 0",
                          borderBottom: lIdx < linkedList.lines.length - 1 ? "1px solid var(--border, #f3f4f6)" : "none",
                          fontSize: "13px",
                        }}
                      >
                        <div>
                          <div style={{ fontWeight: 600 }}>{line.product_name || line.free_text || "Item"}</div>
                          <div style={{ fontSize: "11px", color: "var(--ink-secondary, #6b7280)" }}>
                            Qty: {line.quantity} {line.unit || "pcs"} &bull; Unit: {formatMoney(line.shop_price || "0", currency)}
                          </div>
                        </div>
                        <div style={{ fontWeight: 700, color: "var(--leaf, #238636)" }}>
                          {formatMoney(line.line_total || (Number(line.shop_price || 0) * Number(line.quantity || 1)).toString(), currency)}
                        </div>
                      </div>
                    ))}
                </div>
              ) : null}

              {/* Quick Actions */}
              <div style={{ display: "flex", gap: "10px", marginTop: "8px" }}>
                <button
                  type="button"
                  onClick={() => window.print()}
                  style={{
                    flex: 1,
                    padding: "10px 16px",
                    borderRadius: "8px",
                    border: "none",
                    background: "var(--leaf, #238636)",
                    color: "#fff",
                    fontWeight: 700,
                    fontSize: "13px",
                    cursor: "pointer",
                  }}
                >
                  Print / Save Invoice
                </button>
                {linkedList?.customer_phone ? (
                  <a
                    href={`https://wa.me/${linkedList.customer_phone.replace(/[^\d]/g, "")}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      flex: 1,
                      padding: "10px 16px",
                      borderRadius: "8px",
                      border: "none",
                      background: "#1f6feb",
                      color: "#fff",
                      fontWeight: 700,
                      fontSize: "13px",
                      textAlign: "center",
                      textDecoration: "none",
                    }}
                  >
                    WhatsApp Customer
                  </a>
                ) : null}
              </div>
            </div>
          );
        })() : null}
      </Sheet>

      {/* Log Expense Sheet */}
      <Sheet open={showExpenseModal} title="Log Business Expense" onClose={() => setShowExpenseModal(false)}>
        <Field
          label="Amount Spent"
          id="exp-amount"
          value={expenseAmount}
          onChange={setExpenseAmount}
          placeholder="5000.00"
          inputMode="decimal"
        />
        <Select
          label="Expense Category"
          id="exp-cat"
          value={expenseCategory}
          onChange={(val) => setExpenseCategory(val as ExpenseCategoryCode)}
          options={
            expenseCategories.length > 0
              ? expenseCategories.map((c) => ({ value: c.value, label: c.label }))
              : [
                  { value: "STOCK_PURCHASE", label: "Stock Purchase" },
                  { value: "TRANSPORT", label: "Transport & Logistics" },
                  { value: "RENT", label: "Stall Rent & Space" },
                  { value: "UTILITIES", label: "Generator Fuel & Light" },
                  { value: "SALARIES", label: "Staff & Apprentice Pay" },
                  { value: "PACKAGING", label: "Nylon & Packaging" },
                  { value: "MARKETING", label: "Marketing & Ads" },
                  { value: "MAINTENANCE", label: "Repairs & Maintenance" },
                ]
          }
        />
        <Field
          label="Note / Description (Optional)"
          id="exp-desc"
          value={expenseDescription}
          onChange={setExpenseDescription}
          placeholder="Fuel for generator, motor park loading..."
          optional
        />
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button type="button" className={styles.secondaryBtn} onClick={() => setShowExpenseModal(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={handleLogExpense}
            disabled={savingExpense || !expenseAmount.trim()}
          >
            {savingExpense ? "Saving..." : "Record Expense"}
          </button>
        </div>
      </Sheet>

      {notice ? <Toast message={notice} tone="bad" onDismiss={() => setNotice(null)} /> : null}
    </main>
  );
}
