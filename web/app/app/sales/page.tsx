"use client";

/**
 * What has been sold.
 *
 * The second of two destinations that led nowhere until now - the frame has offered "Sales" since it was built
 * and the page behind it did not exist, so tapping it gave a 404. It reads the same sales the dashboard
 * summarises, and it shows what is already in the browser **before** it asks, so arriving here is instant.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SaleIcon } from "@/components/icons";
import { EmptySalesIllustration } from "@/components/illustrations";
import { Card, Empty, Loading, Pill, Toast } from "@/components/ui";
import {
  cachedRead,
  firstPaint,
  rememberedBusinessId,
  currentUser,
  dailySales,
  getBusiness,
  listBusinesses,
  listProducts,
  listSales,
  type DailySalesSummary,
  type Product,
  type SaleSummary,
  type Tenant,
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
  const [dailySummary, setDailySummary] = useState<DailySalesSummary | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [currency, setCurrency] = useState("NGN");
  const [state, setState] = useState<"loading" | "ready">(() =>
    rememberedBusinessId() ? "ready" : "loading",
  );
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async (tenantId: string) => {
    const [found, summary, prods] = await Promise.all([
      listSales(tenantId, "50"),
      dailySales(tenantId).catch(() => null),
      listProducts(tenantId).catch(() => []),
    ]);
    setSales(found);
    setDailySummary(summary);
    setProducts(prods);
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
        setBusiness(detail);
        setCurrency(detail.currency);
        // What the browser already holds, painted before anything is asked for.
        const rememberedSales = cachedRead<SaleSummary[]>(`/api/v1/tenants/${chosen.id}/sales`);
        if (rememberedSales) {
          setSales(rememberedSales);
          setState("ready");
        }
        await load(chosen.id);
      } catch (error) {
        setNotice("We could not fetch your sales. Pull down to try again.");
      }
    })();
  }, [load]);

  const total = useMemo(
    () => (sales ?? []).reduce((running, sale) => running + Number(sale.total_amount ?? "0"), 0),
    [sales],
  );

  const profitMetrics = useMemo(
    () => calculateProfitMetrics({ revenue: total, products }),
    [total, products],
  );

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Sales</h1>
      <p className={styles.lede}>
        Everything you have sold, newest first. {sales ? `${sales.length} so far` : ""}
      </p>

      {state === "loading" ? <Loading label="Fetching your sales..." /> : null}
      {state === "ready" && (sales ?? []).length === 0 ? (
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

      {(sales ?? []).length > 0 ? (
        <>
          <SalesTimelineChart
            days={dailySummary?.days ?? []}
            sales={sales ?? []}
            currency={currency}
            marginRatio={
              profitMetrics.revenue > 0 ? profitMetrics.grossProfit / profitMetrics.revenue : 0.28
            }
          />
          <Card title={`${sales?.length ?? 0} sales`}>
            <p className={styles.totalPreview}>
              {formatMoney(total.toFixed(2), currency)} in total | Est. Profit:{" "}
              <strong style={{ color: "var(--leaf, #238636)" }}>
                {formatMoney(profitMetrics.grossProfit.toFixed(2), currency)}
              </strong>{" "}
              ({profitMetrics.marginPercent}%)
            </p>
            <ul className={styles.list}>
            {(sales ?? []).map((sale) => (
              <li key={sale.id} className={styles.row}>
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
        </Card>
      </>
    ) : null}

      {notice ? <Toast message={notice} tone="bad" onDismiss={() => setNotice(null)} /> : null}
    </main>
  );
}
