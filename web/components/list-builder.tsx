"use client";

/**
 * Building a list for one shop.
 *
 * The customer would otherwise stand at a counter saying "bring Hot 8 five, bring XR five 21D, bring
 * universal metal ten" - item by item, for twenty minutes. Here they do it once, and the trader packs it
 * before they arrive.
 *
 * Four decisions shape it, and three of them correct my own earlier attempts:
 *
 * - **It is a cart, not a form.** They search and tap add. A stepper against every catalogue row was the
 *   first design and it was wrong: two hundred models would be two hundred controls.
 * - **The list reads like a written one** - a heading in the trader's words, the lines under it, counts
 *   beside them - because that is how the trade writes and reads lists.
 * - **Anything can be asked for**, with the price left blank: a customer does not price what the shop has
 *   to go and find.
 * - **It is sent as a picture.** A typed list is unreadable on a phone, arrives truncated and cannot be
 *   forwarded as a list; an image of it can, and it is what the trader would have received on paper.
 */

import { useEffect, useMemo, useState } from "react";

import { formatMoneyOrOnRequest } from "@/lib/format";
import styles from "./list-builder.module.css";

export interface ListShopProduct {
  product_slug: string;
  name: string;
  selling_price: string | null;
  /** The heading this item sits under, in the trader's own words. */
  group_name: string | null;
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
  text: string;
  group: string;
  quantity: number;
  price: string | null;
}

/** Where the customer's own details are kept, so a returning one does not retype them. */
const PHONE_KEY = "ahia.customer.phone";
const NAME_KEY = "ahia.customer.name";

function priceOf(value: string | null): number {
  const parsed = Number(value ?? "0");
  return Number.isFinite(parsed) ? parsed : 0;
}

export function ListBuilder({ shop }: { shop: ListShop }) {
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<ChosenLine[]>([]);
  const [askedText, setAskedText] = useState("");
  const [askedGroup, setAskedGroup] = useState("");
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [sent, setSent] = useState<{ lines: number } | null>(null);
  const [picture, setPicture] = useState<string | null>(null);

  useEffect(() => {
    const rememberedPhone = window.localStorage.getItem(PHONE_KEY);
    const rememberedName = window.localStorage.getItem(NAME_KEY);
    if (rememberedPhone) setPhone(rememberedPhone);
    if (rememberedName) setName(rememberedName);
  }, []);

  const results = useMemo(() => {
    const wanted = query.trim().toLowerCase();
    if (wanted.length === 0) return [];
    return shop.products
      .filter(
        (product) =>
          !chosen.some((line) => line.productSlug === product.product_slug) &&
          (product.name.toLowerCase().includes(wanted) ||
            (product.group_name ?? "").toLowerCase().includes(wanted)),
      )
      .slice(0, 8);
  }, [query, shop.products, chosen]);

  const total = chosen.reduce((running, line) => running + priceOf(line.price) * line.quantity, 0);
  const toBePriced = chosen.filter((line) => line.price === null).length;

  /** The list as it will be read: headings, and the lines under each one. */
  const grouped = useMemo(() => {
    const headings = new Map<string, ChosenLine[]>();
    for (const line of chosen) {
      const heading = line.group.trim() || "Other";
      headings.set(heading, [...(headings.get(heading) ?? []), line]);
    }
    return [...headings.entries()];
  }, [chosen]);

  function addProduct(product: ListShopProduct) {
    setChosen((current) => [
      ...current,
      {
        key: product.product_slug,
        productSlug: product.product_slug,
        text: product.name,
        group: product.group_name ?? "",
        quantity: 1,
        price: product.selling_price,
      },
    ]);
    setQuery("");
  }

  function addAsked() {
    const text = askedText.trim();
    if (text.length < 2) return;
    setChosen((current) => [
      ...current,
      {
        key: `asked-${Date.now()}-${current.length}`,
        productSlug: null,
        text,
        group: askedGroup.trim(),
        quantity: 1,
        price: null,
      },
    ]);
    setAskedText("");
    setAskedGroup("");
  }

  function changeQuantity(key: string, delta: number) {
    setChosen((current) =>
      current.map((line) =>
        line.key === key ? { ...line, quantity: Math.max(1, line.quantity + delta) } : line,
      ),
    );
  }

  /**
   * Draw the list as the piece of paper it replaces.
   *
   * This is what gets sent. A typed list is unreadable on a phone, arrives truncated, and cannot be
   * forwarded as a list; a picture of one can - and the trader can print it and tick lines off with a
   * pen, which is how he already works.
   */
  async function drawList(): Promise<Blob | null> {
    const width = 900;
    const rowHeight = 44;
    const headingHeight = 56;
    const rows = grouped.reduce((count, [, lines]) => count + lines.length, 0);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = Math.max(620, 260 + rows * rowHeight + grouped.length * headingHeight);
    const context = canvas.getContext("2d");
    if (!context) return null;

    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#1e1b16";
    context.font = "bold 34px system-ui, sans-serif";
    context.fillText(shop.business_name, 48, 84);
    context.fillStyle = "#5c5549";
    context.font = "20px system-ui, sans-serif";
    context.fillText(
      `${name.trim() || "A customer"} - ${phone.trim()} - ${new Date().toLocaleDateString()}`,
      48,
      118,
    );
    context.fillStyle = "#0b5d3b";
    context.font = "bold 22px system-ui, sans-serif";
    context.fillText("LIST", 48, 172);
    context.fillStyle = "#e7dfd2";
    context.fillRect(48, 186, width - 96, 2);

    let y = 232;
    for (const [heading, lines] of grouped) {
      context.fillStyle = "#084a2f";
      context.font = "bold 26px system-ui, sans-serif";
      context.fillText(heading, 48, y);
      y += headingHeight;
      for (const line of lines) {
        context.fillStyle = "#1e1b16";
        context.font = "22px system-ui, sans-serif";
        context.fillText(line.text.length > 54 ? `${line.text.slice(0, 53)}...` : line.text, 72, y);
        context.fillStyle = "#5c5549";
        context.font = "bold 22px system-ui, sans-serif";
        context.textAlign = "right";
        context.fillText(`${line.quantity} pcs`, width - 48, y);
        context.textAlign = "left";
        y += rowHeight;
      }
      y += 10;
    }

    context.fillStyle = "#e7dfd2";
    context.fillRect(48, y + 6, width - 96, 2);
    context.fillStyle = "#084a2f";
    context.font = "bold 26px system-ui, sans-serif";
    context.fillText(
      toBePriced > 0
        ? `${formatMoneyOrOnRequest(total.toFixed(2))} + ${toBePriced} to price`
        : formatMoneyOrOnRequest(total.toFixed(2)),
      48,
      y + 56,
    );
    context.fillStyle = "#8b8377";
    context.font = "18px system-ui, sans-serif";
    context.fillText("Sent with AHIA", 48, y + 92);

    return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  }

  async function send() {
    setProblem(null);
    if (chosen.length === 0) {
      setProblem("Add at least one thing to your list.");
      return;
    }
    if (phone.trim().length < 7) {
      setProblem("We need your phone number so the shop knows whose list this is.");
      return;
    }
    setBusy(true);
    try {
      // Remembered on this device, so the next list starts with them already known.
      window.localStorage.setItem(PHONE_KEY, phone.trim());
      if (name.trim()) window.localStorage.setItem(NAME_KEY, name.trim());

      const drawn = await drawList();
      if (drawn) setPicture(URL.createObjectURL(drawn));

      const response = await fetch(`/shop/${shop.tenant_slug}/requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_phone: phone.trim(),
          customer_name: name.trim() || null,
          lines: chosen.map((line) => ({
            ...(line.productSlug ? { product_slug: line.productSlug } : { free_text: line.text }),
            quantity: String(line.quantity),
            unit: "piece",
            ...(line.price ? { customer_price: line.price } : {}),
            ...(line.group.trim() ? { note: line.group.trim() } : {}),
          })),
        }),
      });
      const payload = (await response.json().catch(() => null)) as
        | { line_count?: number; error?: { message?: string } }
        | null;
      if (!response.ok) {
        setProblem(payload?.error?.message ?? "The list did not go through. Try again.");
        return;
      }
      setSent({ lines: payload?.line_count ?? chosen.length });
    } catch {
      setProblem("We could not reach the shop. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function sharePicture() {
    if (picture === null) return;
    try {
      const blob = await (await fetch(picture)).blob();
      const file = new File([blob], `${shop.tenant_slug}-list.png`, { type: "image/png" });
      const message = `My list for ${shop.business_name}`;
      // As a picture where the browser allows it - which is what a customer would have sent as a
      // photograph of paper - and as a download with a message already written where it does not.
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], text: message });
        return;
      }
      const link = document.createElement("a");
      link.href = picture;
      link.download = file.name;
      link.click();
      const number = (shop.contact_phone ?? "").replace(/[^\d]/g, "");
      if (number) {
        window.open(`https://wa.me/${number}?text=${encodeURIComponent(message)}`, "_blank");
      }
    } catch {
      // A share somebody cancelled is not a failure worth telling them about.
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
          {picture ? (
            <>
              <p className={styles.doneText}>
                This is the list they received. Send it on WhatsApp as well, so it sits in their messages
                where they will look for it.
              </p>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className={styles.preview} src={picture} alt="Your list" />
              <button type="button" className={styles.primary} onClick={() => void sharePicture()}>
                Send the list on WhatsApp
              </button>
            </>
          ) : null}
          <p className={styles.doneText}>
            Next time you will not start from nothing: your number brings this list back.
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.kicker}>Sending a list to</p>
        <h1 className={styles.shopName}>{shop.business_name}</h1>
        {shop.headline ? <p className={styles.headline}>{shop.headline}</p> : null}
      </header>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>What do you want?</h2>
        <p className={styles.sectionHint}>Search the shop and add what you need.</p>
        <input
          className={styles.extraInput}
          id="list_search"
          value={query}
          placeholder="Start typing - 21D, privacy, charger"
          onChange={(event) => setQuery(event.target.value)}
        />
        {results.length > 0 ? (
          <ul className={styles.items}>
            {results.map((product) => (
              <li key={product.product_slug} className={styles.item}>
                <span className={styles.itemBody}>
                  <span className={styles.itemName}>{product.name}</span>
                  <span className={styles.itemPrice}>
                    {product.group_name ? `${product.group_name} - ` : ""}
                    {formatMoneyOrOnRequest(product.selling_price)}
                  </span>
                </span>
                <button
                  type="button"
                  className={styles.addButton}
                  onClick={() => addProduct(product)}
                  aria-label={`Add ${product.name}`}
                >
                  Add
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        <p className={styles.sectionHint}>Not in the shop? Ask for it and leave the price blank.</p>
        <div className={styles.extraRow}>
          <input
            className={styles.extraInput}
            id="list_asked"
            value={askedText}
            placeholder="e.g. universal metal frame, any brand"
            onChange={(event) => setAskedText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addAsked();
              }
            }}
          />
          <button type="button" className={styles.addButton} onClick={addAsked}>
            Add
          </button>
        </div>
        <input
          className={styles.extraInput}
          id="list_asked_group"
          value={askedGroup}
          placeholder="Under which heading? (optional)"
          onChange={(event) => setAskedGroup(event.target.value)}
        />
      </section>

      {chosen.length > 0 ? (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Your list</h2>
          {grouped.map(([heading, lines]) => (
            <div key={heading}>
              <h3 className={styles.groupName}>{heading}</h3>
              <ul className={styles.items}>
                {lines.map((line) => (
                  <li key={line.key} className={styles.itemChosen}>
                    <span className={styles.itemBody}>
                      <span className={styles.itemName}>{line.text}</span>
                      <span className={styles.itemPrice}>
                        {line.price === null
                          ? "price to be confirmed"
                          : formatMoneyOrOnRequest(line.price)}
                      </span>
                    </span>
                    <span className={styles.stepper}>
                      <button
                        type="button"
                        className={styles.stepButton}
                        onClick={() => changeQuantity(line.key, -1)}
                        aria-label={`One fewer ${line.text}`}
                      >
                        -
                      </button>
                      <span className={styles.stepValue}>{line.quantity}</span>
                      <button
                        type="button"
                        className={styles.stepButton}
                        onClick={() => changeQuantity(line.key, 1)}
                        aria-label={`One more ${line.text}`}
                      >
                        +
                      </button>
                      <button
                        type="button"
                        className={styles.removeButton}
                        onClick={() =>
                          setChosen((current) => current.filter((one) => one.key !== line.key))
                        }
                        aria-label={`Remove ${line.text}`}
                      >
                        Remove
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      ) : null}

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Who is this list for?</h2>
        <p className={styles.sectionHint}>
          Your phone number lets the shop keep track of whose list this is - and means you can start from
          this list next time instead of typing it again.
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
      </section>

      <section className={styles.summary} aria-live="polite">
        <div>
          <p className={styles.summaryCount}>
            {chosen.length} {chosen.length === 1 ? "item" : "items"} on your list
          </p>
          <p className={styles.summaryTotal}>
            {chosen.length === 0
              ? "Nothing added yet"
              : `${formatMoneyOrOnRequest(total.toFixed(2))}${
                  toBePriced > 0 ? ` + ${toBePriced} to price` : ""
                }`}
          </p>
          {toBePriced > 0 ? (
            <p className={styles.summaryNote}>
              The shop will price what it has to find. That is normal; the price you see for the rest is
              what you would pay today.
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
