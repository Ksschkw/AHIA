"use client";

/**
 * A list, kept current while two people work on it.
 *
 * The customer adds a line while the trader is looking at it; the trader prices a line while the customer
 * is still on the page. Neither of them should have to refresh to find that out, so this asks again every
 * fifteen seconds - often enough to feel live, rarely enough not to matter on a market connection.
 *
 * **What it shows is the customer's view**: their lines, the shop's prices, and the total. What the goods
 * cost the trader never arrives here, because the API sends a different shape to this address - the
 * omission is structural, not a matter of remembering.
 */

import { useEffect, useState } from "react";

import { formatMoneyOrOnRequest } from "@/lib/format";
import type { PublicList } from "@/lib/server-api";
import styles from "./live-list.module.css";

const REFRESH_MS = 15_000;

const STATE_WORD: Record<string, string> = {
  somewhere: "Not looked at yet",
  have_it: "The shop has it",
  buy_it: "The shop is finding it",
  cannot_get: "The shop could not get it",
};

export function LiveList({
  initial,
  slug,
  token,
}: {
  initial: PublicList;
  slug: string;
  token: string;
}) {
  const [list, setList] = useState<PublicList>(initial);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const response = await fetch(
          `/shop/${encodeURIComponent(slug)}/requests/${encodeURIComponent(token)}`,
          { cache: "no-store" },
        );
        if (!response.ok) return;
        const fresh = (await response.json()) as PublicList;
        if (!cancelled) {
          setList(fresh);
          setCheckedAt(new Date());
        }
      } catch {
        // A dropped connection is not worth telling a customer about; the page simply stops updating
        // until the next attempt.
      }
    };
    const timer = window.setInterval(() => void check(), REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [slug, token]);

  const headings = new Map<string, PublicList["lines"]>();
  for (const line of list.lines) {
    const heading = line.group?.trim() || "Your list";
    headings.set(heading, [...(headings.get(heading) ?? []), line]);
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.kicker}>Your list for</p>
        <h1 className={styles.shopName}>{list.business_name}</h1>
        <p className={styles.status}>
          {list.status === "confirmed"
            ? "Confirmed - the shop is packing it."
            : `${list.lines.length} items, sent ${new Date(list.created_at).toLocaleString()}`}
        </p>
      </header>

      {[...headings.entries()].map(([heading, lines]) => (
        <section key={heading} className={styles.section}>
          <h2 className={styles.heading}>{heading}</h2>
          <ul className={styles.items}>
            {lines.map((line) => (
              <li key={`${line.position}-${line.text}`} className={styles.item}>
                <span className={styles.itemBody}>
                  <span className={styles.itemName}>{line.text}</span>
                  <span className={styles.itemMeta}>
                    {line.quantity} pcs - {STATE_WORD[line.state] ?? line.state}
                  </span>
                </span>
                <span className={styles.itemPrice}>
                  {line.shop_price
                    ? formatMoneyOrOnRequest(line.shop_price)
                    : "price to be confirmed"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}

      <section className={styles.summary}>
        <span className={styles.totalLabel}>
          {list.unpriced_line_count > 0
            ? `${list.unpriced_line_count} ${list.unpriced_line_count === 1 ? "line" : "lines"} still to be priced`
            : "Everything is priced"}
        </span>
        <span className={styles.total}>
          {list.priced_total
            ? `${formatMoneyOrOnRequest(list.priced_total)}${
                list.unpriced_line_count > 0 ? " + the rest" : ""
              }`
            : "Nothing priced yet"}
        </span>
        <span className={styles.updated}>
          {checkedAt
            ? `Checked at ${checkedAt.toLocaleTimeString()} - this page updates on its own`
            : "This page updates on its own as the shop works."}
        </span>
      </section>
    </main>
  );
}
