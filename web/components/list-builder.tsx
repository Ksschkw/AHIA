"use client";

/**
 * The list a customer builds, and sends.
 *
 * This is the screen the whole product is for. A customer who would otherwise stand at a counter saying
 * "bring Hot 8 five, bring XR five, bring universal metal ten" - item by item, with corrections, for
 * twenty minutes - builds the same list here in one sitting, and the trader packs it before they arrive.
 *
 * Four decisions shape it:
 *
 * - **Counts are the interface.** What a customer knows is "I want twenty of these", so the stepper is
 *   the primary control and the price is context, not the point.
 * - **Anything can be asked for.** A free-text line with a photograph is how somebody requests what the
 *   shop has not listed, and a list that cannot hold that request gets written on paper again.
 * - **The phone number is the price of entry, and the reason is said out loud.** It is the only thing
 *   asked of them, and it is what means their next list starts from this one.
 * - **Nothing about stock.** The shop sources what it does not have; a customer never reads a word about
 *   availability, because a trader who does not have something today can still serve them tomorrow.
 */

import { useMemo, useState } from "react";

import { formatMoneyOrOnRequest } from "@/lib/format";
import styles from "./list-builder.module.css";

export interface ListShopProduct {
  product_slug: string;
  name: string;
  selling_price: string | null;
}

export interface ListShop {
  tenant_slug: string;
  business_name: string;
  headline: string | null;
  contact_phone: string | null;
  products: ListShopProduct[];
}

interface ChosenLine {
  key: string;
  productSlug: string | null;
  freeText: string | null;
  quantity: number;
  customerPrice: string | null;
}

function priceOf(value: string | null): number {
  const parsed = Number(value ?? "0");
  return Number.isFinite(parsed) ? parsed : 0;
}

export function ListBuilder({ shop }: { shop: ListShop }) {
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [extras, setExtras] = useState<ChosenLine[]>([]);
  const [draftText, setDraftText] = useState("");
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<{ id: string; lines: number } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const chosen: ChosenLine[] = useMemo(() => {
    const fromCatalogue: ChosenLine[] = shop.products
      .filter((product) => (quantities[product.product_slug] ?? 0) > 0)
      .map((product) => ({
        key: product.product_slug,
        productSlug: product.product_slug,
        freeText: null,
        quantity: quantities[product.product_slug] ?? 0,
        customerPrice: product.selling_price,
      }));
    return [...fromCatalogue, ...extras];
  }, [shop.products, quantities, extras]);

  const total = chosen.reduce(
    (running, line) => running + priceOf(line.customerPrice) * line.quantity,
    0,
  );
  const hasUnpriced = chosen.some((line) => line.customerPrice === null || line.productSlug === null);

  function step(slug: string, delta: number) {
    setQuantities((current) => {
      const next = Math.max(0, (current[slug] ?? 0) + delta);
      return { ...current, [slug]: next };
    });
  }

  function addExtra() {
    const text = draftText.trim();
    if (text.length < 2) return;
    setExtras((current) => [
      ...current,
      {
        key: `extra-${Date.now()}-${current.length}`,
        productSlug: null,
        freeText: text,
        quantity: 1,
        customerPrice: null,
      },
    ]);
    setDraftText("");
  }

  async function send() {
    setProblem(null);
    if (chosen.length === 0) {
      setProblem("Add at least one thing to your list.");
      return;
    }
    if (phone.trim().length < 7) {
      setProblem("We need your phone number to keep track of whose list this is.");
      return;
    }
    setBusy(true);
    try {
      const response = await fetch(`/shop/${shop.tenant_slug}/requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_phone: phone.trim(),
          customer_name: name.trim() || null,
          note: note.trim() || null,
          lines: chosen.map((line) => ({
            // The catalogue is addressed by slug: it is what appears in a link, and an internal
            // identifier is never handed to a customer.
            ...(line.productSlug ? { product_slug: line.productSlug } : { free_text: line.freeText }),
            quantity: String(line.quantity),
            unit: "piece",
            ...(line.customerPrice ? { customer_price: line.customerPrice } : {}),
          })),
        }),
      });
      const payload = (await response.json().catch(() => null)) as
        | { request_id?: string; line_count?: number; error?: { message?: string } }
        | null;
      if (!response.ok) {
        setProblem(payload?.error?.message ?? "The list did not go through. Try again.");
        return;
      }
      setSent({ id: payload?.request_id ?? "", lines: payload?.line_count ?? chosen.length });
    } catch {
      setProblem("We could not reach the shop. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <main className={styles.page}>
        <section className={styles.done}>
          <h1 className={styles.doneTitle}>Your list has reached {shop.business_name}</h1>
          <p className={styles.doneText}>
            {sent.lines} {sent.lines === 1 ? "item" : "items"} sent. They will get back to you on{" "}
            {phone}.
          </p>
          <p className={styles.doneText}>
            Next time you will not start from nothing - your number brings this list back so you can
            change a count or two and send it again.
          </p>
          {shop.contact_phone ? (
            <a
              className={styles.primary}
              href={`https://wa.me/${shop.contact_phone.replace(/[^\d]/g, "")}`}
              rel="noreferrer noopener"
              target="_blank"
            >
              Talk to the shop now
            </a>
          ) : null}
        </section>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <p className={styles.kicker}>Sending a list to</p>
          <h1 className={styles.shopName}>{shop.business_name}</h1>
          {shop.headline ? <p className={styles.headline}>{shop.headline}</p> : null}
        </div>
      </header>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>How many of each?</h2>
        <p className={styles.sectionHint}>
          Put the counts - the shop will confirm the prices and get back to you.
        </p>
        <ul className={styles.items}>
          {shop.products.map((product) => {
            const quantity = quantities[product.product_slug] ?? 0;
            return (
              <li
                key={product.product_slug}
                className={quantity > 0 ? styles.itemChosen : styles.item}
              >
                <span className={styles.itemBody}>
                  <span className={styles.itemName}>{product.name}</span>
                  <span className={styles.itemPrice}>
                    {formatMoneyOrOnRequest(product.selling_price)}
                  </span>
                </span>
                <span className={styles.stepper}>
                  <button
                    type="button"
                    className={styles.stepButton}
                    onClick={() => step(product.product_slug, -1)}
                    disabled={quantity === 0}
                    aria-label={`One fewer ${product.name}`}
                  >
                    -
                  </button>
                  <input
                    className={styles.stepValue}
                    value={quantity === 0 ? "" : String(quantity)}
                    placeholder="0"
                    inputMode="numeric"
                    aria-label={`How many ${product.name}`}
                    onChange={(event) => {
                      const parsed = Number.parseInt(event.target.value.replace(/[^\d]/g, ""), 10);
                      setQuantities((current) => ({
                        ...current,
                        [product.product_slug]: Number.isNaN(parsed) ? 0 : parsed,
                      }));
                    }}
                  />
                  <button
                    type="button"
                    className={styles.stepButton}
                    onClick={() => step(product.product_slug, 1)}
                    aria-label={`One more ${product.name}`}
                  >
                    +
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Anything else?</h2>
        <p className={styles.sectionHint}>
          If you do not see it, ask for it - the shop will find it. A description is enough.
        </p>
        <div className={styles.extraRow}>
          <input
            className={styles.extraInput}
            value={draftText}
            placeholder="e.g. 21D screenguard for iPhone 15, the matte one"
            onChange={(event) => setDraftText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addExtra();
              }
            }}
          />
          <button type="button" className={styles.addButton} onClick={addExtra}>
            Add
          </button>
        </div>
        {extras.length > 0 ? (
          <ul className={styles.items}>
            {extras.map((line) => (
              <li key={line.key} className={styles.itemChosen}>
                <span className={styles.itemBody}>
                  <span className={styles.itemName}>{line.freeText}</span>
                  <span className={styles.itemPrice}>price to be confirmed</span>
                </span>
                <button
                  type="button"
                  className={styles.removeButton}
                  onClick={() => setExtras((current) => current.filter((one) => one.key !== line.key))}
                  aria-label={`Remove ${line.freeText}`}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Who is this list for?</h2>
        <p className={styles.sectionHint}>
          Your phone number lets the shop keep track of whose list this is - and means you can start
          from this list next time instead of typing it all again.
        </p>
        <input
          className={styles.field}
          id="list_phone"
          value={phone}
          placeholder="Your phone number"
          inputMode="tel"
          onChange={(event) => setPhone(event.target.value)}
        />
        <input
          className={styles.field}
          id="list_name"
          value={name}
          placeholder="Your name (optional)"
          onChange={(event) => setName(event.target.value)}
        />
        <textarea
          className={styles.textarea}
          id="list_note"
          value={note}
          placeholder="Anything the shop should know (optional)"
          onChange={(event) => setNote(event.target.value)}
        />
      </section>

      <section className={styles.summary} aria-live="polite">
        <div>
          <p className={styles.summaryCount}>
            {chosen.length} {chosen.length === 1 ? "item" : "items"} on your list
          </p>
          <p className={styles.summaryTotal}>
            {chosen.length === 0
              ? "Nothing added yet"
              : `${formatMoneyOrOnRequest(String(total))}${hasUnpriced ? " + items to price" : ""}`}
          </p>
          {hasUnpriced && chosen.length > 0 ? (
            <p className={styles.summaryNote}>
              The shop will price what it has to find. That is normal, and the price you see for the
              rest is what you would pay today.
            </p>
          ) : null}
        </div>
        <button type="button" className={styles.send} onClick={() => void send()} disabled={busy}>
          {busy ? "Sending..." : "Send my list"}
        </button>
        {problem ? <p className={styles.problem}>{problem}</p> : null}
      </section>
    </main>
  );
}
