"use client";

import { useMemo, useState } from "react";
import type { SaleSummary } from "@/lib/api";
import { formatMoney } from "@/lib/format";

export interface TimelineDay {
  dateStr: string;
  dayLabel: string;
  shortDate: string;
  fullDate: string;
  revenue: number;
  saleCount: number;
  profit: number;
  isToday: boolean;
}

interface SalesTimelineChartProps {
  days?: Array<{ sold_on: string; revenue: string; sale_count: number }>;
  sales?: SaleSummary[];
  currency?: string;
  marginRatio?: number;
}

function getLocalDateString(d: Date = new Date()): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatCompact(amount: number, currency = "NGN"): string {
  const symbol = currency === "USD" ? "$" : currency === "GBP" ? "\u00A3" : currency === "EUR" ? "\u20AC" : "\u20A6";
  if (amount >= 1_000_000) {
    return `${symbol}${(amount / 1_000_000).toFixed(1)}M`;
  }
  if (amount >= 1_000) {
    return `${symbol}${(amount / 1_000).toFixed(0)}k`;
  }
  return `${symbol}${amount.toLocaleString()}`;
}

export function SalesTimelineChart({
  days = [],
  sales = [],
  currency = "NGN",
  marginRatio = 0.28,
}: SalesTimelineChartProps) {
  const [periodDays, setPeriodDays] = useState<7 | 14 | 30>(7);
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);

  const timelineData = useMemo<TimelineDay[]>(() => {
    const today = new Date();
    const todayStr = getLocalDateString(today);
    const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

    // Remote map
    const remoteMap = new Map<string, { revenue: number; saleCount: number }>();
    for (const d of days) {
      remoteMap.set(d.sold_on, {
        revenue: Number(d.revenue || 0),
        saleCount: Number(d.sale_count || 0),
      });
    }

    // Local sales map
    const localMap = new Map<string, { revenue: number; saleCount: number }>();
    for (const s of sales) {
      if (!s.occurred_at || s.cancelled_at || s.payment_status === "cancelled") continue;
      const d = new Date(s.occurred_at);
      if (Number.isNaN(d.getTime())) continue;
      const sDate = getLocalDateString(d);
      const curr = localMap.get(sDate) || { revenue: 0, saleCount: 0 };
      curr.revenue += Number(s.total_amount || 0);
      curr.saleCount += 1;
      localMap.set(sDate, curr);
    }

    const result: TimelineDay[] = [];
    for (let i = periodDays - 1; i >= 0; i--) {
      const target = new Date();
      target.setDate(today.getDate() - i);
      const dateStr = getLocalDateString(target);
      const isToday = dateStr === todayStr;

      const remote = remoteMap.get(dateStr);
      const local = localMap.get(dateStr);

      const revenue = Math.max(remote?.revenue || 0, local?.revenue || 0);
      const saleCount = Math.max(remote?.saleCount || 0, local?.saleCount || 0);
      const profit = Math.max(0, revenue * marginRatio);

      const dayLabel = isToday ? "Today" : dayNames[target.getDay()];
      const shortDate = `${target.getDate()} ${monthNames[target.getMonth()]}`;
      const fullDate = `${dayNames[target.getDay()]}, ${target.getDate()} ${monthNames[target.getMonth()]}`;

      result.push({
        dateStr,
        dayLabel,
        shortDate,
        fullDate,
        revenue,
        saleCount,
        profit,
        isToday,
      });
    }

    return result;
  }, [days, sales, periodDays, marginRatio]);

  const activeDay = useMemo(() => {
    if (hoveredDate) {
      const found = timelineData.find((d) => d.dateStr === hoveredDate);
      if (found) return found;
    }
    return timelineData[timelineData.length - 1];
  }, [timelineData, hoveredDate]);

  const aggregateMetrics = useMemo(() => {
    let totalRev = 0;
    let totalSales = 0;
    let maxRev = 0;

    for (const d of timelineData) {
      totalRev += d.revenue;
      totalSales += d.saleCount;
      if (d.revenue > maxRev) {
        maxRev = d.revenue;
      }
    }

    const totalProfit = Math.max(0, totalRev * marginRatio);
    const avgDailyRev = timelineData.length > 0 ? totalRev / timelineData.length : 0;

    return {
      totalRev,
      totalSales,
      totalProfit,
      avgDailyRev,
      maxRev: Math.max(maxRev, 100),
    };
  }, [timelineData, marginRatio]);

  return (
    <section
      style={{
        background: "var(--paper, #ffffff)",
        border: "1px solid var(--border, #e5e7eb)",
        borderRadius: "16px",
        padding: "20px",
        marginBottom: "20px",
        boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
      }}
    >
      {/* Top Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          marginBottom: "16px",
        }}
      >
        <div>
          <h2
            style={{
              fontSize: "17px",
              fontWeight: 700,
              color: "var(--ink, #111827)",
              margin: 0,
              letterSpacing: "-0.01em",
            }}
          >
            Sales & Profit Progress Timeline
          </h2>
          <p
            style={{
              fontSize: "12px",
              color: "var(--ink-secondary, #6b7280)",
              margin: "3px 0 0 0",
            }}
          >
            Daily revenue and estimated profit trend over the past {periodDays} days
          </p>
        </div>

        {/* Timeframe Buttons */}
        <div style={{ display: "inline-flex", gap: "6px" }}>
          {([7, 14, 30] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriodDays(p)}
              style={{
                padding: "6px 12px",
                borderRadius: "8px",
                fontSize: "12px",
                fontWeight: periodDays === p ? 700 : 500,
                cursor: "pointer",
                border: "1px solid",
                borderColor: periodDays === p ? "var(--leaf, #238636)" : "var(--border, #e5e7eb)",
                background: periodDays === p ? "var(--leaf, #238636)" : "transparent",
                color: periodDays === p ? "#ffffff" : "var(--ink, #374151)",
                transition: "all 0.15s ease",
              }}
            >
              {p} Days
            </button>
          ))}
        </div>
      </div>

      {/* Aggregate KPI Strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
          gap: "10px",
          background: "var(--wash, #f9fafb)",
          border: "1px solid var(--border, #e5e7eb)",
          borderRadius: "12px",
          padding: "12px 16px",
          marginBottom: "20px",
        }}
      >
        <div>
          <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--ink-secondary, #6b7280)", textTransform: "uppercase" }}>
            Total Revenue
          </div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--ink, #111827)", marginTop: "2px" }}>
            {formatCompact(aggregateMetrics.totalRev, currency)}
          </div>
        </div>

        <div>
          <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--ink-secondary, #6b7280)", textTransform: "uppercase" }}>
            Est. Net Profit
          </div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--leaf, #238636)", marginTop: "2px" }}>
            {formatCompact(aggregateMetrics.totalProfit, currency)}
          </div>
        </div>

        <div>
          <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--ink-secondary, #6b7280)", textTransform: "uppercase" }}>
            Completed Sales
          </div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--ink, #111827)", marginTop: "2px" }}>
            {aggregateMetrics.totalSales} transactions
          </div>
        </div>

        <div>
          <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--ink-secondary, #6b7280)", textTransform: "uppercase" }}>
            Daily Average
          </div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--ink, #111827)", marginTop: "2px" }}>
            {formatCompact(aggregateMetrics.avgDailyRev, currency)}
          </div>
        </div>
      </div>

      {/* Interactive Chart Container */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: periodDays === 30 ? "4px" : "10px",
          height: "150px",
          padding: "10px 4px 0 4px",
          borderBottom: "1px solid var(--border, #e5e7eb)",
          overflowX: "auto",
        }}
      >
        {timelineData.map((day) => {
          const isSelected = activeDay?.dateStr === day.dateStr;
          const revHeight = Math.max(
            6,
            Math.min(100, Math.round((day.revenue / aggregateMetrics.maxRev) * 100))
          );
          const profitHeight = Math.max(
            3,
            Math.min(revHeight, Math.round((day.profit / aggregateMetrics.maxRev) * 100))
          );

          return (
            <div
              key={day.dateStr}
              onMouseEnter={() => setHoveredDate(day.dateStr)}
              onClick={() => setHoveredDate(day.dateStr)}
              style={{
                flex: 1,
                minWidth: periodDays === 30 ? "16px" : "28px",
                maxWidth: "60px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                height: "100%",
                justifyContent: "flex-end",
                cursor: "pointer",
                padding: "2px",
                borderRadius: "6px",
                background: isSelected ? "rgba(35, 134, 54, 0.08)" : "transparent",
                transition: "background 0.15s ease",
              }}
            >
              {/* Bar Column Track */}
              <div
                style={{
                  width: periodDays === 30 ? "10px" : "18px",
                  height: "105px",
                  background: "var(--wash, #f3f4f6)",
                  borderRadius: "6px",
                  overflow: "hidden",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "flex-end",
                  position: "relative",
                }}
              >
                {day.revenue > 0 ? (
                  <div
                    style={{
                      width: "100%",
                      height: `${revHeight}%`,
                      background: "var(--leaf, #238636)",
                      borderRadius: "6px",
                      position: "relative",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "flex-end",
                    }}
                  >
                    {/* Profit layer */}
                    <div
                      style={{
                        width: "100%",
                        height: `${(profitHeight / revHeight) * 100}%`,
                        background: "#3fb950",
                        borderTopLeftRadius: "4px",
                        borderTopRightRadius: "4px",
                      }}
                    />
                  </div>
                ) : (
                  <div
                    style={{
                      height: "3px",
                      width: "100%",
                      background: "var(--border, #cbd5e1)",
                    }}
                  />
                )}
              </div>

              {/* Day Label */}
              <div
                style={{
                  fontSize: periodDays === 30 ? "9px" : "11px",
                  fontWeight: day.isToday ? 700 : 500,
                  color: day.isToday ? "var(--leaf, #238636)" : "var(--ink-secondary, #6b7280)",
                  marginTop: "6px",
                  whiteSpace: "nowrap",
                }}
              >
                {day.dayLabel}
              </div>
            </div>
          );
        })}
      </div>

      {/* Active Day Detail Card */}
      {activeDay && (
        <div
          style={{
            marginTop: "16px",
            padding: "12px 16px",
            borderRadius: "12px",
            background: "var(--wash, #f9fafb)",
            border: "1px solid var(--border, #e5e7eb)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "12px",
          }}
        >
          <div>
            <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--ink, #111827)" }}>
              {activeDay.fullDate} {activeDay.isToday ? "(Today)" : ""}
            </div>
            <div style={{ fontSize: "12px", color: "var(--ink-secondary, #6b7280)", marginTop: "2px" }}>
              {activeDay.saleCount} completed sales
            </div>
          </div>

          <div style={{ display: "flex", gap: "24px" }}>
            <div>
              <div style={{ fontSize: "11px", color: "var(--ink-secondary, #6b7280)", fontWeight: 600 }}>REVENUE</div>
              <div style={{ fontSize: "15px", fontWeight: 700, color: "var(--ink, #111827)" }}>
                {formatMoney(activeDay.revenue.toFixed(2), currency)}
              </div>
            </div>

            <div>
              <div style={{ fontSize: "11px", color: "var(--ink-secondary, #6b7280)", fontWeight: 600 }}>EST. PROFIT</div>
              <div style={{ fontSize: "15px", fontWeight: 700, color: "var(--leaf, #238636)" }}>
                {formatMoney(activeDay.profit.toFixed(2), currency)}
              </div>
            </div>

            <div>
              <div style={{ fontSize: "11px", color: "var(--ink-secondary, #6b7280)", fontWeight: 600 }}>MARGIN</div>
              <div style={{ fontSize: "15px", fontWeight: 700, color: "var(--ink, #111827)" }}>
                {activeDay.revenue > 0 ? `${Math.round(marginRatio * 100)}%` : "0%"}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
