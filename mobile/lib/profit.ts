/**
 * Profit and margin calculation for Ahia trader business.
 *
 * Computes gross profit, expenses, and net take-home profit based on
 * catalog cost prices, customer list margins, and logged expenses.
 */

export interface ProfitMetrics {
  revenue: number;
  costOfGoods: number;
  grossProfit: number;
  expenses: number;
  netProfit: number;
  marginPercent: number;
  hasCustomCosts: boolean;
}

export function calculateProfitMetrics(options: {
  revenue: number;
  products?: Array<{ selling_price?: string | null; cost_price?: string | null }>;
  expenses?: Array<{ amount: string; incurred_at?: string; is_reversed?: boolean }>;
  todayStr?: string;
}): ProfitMetrics {
  const { revenue, products = [], expenses = [], todayStr } = options;

  // Determine average margin across catalog items with configured cost prices
  const validProducts = products.filter((p) => {
    const s = Number(p.selling_price || 0);
    const c = Number(p.cost_price || 0);
    return s > 0 && c > 0 && s >= c;
  });

  const hasCustomCosts = validProducts.length > 0;
  let marginRatio = 0.28; // Default 28% typical retail markup if no product costs entered

  if (hasCustomCosts) {
    const sumMargins = validProducts.reduce((acc, p) => {
      const s = Number(p.selling_price);
      const c = Number(p.cost_price);
      return acc + (s - c) / s;
    }, 0);
    marginRatio = sumMargins / validProducts.length;
  }

  const grossProfit = Math.max(0, revenue * marginRatio);
  const costOfGoods = Math.max(0, revenue - grossProfit);

  // Filter expenses (if todayStr is provided, only include expenses from that day)
  const filteredExpenses = expenses.filter((e) => {
    if (e.is_reversed) return false;
    if (todayStr && e.incurred_at) {
      return e.incurred_at.slice(0, 10) === todayStr;
    }
    return true;
  });

  const totalExpenses = filteredExpenses.reduce((sum, e) => sum + (Number(e.amount) || 0), 0);
  const netProfit = grossProfit - totalExpenses;
  const marginPercent = revenue > 0 ? (netProfit / revenue) * 100 : 0;

  return {
    revenue,
    costOfGoods,
    grossProfit,
    expenses: totalExpenses,
    netProfit,
    marginPercent: Math.round(marginPercent * 10) / 10,
    hasCustomCosts,
  };
}
