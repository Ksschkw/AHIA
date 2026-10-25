import React, { useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
} from "react-native";
import * as Haptics from "expo-haptics";
import type { SaleSummary } from "@/lib/api";
import { getLocalDateString } from "@/lib/db";

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
  isDarkMode?: boolean;
}

function formatAmount(amount: number, currency = "NGN"): string {
  const symbol = currency === "USD" ? "$" : currency === "GBP" ? "\u00A3" : currency === "EUR" ? "\u20AC" : "\u20A6";
  if (amount >= 1_000_000) {
    return `${symbol}${(amount / 1_000_000).toFixed(1)}M`;
  }
  if (amount >= 1_000) {
    return `${symbol}${(amount / 1_000).toFixed(0)}k`;
  }
  return `${symbol}${amount.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function formatFullMoney(amount: number, currency = "NGN"): string {
  const symbol = currency === "USD" ? "$" : currency === "GBP" ? "\u00A3" : currency === "EUR" ? "\u20AC" : "\u20A6";
  return `${symbol}${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function SalesTimelineChart({
  days = [],
  sales = [],
  currency = "NGN",
  marginRatio = 0.28,
  isDarkMode = false,
}: SalesTimelineChartProps) {
  const [periodDays, setPeriodDays] = useState<7 | 14 | 30>(7);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const timelineData = useMemo<TimelineDay[]>(() => {
    const today = new Date();
    const todayStr = getLocalDateString(today);
    const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

    // Build map of remote days
    const remoteMap = new Map<string, { revenue: number; saleCount: number }>();
    for (const d of days) {
      remoteMap.set(d.sold_on, {
        revenue: Number(d.revenue || 0),
        saleCount: Number(d.sale_count || 0),
      });
    }

    // Build map of local sales
    const localMap = new Map<string, { revenue: number; saleCount: number }>();
    for (const s of sales) {
      if (!s.created_at || s.cancelled_at || s.payment_status === "cancelled") continue;
      const d = new Date(s.created_at);
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

  // Selected Day Details (defaults to today or selected)
  const activeDay = useMemo(() => {
    if (selectedDate) {
      const found = timelineData.find((d) => d.dateStr === selectedDate);
      if (found) return found;
    }
    // Default to today or the latest day with sales
    return timelineData[timelineData.length - 1];
  }, [timelineData, selectedDate]);

  // Aggregate metrics for the whole period
  const aggregateMetrics = useMemo(() => {
    let totalRev = 0;
    let totalSales = 0;
    let maxRev = 0;
    let peakDay: TimelineDay | null = null;

    for (const d of timelineData) {
      totalRev += d.revenue;
      totalSales += d.saleCount;
      if (d.revenue > maxRev) {
        maxRev = d.revenue;
        peakDay = d;
      }
    }

    const totalProfit = Math.max(0, totalRev * marginRatio);
    const avgDailyRev = timelineData.length > 0 ? totalRev / timelineData.length : 0;

    return {
      totalRev,
      totalSales,
      totalProfit,
      avgDailyRev,
      maxRev: Math.max(maxRev, 100), // Avoid division by zero
      peakDay,
    };
  }, [timelineData, marginRatio]);

  const colors = {
    bg: isDarkMode ? "#161b22" : "#ffffff",
    cardBg: isDarkMode ? "#0d1117" : "#f6f8fa",
    border: isDarkMode ? "#30363d" : "#e1e4e8",
    textPrimary: isDarkMode ? "#f0f6fc" : "#1f2328",
    textSecondary: isDarkMode ? "#8b949e" : "#656d76",
    barBg: isDarkMode ? "#21262d" : "#eaeef2",
    barRev: "#238636",
    barProfit: "#3fb950",
    activeOutline: "#1f883d",
  };

  return (
    <View style={[styles.container, { backgroundColor: colors.bg, borderColor: colors.border }]}>
      {/* Header with Title and Period Filter Buttons */}
      <View style={styles.headerRow}>
        <View>
          <Text style={[styles.title, { color: colors.textPrimary }]}>Sales & Profit Timeline</Text>
          <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
            {periodDays}-day performance & progress
          </Text>
        </View>

        <View style={styles.periodPills}>
          {([7, 14, 30] as const).map((p) => (
            <Pressable
              key={p}
              style={[
                styles.periodPill,
                periodDays === p && styles.periodPillActive,
                { borderColor: colors.border },
              ]}
              onPress={() => {
                void Haptics.selectionAsync();
                setPeriodDays(p);
              }}
            >
              <Text
                style={[
                  styles.periodPillText,
                  periodDays === p && styles.periodPillTextActive,
                ]}
              >
                {p}d
              </Text>
            </Pressable>
          ))}
        </View>
      </View>

      {/* Aggregate Metrics Ribbon */}
      <View style={[styles.metricsRibbon, { backgroundColor: colors.cardBg, borderColor: colors.border }]}>
        <View style={styles.metricItem}>
          <Text style={[styles.metricLabel, { color: colors.textSecondary }]}>Revenue</Text>
          <Text style={[styles.metricValue, { color: colors.textPrimary }]}>
            {formatAmount(aggregateMetrics.totalRev, currency)}
          </Text>
        </View>
        <View style={[styles.metricDivider, { backgroundColor: colors.border }]} />
        <View style={styles.metricItem}>
          <Text style={[styles.metricLabel, { color: colors.textSecondary }]}>Est. Profit</Text>
          <Text style={[styles.metricValue, { color: "#238636" }]}>
            {formatAmount(aggregateMetrics.totalProfit, currency)}
          </Text>
        </View>
        <View style={[styles.metricDivider, { backgroundColor: colors.border }]} />
        <View style={styles.metricItem}>
          <Text style={[styles.metricLabel, { color: colors.textSecondary }]}>Sales Count</Text>
          <Text style={[styles.metricValue, { color: colors.textPrimary }]}>
            {aggregateMetrics.totalSales}
          </Text>
        </View>
        <View style={[styles.metricDivider, { backgroundColor: colors.border }]} />
        <View style={styles.metricItem}>
          <Text style={[styles.metricLabel, { color: colors.textSecondary }]}>Daily Avg</Text>
          <Text style={[styles.metricValue, { color: colors.textPrimary }]}>
            {formatAmount(aggregateMetrics.avgDailyRev, currency)}
          </Text>
        </View>
      </View>

      {/* Interactive Bar Chart */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.chartScroll}
      >
        <View style={styles.barsContainer}>
          {timelineData.map((day) => {
            const isSelected = activeDay?.dateStr === day.dateStr;
            const revHeightPercent = Math.max(
              4,
              Math.min(100, Math.round((day.revenue / aggregateMetrics.maxRev) * 100))
            );
            const profitHeightPercent = Math.max(
              2,
              Math.min(revHeightPercent, Math.round((day.profit / aggregateMetrics.maxRev) * 100))
            );

            return (
              <Pressable
                key={day.dateStr}
                style={[
                  styles.barColumn,
                  isSelected && styles.barColumnActive,
                ]}
                onPress={() => {
                  void Haptics.selectionAsync();
                  setSelectedDate(day.dateStr);
                }}
              >
                {/* Visual Bar Track */}
                <View style={[styles.barTrack, { backgroundColor: colors.barBg }]}>
                  {day.revenue > 0 ? (
                    <View
                      style={[
                        styles.barFillRevenue,
                        { height: `${revHeightPercent}%` },
                      ]}
                    >
                      {/* Profit Highlight inside bar */}
                      <View
                        style={[
                          styles.barFillProfit,
                          { height: `${(profitHeightPercent / revHeightPercent) * 100}%` },
                        ]}
                      />
                    </View>
                  ) : (
                    <View style={styles.barZeroLine} />
                  )}
                </View>

                {/* Day Label & Date */}
                <Text
                  style={[
                    styles.barDayText,
                    { color: day.isToday ? "#238636" : colors.textPrimary },
                    day.isToday && styles.barDayTextToday,
                  ]}
                  numberOfLines={1}
                >
                  {day.dayLabel}
                </Text>
                <Text style={[styles.barDateText, { color: colors.textSecondary }]}>
                  {day.dateStr.slice(8, 10)}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </ScrollView>

      {/* Selected Day Breakdown Card */}
      {activeDay && (
        <View style={[styles.detailCard, { backgroundColor: colors.cardBg, borderColor: colors.border }]}>
          <View style={styles.detailHeader}>
            <Text style={[styles.detailDate, { color: colors.textPrimary }]}>
              {activeDay.fullDate} {activeDay.isToday ? "(Today)" : ""}
            </Text>
            <View style={styles.detailBadge}>
              <Text style={styles.detailBadgeText}>{activeDay.saleCount} sales</Text>
            </View>
          </View>

          <View style={styles.detailRow}>
            <View style={styles.detailCol}>
              <Text style={[styles.detailSubLabel, { color: colors.textSecondary }]}>Revenue</Text>
              <Text style={[styles.detailRevenue, { color: colors.textPrimary }]}>
                {formatFullMoney(activeDay.revenue, currency)}
              </Text>
            </View>

            <View style={styles.detailCol}>
              <Text style={[styles.detailSubLabel, { color: colors.textSecondary }]}>Estimated Profit</Text>
              <Text style={styles.detailProfit}>
                {formatFullMoney(activeDay.profit, currency)}
              </Text>
            </View>

            <View style={styles.detailCol}>
              <Text style={[styles.detailSubLabel, { color: colors.textSecondary }]}>Profit Margin</Text>
              <Text style={[styles.detailMargin, { color: colors.textPrimary }]}>
                {activeDay.revenue > 0 ? `${Math.round(marginRatio * 100)}%` : "0%"}
              </Text>
            </View>
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderRadius: 14,
    borderWidth: 1,
    padding: 14,
    marginVertical: 8,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  title: {
    fontSize: 16,
    fontWeight: "700",
    letterSpacing: -0.2,
  },
  subtitle: {
    fontSize: 12,
    marginTop: 2,
  },
  periodPills: {
    flexDirection: "row",
    gap: 4,
  },
  periodPill: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    borderWidth: 1,
  },
  periodPillActive: {
    backgroundColor: "#238636",
    borderColor: "#238636",
  },
  periodPillText: {
    fontSize: 11,
    fontWeight: "600",
    color: "#656d76",
  },
  periodPillTextActive: {
    color: "#ffffff",
    fontWeight: "700",
  },
  metricsRibbon: {
    flexDirection: "row",
    justifyContent: "space-around",
    alignItems: "center",
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    marginBottom: 12,
  },
  metricItem: {
    alignItems: "center",
  },
  metricLabel: {
    fontSize: 10,
    fontWeight: "600",
    textTransform: "uppercase",
    marginBottom: 2,
  },
  metricValue: {
    fontSize: 14,
    fontWeight: "700",
  },
  metricDivider: {
    width: 1,
    height: 22,
  },
  chartScroll: {
    paddingVertical: 6,
  },
  barsContainer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    minHeight: 120,
    paddingHorizontal: 4,
  },
  barColumn: {
    alignItems: "center",
    width: 38,
    paddingVertical: 4,
    borderRadius: 8,
  },
  barColumnActive: {
    backgroundColor: "rgba(35, 134, 54, 0.12)",
  },
  barTrack: {
    width: 18,
    height: 84,
    borderRadius: 6,
    overflow: "hidden",
    justifyContent: "flex-end",
    alignItems: "center",
    marginBottom: 6,
  },
  barFillRevenue: {
    width: "100%",
    backgroundColor: "#238636",
    borderRadius: 6,
    justifyContent: "flex-end",
  },
  barFillProfit: {
    width: "100%",
    backgroundColor: "#3fb950",
    borderTopLeftRadius: 4,
    borderTopRightRadius: 4,
  },
  barZeroLine: {
    width: 10,
    height: 3,
    backgroundColor: "#8b949e",
    borderRadius: 2,
    marginBottom: 2,
  },
  barDayText: {
    fontSize: 10,
    fontWeight: "600",
    marginTop: 2,
  },
  barDayTextToday: {
    fontWeight: "800",
  },
  barDateText: {
    fontSize: 9,
  },
  detailCard: {
    marginTop: 12,
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
  },
  detailHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  detailDate: {
    fontSize: 13,
    fontWeight: "700",
  },
  detailBadge: {
    backgroundColor: "#238636",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
  },
  detailBadgeText: {
    color: "#ffffff",
    fontSize: 10,
    fontWeight: "700",
  },
  detailRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
  detailCol: {
    flex: 1,
  },
  detailSubLabel: {
    fontSize: 10,
    marginBottom: 2,
  },
  detailRevenue: {
    fontSize: 13,
    fontWeight: "700",
  },
  detailProfit: {
    fontSize: 13,
    fontWeight: "700",
    color: "#238636",
  },
  detailMargin: {
    fontSize: 13,
    fontWeight: "700",
  },
});
