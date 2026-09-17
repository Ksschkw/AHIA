/**
 * Formatting, in one place so a number never renders two ways on two screens.
 *
 * Money arrives from the API as a decimal string ("45000.00") precisely so that no float rounding
 * happens in transit. It is formatted with `Intl` rather than by string surgery, which is what makes
 * the currency symbol, the grouping and the decimals follow the business's own currency instead of
 * the developer's assumption.
 */

const DEFAULT_CURRENCY = "NGN";

/**
 * A price that may not exist yet, said in words.
 *
 * An item with no price of its own follows its group, and a group may have no price either - so a
 * price can genuinely be absent. Showing nothing looks like a rendering fault and showing zero is a
 * lie about money, so it says that a price is to be asked for.
 */
export function formatMoneyOrOnRequest(
  amount: string | number | null | undefined,
  currency: string = DEFAULT_CURRENCY,
): string {
  if (amount === null || amount === undefined || amount === "") {
    return "Price on request";
  }
  return formatMoney(amount, currency);
}

export function formatMoney(amount: string | number, currency: string = DEFAULT_CURRENCY): string {
  const value = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(value)) {
    return String(amount);
  }
  try {
    return new Intl.NumberFormat("en-NG", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    // An unknown currency code must not break a screen; the number still matters.
    return `${currency} ${value.toFixed(2)}`;
  }
}

/** Quantities carry three decimals in the API and are read by a person with no use for them. */
export function formatQuantity(quantity: string | number): string {
  const value = typeof quantity === "string" ? Number(quantity) : quantity;
  if (!Number.isFinite(value)) {
    return String(quantity);
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

export function formatCount(count: number): string {
  return new Intl.NumberFormat("en-NG").format(count);
}
