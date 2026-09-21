"use client";

/**
 * Building a list for one shop.
 *
 * **This is the second attempt.** The first was built around the trader's catalogue: chips for groups, a search
 * box underneath, and a customer who had to work out what a "heading" was before he could write one. The product
 * owner's verdict was the useful one - "confusing for even me, imagine an Alaba bloke" - and he was right: it
 * asked the customer to understand the model instead of just letting him say what he wants.
 *
 * What it is now, in the order a customer actually does it:
 *
 * 1. **Search.** The first thing on the screen, because most customers arrive knowing what they want. Typing
 *    searches the whole shop, at any depth, without making anybody open a folder.
 * 2. **Or browse.** Taps down the shop's own structure for somebody who does not know the name of the thing -
 *    one level at a time, with a breadcrumb back, and only the exceptions shown by name.
 * 3. **"Can't find it? Add your own."** A first-class button rather than an afterthought, because in this trade
 *    it is the *normal* case: the thing he wants is often not in any catalogue.
 * 4. **His list, always there.** A bar that never leaves the screen saying how many things are on it and what
 *    they come to. A customer who cannot see his list assumes he has lost it and starts again.
 *
 * **His own headings can nest**, which is what `parent_position` is for: he puts a heading down, then things
 * under it, and can put a heading under that. Nothing he writes touches the trader's catalogue.
 */

import { useMemo, useState } from "react";

import { formatMoneyOrOnRequest } from "@/lib/format";
import styles from "./list-builder.module.css";

export interface ListShopProduct {
  product_slug: string;
  name: string;
  selling_price: string | null;
  group_name: string | null;
  /** True when the shop prices this one differently from the rest of its group. */
  is_special: boolean;
}

export interface ListShopGroup {
  name: string;
  parent_name: string | null;
  normal_price: string | null;
}

export interface ListShop {
  tenant_slug: string;
  business_name: string;
  headline: string | null;
  contact_phone: string | null;
  products: ListShopProduct[];
  groups: ListShopGroup[];
}

interface ChosenLine {
  key: string;
  /** The catalogue item, when they picked one. */
  productSlug: string | null;
  text: string;
  quantity: number;
  price: string | null;
  /** The key of the heading this sits under, when they made one. */
  underKey: string | null;
  /** True when the line *is* a heading they made. */
  isHeading: boolean;
  note: string;
}

const PHONE_KEY = "ahia.customer.phone";
const NAME_KEY = "ahia.customer.name";

function priceOf(value: string | null): number {
  const parsed = Number(value ?? "0");
  return Number.isFinite(parsed) ? parsed : 0;
}

export function ListBuilder({ shop }: { shop: ListShop }) {
  const [query, setQuery] = useState("");
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [chosen, setChosen] = useState<ChosenLine[]>([]);
  const [showingList, setShowingList] = useState(false);
  const [addingOwn, setAddingOwn] = useState(false);
  const [ownText, setOwnText] = useState("");
  const [ownQuantity, setOwnQuantity] = useState("1");
  const [ownUnder, setOwnUnder] = useState<string | null>(null);
  const [newHeading, setNewHeading] = useState("");
  const [phone, setPhone] = useState(
    typeof window === "undefined" ? "" : window.localStorage.getItem(PHONE_KEY) ?? "",
  );
  const [name, setName] = useState(
    typeof window === "undefined" ? "" : window.localStorage.getItem(NAME_KEY) ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [sent, setSent] = useState<number | null>(null);
  const [picture, setPicture] = useState<string | null>(null);

  const headings = chosen.filter((line) => line.isHeading);
  const items = chosen.filter((line) => !line.isHeading);
  const total = items.reduce((running, line) => running + priceOf(line.price) * line.quantity, 0);
  const toBePriced = items.filter((line) => line.price === null).length;

  /** What search turns up: everything at every depth, because the customer should not have to guess a level. */
  const found = useMemo(() => {
    const wanted = query.trim().toLowerCase();
    if (wanted.length < 2) return [];
    return shop.products
      .filter(
        (product) =>
          product.name.toLowerCase().includes(wanted) ||
          (product.group_name ?? "").toLowerCase().includes(wanted),
      )
      .slice(0, 12);
  }, [query, shop.products]);

  /** What browsing shows: the children of wherever they are, and the things priced differently there. */
  const children = useMemo(() => {
    if (openGroup === null) {
      return shop.groups.filter(
        (group) =>
          group.parent_name === null ||
          !shop.groups.some((candidate) => candidate.name === group.parent_name),
      );
    }
    return shop.groups.filter((group) => group.parent_name === openGroup);
  }, [openGroup, shop.groups]);

  const specialsHere = useMemo(() => {
    if (openGroup === null) return [];
    return shop.products.filter(
      (product) => product.is_special && product.group_name === openGroup,
    );
  }, [openGroup, shop.products]);

  function addProduct(product: ListShopProduct, under: string | null = null) {
    setChosen((current) => [
      ...current,
      {
        key: `item-${product.product_slug}-${current.length}`,
        productSlug: product.product_slug,
        text: product.name,
        quantity: 1,
        price: product.selling_price,
        underKey: under,
        isHeading: false,
        note: "",
      },
    ]);
    setQuery("");
    setProblem(null);
  }

  function addHeading() {
    const text = newHeading.trim();
    if (text.length < 2) return;
    const key = `head-${Date.now()}`;
    setChosen((current) => [
      ...current,
      {
        key,
        productSlug: null,
        text,
        quantity: 1,
        price: null,
        underKey: null,
        isHeading: true,
        note: "heading",
      },
    ]);
    setNewHeading("");
    setOwnUnder(key);
  }

  function addOwnItem() {
    const text = ownText.trim();
    if (text.length < 2) return;
    setChosen((current) => [
      ...current,
      {
        key: `own-${Date.now()}-${current.length}`,
        productSlug: null,
        text,
        quantity: Math.max(1, Number(ownQuantity) || 1),
        price: null,
        underKey: ownUnder,
        isHeading: false,
        note: "",
      },
    ]);
    setOwnText("");
    setOwnQuantity("1");
    setAddingOwn(false);
    setProblem(null);
  }

  function changeQuantity(key: string, delta: number) {
    setChosen((current) =>
      current.map((line) =>
        line.key === key ? { ...line, quantity: Math.max(1, line.quantity + delta) } : line,
      ),
    );
  }

  function removeLine(key: string) {
    // Taking a heading away takes what was under it, which is what a person means by deleting a heading.
    setChosen((current) => current.filter((line) => line.key !== key && line.underKey !== key));
  }

  /** The list, drawn as the paper it replaces: headings, the things under them, and the counts. */
  async function drawList(): Promise<Blob | null> {
    const width = 900;
    const row = 46;
    const canvasHeight = Math.max(640, 300 + chosen.filter((line) => !line.isHeading).length * row + headings.length * 60);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = canvasHeight;
    const context = canvas.getContext("2d");
    if (!context) return null;

    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#1e1b16";
    context.font = "bold 34px system-ui, sans-serif";
    context.fillText(shop.business_name, 48, 88);
    context.fillStyle = "#5c5549";
    context.font = "20px system-ui, sans-serif";
    context.fillText(`${name.trim() || "A customer"} - ${phone.trim()}`, 48, 122);
    context.fillStyle = "#0b5d3b";
    context.font = "bold 22px system-ui, sans-serif";
    context.fillText("LIST", 48, 176);
    context.fillStyle = "#e7dfd2";
    context.fillRect(48, 190, width - 96, 2);

    // The shape the customer made, drawn: a heading, and what they put under it, indented.
    const ordered: ChosenLine[] = [];
    for (const heading of headings) {
      ordered.push(heading);
      for (const item of items.filter((line) => line.underKey === heading.key)) ordered.push(item);
    }
    for (const item of items.filter((line) => line.underKey === null)) ordered.push(item);

    let y = 240;
    for (const line of ordered) {
      const indented = line.isHeading || line.underKey !== null;
      context.fillStyle = line.isHeading ? "#084a2f" : "#1e1b16";
      context.font = line.isHeading ? "bold 26px system-ui, sans-serif" : "22px system-ui, sans-serif";
      const label = line.text.length > 50 ? `${line.text.slice(0, 49)}...` : line.text;
      context.fillText(label, indented ? 72 : 48, y);
      if (!line.isHeading) {
        context.fillStyle = "#5c5549";
        context.font = "bold 22px system-ui, sans-serif";
        context.textAlign = "right";
        context.fillText(`${line.quantity} pcs`, width - 48, y);
        context.textAlign = "left";
      }
      y += line.isHeading ? 60 : row;
    }

    context.fillStyle = "#e7dfd2";
    context.fillRect(48, y + 8, width - 96, 2);
    context.fillStyle = "#084a2f";
    context.font = "bold 26px system-ui, sans-serif";
    context.fillText(
      toBePriced > 0
        ? `${formatMoneyOrOnRequest(total.toFixed(2))} + ${toBePriced} to price`
        : formatMoneyOrOnRequest(total.toFixed(2)),
      48,
      y + 58,
    );
    context.fillStyle = "#8b8377";
    context.font = "18px system-ui, sans-serif";
    context.fillText("Sent with AHIA", 48, y + 94);

    return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  }

  async function send() {
    setProblem(null);
    if (items.length === 0) {
      setProblem("Add at least one thing to your list.");
      return;
    }
    if (phone.trim().length < 7) {
      setProblem("We need your phone number so the shop knows whose list this is.");
      setShowingList(true);
      return;
    }
    setBusy(true);
    try {
      window.localStorage.setItem(PHONE_KEY, phone.trim());
      if (name.trim()) window.localStorage.setItem(NAME_KEY, name.trim());
      const drawn = await drawList();
      if (drawn) setPicture(URL.createObjectURL(drawn));

      // **Positions, not keys.** The API addresses a parent by where it sits in this submission, because the
      // lines do not exist yet. So the order is worked out once, and every parent is a number in it.
      const ordered: ChosenLine[] = [];
      for (const heading of headings) {
        ordered.push(heading);
        for (const item of items.filter((line) => line.underKey === heading.key)) ordered.push(item);
      }
      for (const item of items.filter((line) => line.underKey === null)) ordered.push(item);

      const positionOf = (key: string) => ordered.findIndex((line) => line.key === key);
      const payload = ordered.map((line) => {
        const under = line.underKey === null ? -1 : positionOf(line.underKey);
        return {
          ...(line.productSlug ? { product_slug: line.productSlug } : { free_text: line.text }),
          quantity: String(line.quantity),
          unit: "piece",
          ...(line.isHeading ? { note: "heading" } : {}),
          ...(line.note && !line.isHeading ? { note: line.note } : {}),
          // A heading at the top has no parent; anything under one names it by position.
          ...(under >= 0 ? { parent_position: under } : {}),
        };
      });

      const response = await fetch(`/shop/${shop.tenant_slug}/requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_phone: phone.trim(),
          customer_name: name.trim() || null,
          lines: payload,
        }),
      });
      const body = (await response.json().catch(() => null)) as
        | { line_count?: number; error?: { message?: string } }
        | null;
      if (!response.ok) {
        setProblem(body?.error?.message ?? "The list did not go through. Try again.");
        return;
      }
      setSent(body?.line_count ?? items.length);
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
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], text: message });
        return;
      }
      const link = document.createElement("a");
      link.href = picture;
      link.download = file.name;
      link.click();
      const number = (shop.contact_phone ?? "").replace(/[^\d]/g, "");
      if (number) window.open(`https://wa.me/${number}?text=${encodeURIComponent(message)}`, "_blank");
    } catch {
      // A share somebody cancelled is not a failure worth telling them about.
    }
  }

  if (sent !== null) {
    return (
      <main className={styles.page}>
        <section className={styles.done}>
          <h1 className={styles.doneTitle}>Your list has reached {shop.business_name}</h1>
          <p className={styles.doneText}>
            {sent} {sent === 1 ? "item" : "items"} sent. They will get back to you on {phone}.
          </p>
          {picture ? (
            <>
              <p className={styles.doneText}>
                This is the list they received. Send it on WhatsApp as well, so it sits in their messages.
              </p>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className={styles.preview} src={picture} alt="Your list" />
              <button type="button" className={styles.primary} onClick={() => void sharePicture()}>
                Send the list on WhatsApp
              </button>
            </>
          ) : null}
        </section>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.kicker}>Sending a list to</p>
        <h1 className={styles.shopName}>{shop.business_name}</h1>
        {openGroup === null ? (
          <nav className={styles.crumbs} aria-label="Where you are">
            <span className={styles.crumbNow}>All of the shop</span>
          </nav>
        ) : (
          <nav className={styles.crumbs} aria-label="Where you are">
            <button type="button" className={styles.crumbLink} onClick={() => setOpenGroup(null)}>
              All of the shop
            </button>
            <span className={styles.crumbSep}>/</span>
            <span className={styles.crumbNow}>{openGroup}</span>
          </nav>
        )}
      </header>

      <section className={styles.section}>
        <label className={styles.searchLabel} htmlFor="list_search">
          What are you looking for?
        </label>
        <input
          className={styles.search}
          id="list_search"
          value={query}
          placeholder="Type anything - 21D, privacy, charger"
          onChange={(event) => setQuery(event.target.value)}
        />
        {found.length > 0 ? (
          <ul className={styles.rows}>
            {found.map((product) => (
              <li key={product.product_slug} className={styles.row}>
                <span className={styles.rowBody}>
                  <span className={styles.rowName}>{product.name}</span>
                  <span className={styles.rowMeta}>
                    {product.group_name ? `${product.group_name} - ` : ""}
                    {formatMoneyOrOnRequest(product.selling_price)}
                  </span>
                </span>
                <button
                  type="button"
                  className={styles.addHere}
                  onClick={() => addProduct(product, openGroup ? headingKeyFor(openGroup) : null)}
                  aria-label={`Add ${product.name}`}
                >
                  Add
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {query.trim().length >= 2 && found.length === 0 ? (
          <p className={styles.nothing}>Nothing by that name. Add it yourself below.</p>
        ) : null}
      </section>

      {query.trim().length < 2 ? (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>
            {openGroup === null ? "Or look through the shop" : `Inside ${openGroup}`}
          </h2>
          {openGroup !== null && children.length === 0 ? null : (
            <ul className={styles.rows}>
              {children.map((group) => (
                <li key={group.name} className={styles.row}>
                  <button
                    type="button"
                    // Named, so a check can find the row rather than the first button whose text mentions the
                    // same words - which is how a product's Add button got pressed instead of a group once.
                    id={`group_${group.name}`}
                    className={styles.rowOpen}
                    onClick={() => setOpenGroup(group.name)}
                  >
                    <span className={styles.rowName}>{group.name}</span>
                    <span className={styles.rowMeta}>
                      {group.normal_price
                        ? `${formatMoneyOrOnRequest(group.normal_price)} each`
                        : "priced when they get it"}
                    </span>
                  </button>
                  <span className={styles.chev} aria-hidden>
                    &gt;
                  </span>
                </li>
              ))}
            </ul>
          )}
          {specialsHere.length > 0 ? (
            <>
              <p className={styles.onlyThese}>Priced differently here:</p>
              <ul className={styles.rows}>
                {specialsHere.map((product) => (
                  <li key={product.product_slug} className={styles.row}>
                    <span className={styles.rowBody}>
                      <span className={styles.rowName}>{product.name}</span>
                      <span className={styles.rowPrice}>
                        {formatMoneyOrOnRequest(product.selling_price)}
                      </span>
                    </span>
                    <button
                      type="button"
                      className={styles.addHere}
                      onClick={() => addProduct(product, headingKeyFor(openGroup))}
                    >
                      Add
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {openGroup !== null ? (
            <p className={styles.nothing}>
              Anything else here is the same price - just type it in below.
            </p>
          ) : null}
        </section>
      ) : null}

      <section className={styles.section}>
        <button type="button" className={styles.ownButton} onClick={() => setAddingOwn((open) => !open)}>
          + Can&apos;t find it? Add your own
        </button>
        {addingOwn ? (
          <div className={styles.ownForm}>
            <input
              className={styles.search}
              id="list_own_text"
              value={ownText}
              placeholder="What do you want? e.g. universal metal frame"
              onChange={(event) => setOwnText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addOwnItem();
                }
              }}
            />
            <div className={styles.ownRow}>
              <input
                className={styles.qty}
                id="list_own_quantity"
                value={ownQuantity}
                inputMode="numeric"
                aria-label="How many"
                onChange={(event) => setOwnQuantity(event.target.value)}
              />
              <button type="button" className={styles.addHere} onClick={addOwnItem}>
                Add to my list
              </button>
            </div>
            <p className={styles.nothing}>The shop will put a price on it.</p>

            <p className={styles.onlyThese}>Or start your own heading, with things under it:</p>
            <div className={styles.ownRow}>
              <input
                className={styles.search}
                id="list_new_heading"
                value={newHeading}
                placeholder="e.g. Items for my shop"
                onChange={(event) => setNewHeading(event.target.value)}
              />
              <button type="button" className={styles.addHere} onClick={addHeading}>
                Add heading
              </button>
            </div>
            {headings.length > 0 ? (
              <div className={styles.chooseUnder}>
                <span className={styles.onlyThese}>Put the next thing under:</span>
                <button
                  type="button"
                  className={ownUnder === null ? styles.underOn : styles.underOff}
                  onClick={() => setOwnUnder(null)}
                >
                  Nothing - top of my list
                </button>
                {headings.map((heading) => (
                  <button
                    key={heading.key}
                    type="button"
                    className={ownUnder === heading.key ? styles.underOn : styles.underOff}
                    onClick={() => setOwnUnder(heading.key)}
                  >
                    {heading.text}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {showingList ? (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>My list</h2>
          {chosen.length === 0 ? <p className={styles.nothing}>Nothing on it yet.</p> : null}
          {chosen.map((line) => (
            <div
              key={line.key}
              className={line.underKey !== null ? styles.lineUnder : styles.lineTop}
            >
              {line.isHeading ? (
                <div className={styles.headingRow}>
                  <span className={styles.headingName}>{line.text}</span>
                  <button
                    type="button"
                    className={styles.remove}
                    onClick={() => removeLine(line.key)}
                    aria-label={`Remove heading ${line.text}`}
                  >
                    Remove
                  </button>
                </div>
              ) : (
                <div className={styles.lineRow}>
                  <span className={styles.rowBody}>
                    <span className={styles.rowName}>{line.text}</span>
                    <span className={styles.rowMeta}>
                      {line.price === null
                        ? "the shop will price it"
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
                      {"-"}
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
                      className={styles.remove}
                      onClick={() => removeLine(line.key)}
                      aria-label={`Remove ${line.text}`}
                    >
                      Remove
                    </button>
                  </span>
                </div>
              )}
            </div>
          ))}

          <div className={styles.who}>
            <input
              className={styles.search}
              id="list_phone"
              value={phone}
              placeholder="Your phone number"
              inputMode="tel"
              aria-label="Your phone number"
              onChange={(event) => setPhone(event.target.value)}
            />
            <p className={styles.nothing}>
              So the shop knows whose list this is, and so you do not type it all again next time.
            </p>
            <input
              className={styles.search}
              id="list_name"
              value={name}
              placeholder="Your name (optional)"
              aria-label="Your name"
              onChange={(event) => setName(event.target.value)}
            />
          </div>
        </section>
      ) : null}

      {/* The bar that never leaves: a customer who cannot see his list assumes he has lost it. */}
      <div className={styles.bar}>
        <button
          type="button"
          className={styles.barList}
          onClick={() => setShowingList((open) => !open)}
          aria-expanded={showingList}
        >
          <span className={styles.barCount}>
            My list ({items.length} {items.length === 1 ? "item" : "items"})
          </span>
          <span className={styles.barTotal}>
            {items.length === 0
              ? "Empty"
              : `${formatMoneyOrOnRequest(total.toFixed(2))}${toBePriced > 0 ? ` + ${toBePriced} to price` : ""}`}
          </span>
          <span className={styles.barAction}>{showingList ? "Hide" : "Review"}</span>
        </button>
        <button
          type="button"
          id="send_list"
          className={styles.send}
          disabled={busy || items.length === 0}
          onClick={() => void send()}
        >
          {busy ? "Sending..." : "Send my list"}
        </button>
        {problem ? <p className={styles.problem}>{problem}</p> : null}
      </div>
    </main>
  );

  /**
   * The customer heading that matches the shop group they are browsing, if they made one.
   *
   * It answers `null` for "not browsing anything", which is what the caller has: making this require a string
   * would mean every call site asserting one it cannot prove.
   */
  function headingKeyFor(group: string | null): string | null {
    if (group === null) return null;
    return headings.find((line) => line.text.toLowerCase() === group.toLowerCase())?.key ?? null;
  }
}
