"use client";

/**
 * The lists customers have sent, and the work of answering them.
 *
 * This is the screen the trader uses every morning: a customer's list arrives, he walks the market with
 * it, and line by line he says **I have it**, **I will buy it**, or **I cannot get it** - writing down
 * what it cost him when he had to buy it, and what he charges for it. At the end he knows what the
 * order comes to and what he made on it, which is the one thing paper has never been able to tell him.
 *
 * Three decisions shape the screen:
 *
 * - **The line is the unit of work.** Everything he needs for one item is on one row, because he is
 *   holding the item in one hand and the phone in the other.
 * - **Nothing is hidden.** What the customer asked for, what he paid, what he charges and what he makes
 *   are all visible at once - including a margin that says nothing until both numbers are known.
 * - **He decides, always.** There is no suggested price, no maximum, and no rule about what a discount
 *   may be. The app does his arithmetic and never argues with him.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  CannotGetIcon,
  CheckMarkIcon,
  ClockIcon,
  ItemBoxIcon,
  PhoneIcon,
} from "@/components/icons";
import { EmptyRequestsIllustration } from "@/components/illustrations";
import { Button, Card, Empty, Field, Loading, Pill, Toast } from "@/components/ui";
import {
  LINE_STATES,
  dispatchCustomerList,
  cachedRead,
  confirmCustomerList,
  currentUser,
  getBusiness,
  listBusinesses,
  listCustomerLists,
  workListLine,
  type CustomerList,
  type CustomerListLine,
  type ListLineState,
  type Tenant,
} from "@/lib/api";
import { PinGate } from "@/components/pin-gate";
import { explainFailure } from "@/lib/errors";
import { formatMoneyOrOnRequest } from "@/lib/format";
import styles from "./lists.module.css";

type Notice = { message: string; tone: "good" | "bad"; hint?: string };

const STATE_LABEL: Record<string, string> = {
  somewhere: "Not looked at yet",
  have_it: "On the shelf",
  buy_it: "Going to the market",
  cannot_get: "Cannot get it",
};

export default function Lists() {
  const [business, setBusiness] = useState<Tenant | null>(null);
  const [lists, setLists] = useState<CustomerList[]>([]);
  const [state, setState] = useState<"loading" | "ready">("loading");
  const [openId, setOpenId] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  //: The action waiting on the question, if the person holding the phone has not answered yet.
  const [gated, setGated] = useState<{ run: () => void } | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  //: Keyed by **line**, not by list. One draft per list meant two fields on the same line shared one
  //: object, and the second keystroke was written from a stale copy of the first - so a cost typed
  //: before a price disappeared, and the line saved without it. A trader would have watched his own
  //: numbers vanish.
  const [drafts, setDrafts] = useState<Record<string, { cost: string; price: string }>>({});
  //: What he writes down on the way to the park: the transporter, the number, the cost, the link.
  const [dispatchDraft, setDispatchDraft] = useState({
    transporter: "",
    phone: "",
    waybill: "",
    cost: "",
    tracking: "",
  });
  const [adjustments, setAdjustments] = useState<Record<string, string>>({});

  const run = useCallback(async (key: string, action: () => Promise<void>, skipGate = false) => {
    // **Confirming a list is confirming money.** It is the moment a total stops being a suggestion and becomes
    // what a customer owes, so it is the third of the three actions the objective names for the PIN - and in
    // this product it is what "confirming a payout" means. Pricing a line stays ungated: a trader prices thirty
    // lines in a morning with a customer waiting, and a PIN asked for that often is a PIN people share.
    if (!skipGate && key.startsWith("confirm-")) {
      setGated({ run: () => void run(key, action, true) });
      return;
    }
    setBusyAction(key);
    setNotice(null);
    try {
      await action();
    } catch (error) {
      const explained = explainFailure(error);
      setNotice({ message: explained.message, hint: explained.hint, tone: "bad" });
    } finally {
      setBusyAction(null);
    }
  }, []);

  const load = useCallback(async (tenantId: string) => {
    const found = await listCustomerLists(tenantId);
    setLists(found);
    setState("ready");
    return found;
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await currentUser();
        const businesses = await listBusinesses();
        const remembered =
          typeof window === "undefined" ? null : window.localStorage.getItem("ahia.business");
        const chosen = businesses.find((candidate) => candidate.id === remembered) ?? businesses[0];
        if (!chosen) return;
        setBusiness(await getBusiness(chosen.id));
        // What we already had is painted before anything is asked for, so opening this screen on a
        // phone in a market does not start with an empty page and a wait.
        const rememberedLists = cachedRead<CustomerList[]>(
          `/api/v1/tenants/${chosen.id}/requests`,
        );
        if (rememberedLists) {
          setLists(rememberedLists);
          setState("ready");
        }
        await load(chosen.id);
      } catch {
        // The frame sends an unauthenticated visitor to sign in; nothing else to do here.
      }
    })();
  }, [load]);

  if (!business) {
    return (
      <main className={styles.page}>
        <Loading label="Opening your lists..." />
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Lists customers sent</h1>
        <p className={styles.lede}>
          Review customer requests, set your prices, and confirm orders.
        </p>
      </header>

      {state === "loading" ? <Loading label="Fetching the lists..." /> : null}

      {state === "ready" && lists.length === 0 ? (
        <Empty
          illustration={<EmptyRequestsIllustration size={110} />}
          action={
            business.slug ? (
              <Link
                href={`/shop/${business.slug}`}
                target="_blank"
                className={styles.openShopBtn}
              >
                View your public shop
              </Link>
            ) : null
          }
        >
          No customer lists yet.
          <br />
          Share your shop link with customers on WhatsApp and their orders will arrive directly here.
        </Empty>
      ) : null}

      {lists.map((list) => {
        const open = openId === list.id;
        const unpriced = list.unpriced_line_count;
        const adjustment = Number(adjustments[list.id] ?? "0");
        const total = Number(list.priced_total ?? "0");
        const afterAdjustment = Number.isFinite(adjustment) ? total - adjustment : total;

        return (
          <Card
            key={list.id}
            title={list.customer_name ?? list.customer_phone}
          >
            <div className={styles.listHead}>
              <span className={styles.meta}>
                <span className={styles.phoneMeta}>
                  <PhoneIcon size={14} />
                  <span>{list.customer_phone}</span>
                </span>
                <span> - </span>
                <span>{new Date(list.created_at).toLocaleString()}</span>
              </span>
              <div className={styles.headPills}>
                <Pill tone={list.status === "confirmed" ? "good" : "warn"}>
                  {list.status === "confirmed" ? "Confirmed" : `${list.lines.length} lines`}
                </Pill>
                {unpriced > 0 && list.status !== "confirmed" ? (
                  <Pill tone="warn">{unpriced} to price</Pill>
                ) : null}
              </div>
            </div>

            {list.note ? <p className={styles.note}>Note: {list.note}</p> : null}

            <div className={styles.headActions}>
              <Button
                busy={busyAction === `open-${list.id}`}
                onClick={() => setOpenId(open ? null : list.id)}
              >
                {open ? "Close" : "Work this list"}
              </Button>
              {!open ? (
                <span className={styles.totalPreview}>
                  {list.priced_total
                    ? formatMoneyOrOnRequest(list.priced_total)
                    : "Nothing priced yet"}
                </span>
              ) : null}
            </div>

            {open ? (
              <>
                <ul className={styles.lines}>
                  {list.lines.map((line) => {
                    if (line.note === "heading") {
                      return (
                        <li key={line.id} className={styles.sectionDivider}>
                          <span className={styles.sectionDividerTitle}>
                            {line.product_name ?? line.free_text}
                          </span>
                        </li>
                      );
                    }

                    const qtyNum = Number(line.quantity);
                    const qtyFormatted =
                      line.unit === "pack" && line.pieces_per_pack
                        ? `${qtyNum} packs (${Number(line.pieces)} pcs)`
                        : `${qtyNum} pcs`;
                    const itemName = line.product_name ?? line.free_text ?? "Item";
                    const isUnavailable = line.state === "cannot_get";

                    return (
                      <li
                        key={line.id}
                        className={`${styles.line} ${isUnavailable ? styles.lineUnavailable : ""}`}
                      >
                        <div className={styles.lineWho}>
                          {line.group_name ? (
                            <span className={styles.categoryBadge}>{line.group_name}</span>
                          ) : null}
                          <span className={styles.lineNameRow}>
                            <ItemBoxIcon size={16} className={styles.lineItemIcon} />
                            <span className={styles.lineName}>{itemName}</span>
                          </span>
                          <span className={styles.lineMeta}>
                            {qtyFormatted}
                            {line.note && line.note !== "heading" ? ` - ${line.note}` : ""}
                          </span>
                          {line.customer_price ? (
                            <span className={styles.lineMeta}>
                              Customer saw {formatMoneyOrOnRequest(line.customer_price)}
                            </span>
                          ) : null}
                        </div>

                        <div className={styles.compactPriceRow}>
                          <div className={styles.compactPriceField}>
                            <Field
                              label="Price"
                              id={`price_${line.id}`}
                              value={drafts[line.id]?.price ?? ""}
                              onChange={(value) =>
                                setDrafts((current) => ({
                                  ...current,
                                  [line.id]: { cost: current[line.id]?.cost ?? "", price: value },
                                }))
                              }
                              inputMode="decimal"
                              placeholder={line.shop_price ?? "0.00"}
                              optional
                            />
                          </div>
                          <Button
                            id={`save_${line.id}`}
                            busy={busyAction === `save-${line.id}`}
                            disabled={list.status === "confirmed"}
                            onClick={() =>
                              run(`save-${line.id}`, async () => {
                                const typed = drafts[line.id] ?? { cost: "", price: "" };
                                const updated = await workListLine(
                                  business.id,
                                  list.id,
                                  line.id,
                                  {
                                    ...(typed.price.trim()
                                      ? { shop_price: typed.price.trim() }
                                      : {}),
                                  },
                                );
                                setLists((current) =>
                                  current.map((one) => (one.id === updated.id ? updated : one)),
                                );
                                setDrafts((current) => ({
                                  ...current,
                                  [line.id]: { cost: "", price: "" },
                                }));
                                setNotice({
                                  message: `${itemName} saved.`,
                                  tone: "good",
                                });
                              })
                            }
                          >
                            Save
                          </Button>
                          <button
                            type="button"
                            className={isUnavailable ? styles.cannotGetOn : styles.cannotGetOff}
                            title={isUnavailable ? "Mark as available" : "Mark as cannot get"}
                            disabled={list.status === "confirmed"}
                            onClick={() =>
                              run(`state-${line.id}`, async () => {
                                const nextState = isUnavailable ? "have_it" : "cannot_get";
                                const updated = await workListLine(
                                  business.id,
                                  list.id,
                                  line.id,
                                  { state: nextState as NonNullable<ListLineState> },
                                );
                                setLists((current) =>
                                  current.map((one) => (one.id === updated.id ? updated : one)),
                                );
                              })
                            }
                          >
                            <CannotGetIcon size={14} />
                            <span>{isUnavailable ? "Cannot get" : "Cannot get?"}</span>
                          </button>
                        </div>

                        {line.line_total ? (
                          <p className={styles.lineTotal}>
                            <CheckMarkIcon size={14} className={styles.pricedCheck} />
                            <span>Comes to {formatMoneyOrOnRequest(line.line_total)}</span>
                            {line.margin
                              ? ` - you make ${formatMoneyOrOnRequest(line.margin)}`
                              : ""}
                          </p>
                        ) : (
                          <p className={styles.lineUnpriced}>
                            <ClockIcon size={14} className={styles.unpricedClock} />
                            <span>Not priced yet</span>
                          </p>
                        )}
                      </li>
                    );
                  })}
                </ul>

                <div className={styles.quote}>
                  <Field
                    label="Take off (optional)"
                    id={`adjust_${list.id}`}
                    value={adjustments[list.id] ?? ""}
                    onChange={(value) =>
                      setAdjustments((current) => ({ ...current, [list.id]: value }))
                    }
                    inputMode="decimal"
                    placeholder="0.00"
                    hint="Any amount. It is your shop."
                    optional
                  />
                  <p className={styles.quoteTotal}>
                    {list.priced_total
                      ? formatMoneyOrOnRequest(afterAdjustment.toFixed(2))
                      : "Nothing priced yet"}
                  </p>
                  <Button
                    id={`confirm_${list.id}`}
                    busy={busyAction === `confirm-${list.id}`}
                    disabled={list.status === "confirmed" || unpriced > 0}
                    onClick={() =>
                      run(`confirm-${list.id}`, async () => {
                        const confirmed = await confirmCustomerList(business.id, list.id);
                        setLists((current) =>
                          current.map((one) => (one.id === confirmed.id ? confirmed : one)),
                        );
                        setNotice({
                          message: `${list.customer_name ?? list.customer_phone} is confirmed.`,
                          hint: "The sale is recorded, and what you made is on each line.",
                          tone: "good",
                        });
                      })
                    }
                  >
                    {list.status === "confirmed" ? "Confirmed" : "Confirm this list"}
                  </Button>
                  {list.status === "confirmed" ? (
                    <div className={styles.dispatch}>
                      <h3 className={styles.dispatchTitle}>
                        {list.dispatched_at ? "How it went" : "Send it"}
                      </h3>
                      {list.dispatched_at ? (
                        <p className={styles.dispatchDone}>
                          {list.transporter_name ?? "Carried by hand"}
                          {list.waybill_number ? ` - waybill ${list.waybill_number}` : ""}
                          {list.dispatch_cost
                            ? ` - ${formatMoneyOrOnRequest(list.dispatch_cost)} to send`
                            : ""}
                        </p>
                      ) : null}
                      <div className={styles.dispatchRow}>
                        <Field
                          label="Who is carrying it"
                          id={`transporter_${list.id}`}
                          value={dispatchDraft.transporter}
                          onChange={(value) =>
                            setDispatchDraft((current) => ({ ...current, transporter: value }))
                          }
                          placeholder="Emeka Motors"
                          optional
                        />
                        <Field
                          label="Their number"
                          id={`transporter_phone_${list.id}`}
                          value={dispatchDraft.phone}
                          onChange={(value) =>
                            setDispatchDraft((current) => ({ ...current, phone: value }))
                          }
                          inputMode="tel"
                          optional
                        />
                        <Field
                          label="Waybill number"
                          id={`waybill_${list.id}`}
                          value={dispatchDraft.waybill}
                          onChange={(value) =>
                            setDispatchDraft((current) => ({ ...current, waybill: value }))
                          }
                          optional
                        />
                        <Field
                          label="What it cost to send"
                          id={`dispatch_cost_${list.id}`}
                          value={dispatchDraft.cost}
                          onChange={(value) =>
                            setDispatchDraft((current) => ({ ...current, cost: value }))
                          }
                          inputMode="decimal"
                          optional
                        />
                        <Field
                          label="Tracking link"
                          id={`tracking_${list.id}`}
                          value={dispatchDraft.tracking}
                          onChange={(value) =>
                            setDispatchDraft((current) => ({ ...current, tracking: value }))
                          }
                          optional
                        />
                        <Button
                          id={`dispatch_${list.id}`}
                          busy={busyAction === `dispatch-${list.id}`}
                          onClick={() =>
                            run(`dispatch-${list.id}`, async () => {
                              const updated = await dispatchCustomerList(business.id, list.id, {
                                ...(dispatchDraft.transporter.trim()
                                  ? { transporter_name: dispatchDraft.transporter.trim() }
                                  : {}),
                                ...(dispatchDraft.phone.trim()
                                  ? { transporter_phone: dispatchDraft.phone.trim() }
                                  : {}),
                                ...(dispatchDraft.waybill.trim()
                                  ? { waybill_number: dispatchDraft.waybill.trim() }
                                  : {}),
                                ...(dispatchDraft.cost.trim()
                                  ? { dispatch_cost: dispatchDraft.cost.trim() }
                                  : {}),
                                ...(dispatchDraft.tracking.trim()
                                  ? { tracking_url: dispatchDraft.tracking.trim() }
                                  : {}),
                              });
                              setLists((current) =>
                                current.map((one) => (one.id === updated.id ? updated : one)),
                              );
                              setNotice({
                                message: "Written down.",
                                hint: "It is on the list, where you will look for it.",
                                tone: "good",
                              });
                            })
                          }
                        >
                          {list.dispatched_at ? "Update it" : "Record the waybill"}
                        </Button>
                      </div>
                    </div>
                  ) : null}

                  {unpriced > 0 ? (
                    <p className={styles.blocked}>
                      {unpriced} {unpriced === 1 ? "line has" : "lines have"} no price yet. Price them
                      and this becomes a sale.
                    </p>
                  ) : null}
                </div>
              </>
            ) : null}
          </Card>
        );
      })}

      <p className={styles.foot}>
        <Link className={styles.footLink} href="/app">
          Back to the shop
        </Link>
      </p>

      {/* The moment the list becomes a sale, and the moment money exists. */}
      <PinGate
        open={gated !== null}
        reason="confirm this list - it is what the customer owes"
        onConfirmed={() => {
          gated?.run();
          setGated(null);
        }}
        onClose={() => setGated(null)}
      />

      {notice ? (
        <Toast
          message={notice.message}
          hint={notice.hint}
          tone={notice.tone}
          onDismiss={() => setNotice(null)}
        />
      ) : null}
    </main>
  );
}
