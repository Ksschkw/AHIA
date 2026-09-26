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

import { useEffect, useMemo, useState } from "react";

import {
  ChevronRightIcon,
  ItemBoxIcon,
  PhoneIcon,
  PlusIcon,
  SearchIcon,
  SparklesIcon,
  TrashIcon,
} from "@/components/icons";
import { EmptyBasketIllustration } from "@/components/illustrations";
import { getCustomerPastLists, type CustomerListSummary } from "@/lib/api";
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
  groupName?: string | null;
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

function parseQuickPaste(raw: string): Array<{ text: string; quantity: number }> {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      const leadingMatch = line.match(/^(\d+)\s*(?:x\s*|\*|\s+|-)?\s*(.+)$/i);
      if (leadingMatch && leadingMatch[2].trim().length > 0) {
        return {
          quantity: Math.max(1, parseInt(leadingMatch[1], 10)),
          text: leadingMatch[2].trim(),
        };
      }
      const trailingMatch = line.match(/^(.+?)\s*(?:-|\:|\s)\s*(\d+)\s*(?:pcs|pieces|pack|packs|ctn)?$/i);
      if (trailingMatch && trailingMatch[1].trim().length > 0) {
        return {
          quantity: Math.max(1, parseInt(trailingMatch[2], 10)),
          text: trailingMatch[1].trim(),
        };
      }
      return { quantity: 1, text: line };
    });
}

export function ListBuilder({ shop }: { shop: ListShop }) {
  const draftKey = `ahia.draft.${shop.tenant_slug}`;
  const historyKey = `ahia.history.${shop.tenant_slug}`;

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

  const [restoredDraft, setRestoredDraft] = useState(false);
  const [lastList, setLastList] = useState<ChosenLine[] | null>(null);
  const [isOffline, setIsOffline] = useState(false);
  const [quickPaste, setQuickPaste] = useState(false);
  const [quickPasteText, setQuickPasteText] = useState("");

  const headings = chosen.filter((line) => line.isHeading);
  const items = chosen.filter((line) => !line.isHeading);
  const total = items.reduce((running, line) => running + priceOf(line.price) * line.quantity, 0);
  const toBePriced = items.filter((line) => line.price === null).length;

  useEffect(() => {
    if (typeof window === "undefined") return;
    const handleOnline = () => setIsOffline(false);
    const handleOffline = () => setIsOffline(true);
    setIsOffline(!navigator.onLine);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const rawDraft = window.localStorage.getItem(draftKey);
      if (rawDraft) {
        const parsed = JSON.parse(rawDraft);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setChosen(parsed);
          setRestoredDraft(true);
        }
      } else {
        const rawHistory = window.localStorage.getItem(historyKey);
        if (rawHistory) {
          const parsed = JSON.parse(rawHistory);
          if (Array.isArray(parsed) && parsed.length > 0 && Array.isArray(parsed[0].lines)) {
            setLastList(parsed[0].lines);
          }
        }
      }
    } catch {
      // Ignore parse failure
    }
  }, [draftKey, historyKey]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (sent !== null) return;
    if (chosen.length > 0) {
      window.localStorage.setItem(draftKey, JSON.stringify(chosen));
    } else {
      window.localStorage.removeItem(draftKey);
    }
  }, [chosen, draftKey, sent]);

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

  const [pastLists, setPastLists] = useState<CustomerListSummary[] | null>(null);
  const [loadingPast, setLoadingPast] = useState(false);
  const [pastError, setPastError] = useState<string | null>(null);
  const [showPastSection, setShowPastSection] = useState(false);

  async function loadPastListsForCustomer() {
    const cleanPhone = phone.trim();
    if (cleanPhone.length < 7) {
      setProblem("Enter your phone number below first to find your previous lists.");
      setShowingList(true);
      return;
    }
    setLoadingPast(true);
    setPastError(null);
    try {
      const found = await getCustomerPastLists(shop.tenant_slug, cleanPhone);
      setPastLists(found);
      if (found.length === 0) {
        setPastError("No previous lists found for this phone number at this shop.");
      }
    } catch {
      setPastError("Could not fetch past lists. Please check your connection.");
    } finally {
      setLoadingPast(false);
    }
  }

  function loadFromPastList(list: CustomerListSummary) {
    const loadedLines: ChosenLine[] = list.lines.map((l, index) => ({
      key: `past-${list.id}-${l.position || index}`,
      productSlug: null,
      text: l.text,
      quantity: Number(l.quantity) || 1,
      price: l.shop_price ?? null,
      groupName: l.group ?? null,
      underKey: null,
      isHeading: false,
      note: "",
    }));
    setChosen(loadedLines);
    setShowPastSection(false);
    setShowingList(true);
    setProblem(null);
  }

  function addProduct(product: ListShopProduct, under: string | null = null) {
    setChosen((current) => {
      const existing = current.find((line) => line.productSlug === product.product_slug);
      if (existing) {
        return current.map((line) =>
          line.key === existing.key ? { ...line, quantity: line.quantity + 1 } : line,
        );
      }
      return [
        ...current,
        {
          key: `item-${product.product_slug}-${Date.now()}-${current.length}`,
          productSlug: product.product_slug,
          text: product.name,
          quantity: 1,
          price: product.selling_price,
          groupName: product.group_name ?? null,
          underKey: under,
          isHeading: false,
          note: "",
        },
      ];
    });
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
        groupName: null,
        underKey: ownUnder,
        isHeading: false,
        note: "",
      },
    ]);
    setOwnText("");
    setOwnQuantity("1");
    setProblem(null);
  }

  function changeQuantity(key: string, delta: number) {
    setChosen((current) =>
      current
        .map((line) => {
          if (line.key !== key) return line;
          const next = line.quantity + delta;
          return next <= 0 ? null : { ...line, quantity: next };
        })
        .filter((line): line is ChosenLine => line !== null),
    );
  }

  function removeLine(key: string) {
    // Taking a heading away takes what was under it, which is what a person means by deleting a heading.
    setChosen((current) => current.filter((line) => line.key !== key && line.underKey !== key));
  }

  /** The list, drawn as the paper it replaces: category headings, the things under them, and the counts. */
  async function drawList(): Promise<Blob | null> {
    const width = 900;
    const row = 46;

    // Group items:
    // 1. If customer created headings, group under customer headings.
    // 2. Otherwise (or for items not under customer headings), group by catalogue category (groupName).
    type Section = { title: string; lines: ChosenLine[]; isCustomerHeading?: boolean };
    const sections: Section[] = [];

    if (headings.length > 0) {
      for (const heading of headings) {
        const childItems = items.filter((line) => line.underKey === heading.key);
        sections.push({ title: heading.text, lines: childItems, isCustomerHeading: true });
      }
      const unassigned = items.filter((line) => line.underKey === null);
      if (unassigned.length > 0) {
        const byGroup = new Map<string, ChosenLine[]>();
        for (const item of unassigned) {
          const g = item.groupName ?? "Other Items";
          byGroup.set(g, [...(byGroup.get(g) ?? []), item]);
        }
        for (const [groupTitle, groupLines] of byGroup.entries()) {
          sections.push({ title: groupTitle, lines: groupLines });
        }
      }
    } else {
      const byGroup = new Map<string, ChosenLine[]>();
      for (const item of items) {
        const g = item.groupName ?? "Items";
        byGroup.set(g, [...(byGroup.get(g) ?? []), item]);
      }
      for (const [groupTitle, groupLines] of byGroup.entries()) {
        sections.push({ title: groupTitle, lines: groupLines });
      }
    }

    const totalLinesCount = items.length;
    const canvasHeight = Math.max(
      640,
      300 + totalLinesCount * row + sections.length * 64,
    );
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
    context.fillText("ORDER LIST", 48, 172);
    context.fillStyle = "#e7dfd2";
    context.fillRect(48, 186, width - 96, 2);

    let y = 236;
    for (const section of sections) {
      if (section.lines.length === 0) continue;

      // Draw Category Header banner
      context.fillStyle = "#f4f0e8";
      context.fillRect(48, y - 26, width - 96, 36);
      context.fillStyle = "#084a2f";
      context.fillRect(48, y - 26, 6, 36);

      context.font = "bold 20px system-ui, sans-serif";
      const sectionLabel =
        section.title.length > 55 ? `${section.title.slice(0, 54)}...` : section.title;
      context.fillText(sectionLabel.toUpperCase(), 64, y);
      y += 42;

      for (const line of section.lines) {
        context.fillStyle = "#1e1b16";
        context.font = "22px system-ui, sans-serif";
        const label = line.text.length > 46 ? `${line.text.slice(0, 45)}...` : line.text;
        context.fillText(label, 72, y);

        context.fillStyle = "#5c5549";
        context.font = "bold 22px system-ui, sans-serif";
        context.textAlign = "right";
        context.fillText(`${line.quantity} pcs`, width - 48, y);
        context.textAlign = "left";

        y += row;
      }
      y += 18;
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
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(draftKey);
        try {
          const past = JSON.parse(window.localStorage.getItem(historyKey) ?? "[]");
          const record = {
            date: new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short" }),
            count: items.length,
            lines: ordered,
          };
          const updated = [record, ...(Array.isArray(past) ? past.slice(0, 4) : [])];
          window.localStorage.setItem(historyKey, JSON.stringify(updated));
        } catch {
          // ignore error saving local history
        }
      }
      setRestoredDraft(false);
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
            <ChevronRightIcon size={12} className={styles.crumbSep} />
            <span className={styles.crumbNow}>{openGroup}</span>
          </nav>
        )}
      </header>

      {isOffline ? (
        <div className={styles.offlineAlert}>
          You are offline right now. Your list is saved safely on your phone and will be ready to send when your network returns.
        </div>
      ) : null}

      {restoredDraft && items.length > 0 ? (
        <div className={styles.bannerNotice}>
          <span className={styles.bannerText}>
            We kept your list from earlier ({items.length} {items.length === 1 ? "item" : "items"}).
          </span>
          <button
            type="button"
            className={styles.bannerAction}
            onClick={() => {
              setChosen([]);
              setRestoredDraft(false);
              if (typeof window !== "undefined") window.localStorage.removeItem(draftKey);
            }}
          >
            Start fresh
          </button>
        </div>
      ) : null}

      {!restoredDraft && chosen.length === 0 && lastList && lastList.length > 0 ? (
        <div className={styles.historyPrompt}>
          <div className={styles.historyHeader}>
            <span className={styles.historyTitle}>
              Start from your previous list? ({lastList.filter((l) => !l.isHeading).length} items)
            </span>
            <button
              type="button"
              className={styles.bannerAction}
              onClick={() => setLastList(null)}
            >
              Dismiss
            </button>
          </div>
          <button
            type="button"
            className={styles.historyAction}
            onClick={() => {
              setChosen(lastList);
              setLastList(null);
            }}
          >
            Load previous list
          </button>
        </div>
      ) : null}

      <section className={styles.section}>
        <label className={styles.searchLabel} htmlFor="list_search">
          What are you looking for?
        </label>
        <div className={styles.searchWrap}>
          <SearchIcon size={18} className={styles.searchIcon} />
          <input
            className={styles.search}
            id="list_search"
            value={query}
            placeholder="Type anything - 21D, privacy, charger"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        {found.length > 0 ? (
          <ul className={styles.rows}>
            {found.map((product) => {
              const currentLine = chosen.find((line) => line.productSlug === product.product_slug);
              return (
                <li key={product.product_slug} className={styles.row}>
                  <span className={styles.rowBody}>
                    <span className={styles.rowName}>{product.name}</span>
                    <span className={styles.rowMeta}>
                      {product.group_name ? `${product.group_name} - ` : ""}
                      {formatMoneyOrOnRequest(product.selling_price)}
                    </span>
                  </span>
                  {currentLine ? (
                    <div className={styles.stepperInline}>
                      <button
                        type="button"
                        className={styles.stepButtonSmall}
                        onClick={() => changeQuantity(currentLine.key, -1)}
                        aria-label={`One fewer ${product.name}`}
                      >
                        -
                      </button>
                      <span className={styles.stepValueSmall}>{currentLine.quantity}</span>
                      <button
                        type="button"
                        className={styles.stepButtonSmall}
                        onClick={() => changeQuantity(currentLine.key, 1)}
                        aria-label={`One more ${product.name}`}
                      >
                        +
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className={styles.addHere}
                      onClick={() => addProduct(product, openGroup ? headingKeyFor(openGroup) : null)}
                      aria-label={`Add ${product.name}`}
                    >
                      Add
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        ) : null}
        {query.trim().length >= 2 && found.length === 0 ? (
          <p className={styles.nothing}>Nothing by that name. Add it yourself below.</p>
        ) : null}
      </section>

      {openGroup !== null || query.trim().length < 2 || found.length > 0 ? (
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
                  <ChevronRightIcon size={16} className={styles.chev} />
                </li>
              ))}
            </ul>
          )}
          {specialsHere.length > 0 ? (
            <>
              <p className={styles.onlyThese}>Priced differently here:</p>
              <ul className={styles.rows}>
                {specialsHere.map((product) => {
                  const currentLine = chosen.find((line) => line.productSlug === product.product_slug);
                  return (
                    <li key={product.product_slug} className={styles.row}>
                      <span className={styles.rowBody}>
                        <span className={styles.rowName}>{product.name}</span>
                        <span className={styles.rowPrice}>
                          {formatMoneyOrOnRequest(product.selling_price)}
                        </span>
                      </span>
                      {currentLine ? (
                        <div className={styles.stepperInline}>
                          <button
                            type="button"
                            className={styles.stepButtonSmall}
                            onClick={() => changeQuantity(currentLine.key, -1)}
                            aria-label={`One fewer ${product.name}`}
                          >
                            -
                          </button>
                          <span className={styles.stepValueSmall}>{currentLine.quantity}</span>
                          <button
                            type="button"
                            className={styles.stepButtonSmall}
                            onClick={() => changeQuantity(currentLine.key, 1)}
                            aria-label={`One more ${product.name}`}
                          >
                            +
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className={styles.addHere}
                          onClick={() => addProduct(product, headingKeyFor(openGroup))}
                          aria-label={`Add ${product.name}`}
                        >
                          Add
                        </button>
                      )}
                    </li>
                  );
                })}
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
          <PlusIcon size={16} />
          <span>Can&apos;t find it? Add your own</span>
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
              <button
                type="button"
                className={styles.doneAddingBtn}
                onClick={() => setAddingOwn(false)}
              >
                Done
              </button>
            </div>
            <p className={styles.nothing}>The shop will put a price on it. Keep adding items or tap Done when finished.</p>

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

            <button
              type="button"
              className={styles.quickPasteToggle}
              onClick={() => setQuickPaste((open) => !open)}
            >
              <SparklesIcon size={15} />
              <span>{quickPaste ? "Hide quick paste" : "Paste list from WhatsApp"}</span>
            </button>
            {quickPaste ? (
              <div className={styles.quickPasteBox}>
                <p className={styles.nothing}>
                  Paste lines from WhatsApp, messages, or notes. One item per line:
                  <br />
                  e.g. 5 Hot 8 21D
                  <br />
                  e.g. 2 Camon 30
                  <br />
                  e.g. Charger Type C - 10pcs
                </p>
                <textarea
                  className={styles.search}
                  rows={4}
                  value={quickPasteText}
                  placeholder={"5 Hot 8 21D\n2 Camon 30\nCharger Type C - 10pcs"}
                  onChange={(event) => setQuickPasteText(event.target.value)}
                />
                <button
                  type="button"
                  className={styles.addHere}
                  style={{ alignSelf: "flex-start" }}
                  disabled={quickPasteText.trim().length === 0}
                  onClick={() => {
                    const parsed = parseQuickPaste(quickPasteText);
                    if (parsed.length === 0) return;
                    const newLines: ChosenLine[] = parsed.map((item, index) => {
                      const match = shop.products.find(
                        (p) => p.name.toLowerCase() === item.text.toLowerCase(),
                      );
                      return {
                        key: `paste-${Date.now()}-${index}`,
                        productSlug: match?.product_slug ?? null,
                        text: match?.name ?? item.text,
                        quantity: item.quantity,
                        price: match?.selling_price ?? null,
                        groupName: match?.group_name ?? null,
                        underKey: ownUnder,
                        isHeading: false,
                        note: "",
                      };
                    });
                    setChosen((current) => [...current, ...newLines]);
                    setQuickPasteText("");
                    setQuickPaste(false);
                  }}
                >
                  Add all to my list
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {showingList ? (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>My list</h2>
          {chosen.length === 0 ? (
            <div className={styles.emptyCartBox}>
              <EmptyBasketIllustration size={90} />
              <p className={styles.nothing}>Nothing on it yet. Add items from the shop above or type your own.</p>
            </div>
          ) : null}
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
                    <TrashIcon size={14} />
                    <span>Remove</span>
                  </button>
                </div>
              ) : (
                <div className={styles.lineRow}>
                  <span className={styles.rowBody}>
                    <span className={styles.rowNameRow}>
                      <ItemBoxIcon size={16} className={styles.rowItemIcon} />
                      <span className={styles.rowName}>{line.text}</span>
                    </span>
                    {line.groupName ? (
                      <span className={styles.categoryBadge}>{line.groupName}</span>
                    ) : null}
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
                      <TrashIcon size={14} />
                      <span>Remove</span>
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
            <button
              type="button"
              className={styles.historyAction}
              style={{ marginTop: "4px", display: "inline-flex", alignItems: "center", gap: "6px" }}
              disabled={loadingPast || phone.trim().length < 7}
              onClick={() => void loadPastListsForCustomer()}
            >
              <PhoneIcon size={14} />
              <span>{loadingPast ? "Finding your past lists..." : "Find past lists for this phone number"}</span>
            </button>
            {pastError ? <p className={styles.problem}>{pastError}</p> : null}
            {pastLists && pastLists.length > 0 ? (
              <div className={styles.pastListsSection}>
                <span className={styles.onlyThese}>Your previous orders with {shop.business_name}:</span>
                <div className={styles.pastListsGrid}>
                  {pastLists.map((past) => (
                    <div key={past.id} className={styles.pastListCard}>
                      <div className={styles.pastListRow}>
                        <span className={styles.pastListDate}>
                          {new Date(past.created_at).toLocaleDateString("en-GB", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })}
                        </span>
                        <span className={styles.pastListStatus}>{past.status}</span>
                      </div>
                      <div className={styles.pastListPreview}>
                        {past.lines.length} {past.lines.length === 1 ? "item" : "items"}:{" "}
                        {past.lines
                          .slice(0, 4)
                          .map((l) => `${Number(l.quantity)}x ${l.text}`)
                          .join(", ")}
                        {past.lines.length > 4 ? "..." : ""}
                      </div>
                      <button
                        type="button"
                        className={styles.pastListLoadBtn}
                        onClick={() => loadFromPastList(past)}
                      >
                        Load this list
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
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
