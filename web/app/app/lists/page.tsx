"use client";

/**
 * The unified Orders & Waybills screen for AHIA.
 *
 * Matches the mobile app's Lists tab identically:
 * - Header: "Orders & Waybills" with "+ Quick-Paste" button
 * - Filter tabs: "Unworked", "Worked", "All"
 * - Sub-filter chips for Worked orders: "All", "Priced Quotes", "Confirmed", "Dispatched", "With Payment"
 * - Card header: Customer name/phone, fulfillment badge (Waybill/Pickup), payment badge (Paid Full/Part Paid/Unpaid), trash icon, status badge, expand chevron
 * - Customer Payment Proof banner with "Accept & Record"
 * - Customer Fulfillment info
 * - Payment & Ledger Tracker card with collapsible itemized payment history
 * - Hierarchical collapsible category sections with lines
 * - Line item card with state badge, spec/variant note, price, market buy, profit, status cycle button, edit price button
 * - Waybill tracking banner
 * - List footer with Total Quoted, Auto-Price (sparkles), WhatsApp, Invoice (PDF/Print), Waybill, and Confirm (PIN gated)
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  BoxIcon,
  CannotGetIcon,
  CartIcon,
  CheckMarkIcon,
  ChevronDownIcon,
  EditIcon,
  ListIcon,
  PlusIcon,
  ReceiptIcon,
  ShareIcon,
  SparklesIcon,
  TrashIcon,
  TruckIcon,
} from "@/components/icons";
import { Field, Loading, Select, Sheet, Toast } from "@/components/ui";
import {
  confirmCustomerList,
  deleteCustomerList,
  dispatchCustomerList,
  getBusiness,
  listBusinesses,
  listCategories,
  listCustomerLists,
  listProducts,
  rememberedBusinessId,
  submitCustomerList,
  workListLine,
  type Category,
  type CustomerList,
  type CustomerListLine,
  type ListLineState,
  type ListPayment,
  type Product,
  type Tenant,
} from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { buildInvoiceHtml, printInvoice } from "@/lib/invoice";
import { hasBusinessPin, verifyBusinessPin } from "@/lib/pin";
import styles from "./lists.module.css";

function formatWaNumber(rawPhone: string | null | undefined): string | null {
  if (!rawPhone) return null;
  const digits = rawPhone.replace(/\D/g, "");
  if (!digits || digits.length < 7) return null;
  if (digits.startsWith("00234")) return digits.slice(2);
  if (digits.startsWith("234")) return digits;
  if (digits.startsWith("0")) return "234" + digits.slice(1);
  if (digits.length === 10) return "234" + digits;
  return digits;
}

function parseQuickPaste(raw: string): Array<{ text: string; quantity: string }> {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      const leadingMatch = line.match(/^(\d+)\s*(?:x\s*|\*|\s+|-)?\s*(.+)$/i);
      if (leadingMatch && leadingMatch[2].trim().length > 0) {
        return {
          quantity: String(Math.max(1, parseInt(leadingMatch[1], 10))),
          text: leadingMatch[2].trim(),
        };
      }
      const trailingMatch = line.match(/^(.+?)\s*(?:-|\:|\s)\s*(\d+)\s*(?:pcs|pieces|pack|packs|ctn)?$/i);
      if (trailingMatch && trailingMatch[1].trim().length > 0) {
        return {
          quantity: String(Math.max(1, parseInt(trailingMatch[2], 10))),
          text: trailingMatch[1].trim(),
        };
      }
      return { quantity: "1", text: line };
    });
}

function buildCategoryPath(catId: string, allCategories: Category[]): string {
  const cat = allCategories.find((c) => c.id === catId);
  if (!cat) return "";
  if (cat.parent_id) {
    const parentPath = buildCategoryPath(cat.parent_id, allCategories);
    return parentPath ? `${parentPath} > ${cat.name}` : cat.name;
  }
  return cat.name;
}

function groupCustomerListLines(
  lines: CustomerListLine[],
  allProducts: Product[] = [],
  allCategories: Category[] = [],
) {
  const rootMap = new Map<string, Map<string, CustomerListLine[]>>();

  for (const line of lines) {
    if (line.note === "heading") continue;

    let rawGroup = line.group_name?.trim();

    if (line.parent_position !== undefined && line.parent_position !== null && lines[line.parent_position]) {
      const parentHeading = lines[line.parent_position];
      const headingText = parentHeading.free_text?.trim() || parentHeading.product_name?.trim();
      if (headingText) {
        if (rawGroup && !rawGroup.toLowerCase().includes(headingText.toLowerCase())) {
          rawGroup = `${rawGroup} > ${headingText}`;
        } else if (!rawGroup) {
          rawGroup = headingText;
        }
      }
    }

    if ((!rawGroup || rawGroup === "General Items") && line.product_id && allProducts.length > 0) {
      const prod = allProducts.find((p) => p.id === line.product_id);
      if (prod?.category_id && allCategories.length > 0) {
        const catPath = buildCategoryPath(prod.category_id, allCategories);
        if (catPath) {
          rawGroup = rawGroup && rawGroup !== "General Items" ? `${catPath} > ${rawGroup}` : catPath;
        }
      }
    }

    if (line.note && line.note !== "heading") {
      const trimmedNote = line.note.trim();
      if (rawGroup && !rawGroup.toLowerCase().includes(trimmedNote.toLowerCase())) {
        rawGroup = `${rawGroup} > ${trimmedNote}`;
      } else if (!rawGroup) {
        rawGroup = trimmedNote;
      }
    }

    let root = "General Items";
    let sub: string | null = null;

    if (rawGroup) {
      if (rawGroup.includes(" > ")) {
        const parts = rawGroup.split(" > ").map((s: string) => s.trim()).filter(Boolean);
        root = parts[0] || "General Items";
        sub = parts.length > 1 ? parts.slice(1).join(" > ") : null;
      } else {
        root = rawGroup;
      }
    }

    const subKey = sub ?? "__direct__";
    if (!rootMap.has(root)) {
      rootMap.set(root, new Map());
    }
    const subs = rootMap.get(root)!;
    if (!subs.has(subKey)) {
      subs.set(subKey, []);
    }
    subs.get(subKey)!.push(line);
  }

  const sections: Array<{
    root: string;
    subs: Array<{ sub: string | null; lines: CustomerListLine[] }>;
  }> = [];

  for (const [root, subsMap] of rootMap.entries()) {
    const subList: Array<{ sub: string | null; lines: CustomerListLine[] }> = [];
    for (const [subKey, subLines] of subsMap.entries()) {
      subList.push({
        sub: subKey === "__direct__" ? null : subKey,
        lines: subLines,
      });
    }
    sections.push({ root, subs: subList });
  }

  return sections;
}

function getEffectiveCategoryPrice(catId: string, allCats: Category[]): { normal: string | null; wholesale: string | null } {
  const cat = allCats.find((c) => c.id === catId);
  if (!cat) return { normal: null, wholesale: null };
  const normal = cat.default_normal_price || null;
  const wholesale = cat.default_wholesale_price || null;
  if (normal || wholesale) return { normal, wholesale };
  if (cat.parent_id) return getEffectiveCategoryPrice(cat.parent_id, allCats);
  return { normal: null, wholesale: null };
}

function findBestPricesForLine(
  line: CustomerListLine,
  allProducts: Product[],
  allCats: Category[],
): { normal: string | null; wholesale: string | null; source: string | null } {
  if (line.product_id) {
    const prod = allProducts.find((p) => p.id === line.product_id);
    if (prod) {
      const normal = prod.effective_normal_price || prod.selling_price || null;
      const wholesale = prod.effective_wholesale_price || null;
      if (normal || wholesale) {
        return { normal, wholesale, source: prod.name };
      }
      if (prod.category_id) {
        const catPrices = getEffectiveCategoryPrice(prod.category_id, allCats);
        if (catPrices.normal || catPrices.wholesale) {
          return { normal: catPrices.normal, wholesale: catPrices.wholesale, source: "Category" };
        }
      }
    }
  }

  const nameToMatch = (line.product_name || line.free_text || "").toLowerCase().trim();
  if (nameToMatch) {
    const matched = allProducts.find(
      (p) => p.name.toLowerCase() === nameToMatch || nameToMatch.includes(p.name.toLowerCase()),
    );
    if (matched) {
      const normal = matched.effective_normal_price || matched.selling_price || null;
      const wholesale = matched.effective_wholesale_price || null;
      if (normal || wholesale) {
        return { normal, wholesale, source: matched.name };
      }
      if (matched.category_id) {
        const catPrices = getEffectiveCategoryPrice(matched.category_id, allCats);
        if (catPrices.normal || catPrices.wholesale) {
          return { normal: catPrices.normal, wholesale: catPrices.wholesale, source: "Category" };
        }
      }
    }
  }

  return { normal: null, wholesale: null, source: null };
}

function computeCustomerListPaid(list: CustomerList): number {
  if (list.payments && list.payments.length > 0) {
    return list.payments.reduce((acc, p) => acc + (Number(p.amount) || 0), 0);
  }
  return Number(list.amount_paid ?? list.advance_payment ?? 0);
}

export default function ListsPage() {
  const [business, setBusiness] = useState<Tenant | null>(null);
  const [lists, setLists] = useState<CustomerList[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [hasPin, setHasPin] = useState(false);
  const [state, setState] = useState<"loading" | "ready">("loading");
  const [notice, setNotice] = useState<{ message: string; tone: "good" | "bad" } | null>(null);

  // Filters & Tabs
  const [listFilterTab, setListFilterTab] = useState<"unworked" | "worked" | "all">("unworked");
  const [workedSubFilter, setWorkedSubFilter] = useState<"all" | "unconfirmed" | "confirmed" | "dispatched" | "paid">("all");
  const [deletedListIds, setDeletedListIds] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set<string>();
    try {
      const raw = window.localStorage.getItem("ahia_deleted_list_ids");
      return raw ? new Set<string>(JSON.parse(raw)) : new Set<string>();
    } catch {
      return new Set<string>();
    }
  });

  // Collapsible tracking
  const [expandedListIds, setExpandedListIds] = useState<Set<string>>(() => new Set());
  const [expandedPaymentListIds, setExpandedPaymentListIds] = useState<Set<string>>(() => new Set());
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});

  // Auto-pricing loading state
  const [autoPricingListId, setAutoPricingListId] = useState<string | null>(null);

  // Modals & Sheets
  const [showQuickPasteModal, setShowQuickPasteModal] = useState(false);
  const [quickPastePhone, setQuickPastePhone] = useState("");
  const [quickPasteName, setQuickPasteName] = useState("");
  const [quickPasteText, setQuickPasteText] = useState("");
  const [savingQuickPaste, setSavingQuickPaste] = useState(false);

  const [pricingLine, setPricingLine] = useState<{
    listId: string;
    lineId: string;
    itemName: string;
    categoryRoot: string;
  } | null>(null);
  const [priceInput, setPriceInput] = useState("");
  const [costInput, setCostInput] = useState("");
  const [applyPriceToAll, setApplyPriceToAll] = useState(false);
  const [savingPricing, setSavingPricing] = useState(false);

  const [paymentModalList, setPaymentModalList] = useState<CustomerList | null>(null);
  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("transfer");
  const [paymentNote, setPaymentNote] = useState("");
  const [savingPayment, setSavingPayment] = useState(false);

  const [dispatchModalList, setDispatchModalList] = useState<CustomerList | null>(null);
  const [transporterName, setTransporterName] = useState("");
  const [transporterPhone, setTransporterPhone] = useState("");
  const [waybillNumber, setWaybillNumber] = useState("");
  const [dispatchCost, setDispatchCost] = useState("");
  const [trackingUrl, setTrackingUrl] = useState("");
  const [savingDispatch, setSavingDispatch] = useState(false);

  const [invoiceModalList, setInvoiceModalList] = useState<CustomerList | null>(null);

  const [pinConfirmList, setPinConfirmList] = useState<CustomerList | null>(null);
  const [pinValue, setPinValue] = useState("");
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [savingConfirm, setSavingConfirm] = useState(false);

  const [listPendingDelete, setListPendingDelete] = useState<CustomerList | null>(null);

  const loadData = useCallback(async () => {
    try {
      const businesses = await listBusinesses();
      const remembered =
        typeof window === "undefined" ? null : window.localStorage.getItem("ahia.business");
      const chosen = businesses.find((b) => b.id === remembered) ?? businesses[0];

      if (chosen) {
        const [bizDetail, rawLists, prods, cats, pinExists] = await Promise.all([
          getBusiness(chosen.id).catch(() => null),
          listCustomerLists(chosen.id).catch(() => []),
          listProducts(chosen.id).catch(() => []),
          listCategories(chosen.id).catch(() => []),
          hasBusinessPin(chosen.id),
        ]);

        // Hydrate local payments
        const hydratedLists = rawLists.map((l) => {
          let localPayments: ListPayment[] = [];
          if (typeof window !== "undefined") {
            try {
              const stored = window.localStorage.getItem(`ahia.list_payments.${l.id}`);
              if (stored) localPayments = JSON.parse(stored);
            } catch {
              // ignore
            }
          }
          return {
            ...l,
            payments: localPayments.length > 0 ? localPayments : l.payments,
          };
        });

        setBusiness(bizDetail);
        setLists(hydratedLists);
        setProducts(prods);
        setCategories(cats);
        setHasPin(pinExists);

        // Auto-expand first unworked list if none expanded
        const firstUnworked = hydratedLists.find((l) => {
          const items = l.lines.filter((x) => x.note !== "heading");
          return l.status !== "confirmed" && items.some((x) => !x.shop_price);
        });
        if (firstUnworked) {
          setExpandedListIds(new Set([firstUnworked.id]));
        }
      }
      setState("ready");
    } catch {
      setState("ready");
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const isListWorked = useCallback((item: CustomerList): boolean => {
    if (item.status === "confirmed") return true;
    const items = item.lines.filter((l) => l.note !== "heading");
    if (items.length > 0 && items.every((l) => Boolean(l.shop_price))) return true;
    return false;
  }, []);

  const unworkedListsCount = useMemo(() => {
    return lists.filter((l) => !deletedListIds.has(l.id) && !isListWorked(l)).length;
  }, [lists, deletedListIds, isListWorked]);

  const workedListsCount = useMemo(() => {
    return lists.filter((l) => !deletedListIds.has(l.id) && isListWorked(l)).length;
  }, [lists, deletedListIds, isListWorked]);

  const totalListsCount = useMemo(() => {
    return lists.filter((l) => !deletedListIds.has(l.id)).length;
  }, [lists, deletedListIds]);

  const workedUnconfirmedCount = useMemo(() => {
    return lists.filter((l) => !deletedListIds.has(l.id) && isListWorked(l) && l.status !== "confirmed").length;
  }, [lists, deletedListIds, isListWorked]);

  const workedConfirmedCount = useMemo(() => {
    return lists.filter((l) => !deletedListIds.has(l.id) && l.status === "confirmed").length;
  }, [lists, deletedListIds]);

  const workedDispatchedCount = useMemo(() => {
    return lists.filter((l) => !deletedListIds.has(l.id) && Boolean(l.waybill_number)).length;
  }, [lists, deletedListIds]);

  const workedPaidCount = useMemo(() => {
    return lists.filter((l) => !deletedListIds.has(l.id) && computeCustomerListPaid(l) > 0).length;
  }, [lists, deletedListIds]);

  const visibleCustomerLists = useMemo(() => {
    const nonDeleted = lists.filter((l) => !deletedListIds.has(l.id));
    if (listFilterTab === "unworked") {
      return nonDeleted.filter((l) => !isListWorked(l));
    }
    if (listFilterTab === "worked") {
      const worked = nonDeleted.filter((l) => isListWorked(l));
      if (workedSubFilter === "unconfirmed") return worked.filter((l) => l.status !== "confirmed");
      if (workedSubFilter === "confirmed") return worked.filter((l) => l.status === "confirmed");
      if (workedSubFilter === "dispatched") return worked.filter((l) => Boolean(l.waybill_number));
      if (workedSubFilter === "paid") return worked.filter((l) => computeCustomerListPaid(l) > 0);
      return worked;
    }
    return nonDeleted;
  }, [lists, deletedListIds, listFilterTab, workedSubFilter, isListWorked]);

  const toggleSectionCollapse = (key: string) => {
    setCollapsedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleCycleLineState = async (listId: string, lineId: string, currentState: ListLineState) => {
    if (!business) return;
    const sequence: NonNullable<ListLineState>[] = ["have_it", "buy_it", "cannot_get", "somewhere"];
    const currentIdx = sequence.indexOf((currentState || "somewhere") as NonNullable<ListLineState>);
    const nextState = sequence[(currentIdx + 1) % sequence.length];
    try {
      const updated = await workListLine(business.id, listId, lineId, { state: nextState });
      setLists((prev) => prev.map((l) => (l.id === updated.id ? { ...l, lines: updated.lines } : l)));
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not update status.", tone: "bad" });
    }
  };

  const handleSavePricing = async () => {
    if (!business || !pricingLine) return;
    setSavingPricing(true);
    try {
      const updated = await workListLine(business.id, pricingLine.listId, pricingLine.lineId, {
        shop_price: priceInput.trim() || undefined,
        cost_price: costInput.trim() || undefined,
      });

      let currentList = updated;

      if (applyPriceToAll && pricingLine.categoryRoot) {
        const targetLines = currentList.lines.filter(
          (l) =>
            l.id !== pricingLine.lineId &&
            l.group_name?.includes(pricingLine.categoryRoot) &&
            !l.shop_price &&
            l.note !== "heading",
        );
        for (const line of targetLines) {
          try {
            currentList = await workListLine(business.id, currentList.id, line.id, {
              shop_price: priceInput.trim() || undefined,
              cost_price: costInput.trim() || undefined,
            });
          } catch {
            // ignore
          }
        }
      }

      setLists((prev) => prev.map((l) => (l.id === currentList.id ? currentList : l)));
      setPricingLine(null);
      setNotice({ message: "Item price updated!", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not save price.", tone: "bad" });
    } finally {
      setSavingPricing(false);
    }
  };

  const handleAutoPriceList = async (list: CustomerList) => {
    if (!business) return;
    const unpriced = list.lines.filter((l) => !l.shop_price && l.note !== "heading");
    if (unpriced.length === 0) {
      setNotice({ message: "All items in this list already have prices!", tone: "good" });
      return;
    }
    setAutoPricingListId(list.id);
    try {
      let updated = list;
      let pricedCount = 0;
      for (const line of unpriced) {
        const matched = findBestPricesForLine(line, products, categories);
        if (matched.normal || matched.wholesale) {
          try {
            updated = await workListLine(business.id, list.id, line.id, {
              shop_price: matched.wholesale || matched.normal,
              cost_price: line.cost_price || undefined,
            });
            pricedCount++;
          } catch {
            // ignore
          }
        }
      }
      setLists((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
      if (pricedCount > 0) {
        setNotice({ message: `Auto-priced ${pricedCount} item(s) from catalog!`, tone: "good" });
      } else {
        setNotice({ message: "No catalog matches found. Set prices manually.", tone: "bad" });
      }
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not auto-price list.", tone: "bad" });
    } finally {
      setAutoPricingListId(null);
    }
  };

  const handleRecordPayment = async () => {
    if (!business || !paymentModalList) return;
    const amt = Number(paymentAmount.trim());
    if (!Number.isFinite(amt) || amt <= 0) {
      setNotice({ message: "Please enter a valid payment amount.", tone: "bad" });
      return;
    }
    setSavingPayment(true);
    try {
      const paymentRecord: ListPayment = {
        id: `pay-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        amount: amt.toString(),
        date: new Date().toISOString(),
        note: paymentNote.trim() || "Order Payment",
        payment_method: paymentMethod,
      };

      const priorAdvance = Number(paymentModalList.amount_paid ?? paymentModalList.advance_payment ?? 0);
      const existingPayments =
        paymentModalList.payments && paymentModalList.payments.length > 0
          ? paymentModalList.payments
          : priorAdvance > 0
          ? [
              {
                id: `pay-advance-${paymentModalList.id}`,
                amount: priorAdvance.toString(),
                date: paymentModalList.created_at || new Date().toISOString(),
                note: "Advance Deposit",
                payment_method: "cash",
              },
            ]
          : [];

      const updatedPayments = [...existingPayments, paymentRecord];
      const newTotalPaid = updatedPayments.reduce((sum, p) => sum + (Number(p.amount) || 0), 0);

      const updatedList: CustomerList = {
        ...paymentModalList,
        payments: updatedPayments,
        amount_paid: newTotalPaid.toString(),
      };

      if (typeof window !== "undefined") {
        window.localStorage.setItem(`ahia.list_payments.${paymentModalList.id}`, JSON.stringify(updatedPayments));
      }

      setLists((prev) => prev.map((l) => (l.id === updatedList.id ? updatedList : l)));
      setPaymentModalList(null);
      setNotice({ message: `Recorded payment of ${formatMoney(amt.toString())}!`, tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not record payment.", tone: "bad" });
    } finally {
      setSavingPayment(false);
    }
  };

  const handleAcceptCustomerProof = (item: CustomerList, proofAmt: string, proofRef: string) => {
    setPaymentModalList(item);
    setPaymentAmount(proofAmt);
    setPaymentNote(`Customer transfer proof (Ref: ${proofRef})`);
  };

  const handleDispatchList = async () => {
    if (!business || !dispatchModalList) return;
    setSavingDispatch(true);
    try {
      const updated = await dispatchCustomerList(business.id, dispatchModalList.id, {
        transporter_name: transporterName.trim() || undefined,
        transporter_phone: transporterPhone.trim() || undefined,
        waybill_number: waybillNumber.trim() || undefined,
        dispatch_cost: dispatchCost.trim() || undefined,
        tracking_url: trackingUrl.trim() || undefined,
      });
      setLists((prev) => prev.map((l) => (l.id === updated.id ? { ...l, ...updated } : l)));
      setDispatchModalList(null);
      setNotice({ message: "Order dispatched with waybill tracking!", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not dispatch waybill.", tone: "bad" });
    } finally {
      setSavingDispatch(false);
    }
  };

  const handleConfirmOrder = async () => {
    if (!business || !pinConfirmList) return;
    const currentList = lists.find((l) => l.id === pinConfirmList.id) || pinConfirmList;
    const unpriced = currentList.lines.filter((l) => !l.shop_price && l.note !== "heading");
    if (unpriced.length > 0) {
      setConfirmError(`Cannot confirm order: ${unpriced.length} item(s) are unpriced.`);
      return;
    }
    if (hasPin) {
      if (!pinValue || pinValue.length < 4) {
        setConfirmError("Enter your 4-digit security PIN");
        return;
      }
      const isValid = await verifyBusinessPin(business.id, pinValue);
      if (!isValid) {
        setConfirmError("Incorrect business security PIN. Please try again.");
        return;
      }
    }
    setSavingConfirm(true);
    try {
      const confirmed = await confirmCustomerList(business.id, currentList.id);
      setLists((prev) => prev.map((l) => (l.id === confirmed.id ? { ...l, ...confirmed } : l)));
      setPinConfirmList(null);
      setPinValue("");
      setNotice({
        message: `Order from ${confirmed.customer_name || confirmed.customer_phone} confirmed!`,
        tone: "good",
      });
    } catch (err: unknown) {
      setConfirmError((err as Error)?.message || "Could not confirm order.");
    } finally {
      setSavingConfirm(false);
    }
  };

  const handleDeleteList = async (item: CustomerList) => {
    if (!business) return;
    try {
      await deleteCustomerList(business.id, item.id);
      setDeletedListIds((prev) => {
        const next = new Set(prev);
        next.add(item.id);
        if (typeof window !== "undefined") {
          window.localStorage.setItem("ahia_deleted_list_ids", JSON.stringify(Array.from(next)));
        }
        return next;
      });
      setLists((prev) => prev.filter((l) => l.id !== item.id));
      setListPendingDelete(null);
      setNotice({ message: "Order list deleted.", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not delete order list.", tone: "bad" });
    }
  };

  const handleQuickPasteSubmit = async () => {
    if (!business) return;
    if (!quickPastePhone.trim()) {
      setNotice({ message: "Customer phone number is required.", tone: "bad" });
      return;
    }
    const parsed = parseQuickPaste(quickPasteText);
    if (parsed.length === 0) {
      setNotice({ message: "Paste at least one line item (e.g. 2x 2.5mm cable).", tone: "bad" });
      return;
    }

    setSavingQuickPaste(true);
    try {
      const lines = parsed.map((item) => {
        const matchedProd = products.find((p) => p.name.toLowerCase() === item.text.toLowerCase());
        return {
          product_slug: matchedProd ? matchedProd.slug : null,
          free_text: matchedProd ? null : item.text,
          quantity: item.quantity,
          unit: "piece",
        };
      });

      await submitCustomerList(business.slug, {
        customer_phone: quickPastePhone.trim(),
        customer_name: quickPasteName.trim() || null,
        lines,
      });

      setShowQuickPasteModal(false);
      setQuickPastePhone("");
      setQuickPasteName("");
      setQuickPasteText("");
      setNotice({ message: `Order created with ${parsed.length} items!`, tone: "good" });
      void loadData();
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not create order.", tone: "bad" });
    } finally {
      setSavingQuickPaste(false);
    }
  };

  const handleShareQuoteOnWhatsApp = (list: CustomerList) => {
    const rawNumber = list.customer_phone;
    const cleanNumber = formatWaNumber(rawNumber);
    const shopName = business?.name ?? "Our Shop";

    const sections = groupCustomerListLines(list.lines, products, categories);
    let itemsSummary = "";
    for (const sec of sections) {
      itemsSummary += `\n*${sec.root.toUpperCase()}*\n`;
      for (const sub of sec.subs) {
        if (sub.sub) itemsSummary += ` _> ${sub.sub}_\n`;
        for (const line of sub.lines) {
          const priceStr = line.shop_price ? ` - ${formatMoney(line.shop_price)}` : " - to be confirmed";
          const statusStr = line.state === "cannot_get" ? " (UNAVAILABLE)" : "";
          itemsSummary += ` - ${line.quantity}x ${line.product_name ?? line.free_text}${priceStr}${statusStr}\n`;
        }
      }
    }

    const message =
      `Hello ${list.customer_name || "Customer"}, here is your order update from ${shopName}:\n` +
      itemsSummary +
      (list.priced_total ? `\n*Total: ${formatMoney(list.priced_total)}*\n` : "\n") +
      `Thank you for your business!`;

    const waUrl = cleanNumber
      ? `https://wa.me/${cleanNumber}?text=${encodeURIComponent(message)}`
      : `https://wa.me/?text=${encodeURIComponent(message)}`;

    window.open(waUrl, "_blank");
  };

  return (
    <main className={styles.page}>
      {state === "loading" ? <Loading label="Loading orders & waybills..." /> : null}

      {/* Header with Title and Quick-Paste Button */}
      <div className={styles.listsHeaderWrap}>
        <div className={styles.listsHeaderTop}>
          <div>
            <h2 className={styles.listsHeaderTitle}>Orders & Waybills</h2>
            <p className={styles.listsHeaderSubtitle}>
              {visibleCustomerLists.length} {listFilterTab} order{visibleCustomerLists.length === 1 ? "" : "s"}
            </p>
          </div>
          <button
            type="button"
            className={styles.quickPasteBtn}
            onClick={() => setShowQuickPasteModal(true)}
          >
            <PlusIcon size={14} />
            <span>Quick-Paste</span>
          </button>
        </div>

        {/* Filter Pills */}
        <div className={styles.listFilterPillsRow}>
          <button
            type="button"
            className={`${styles.listFilterPill} ${listFilterTab === "unworked" ? styles.listFilterPillActive : ""}`}
            onClick={() => setListFilterTab("unworked")}
          >
            Unworked ({unworkedListsCount})
          </button>
          <button
            type="button"
            className={`${styles.listFilterPill} ${listFilterTab === "worked" ? styles.listFilterPillActive : ""}`}
            onClick={() => setListFilterTab("worked")}
          >
            Worked ({workedListsCount})
          </button>
          <button
            type="button"
            className={`${styles.listFilterPill} ${listFilterTab === "all" ? styles.listFilterPillActive : ""}`}
            onClick={() => setListFilterTab("all")}
          >
            All ({totalListsCount})
          </button>
        </div>

        {/* Sub-filters for Worked */}
        {listFilterTab === "worked" && (
          <div className={styles.subFilterRow}>
            <button
              type="button"
              className={`${styles.subFilterChip} ${workedSubFilter === "all" ? styles.subFilterChipActive : ""}`}
              onClick={() => setWorkedSubFilter("all")}
            >
              All ({workedListsCount})
            </button>
            <button
              type="button"
              className={`${styles.subFilterChip} ${workedSubFilter === "unconfirmed" ? styles.subFilterChipActive : ""}`}
              onClick={() => setWorkedSubFilter("unconfirmed")}
            >
              Priced Quotes ({workedUnconfirmedCount})
            </button>
            <button
              type="button"
              className={`${styles.subFilterChip} ${workedSubFilter === "confirmed" ? styles.subFilterChipActive : ""}`}
              onClick={() => setWorkedSubFilter("confirmed")}
            >
              Confirmed ({workedConfirmedCount})
            </button>
            <button
              type="button"
              className={`${styles.subFilterChip} ${workedSubFilter === "dispatched" ? styles.subFilterChipActive : ""}`}
              onClick={() => setWorkedSubFilter("dispatched")}
            >
              Dispatched ({workedDispatchedCount})
            </button>
            <button
              type="button"
              className={`${styles.subFilterChip} ${workedSubFilter === "paid" ? styles.subFilterChipActive : ""}`}
              onClick={() => setWorkedSubFilter("paid")}
            >
              With Payment ({workedPaidCount})
            </button>
          </div>
        )}
      </div>

      {/* Empty State */}
      {visibleCustomerLists.length === 0 ? (
        <div className={styles.emptyBox}>
          <ListIcon size={36} style={{ color: "#6e7681" }} />
          <h3 className={styles.emptyTitle}>
            {listFilterTab === "unworked"
              ? "No unworked orders"
              : listFilterTab === "worked"
              ? "No worked orders yet"
              : "No customer orders"}
          </h3>
          <p className={styles.emptySubtitle}>
            {listFilterTab === "unworked"
              ? "All customer orders have been worked and priced! New orders from your public shop will appear here."
              : listFilterTab === "worked"
              ? "Orders you have quoted or confirmed will be grouped here."
              : "Tap 'Quick-Paste' above to paste a rough WhatsApp order note and generate an itemized quote."}
          </p>
        </div>
      ) : null}

      {/* List Cards */}
      {visibleCustomerLists.map((item) => {
        const sections = groupCustomerListLines(item.lines, products, categories);
        const isConfirmed = item.status === "confirmed";
        const isExpanded = expandedListIds.has(item.id);
        const unpricedCount = item.lines.filter((l) => !l.shop_price && l.note !== "heading").length;
        const totalPaid = computeCustomerListPaid(item);
        const grandTotalNum = (Number(item.priced_total) || 0) + (Number(item.dispatch_cost) || 0);
        const remainingBal = Math.max(0, grandTotalNum - totalPaid);
        const isFullyPaid = grandTotalNum > 0 && totalPaid >= grandTotalNum;
        const isPartPaid = totalPaid > 0 && totalPaid < grandTotalNum;
        const fulfillmentMode =
          item.fulfillment_type ??
          (item.note?.toLowerCase().includes("waybill") || item.waybill_number ? "waybill" : "pickup");

        return (
          <div key={item.id} className={styles.listCard}>
            {/* Header */}
            <div
              className={styles.listCardHeader}
              onClick={() => {
                setExpandedListIds((prev) => {
                  const next = new Set(prev);
                  if (next.has(item.id)) next.delete(item.id);
                  else next.add(item.id);
                  return next;
                });
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap", marginBottom: "4px" }}>
                  <span className={styles.listCustomerName}>
                    {item.customer_name || item.customer_phone}
                  </span>
                  <span className={`${styles.badgeSmall} ${fulfillmentMode === "waybill" ? styles.badgeWaybill : styles.badgePickup}`}>
                    {fulfillmentMode === "waybill" ? "Waybill" : "Pickup"}
                  </span>
                  <span
                    className={`${styles.badgeSmall} ${
                      isFullyPaid ? styles.badgePaid : isPartPaid ? styles.badgePartPaid : styles.badgeUnpaid
                    }`}
                  >
                    {isFullyPaid
                      ? "Paid Full"
                      : isPartPaid
                      ? `Part Paid (-${formatMoney(remainingBal.toString())})`
                      : "Unpaid"}
                  </span>
                </div>
                <div className={styles.listDate}>
                  {item.lines.length} items &bull; {item.priced_total ? formatMoney(item.priced_total) : "Unpriced"}
                  {unpricedCount > 0 ? ` &bull; ${unpricedCount} unpriced` : ""}
                </div>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <button
                  type="button"
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#f87171", padding: "4px" }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setListPendingDelete(item);
                  }}
                  title="Delete order"
                >
                  <TrashIcon size={16} />
                </button>
                <span className={`${styles.statusBadge} ${isConfirmed ? styles.statusConfirmed : styles.statusPending}`}>
                  {item.status.toUpperCase()}
                </span>
                <span
                  style={{
                    display: "inline-flex",
                    transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
                    transition: "transform 0.2s ease",
                    color: "var(--ink-2)",
                  }}
                >
                  <ChevronDownIcon size={16} />
                </span>
              </div>
            </div>

            {/* Expanded Body */}
            {isExpanded && (
              <div className={styles.cardExpandedBody}>
                {/* Customer Payment Proof Card */}
                {(() => {
                  const proofMatch = item.note?.match(/<!--\s*ahia-proof:({[\s\S]*?})\s*-->/);
                  let proofData: { amount?: string; ref?: string; at?: string } | null = null;
                  if (proofMatch) {
                    try {
                      proofData = JSON.parse(proofMatch[1]);
                    } catch {
                      // ignore
                    }
                  }
                  if (!proofData) return null;
                  return (
                    <div className={styles.customerProofCard}>
                      <div>
                        <div className={styles.customerProofTitle}>Customer Submitted Payment Receipt</div>
                        <div className={styles.customerProofAmount}>
                          {"\u20A6"}{Number(proofData.amount || 0).toLocaleString()} {proofData.ref ? `(Ref: ${proofData.ref})` : ""}
                        </div>
                        <div className={styles.customerProofDate}>
                          {proofData.at ? new Date(proofData.at).toLocaleString() : "Recently submitted"}
                        </div>
                      </div>
                      {!isFullyPaid && (
                        <button
                          type="button"
                          className={styles.customerProofAcceptBtn}
                          onClick={() => handleAcceptCustomerProof(item, proofData!.amount || "0", proofData!.ref || "")}
                        >
                          Accept & Record
                        </button>
                      )}
                    </div>
                  );
                })()}

                {/* Fulfillment Preference */}
                <div className={styles.fulfillmentRow}>
                  <span>CUSTOMER FULFILLMENT:</span>
                  <span className={`${styles.badgeSmall} ${fulfillmentMode === "waybill" ? styles.badgeWaybill : styles.badgePickup}`}>
                    {fulfillmentMode === "waybill"
                      ? "Waybill / Delivery (Customer Requested)"
                      : "In-Shop Pickup (Customer will collect)"}
                  </span>
                </div>

                {/* Payment & Ledger Tracker Card */}
                <div className={styles.paymentSummaryCard}>
                  <div className={styles.paymentSummaryRow}>
                    <div>
                      <div className={styles.paymentLabel}>TOTAL ORDER</div>
                      <div className={styles.paymentVal}>{formatMoney(grandTotalNum.toString())}</div>
                    </div>
                    <div>
                      <div className={styles.paymentLabel}>PAID SO FAR</div>
                      <div className={styles.paymentVal} style={{ color: "#15803d" }}>
                        {formatMoney(totalPaid.toString())}
                      </div>
                    </div>
                    <div>
                      <div className={styles.paymentLabel}>BALANCE DUE</div>
                      <div className={styles.paymentVal} style={{ color: remainingBal > 0 ? "#b91c1c" : "#15803d" }}>
                        {formatMoney(remainingBal.toString())}
                      </div>
                    </div>
                  </div>

                  {/* Payment History (Smartly collapsed by default) */}
                  {item.payments && item.payments.length > 0 ? (
                    <div style={{ marginTop: "12px", paddingTop: "8px", borderTop: "1px solid var(--line, #e7dfd2)" }}>
                      <div
                        style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", padding: "4px 0" }}
                        onClick={() => {
                          setExpandedPaymentListIds((prev) => {
                            const next = new Set(prev);
                            if (next.has(item.id)) next.delete(item.id);
                            else next.add(item.id);
                            return next;
                          });
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <span style={{ fontSize: "11px", fontWeight: 800, color: "var(--ink-2)" }}>
                            PAYMENT HISTORY ({item.payments.length})
                          </span>
                          <span style={{ fontSize: "11px", color: "#15803d", fontWeight: 700 }}>
                            {"\u20A6"}{Number(totalPaid || 0).toLocaleString()} paid
                          </span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "11px", color: "var(--ink-2)" }}>
                          <span>{expandedPaymentListIds.has(item.id) ? "Hide" : "Show"}</span>
                          <span
                            style={{
                              transform: expandedPaymentListIds.has(item.id) ? "rotate(180deg)" : "rotate(0deg)",
                              transition: "transform 0.2s ease",
                            }}
                          >
                            <ChevronDownIcon size={12} />
                          </span>
                        </div>
                      </div>

                      {expandedPaymentListIds.has(item.id) &&
                        item.payments.map((p, pIdx) => (
                          <div
                            key={p.id || pIdx}
                            style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0", fontSize: "12px" }}
                          >
                            <div>
                              <div style={{ fontWeight: 600, color: "var(--ink)" }}>
                                {p.note || (pIdx === 0 ? "Advance Deposit" : `Part Payment #${pIdx + 1}`)}
                              </div>
                              <div style={{ fontSize: "11px", color: "var(--ink-2)" }}>
                                {new Date(p.date).toLocaleString()} via {(p.payment_method || "transfer").toUpperCase()}
                              </div>
                            </div>
                            <div style={{ fontWeight: 700, color: "#15803d" }}>
                              +{formatMoney(p.amount.toString())}
                            </div>
                          </div>
                        ))}
                    </div>
                  ) : null}

                  <button
                    type="button"
                    className={styles.recordPaymentBtn}
                    onClick={() => {
                      setPaymentModalList(item);
                      setPaymentAmount(remainingBal > 0 ? remainingBal.toString() : "");
                      setPaymentNote("");
                    }}
                  >
                    <ReceiptIcon size={14} />
                    <span>{totalPaid === 0 ? "Record Advance Deposit / Payment" : "Add Part Payment"}</span>
                  </button>
                </div>

                {/* Hierarchical Collapsible Category Sections */}
                {sections.map((sec, idx) => {
                  const sectionKey = `${item.id}_${sec.root}`;
                  const isCollapsed = Boolean(collapsedSections[sectionKey]);
                  const secItemCount = sec.subs.reduce((acc, s) => acc + s.lines.length, 0);

                  return (
                    <div key={idx} className={styles.sectionBox}>
                      <div
                        className={styles.sectionHeader}
                        onClick={() => toggleSectionCollapse(sectionKey)}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span className={styles.sectionRootTitle}>{sec.root}</span>
                          <span style={{ fontSize: "11px", color: "var(--ink-2)" }}>
                            ({secItemCount} item{secItemCount === 1 ? "" : "s"})
                          </span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "11px", color: "#0284c7", fontWeight: 700 }}>
                          <span>{isCollapsed ? "Expand" : "Collapse"}</span>
                          <span
                            style={{
                              transform: isCollapsed ? "rotate(0deg)" : "rotate(180deg)",
                              transition: "transform 0.2s ease",
                            }}
                          >
                            <ChevronDownIcon size={12} />
                          </span>
                        </div>
                      </div>

                      {!isCollapsed &&
                        sec.subs.map((sub, sIdx) => {
                          const subKey = `${item.id}_${sec.root}_${sub.sub ?? "__direct__"}`;
                          const isSubCollapsed = sub.sub ? Boolean(collapsedSections[subKey]) : false;

                          return (
                            <div key={sIdx} className={styles.subSectionBox}>
                              {sub.sub && (
                                <div
                                  style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", cursor: "pointer" }}
                                  onClick={() => toggleSectionCollapse(subKey)}
                                >
                                  <span className={styles.subTitle}>&gt; {sub.sub} ({sub.lines.length})</span>
                                  <span style={{ fontSize: "10px", color: "var(--ink-2)" }}>
                                    {isSubCollapsed ? "Expand" : "Collapse"}
                                  </span>
                                </div>
                              )}

                              {!isSubCollapsed &&
                                sub.lines.map((line) => {
                                  const costNum = Number(line.cost_price ?? "0");
                                  const shopNum = Number(line.shop_price ?? "0");
                                  const hasBoth = Boolean(
                                    line.cost_price && line.shop_price && Number.isFinite(costNum) && Number.isFinite(shopNum),
                                  );
                                  const marginVal = shopNum - costNum;
                                  const isPositive = marginVal >= 0;

                                  return (
                                    <div key={line.id} className={styles.lineItem}>
                                      <div className={styles.lineMain}>
                                        <div className={styles.lineTitleRow}>
                                          <span className={styles.lineName}>
                                            {line.quantity}x {line.product_name ?? line.free_text}
                                          </span>
                                          <span
                                            className={`${styles.lineStateBadge} ${
                                              line.state === "have_it"
                                                ? styles.lineStateHaveIt
                                                : line.state === "buy_it"
                                                ? styles.lineStateBuyIt
                                                : line.state === "cannot_get"
                                                ? styles.lineStateCannotGet
                                                : styles.lineStateSomewhere
                                            }`}
                                          >
                                            {line.state === "have_it"
                                              ? "In Stock"
                                              : line.state === "buy_it"
                                              ? "Getting It"
                                              : line.state === "cannot_get"
                                              ? "Not Available"
                                              : "Not Checked"}
                                          </span>
                                        </div>

                                        {line.note && line.note !== "heading" && (
                                          <div style={{ fontSize: "11px", color: "#0284c7", fontStyle: "italic", marginTop: "2px" }}>
                                            Spec / Variant: {line.note}
                                          </div>
                                        )}

                                        <div className={styles.linePriceDetailRow}>
                                          <span className={styles.linePrice}>
                                            Price: {line.shop_price ? formatMoney(line.shop_price) : "Set Price"}
                                          </span>
                                          {line.cost_price && (
                                            <span className={styles.lineCost}>
                                              Market Buy: {formatMoney(line.cost_price)}
                                            </span>
                                          )}
                                          {hasBoth && (
                                            <span className={`${styles.lineMargin} ${isPositive ? styles.marginPositive : styles.marginNegative}`}>
                                              Profit: {isPositive ? "+" : ""}{formatMoney(marginVal.toString())}
                                            </span>
                                          )}
                                        </div>
                                      </div>

                                      <div className={styles.lineActions}>
                                        <button
                                          type="button"
                                          className={`${styles.lineStatusCycleBtn} ${
                                            line.state === "have_it"
                                              ? styles.lineStatusBtnHaveIt
                                              : line.state === "buy_it"
                                              ? styles.lineStatusBtnBuyIt
                                              : line.state === "cannot_get"
                                              ? styles.lineStatusBtnUnavailable
                                              : styles.lineStatusBtnSomewhere
                                          }`}
                                          onClick={() => handleCycleLineState(item.id, line.id, line.state)}
                                          title="Cycle status"
                                        >
                                          {line.state === "have_it" ? (
                                            <CheckMarkIcon size={14} />
                                          ) : line.state === "buy_it" ? (
                                            <CartIcon size={14} />
                                          ) : line.state === "cannot_get" ? (
                                            <CannotGetIcon size={14} />
                                          ) : (
                                            <CheckMarkIcon size={14} />
                                          )}
                                        </button>

                                        <button
                                          type="button"
                                          className={styles.linePriceBtn}
                                          onClick={() => {
                                            const best = findBestPricesForLine(line, products, categories);
                                            const initialShop = line.shop_price ?? best.wholesale ?? best.normal ?? "";
                                            const initialCost = line.cost_price ?? "";
                                            setPricingLine({
                                              listId: item.id,
                                              lineId: line.id,
                                              itemName: line.product_name ?? line.free_text ?? "Item",
                                              categoryRoot: sec.root,
                                            });
                                            setPriceInput(initialShop);
                                            setCostInput(initialCost);
                                            setApplyPriceToAll(false);
                                          }}
                                          title="Set price & cost"
                                        >
                                          <EditIcon size={14} />
                                        </button>
                                      </div>
                                    </div>
                                  );
                                })}
                            </div>
                          );
                        })}
                    </div>
                  );
                })}

                {/* Waybill Tracking Banner */}
                {item.waybill_number && (
                  <div className={styles.waybillBanner}>
                    <TruckIcon size={16} />
                    <span>
                      Dispatched: #{item.waybill_number} via {item.transporter_name ?? "Courier"}
                      {item.dispatch_cost ? ` (Cost: ${formatMoney(item.dispatch_cost)})` : ""}
                    </span>
                  </div>
                )}

                {/* List Total & Actions */}
                <div className={styles.listFooter}>
                  <div className={styles.listFooterTop}>
                    <div>
                      <div className={styles.totalLabel}>Total Quoted</div>
                      <div className={styles.totalAmount}>
                        {item.priced_total
                          ? formatMoney(item.priced_total)
                          : (() => {
                              const pricedSum = item.lines.reduce((acc, l) => {
                                const p = Number(l.shop_price ?? "0");
                                const q = Number(l.quantity) || 1;
                                return acc + (l.shop_price && Number.isFinite(p) ? p * q : 0);
                              }, 0);
                              return pricedSum > 0 ? `${formatMoney(pricedSum.toString())} (Partial)` : "Pending Pricing";
                            })()}
                      </div>
                    </div>
                    <span className={`${styles.statusPill} ${isConfirmed ? styles.statusPillConfirmed : styles.statusPillDraft}`}>
                      {isConfirmed ? "Confirmed" : "Draft"}
                    </span>
                  </div>

                  <div className={styles.footerActions}>
                    {item.lines.some((l) => !l.shop_price && l.note !== "heading") && !isConfirmed && (
                      <button
                        type="button"
                        className={styles.autoPriceBtn}
                        onClick={() => handleAutoPriceList(item)}
                        disabled={autoPricingListId === item.id}
                      >
                        <SparklesIcon size={14} />
                        <span>{autoPricingListId === item.id ? "Pricing..." : "Auto-Price"}</span>
                      </button>
                    )}

                    <button
                      type="button"
                      className={styles.waBtn}
                      onClick={() => handleShareQuoteOnWhatsApp(item)}
                    >
                      <ShareIcon size={14} />
                      <span>WhatsApp</span>
                    </button>

                    <button
                      type="button"
                      className={styles.invoiceBtn}
                      onClick={() => setInvoiceModalList(item)}
                    >
                      <ReceiptIcon size={14} />
                      <span>Invoice</span>
                    </button>

                    {isConfirmed && !item.waybill_number && (
                      <button
                        type="button"
                        className={styles.dispatchBtn}
                        onClick={() => {
                          setDispatchModalList(item);
                          setTransporterName(item.transporter_name ?? "");
                          setTransporterPhone(item.transporter_phone ?? "");
                          setWaybillNumber(item.waybill_number ?? "");
                          setDispatchCost(item.dispatch_cost ?? "");
                          setTrackingUrl(item.tracking_url ?? "");
                        }}
                      >
                        <TruckIcon size={14} />
                        <span>Waybill</span>
                      </button>
                    )}

                    {!isConfirmed && (
                      <button
                        type="button"
                        className={styles.confirmBtn}
                        onClick={() => {
                          setPinConfirmList(item);
                          setPinValue("");
                          setConfirmError(null);
                        }}
                      >
                        <CheckMarkIcon size={14} />
                        <span>Confirm</span>
                      </button>
                    )}

                    <button
                      type="button"
                      className={styles.deleteListBtn}
                      onClick={() => setListPendingDelete(item)}
                    >
                      <TrashIcon size={14} />
                      <span>Delete</span>
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* ---------------- MODALS / SHEETS ---------------- */}

      {/* Quick-Paste Order Sheet */}
      <Sheet open={showQuickPasteModal} title="Quick-Paste Customer Order" onClose={() => setShowQuickPasteModal(false)}>
        <p style={{ fontSize: "13px", color: "var(--ink-2)", marginBottom: "12px" }}>
          Paste a rough WhatsApp order or customer list. Lines like &quot;2x 2.5mm cable&quot; or &quot;switch - 10&quot; will be parsed automatically.
        </p>
        <Field
          label="Customer Phone"
          id="qp-phone"
          value={quickPastePhone}
          onChange={setQuickPastePhone}
          placeholder="08012345678"
        />
        <Field
          label="Customer Name"
          id="qp-name"
          value={quickPasteName}
          onChange={setQuickPasteName}
          placeholder="e.g. Chief Emeka"
          optional
        />
        <div style={{ marginTop: "12px" }}>
          <label htmlFor="qp-text" style={{ display: "block", fontSize: "12px", fontWeight: 700, marginBottom: "4px" }}>
            Paste Order Lines
          </label>
          <textarea
            id="qp-text"
            rows={6}
            style={{
              width: "100%",
              padding: "10px",
              borderRadius: "8px",
              border: "1px solid var(--line)",
              fontFamily: "inherit",
              fontSize: "13px",
              background: "var(--card)",
              color: "var(--ink)",
            }}
            placeholder={"2x 2.5mm Coleman cable\n10 packs switches - white\n1 ctn 18W LED bulb"}
            value={quickPasteText}
            onChange={(e) => setQuickPasteText(e.target.value)}
          />
        </div>
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button
            type="button"
            className={styles.quickPasteBtn}
            style={{ background: "var(--sand-2)", color: "var(--ink)" }}
            onClick={() => setShowQuickPasteModal(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            className={styles.quickPasteBtn}
            onClick={handleQuickPasteSubmit}
            disabled={savingQuickPaste || !quickPastePhone.trim() || !quickPasteText.trim()}
          >
            {savingQuickPaste ? "Creating Order..." : "Create Order"}
          </button>
        </div>
      </Sheet>

      {/* Pricing Sheet */}
      <Sheet
        open={pricingLine !== null}
        title={pricingLine ? `Set Price: ${pricingLine.itemName}` : "Set Price"}
        onClose={() => setPricingLine(null)}
      >
        <Field
          label="Selling / Wholesale Price"
          id="set-shop-price"
          value={priceInput}
          onChange={setPriceInput}
          placeholder="e.g. 5000"
          inputMode="decimal"
        />
        <Field
          label="Market Buy / Cost Price"
          id="set-cost-price"
          value={costInput}
          onChange={setCostInput}
          placeholder="e.g. 4200"
          inputMode="decimal"
          optional
        />
        <div style={{ display: "flex", alignItems: "center", gap: "8px", margin: "12px 0" }}>
          <input
            type="checkbox"
            id="apply-all-cat"
            checked={applyPriceToAll}
            onChange={(e) => setApplyPriceToAll(e.target.checked)}
          />
          <label htmlFor="apply-all-cat" style={{ fontSize: "12px", color: "var(--ink-2)", cursor: "pointer" }}>
            Apply this price to all similar unpriced items in &quot;{pricingLine?.categoryRoot}&quot;
          </label>
        </div>
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button
            type="button"
            className={styles.quickPasteBtn}
            style={{ background: "var(--sand-2)", color: "var(--ink)" }}
            onClick={() => setPricingLine(null)}
          >
            Cancel
          </button>
          <button
            type="button"
            className={styles.quickPasteBtn}
            onClick={handleSavePricing}
            disabled={savingPricing}
          >
            {savingPricing ? "Saving..." : "Save Price"}
          </button>
        </div>
      </Sheet>

      {/* Record Payment Sheet */}
      <Sheet
        open={paymentModalList !== null}
        title="Record Order Payment"
        onClose={() => setPaymentModalList(null)}
      >
        <Field
          label="Payment Amount"
          id="pay-amount"
          value={paymentAmount}
          onChange={setPaymentAmount}
          placeholder="e.g. 50000"
          inputMode="decimal"
        />
        <Select
          label="Payment Method"
          id="pay-method"
          value={paymentMethod}
          onChange={setPaymentMethod}
          options={[
            { value: "transfer", label: "Bank Transfer" },
            { value: "cash", label: "Cash" },
            { value: "pos", label: "POS / Card" },
            { value: "other", label: "Other" },
          ]}
        />
        <Field
          label="Note / Reference"
          id="pay-note"
          value={paymentNote}
          onChange={setPaymentNote}
          placeholder="e.g. Advance deposit, Part payment"
          optional
        />
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button
            type="button"
            className={styles.quickPasteBtn}
            style={{ background: "var(--sand-2)", color: "var(--ink)" }}
            onClick={() => setPaymentModalList(null)}
          >
            Cancel
          </button>
          <button
            type="button"
            className={styles.quickPasteBtn}
            onClick={handleRecordPayment}
            disabled={savingPayment || !paymentAmount.trim()}
          >
            {savingPayment ? "Saving..." : "Save Payment"}
          </button>
        </div>
      </Sheet>

      {/* Dispatch Waybill Sheet */}
      <Sheet
        open={dispatchModalList !== null}
        title="Waybill Logistics & Dispatch"
        onClose={() => setDispatchModalList(null)}
      >
        <Field
          label="Transporter / Carrier Name"
          id="wb-carrier"
          value={transporterName}
          onChange={setTransporterName}
          placeholder="e.g. ABC Transport, Chisco, Peace Mass"
        />
        <Field
          label="Transporter Contact Phone"
          id="wb-carrier-phone"
          value={transporterPhone}
          onChange={setTransporterPhone}
          placeholder="e.g. 08033334444"
          optional
        />
        <Field
          label="Waybill Number / Ticket"
          id="wb-number"
          value={waybillNumber}
          onChange={setWaybillNumber}
          placeholder="e.g. WB-99238"
        />
        <Field
          label="Delivery / Dispatch Cost"
          id="wb-cost"
          value={dispatchCost}
          onChange={setDispatchCost}
          placeholder="e.g. 3500"
          inputMode="decimal"
          optional
        />
        <Field
          label="Tracking Link (Optional)"
          id="wb-url"
          value={trackingUrl}
          onChange={setTrackingUrl}
          placeholder="https://..."
          optional
        />
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button
            type="button"
            className={styles.quickPasteBtn}
            style={{ background: "var(--sand-2)", color: "var(--ink)" }}
            onClick={() => setDispatchModalList(null)}
          >
            Cancel
          </button>
          <button
            type="button"
            className={styles.quickPasteBtn}
            onClick={handleDispatchList}
            disabled={savingDispatch || !waybillNumber.trim()}
          >
            {savingDispatch ? "Saving..." : "Save & Dispatch"}
          </button>
        </div>
      </Sheet>

      {/* Official Invoice Sheet */}
      <Sheet
        open={invoiceModalList !== null}
        title="Official Business Invoice"
        onClose={() => setInvoiceModalList(null)}
      >
        {invoiceModalList && (
          <div>
            <div
              style={{
                background: "var(--card)",
                border: "1px solid var(--line)",
                borderRadius: "10px",
                padding: "16px",
                marginBottom: "16px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "2px solid var(--leaf)", paddingBottom: "10px", marginBottom: "12px" }}>
                <div>
                  <div style={{ fontSize: "18px", fontWeight: 800, color: "var(--leaf-dark)" }}>
                    {business?.name || "Stall"}
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--ink-2)" }}>{business?.phone || "Commercial Merchant"}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: "16px", fontWeight: 800 }}>INVOICE</div>
                  <div style={{ fontSize: "12px", color: "var(--ink-2)" }}>INV-{invoiceModalList.id.slice(0, 8).toUpperCase()}</div>
                </div>
              </div>
              <div style={{ fontSize: "13px", marginBottom: "10px" }}>
                <strong>Billed To:</strong> {invoiceModalList.customer_name || invoiceModalList.customer_phone} ({invoiceModalList.customer_phone})
              </div>
              <div style={{ fontSize: "13px", fontWeight: 700, color: "var(--ink-2)", marginBottom: "4px" }}>
                Items ({invoiceModalList.lines.length}):
              </div>
              <div style={{ maxHeight: "160px", overflowY: "auto", border: "1px solid var(--line)", borderRadius: "6px", padding: "8px" }}>
                {invoiceModalList.lines.map((l) => (
                  <div key={l.id} style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", padding: "3px 0" }}>
                    <span>{l.quantity}x {l.product_name ?? l.free_text}</span>
                    <span style={{ fontWeight: 700 }}>{l.shop_price ? formatMoney(l.shop_price) : "Pending"}</span>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: "12px", textAlign: "right", fontSize: "16px", fontWeight: 800, color: "var(--leaf-dark)" }}>
                Total: {invoiceModalList.priced_total ? formatMoney(invoiceModalList.priced_total) : "Pending"}
              </div>
            </div>

            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <button
                type="button"
                className={styles.quickPasteBtn}
                style={{ background: "#25d366" }}
                onClick={() => handleShareQuoteOnWhatsApp(invoiceModalList)}
              >
                <ShareIcon size={14} />
                <span>Share on WhatsApp</span>
              </button>
              <button
                type="button"
                className={styles.quickPasteBtn}
                onClick={() => {
                  if (!business) return;
                  printInvoice(business, business, invoiceModalList, products, categories);
                }}
              >
                <ReceiptIcon size={14} />
                <span>Print / Save PDF</span>
              </button>
              <button
                type="button"
                className={styles.quickPasteBtn}
                style={{ background: "var(--sand-2)", color: "var(--ink)" }}
                onClick={() => setInvoiceModalList(null)}
              >
                Close
              </button>
            </div>
          </div>
        )}
      </Sheet>

      {/* PIN Confirmation Sheet */}
      <Sheet
        open={pinConfirmList !== null}
        title="Confirm Order & Payout"
        onClose={() => setPinConfirmList(null)}
      >
        <p style={{ fontSize: "13px", color: "var(--ink-2)", marginBottom: "14px" }}>
          Confirming locks this order total and records the transaction in your stall ledger.
        </p>
        {hasPin && (
          <div>
            <Field
              label="Enter 4-Digit Security PIN"
              id="pin-confirm"
              type="password"
              value={pinValue}
              onChange={setPinValue}
              placeholder="****"
            />
          </div>
        )}
        {confirmError ? <p style={{ color: "#cf222e", fontSize: "13px", margin: "8px 0" }}>{confirmError}</p> : null}
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button
            type="button"
            className={styles.quickPasteBtn}
            style={{ background: "var(--sand-2)", color: "var(--ink)" }}
            onClick={() => setPinConfirmList(null)}
          >
            Cancel
          </button>
          <button
            type="button"
            className={styles.quickPasteBtn}
            onClick={handleConfirmOrder}
            disabled={savingConfirm}
          >
            {savingConfirm ? "Confirming..." : "Confirm Order"}
          </button>
        </div>
      </Sheet>

      {/* Delete List Confirmation Sheet */}
      <Sheet
        open={listPendingDelete !== null}
        title="Delete Customer List"
        onClose={() => setListPendingDelete(null)}
      >
        <p style={{ fontSize: "14px", color: "var(--ink-2)", marginBottom: "16px" }}>
          Are you sure you want to delete this order from {listPendingDelete?.customer_name || listPendingDelete?.customer_phone}?
        </p>
        <div style={{ display: "flex", gap: "10px" }}>
          <button
            type="button"
            className={styles.quickPasteBtn}
            style={{ background: "var(--sand-2)", color: "var(--ink)" }}
            onClick={() => setListPendingDelete(null)}
          >
            Cancel
          </button>
          <button
            type="button"
            className={styles.quickPasteBtn}
            style={{ background: "#cf222e" }}
            onClick={() => listPendingDelete && handleDeleteList(listPendingDelete)}
          >
            Confirm Delete
          </button>
        </div>
      </Sheet>

      {notice ? <Toast message={notice.message} tone={notice.tone} onDismiss={() => setNotice(null)} /> : null}
    </main>
  );
}
