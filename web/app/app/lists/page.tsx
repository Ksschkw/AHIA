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

import { Button, Card, Empty, Field, Loading, Pill, Toast } from "@/components/ui";
import {
  LINE_STATES,
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
  const [notice, setNotice] = useState<Notice | null>(null);
  //: Keyed by **line**, not by list. One draft per list meant two fields on the same line shared one
  //: object, and the second keystroke was written from a stale copy of the first - so a cost typed
  //: before a price disappeared, and the line saved without it. A trader would have watched his own
  //: numbers vanish.
  const [drafts, setDrafts] = useState<Record<string, { cost: string; price: string }>>({});
  const [adjustments, setAdjustments] = useState<Record<string, string>>({});

  const run = useCallback(async (key: string, action: () => Promise<void>) => {
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
          Work through a list, line by line: say whether you have it, whether you are going to find it,
          and what it costs. What you paid and what you charge are both yours to set.
        </p>
      </header>

      {state === "loading" ? <Loading label="Fetching the lists..." /> : null}

      {state === "ready" && lists.length === 0 ? (
        <Empty>
          No lists yet. Share your shop link and the lists your customers build will arrive here.
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
                {list.customer_phone} - {new Date(list.created_at).toLocaleString()}
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
                  {list.lines.map((line) => (
                    <li key={line.id} className={styles.line}>
                      <div className={styles.lineWho}>
                        <span className={styles.lineName}>
                          {line.free_text ?? "Catalogue item"}
                        </span>
                        <span className={styles.lineMeta}>
                          {line.quantity} x {line.pieces} pieces
                          {line.note ? ` - ${line.note}` : ""}
                        </span>
                        {line.customer_price ? (
                          <span className={styles.lineMeta}>
                            customer saw {formatMoneyOrOnRequest(line.customer_price)}
                          </span>
                        ) : null}
                      </div>

                      <div className={styles.lineStates}>
                        {LINE_STATES.map((option) => (
                          <button
                            key={option.value}
                            type="button"
                            className={
                              line.state === option.value
                                ? styles.stateOn
                                : styles.stateOff
                            }
                            title={option.hint}
                            disabled={list.status === "confirmed"}
                            onClick={() =>
                              run(`state-${line.id}`, async () => {
                                const updated = await workListLine(
                                  business.id,
                                  list.id,
                                  line.id,
                                  { state: option.value as NonNullable<ListLineState> },
                                );
                                setLists((current) =>
                                  current.map((one) => (one.id === updated.id ? updated : one)),
                                );
                              })
                            }
                          >
                            {option.label}
                          </button>
                        ))}
                      </div>

                      <div className={styles.lineNumbers}>
                        <Field
                          label="It cost me"
                          id={`cost_${line.id}`}
                          value={drafts[line.id]?.cost ?? ""}
                          onChange={(value) =>
                            setDrafts((current) => ({
                              ...current,
                              [line.id]: { cost: value, price: current[line.id]?.price ?? "" },
                            }))
                          }
                          inputMode="decimal"
                          placeholder={line.cost_price ?? "0.00"}
                          optional
                        />
                        <Field
                          label="I am selling for"
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
                                  ...(typed.cost.trim() ? { cost_price: typed.cost.trim() } : {}),
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
                                message: `${line.free_text ?? "Line"} saved.`,
                                tone: "good",
                              });
                            })
                          }
                        >
                          Save this line
                        </Button>
                      </div>

                      {line.line_total ? (
                        <p className={styles.lineTotal}>
                          Comes to {formatMoneyOrOnRequest(line.line_total)}
                          {line.margin
                            ? ` - you make ${formatMoneyOrOnRequest(line.margin)}`
                            : ""}
                        </p>
                      ) : (
                        <p className={styles.lineUnpriced}>Not priced yet</p>
                      )}
                    </li>
                  ))}
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
