"use client";

import Link from "next/link";

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

  /**
   * The list, put back into the shape the customer made.
   *
   * Two things can group a line here, and they are different. **His own headings** are lines he wrote, and the
   * things under them point at them by position - that is his structure, and it nests. **The shop's headings**
   * are the groups a catalogue item came from, which he never chose and which sit flat.
   *
   * His own shape wins, because it is the one he drew: a heading he made is where he expects to find what he
   * put under it.
   */
  const byPosition = new Map(list.lines.map((line) => [line.position, line]));
  const childrenOf = new Map<number | null, PublicList["lines"]>();
  for (const line of list.lines) {
    const under =
      line.parent_position !== null &&
      line.parent_position !== line.position &&
      byPosition.has(line.parent_position)
        ? line.parent_position
        : null;
    childrenOf.set(under, [...(childrenOf.get(under) ?? []), line]);
  }

  const visited = new Set<number>();
  function withChildren(
    line: PublicList["lines"][number],
    depth: number,
  ): { line: PublicList["lines"][number]; depth: number }[] {
    if (visited.has(line.position) || depth > 8) return [];
    visited.add(line.position);
    const mine = (childrenOf.get(line.position) ?? []).filter(
      (child) => !visited.has(child.position) && child.position !== line.position,
    );
    return [
      { line, depth },
      ...mine.flatMap((child) => withChildren(child, depth + 1)),
    ];
  }

  const rootLines = childrenOf.get(null) ?? [];
  const shaped = rootLines.flatMap((line) => withChildren(line, 0));
  for (const line of list.lines) {
    if (!visited.has(line.position)) {
      shaped.push({ line, depth: 0 });
      visited.add(line.position);
    }
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

      <section className={styles.section}>
        {/* **His own shape, drawn.** A line he wrote as a heading is shown as one; what he put under it is
            indented beneath it. The shop's groups are a quieter label on the line itself, because they are the
            trader's words rather than the customer's. */}
        <ul className={styles.items}>
          {shaped.map(({ line, depth }) => (
            <li
              key={`${line.position}-${line.text}`}
              className={depth > 0 ? styles.itemUnder : styles.item}
            >
              <span className={styles.itemBody}>
                <span className={depth > 0 ? styles.itemNameIn : styles.itemName}>{line.text}</span>
                <span className={styles.itemMeta}>
                  {line.quantity} pcs - {STATE_WORD[line.state] ?? line.state}
                  {line.group ? ` - ${line.group}` : ""}
                </span>
              </span>
              <span className={styles.itemPrice}>
                {line.shop_price ? formatMoneyOrOnRequest(line.shop_price) : "price to be confirmed"}
              </span>
            </li>
          ))}
        </ul>
      </section>

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
        <div style={{ marginTop: "16px", display: "flex", gap: "10px", flexWrap: "wrap", justifyContent: "center" }}>
          <Link
            href={`/list/${slug}`}
            style={{
              padding: "10px 18px",
              borderRadius: "10px",
              background: "var(--leaf)",
              color: "#ffffff",
              fontWeight: 700,
              fontSize: "14px",
              textDecoration: "none",
            }}
          >
            Create New List at {list.business_name}
          </Link>
        </div>
      </section>
    </main>
  );
}
