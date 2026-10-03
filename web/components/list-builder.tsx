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

import Link from "next/link";
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
import { downloadWaybillPdf, type WaybillDocument, type WaybillSection } from "@/lib/waybill-pdf";
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

function formatWaNumber(rawPhone: string | null | undefined): string | null {
  if (!rawPhone) return null;
  let digits = rawPhone.replace(/[^\d]/g, "");
  if (!digits) return null;
  if (digits.startsWith("234")) return digits;
  if (digits.startsWith("0")) return "234" + digits.slice(1);
  if (digits.length === 10 && (digits.startsWith("7") || digits.startsWith("8") || digits.startsWith("9"))) {
    return "234" + digits;
  }
  return digits;
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
  const [fulfillment, setFulfillment] = useState<"pickup" | "waybill">("pickup");
  const [deliveryCity, setDeliveryCity] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  interface SentInfo {
    count: number;
    listPath: string | null;
    requestId: string | null;
  }
  const [sent, setSent] = useState<SentInfo | null>(null);
  const [copiedLink, setCopiedLink] = useState(false);
  const [picture, setPicture] = useState<string | null>(null);

  const [restoredDraft, setRestoredDraft] = useState(false);
  const [lastList, setLastList] = useState<ChosenLine[] | null>(null);
  const [isOffline, setIsOffline] = useState(false);
  const [quickPaste, setQuickPaste] = useState(false);
  const [quickPasteText, setQuickPasteText] = useState("");
  const [includePrices, setIncludePrices] = useState(false);

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

  /** The full ancestor chain for the currently open group so customers can step back up through each parent. */
  const groupTrail = useMemo(() => {
    if (!openGroup) return [];
    const trail: string[] = [];
    let curr: string | null = openGroup;
    const visited = new Set<string>();
    while (curr && !visited.has(curr.toLowerCase())) {
      visited.add(curr.toLowerCase());
      trail.unshift(curr);
      const parent = shop.groups.find(
        (g) => g.name.toLowerCase() === curr!.toLowerCase(),
      )?.parent_name ?? null;
      curr = parent;
    }
    return trail;
  }, [openGroup, shop.groups]);

  const productsHere = useMemo(() => {
    if (openGroup === null) return [];
    const openLower = openGroup.toLowerCase();
    return shop.products.filter((product) => {
      if (!product.group_name) return false;
      const gLower = product.group_name.toLowerCase();
      const parts = gLower.split(" > ").map((p) => p.trim());
      return parts.includes(openLower) || gLower === openLower;
    });
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
      const inferredGroup = product.group_name || (openGroup ? groupTrail.join(" > ") : null);
      return [
        ...current,
        {
          key: `item-${product.product_slug}-${Date.now()}-${current.length}`,
          productSlug: product.product_slug,
          text: product.name,
          quantity: 1,
          price: product.selling_price,
          groupName: inferredGroup,
          underKey: under,
          isHeading: false,
          note: "",
        },
      ];
    });
    setProblem(null);
  }

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const addSlug = params.get("add");
    if (addSlug) {
      const match = shop.products.find((p) => p.product_slug === addSlug);
      if (match) {
        addProduct(match);
        setShowingList(true);
        const url = new URL(window.location.href);
        url.searchParams.delete("add");
        window.history.replaceState({}, "", url.toString());
      }
    }
  }, [shop.products]);

  function headingKeyFor(groupName: string | null): string | null {
    if (!groupName) return null;
    const match = headings.find(
      (h) =>
        h.text.toLowerCase() === groupName.toLowerCase() ||
        h.groupName?.toLowerCase() === groupName.toLowerCase(),
    );
    return match?.key ?? null;
  }

  function addHeading(asSub: boolean = false) {
    const text = newHeading.trim();
    if (text.length < 2) return;
    const key = `head-${Date.now()}`;
    const currentGroupPath = openGroup
      ? groupTrail.length > 0
        ? groupTrail.join(" > ")
        : openGroup
      : null;

    setChosen((current) => [
      ...current,
      {
        key,
        productSlug: null,
        text,
        quantity: 1,
        price: null,
        groupName: asSub && ownUnder ? null : currentGroupPath,
        underKey: asSub && ownUnder ? ownUnder : null,
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
    const currentGroupPath = openGroup
      ? groupTrail.length > 0
        ? groupTrail.join(" > ")
        : openGroup
      : null;
    setChosen((current) => [
      ...current,
      {
        key: `own-${Date.now()}-${current.length}`,
        productSlug: null,
        text,
        quantity: Math.max(1, Number(ownQuantity) || 1),
        price: null,
        groupName: currentGroupPath,
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

  function resolveGroupHierarchy(groupName: string | null, groups: ListShopGroup[]): string[] {
    if (!groupName || !groupName.trim()) return ["General Items"];

    // If groupName already contains hierarchy path (e.g. "Screenguard > 21D")
    if (groupName.includes(" > ")) {
      const parts = groupName.split(" > ").map((s) => s.trim()).filter(Boolean);
      if (parts.length > 0) return parts;
    }

    // Otherwise walk the parent_name links in groups
    const hierarchy: string[] = [];
    let current: string | null = groupName.trim();
    const visited = new Set<string>();
    while (current && !visited.has(current.toLowerCase())) {
      visited.add(current.toLowerCase());
      hierarchy.unshift(current);
      const foundGroup = groups.find((g) => g.name.toLowerCase() === current!.toLowerCase());
      current = foundGroup?.parent_name ? foundGroup.parent_name.trim() : null;
    }
    return hierarchy.length > 0 ? hierarchy : [groupName.trim()];
  }

  function resolveHeadingHierarchy(
    headingKey: string,
    allHeadings: ChosenLine[],
    shopGroups: ListShopGroup[],
  ): string[] {
    const hierarchy: string[] = [];
    let currentKey: string | null = headingKey;
    let topGroup: string | null = null;
    const visited = new Set<string>();

    while (currentKey && !visited.has(currentKey)) {
      visited.add(currentKey);
      const h = allHeadings.find((line) => line.key === currentKey);
      if (!h) break;
      hierarchy.unshift(h.text);
      if (h.groupName && !topGroup) {
        topGroup = h.groupName;
      }
      currentKey = h.underKey;
    }

    if (topGroup) {
      const parentParts = resolveGroupHierarchy(topGroup, shopGroups);
      return [...parentParts, ...hierarchy];
    }

    return hierarchy.length > 0 ? hierarchy : ["General Items"];
  }

  interface ResolvedSubSection {
    subName: string | null;
    lines: ChosenLine[];
  }

  interface ResolvedRootSection {
    rootName: string;
    subs: ResolvedSubSection[];
  }

  function buildHierarchicalSections(): ResolvedRootSection[] {
    const rootMap = new Map<string, Map<string, ChosenLine[]>>();

    function addLine(rootCategory: string, subCategory: string | null, line: ChosenLine) {
      const root = rootCategory.trim() || "General Items";
      const sub = subCategory ? subCategory.trim() : "__direct__";
      if (!rootMap.has(root)) {
        rootMap.set(root, new Map());
      }
      const subs = rootMap.get(root)!;
      if (!subs.has(sub)) {
        subs.set(sub, []);
      }
      subs.get(sub)!.push(line);
    }

    // Ensure customer custom headings appear even if no items added yet
    for (const h of headings) {
      const path = resolveHeadingHierarchy(h.key, headings, shop.groups);
      const root = path[0] || h.text;
      const sub = path.length > 1 ? path.slice(1).join(" > ") : null;
      if (!rootMap.has(root)) {
        rootMap.set(root, new Map());
      }
      if (sub && !rootMap.get(root)!.has(sub)) {
        rootMap.get(root)!.set(sub, []);
      }
    }

    for (const item of items) {
      let path: string[];
      if (item.underKey) {
        path = resolveHeadingHierarchy(item.underKey, headings, shop.groups);
      } else if (item.groupName) {
        path = resolveGroupHierarchy(item.groupName, shop.groups);
      } else {
        path = ["General Items"];
      }

      const root = path[0] || "General Items";
      const sub = path.length > 1 ? path.slice(1).join(" > ") : null;
      addLine(root, sub, item);
    }

    const sections: ResolvedRootSection[] = [];
    for (const [rootName, subsMap] of rootMap.entries()) {
      const subs: ResolvedSubSection[] = [];
      for (const [subKey, lines] of subsMap.entries()) {
        subs.push({
          subName: subKey === "__direct__" ? null : subKey,
          lines,
        });
      }
      sections.push({ rootName, subs });
    }
    return sections;
  }

  function downloadPdfDocument() {
    const structuredSections = buildHierarchicalSections();
    const pdfSections: WaybillSection[] = structuredSections.map((sec) => {
      const directSubs = sec.subs.filter((s) => s.subName === null);
      const namedSubs = sec.subs.filter((s) => s.subName !== null);
      const directItems = directSubs.flatMap((s) =>
        s.lines.map((l) => ({
          text: l.text,
          quantity: l.quantity,
          price: l.price ? formatMoneyOrOnRequest(l.price) : null,
        })),
      );
      const subsections = namedSubs.map((s) => ({
        subtitle: s.subName!,
        items: s.lines.map((l) => ({
          text: l.text,
          quantity: l.quantity,
          price: l.price ? formatMoneyOrOnRequest(l.price) : null,
        })),
      }));

      return {
        title: sec.rootName,
        items: directItems.length > 0 ? directItems : undefined,
        subsections: subsections.length > 0 ? subsections : undefined,
      };
    });

    const doc: WaybillDocument = {
      shopName: shop.business_name,
      customerName: name.trim() || "A Customer",
      customerPhone: phone.trim() || shop.contact_phone || "Not specified",
      date: new Date().toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
      }),
      includePrices,
      totalPrice: includePrices
        ? toBePriced > 0
          ? `${formatMoneyOrOnRequest(total.toFixed(2))} + ${toBePriced} to price`
          : formatMoneyOrOnRequest(total.toFixed(2))
        : null,
      sections: pdfSections,
    };

    const safeShopName = shop.tenant_slug || "market";
    const dateStr = new Date().toISOString().slice(0, 10);
    downloadWaybillPdf(doc, `${safeShopName}-waybill-${dateStr}.pdf`);
  }

  /** The list, drawn as the paper it replaces: category headings, the things under them, and the counts. */
  async function drawList(): Promise<Blob | null> {
    const width = 900;
    const row = 44;

    const sections = buildHierarchicalSections();

    const totalLinesCount = items.length;
    let totalSubsCount = 0;
    for (const sec of sections) {
      for (const sub of sec.subs) {
        if (sub.subName !== null) totalSubsCount++;
      }
    }
    const canvasHeight = Math.max(
      640,
      320 + totalLinesCount * row + sections.length * 52 + totalSubsCount * 32,
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
    context.fillText(
      includePrices ? "ORDER LIST" : "ORDER WAYBILL",
      48,
      172,
    );
    context.fillStyle = "#e7dfd2";
    context.fillRect(48, 186, width - 96, 2);

    let y = 236;
    for (const sec of sections) {
      // Draw Root Category Header banner
      context.fillStyle = "#eef4f0";
      context.fillRect(48, y - 24, width - 96, 36);
      context.fillStyle = "#084a2f";
      context.fillRect(48, y - 24, 6, 36);

      context.fillStyle = "#084a2f";
      context.font = "bold 20px system-ui, sans-serif";
      const rootLabel =
        sec.rootName.length > 55 ? `${sec.rootName.slice(0, 54)}...` : sec.rootName;
      context.fillText(rootLabel.toUpperCase(), 64, y + 2);
      y += 44;

      for (const sub of sec.subs) {
        if (sub.subName !== null) {
          context.fillStyle = "#2d3748";
          context.font = "bold 17px system-ui, sans-serif";
          context.fillText(`>  ${sub.subName}`, 70, y);
          context.fillStyle = "#e2e8f0";
          context.fillRect(70, y + 6, width - 128, 1);
          y += 28;
        }

        for (const line of sub.lines) {
          context.fillStyle = "#1e1b16";
          context.font = "22px system-ui, sans-serif";
          const indent = sub.subName !== null ? 86 : 72;
          const displayName = line.text;
          const maxChars = includePrices ? 38 : 46;
          const label =
            displayName.length > maxChars
              ? `${displayName.slice(0, maxChars - 1)}...`
              : displayName;
          context.fillText(label, indent, y);

          context.fillStyle = "#084a2f";
          context.font = "bold 22px system-ui, sans-serif";
          context.textAlign = "right";

          if (includePrices && line.price) {
            context.fillText(`${line.quantity} pcs`, width - 180, y);
            context.fillStyle = "#5c5549";
            context.font = "20px system-ui, sans-serif";
            context.fillText(formatMoneyOrOnRequest(line.price), width - 48, y);
          } else {
            context.fillText(`${line.quantity} pcs`, width - 48, y);
          }
          context.textAlign = "left";

          y += row;
        }
        y += 8;
      }
      y += 16;
    }

    context.fillStyle = "#e7dfd2";
    context.fillRect(48, y + 8, width - 96, 2);
    context.fillStyle = "#084a2f";
    context.font = "bold 24px system-ui, sans-serif";
    if (includePrices) {
      context.fillText(
        toBePriced > 0
          ? `${formatMoneyOrOnRequest(total.toFixed(2))} + ${toBePriced} to price`
          : formatMoneyOrOnRequest(total.toFixed(2)),
        48,
        y + 54,
      );
    } else {
      context.fillText(
        `Total: ${items.length} ${items.length === 1 ? "item" : "items"}`,
        48,
        y + 54,
      );
    }
    context.fillStyle = "#8b8377";
    context.font = "18px system-ui, sans-serif";
    context.fillText("Sent with AHIA - Alaba & Trade Fair Market Operating System", 48, y + 90);

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

      const fulfillmentText = fulfillment === "waybill"
        ? `[Waybill / Delivery] Destination: ${deliveryCity.trim() || "To be arranged"}`
        : `[In-Shop Pickup]`;

      const response = await fetch(`/shop/${shop.tenant_slug}/requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_phone: phone.trim(),
          customer_name: name.trim() || null,
          note: fulfillmentText,
          lines: payload,
        }),
      });
      const body = (await response.json().catch(() => null)) as
        | { request_id?: string; line_count?: number; list_path?: string; error?: { message?: string } }
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
            listPath: body?.list_path ?? null,
          };
          const updated = [record, ...(Array.isArray(past) ? past.slice(0, 4) : [])];
          window.localStorage.setItem(historyKey, JSON.stringify(updated));
        } catch {
          // ignore error saving local history
        }
      }
      setRestoredDraft(false);
      setSent({
        count: body?.line_count ?? items.length,
        listPath: body?.list_path ?? null,
        requestId: body?.request_id ?? null,
      });
    } catch {
      setProblem("We could not reach the shop. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  function shareOnWhatsApp() {
    const cleanNumber = formatWaNumber(shop.contact_phone);
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    const listUrl = sent?.listPath ? `${origin}${sent.listPath}` : `${origin}/list/${shop.tenant_slug}`;
    const structuredSections = buildHierarchicalSections();

    let itemsSummary = "";
    for (const sec of structuredSections) {
      itemsSummary += `\n*${sec.rootName.toUpperCase()}*\n`;
      for (const sub of sec.subs) {
        if (sub.subName) {
          itemsSummary += ` _> ${sub.subName}_\n`;
        }
        for (const line of sub.lines) {
          const pricePart = includePrices && line.price ? ` - ${formatMoneyOrOnRequest(line.price)}` : "";
          itemsSummary += ` - ${line.quantity}x ${line.text}${pricePart}\n`;
        }
      }
    }

    const message =
      `Hello ${shop.business_name}, here is my order list (${items.length} items):\n` +
      itemsSummary +
      `\nOpen & Edit Live Order: ${listUrl}\n` +
      `Customer: ${name.trim() || "Customer"} (${phone.trim()})`;

    const waUrl = cleanNumber
      ? `https://wa.me/${cleanNumber}?text=${encodeURIComponent(message)}`
      : `https://wa.me/?text=${encodeURIComponent(message)}`;

    window.open(waUrl, "_blank");
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
      shareOnWhatsApp();
    } catch {
      // A share somebody cancelled is not a failure worth telling them about.
    }
  }

  if (sent !== null) {
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    const listUrl = sent.listPath ? `${origin}${sent.listPath}` : `${origin}/list/${shop.tenant_slug}`;

    return (
      <main className={styles.page}>
        <section className={styles.done}>
          <h1 className={styles.doneTitle}>Your list has reached {shop.business_name}</h1>
          <p className={styles.doneText}>
            {sent.count} {sent.count === 1 ? "item" : "items"} recorded. They will get back to you on {phone}.
          </p>

          <div className={styles.referenceCard}>
            <div className={styles.referenceHeader}>
              <span className={styles.referenceBadge}>Order Reference Link</span>
              <span style={{ fontSize: "12px", color: "var(--ink-3)" }}>Share or edit anytime</span>
            </div>
            <div className={styles.referenceUrlBox}>
              <span>{listUrl}</span>
            </div>
            <div className={styles.referenceActions}>
              <button
                type="button"
                className={styles.referenceCopyBtn}
                onClick={() => {
                  void navigator.clipboard.writeText(listUrl);
                  setCopiedLink(true);
                  setTimeout(() => setCopiedLink(false), 2500);
                }}
              >
                {copiedLink ? "Link Copied!" : "Copy Reference Link"}
              </button>
              {sent.listPath ? (
                <Link href={sent.listPath} className={styles.referenceOpenBtn}>
                  Open Live Order Tracker
                </Link>
              ) : null}
              <button
                type="button"
                className={styles.referenceReorderBtn}
                onClick={() => {
                  setSent(null);
                  setShowingList(false);
                }}
              >
                Build Another List
              </button>
            </div>
          </div>

          <div className={styles.doneActions}>
            <button type="button" className={styles.primary} onClick={shareOnWhatsApp}>
              Send on WhatsApp (Direct Link & Breakdown)
            </button>
            <button
              type="button"
              className={styles.secondaryPdf}
              onClick={downloadPdfDocument}
            >
              Download Printable Order List
            </button>
          </div>
          {picture ? (
            <>
              <p className={styles.doneText}>
                This is the waybill list generated from your order. Keep your downloaded copy for transporters, market drivers, and physical waybills.
              </p>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className={styles.preview} src={picture} alt="Your list" />
            </>
          ) : null}
        </section>
      </main>
    );
  }

  const customHeadingsHere = useMemo(() => {
    const currentScope = openGroup
      ? groupTrail.length > 0
        ? groupTrail.join(" > ")
        : openGroup
      : null;
    return headings.filter((h) => {
      if (currentScope === null) {
        return !h.groupName && !h.underKey;
      }
      const hGroup = (h.groupName ?? "").toLowerCase();
      const scopeLower = currentScope.toLowerCase();
      return hGroup === scopeLower || hGroup.includes(scopeLower);
    });
  }, [headings, openGroup, groupTrail]);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.kicker}>Sending a list to</p>
        <h1 className={styles.shopName}>{shop.business_name}</h1>
        <nav className={styles.crumbs} aria-label="Where you are">
          {groupTrail.length === 0 ? (
            <span className={styles.crumbNow}>All of the shop</span>
          ) : (
            <>
              <button
                type="button"
                className={styles.crumbLink}
                onClick={() => setOpenGroup(null)}
              >
                All of the shop
              </button>
              {groupTrail.map((crumb, idx) => {
                const isLast = idx === groupTrail.length - 1;
                return (
                  <span key={crumb} className={styles.crumbItem}>
                    <ChevronRightIcon size={12} className={styles.crumbSep} />
                    {isLast ? (
                      <span className={styles.crumbNow}>{crumb}</span>
                    ) : (
                      <button
                        type="button"
                        className={styles.crumbLink}
                        onClick={() => setOpenGroup(crumb)}
                      >
                        {crumb}
                      </button>
                    )}
                  </span>
                );
              })}
            </>
          )}
        </nav>
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
            placeholder="Type anything - items, brands, models, packs"
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

          {/* Custom Subcategories inside this group / scope */}
          {customHeadingsHere.length > 0 ? (
            <div style={{ marginTop: "12px", borderTop: "1px dashed var(--line)", paddingTop: "12px" }}>
              <p className={styles.onlyThese} style={{ color: "var(--leaf-dark)", fontWeight: 700 }}>
                Your custom {openGroup ? "subcategories" : "categories"} in {openGroup || "the shop"}:
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {customHeadingsHere.map((h) => {
                  const itemsUnderH = items.filter((it) => it.underKey === h.key);
                  return (
                    <div
                      key={h.key}
                      style={{
                        background: "var(--sand-2)",
                        border: "1px solid var(--line-strong)",
                        borderRadius: "var(--radius-sm)",
                        padding: "10px",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          marginBottom: itemsUnderH.length > 0 ? "8px" : "0",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span style={{ fontWeight: 800, fontSize: "14px", color: "var(--ink)" }}>
                            {h.text}
                          </span>
                          <span
                            style={{
                              fontSize: "11px",
                              fontWeight: 700,
                              background: "var(--leaf-soft)",
                              color: "var(--leaf-dark)",
                              padding: "2px 6px",
                              borderRadius: "4px",
                            }}
                          >
                            Custom Subcategory
                          </span>
                        </div>
                        <button
                          type="button"
                          className={styles.addHere}
                          style={{ fontSize: "12px", padding: "4px 8px" }}
                          onClick={() => {
                            setOwnUnder(h.key);
                            setAddingOwn(true);
                          }}
                        >
                          + Add item here
                        </button>
                      </div>

                      {itemsUnderH.length > 0 ? (
                        <ul className={styles.rows} style={{ marginTop: "6px" }}>
                          {itemsUnderH.map((line) => (
                            <li key={line.key} className={styles.row}>
                              <span className={styles.rowBody}>
                                <span className={styles.rowName}>{line.text}</span>
                                {includePrices && line.price ? (
                                  <span className={styles.rowMeta}>{formatMoneyOrOnRequest(line.price)}</span>
                                ) : null}
                              </span>
                              <div className={styles.stepperInline}>
                                <button
                                  type="button"
                                  className={styles.stepButtonSmall}
                                  onClick={() => changeQuantity(line.key, -1)}
                                  aria-label={`One fewer ${line.text}`}
                                >
                                  -
                                </button>
                                <span className={styles.stepValueSmall}>{line.quantity}</span>
                                <button
                                  type="button"
                                  className={styles.stepButtonSmall}
                                  onClick={() => changeQuantity(line.key, 1)}
                                  aria-label={`One more ${line.text}`}
                                >
                                  +
                                </button>
                              </div>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {productsHere.length > 0 ? (
            <div style={{ marginTop: "12px" }}>
              <p className={styles.onlyThese}>Items in {openGroup}:</p>
              <ul className={styles.rows}>
                {productsHere.map((product) => {
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
            </div>
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
            {openGroup || ownUnder ? (
              <div
                style={{
                  marginBottom: "8px",
                  padding: "6px 10px",
                  background: "var(--leaf-soft)",
                  borderRadius: "6px",
                  fontSize: "12px",
                  color: "var(--leaf-dark)",
                  fontWeight: 700,
                }}
              >
                Target category:{" "}
                {ownUnder
                  ? resolveHeadingHierarchy(ownUnder, headings, shop.groups).join(" > ")
                  : groupTrail.length > 0
                    ? groupTrail.join(" > ")
                    : openGroup}
              </div>
            ) : null}
            <input
              className={styles.search}
              id="list_own_text"
              value={ownText}
              placeholder={
                ownUnder
                  ? `Item name inside ${resolveHeadingHierarchy(ownUnder, headings, shop.groups).slice(-1)[0]}...`
                  : openGroup
                    ? `Item name for ${openGroup}...`
                    : "What do you want? e.g. universal metal frame"
              }
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

            <p className={styles.onlyThese}>
              {openGroup
                ? `Create a subcategory inside ${openGroup}:`
                : "Or start your own category / heading:"}
            </p>
            <div className={styles.ownRow}>
              <input
                className={styles.search}
                id="list_new_heading"
                value={newHeading}
                placeholder={
                  openGroup
                    ? `e.g. Ceramic, Privacy, 21D (inside ${openGroup})`
                    : "e.g. Screenguard, Chargers, Pouches"
                }
                onChange={(event) => setNewHeading(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addHeading(Boolean(ownUnder));
                  }
                }}
              />
              {ownUnder ? (
                <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                  <button type="button" className={styles.addHere} onClick={() => addHeading(false)}>
                    + Top heading
                  </button>
                  <button type="button" className={styles.addHere} onClick={() => addHeading(true)}>
                    + Subheading
                  </button>
                </div>
              ) : (
                <button type="button" className={styles.addHere} onClick={() => addHeading(false)}>
                  {openGroup ? "+ Add Subcategory" : "+ Add Heading"}
                </button>
              )}
            </div>
            {headings.length > 0 ? (
              <div className={styles.chooseUnder}>
                <span className={styles.onlyThese}>Put the next thing under:</span>
                <button
                  type="button"
                  className={ownUnder === null ? styles.underOn : styles.underOff}
                  onClick={() => setOwnUnder(null)}
                >
                  {openGroup ? `Direct in ${openGroup}` : "Nothing - top of my list"}
                </button>
                {headings.map((heading) => {
                  const resolvedPath = resolveHeadingHierarchy(heading.key, headings, shop.groups).join(" > ");
                  return (
                    <button
                      key={heading.key}
                      type="button"
                      className={ownUnder === heading.key ? styles.underOn : styles.underOff}
                      onClick={() => setOwnUnder(heading.key)}
                    >
                      {resolvedPath}
                    </button>
                  );
                })}
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
                  e.g. 5 Units Model A
                  <br />
                  e.g. 2 Fast Chargers
                  <br />
                  e.g. 10 Pcs Heavy Duty
                </p>
                <textarea
                  className={styles.search}
                  rows={4}
                  value={quickPasteText}
                  placeholder={"5 Units Model A\n2 Fast Chargers\n10 Pcs Heavy Duty"}
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
          {items.length === 0 && headings.length === 0 ? (
            <p className={styles.nothing}>Your list is empty. Pick items from the catalog or type your own.</p>
          ) : (
            <div className={styles.reviewHierarchicalWrap}>
              {buildHierarchicalSections().map((sec) => {
                const totalSecItems = sec.subs.reduce((acc, s) => acc + s.lines.length, 0);
                const isCustomHeading = headings.some((h) => h.text.toLowerCase() === sec.rootName.toLowerCase());
                const headingLine = headings.find((h) => h.text.toLowerCase() === sec.rootName.toLowerCase());

                return (
                  <div key={sec.rootName} className={styles.reviewGroup}>
                    <div className={styles.reviewGroupHeader}>
                      <span className={styles.reviewGroupTitle}>{sec.rootName}</span>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span className={styles.reviewGroupCount}>
                          {totalSecItems} {totalSecItems === 1 ? "item" : "items"}
                        </span>
                        {isCustomHeading && headingLine ? (
                          <button
                            type="button"
                            className={styles.remove}
                            onClick={() => removeLine(headingLine.key)}
                            aria-label={`Remove heading ${sec.rootName}`}
                          >
                            <TrashIcon size={14} />
                          </button>
                        ) : null}
                      </div>
                    </div>

                    {sec.subs.map((sub) => (
                      <div key={sub.subName || "__direct__"} className={styles.reviewSubGroup}>
                        {sub.subName ? (
                          <div className={styles.reviewSubHeader}>
                            <span className={styles.reviewSubIcon}>&rsaquo;</span>
                            <span className={styles.reviewSubTitle}>{sub.subName}</span>
                          </div>
                        ) : null}
                        <div className={styles.reviewLinesList}>
                          {sub.lines.length === 0 ? (
                            <p className={styles.nothing} style={{ padding: "8px 12px", margin: 0 }}>
                              No items yet under this heading.
                            </p>
                          ) : (
                            sub.lines.map((line) => (
                              <div key={line.key} className={styles.lineRow}>
                                <span className={styles.rowBody}>
                                  <span className={styles.rowNameRow}>
                                    <ItemBoxIcon size={16} className={styles.rowItemIcon} />
                                    <span className={styles.rowName}>{line.text}</span>
                                  </span>
                                  {includePrices ? (
                                    <span className={styles.rowMeta}>
                                      {line.price === null ? "Price to be confirmed" : formatMoneyOrOnRequest(line.price)}
                                    </span>
                                  ) : null}
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
                            ))
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          )}

          {chosen.length > 0 ? (
            <div className={styles.trustModeCard}>
              <div className={styles.trustModeHeader}>
                <span className={styles.trustModeBadge}>
                  {includePrices ? "Catalog Prices Included" : "Quantities Only"}
                </span>
                <button
                  type="button"
                  className={styles.trustModeToggleBtn}
                  onClick={() => setIncludePrices((p) => !p)}
                >
                  {includePrices ? "Show Quantities Only" : "Show Catalog Prices"}
                </button>
              </div>
              <div className={styles.waybillDownloadRow} style={{ marginTop: "10px" }}>
                <button
                  type="button"
                  className={styles.pdfDownloadBtn}
                  onClick={downloadPdfDocument}
                >
                  Download Printable Order List
                </button>
              </div>
            </div>
          ) : null}

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

            <div style={{ marginTop: "12px" }}>
              <label style={{ display: "block", fontSize: "12px", fontWeight: "600", color: "#334155", marginBottom: "6px" }}>
                How do you want to collect your items?
              </label>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button
                  type="button"
                  style={{
                    flex: "1 1 120px",
                    padding: "8px 12px",
                    fontSize: "13px",
                    fontWeight: "600",
                    borderRadius: "6px",
                    border: fulfillment === "pickup" ? "2px solid #084a2f" : "1px solid #cbd5e1",
                    backgroundColor: fulfillment === "pickup" ? "#f0fdf4" : "#ffffff",
                    color: fulfillment === "pickup" ? "#084a2f" : "#475569",
                    cursor: "pointer",
                  }}
                  onClick={() => setFulfillment("pickup")}
                >
                  In-Shop Pickup
                </button>
                <button
                  type="button"
                  style={{
                    flex: "1 1 120px",
                    padding: "8px 12px",
                    fontSize: "13px",
                    fontWeight: "600",
                    borderRadius: "6px",
                    border: fulfillment === "waybill" ? "2px solid #084a2f" : "1px solid #cbd5e1",
                    backgroundColor: fulfillment === "waybill" ? "#f0fdf4" : "#ffffff",
                    color: fulfillment === "waybill" ? "#084a2f" : "#475569",
                    cursor: "pointer",
                  }}
                  onClick={() => setFulfillment("waybill")}
                >
                  Waybill / Delivery
                </button>
              </div>
              {fulfillment === "waybill" ? (
                <input
                  className={styles.search}
                  style={{ marginTop: "8px" }}
                  value={deliveryCity}
                  placeholder="Delivery destination (e.g. Onitsha, Aba, Lagos, Kano park)"
                  aria-label="Delivery destination"
                  onChange={(event) => setDeliveryCity(event.target.value)}
                />
              ) : null}
            </div>
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
              : includePrices
                ? `${formatMoneyOrOnRequest(total.toFixed(2))}${toBePriced > 0 ? ` + ${toBePriced} to price` : ""}`
                : "Trust Mode (Quantities only)"}
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
}
