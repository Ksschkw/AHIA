"use client";

/**
 * The price book: what a group costs, and the items that differ.
 *
 * A trader thinks in grades. "All of the 21D are 350" is one number, so this screen is built around
 * that sentence: each heading carries the price everything under it uses, and an item only gets its own
 * price when it is genuinely an exception - Hot 8 at 370 while the rest of the 21D stays at 350.
 *
 * Two prices, both his: the **normal** price is what the shop page shows a browsing customer, and the
 * **wholesale** price is what a list is priced with. There is no tier machinery and nothing to
 * configure - just the numbers he sets, overridable on any line when he wants to.
 *
 * Clearing an item's price is a real action, and it is how an exception stops being one: it goes back
 * to following its group.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Brand, Wordmark } from "@/components/brand";
import { PinGate } from "@/components/pin-gate";
import { Button, Card, Field, Pill, Select, Toast } from "@/components/ui";
import {
  createCategory,
  currentUser,
  getBusiness,
  listBusinesses,
  listCategories,
  listProducts,
  moveItemToGroup,
  setGroupPrices,
  setItemPrices,
  type Category,
  type Product,
  type Tenant,
} from "@/lib/api";
import { explainFailure } from "@/lib/errors";
import { formatMoneyOrOnRequest } from "@/lib/format";
import styles from "./prices.module.css";

type Notice = { message: string; tone: "good" | "bad"; hint?: string };

interface GroupDraft {
  normal: string;
  wholesale: string;
  pack: string;
}

export default function Prices() {
  const router = useRouter();
  const [business, setBusiness] = useState<Tenant | null>(null);
  const [groups, setGroups] = useState<Category[]>([]);
  const [items, setItems] = useState<Product[]>([]);
  const [drafts, setDrafts] = useState<Record<string, GroupDraft>>({});
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [newGroup, setNewGroup] = useState("");
  //: The action waiting on the question, if the person holding the phone has not answered yet.
  const [gated, setGated] = useState<{ run: () => void } | null>(null);

  //: The keys whose action moves money. A price can be changed by a tap and cost real money by the end of
  //: the day, so these ask who is holding the phone first. Everything else goes straight through, because a
  //: PIN asked for too much becomes a PIN people share with whoever is nearest.
  const MOVES_MONEY = /^(group-|item-|clear-)/;

  const run = useCallback(
    async (key: string, action: () => Promise<void>, skipGate = false) => {
      if (!skipGate && MOVES_MONEY.test(key)) {
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
    },
    [],
  );

  const load = useCallback(async (tenantId: string) => {
    const [foundGroups, foundItems] = await Promise.all([
      listCategories(tenantId),
      listProducts(tenantId),
    ]);
    setGroups(foundGroups);
    setItems(foundItems);
    setDrafts(
      Object.fromEntries(
        foundGroups.map((group) => [
          group.id,
          {
            normal: group.default_normal_price ?? "",
            wholesale: group.default_wholesale_price ?? "",
            pack: group.default_pieces_per_pack?.toString() ?? "",
          },
        ]),
      ),
    );
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await currentUser();
        const businesses = await listBusinesses();
        const remembered =
          typeof window === "undefined" ? null : window.localStorage.getItem("ahia.business");
        const chosen = businesses.find((candidate) => candidate.id === remembered) ?? businesses[0];
        if (!chosen) {
          router.replace("/app");
          return;
        }
        setBusiness(await getBusiness(chosen.id));
        await load(chosen.id);
      } catch {
        router.replace("/start");
      }
    })();
  }, [load, router]);

  if (!business) {
    return (
      <main className={styles.page}>
        <header className={styles.topbar}>
          <Brand>
            <Wordmark />
          </Brand>
        </header>
      </main>
    );
  }

  const money = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed === "" ? null : trimmed;
  };

  const ungrouped = items.filter((product) => product.category_id === null);

  const count = (value: string): number | null => {
    const trimmed = value.trim();
    if (trimmed === "") return null;
    const parsed = Number.parseInt(trimmed, 10);
    return Number.isNaN(parsed) ? null : parsed;
  };

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Brand>
          <Wordmark />
        </Brand>
        <Link className={styles.back} href="/app">
          Back to the shop
        </Link>
      </header>

      <div className={styles.content}>
        <div>
          <h1 className={styles.title}>Prices in {business.name}</h1>
          <p className={styles.lede}>
            Set what a group costs and everything under it follows. Give an item its own price only
            when it is genuinely different - that is the exception, and it is marked so you can see it.
          </p>
        </div>

        <Card title="Add a group">
          <div className={styles.addRow}>
            <Field
              label="Name it the way you say it"
              id="new_group"
              value={newGroup}
              onChange={setNewGroup}
              placeholder="21D, Privacy, Charging cords"
              hint="A grade, a heading, a shelf - whatever you call it."
            />
            <Button
              busy={busyAction === "add-group"}
              disabled={newGroup.trim().length < 1}
              onClick={() =>
                run("add-group", async () => {
                  await createCategory(business.id, { name: newGroup.trim() });
                  setNewGroup("");
                  await load(business.id);
                  setNotice({ message: "Group added. Set its price below.", tone: "good" });
                })
              }
            >
              Add group
            </Button>
          </div>
        </Card>

        {groups.length === 0 ? (
          <Card title="No groups yet">
            <p className={styles.note}>
              A group is how a price reaches many items at once. Add one above - "21D" is a good first
              one - then put your models under it.
            </p>
          </Card>
        ) : null}

        {ungrouped.length > 0 ? (
          <Card title="Not under any group">
            <p className={styles.note}>
              These carry their own price. Put one under a group and it follows that group's price
              instead - give it its own again any time.
            </p>
            <ul className={styles.items}>
              {ungrouped.map((product) => (
                <li key={product.id} className={styles.item}>
                  <div className={styles.itemWho}>
                    <span className={styles.itemName}>{product.name}</span>
                    <span className={styles.itemPrice}>
                      sells at {formatMoneyOrOnRequest(product.effective_normal_price)}
                    </span>
                  </div>
                  <Select
                    label="Under"
                    id={`ungrouped_${product.id}`}
                    value=""
                    options={[
                      { value: "", label: "No group" },
                      ...groups.map((candidate) => ({
                        value: candidate.id,
                        label: candidate.name,
                      })),
                    ]}
                    onChange={(value) =>
                      run(`under-${product.id}`, async () => {
                        await moveItemToGroup(business.id, product.id, value);
                        await load(business.id);
                        setNotice({ message: `${product.name} now follows a group.`, tone: "good" });
                      })
                    }
                  />
                </li>
              ))}
            </ul>
          </Card>
        ) : null}

        {groups.map((group) => {
          const draft = drafts[group.id] ?? { normal: "", wholesale: "", pack: "" };
          const members = items.filter((product) => product.category_id === group.id);
          return (
            <Card key={group.id} title={group.name}>
              <div className={styles.groupGrid}>
                <Field
                  label="Normal price (shop page)"
                  id={`normal_${group.id}`}
                  value={draft.normal}
                  onChange={(value) =>
                    setDrafts((current) => ({
                      ...current,
                      [group.id]: { ...draft, normal: value },
                    }))
                  }
                  inputMode="decimal"
                  placeholder="500"
                />
                <Field
                  label="Wholesale price (a list)"
                  id={`wholesale_${group.id}`}
                  value={draft.wholesale}
                  onChange={(value) =>
                    setDrafts((current) => ({
                      ...current,
                      [group.id]: { ...draft, wholesale: value },
                    }))
                  }
                  inputMode="decimal"
                  placeholder="350"
                />
                <Field
                  label="Pieces in a pack"
                  id={`pack_${group.id}`}
                  value={draft.pack}
                  onChange={(value) =>
                    setDrafts((current) => ({
                      ...current,
                      [group.id]: { ...draft, pack: value },
                    }))
                  }
                  inputMode="numeric"
                  optional
                  placeholder="10"
                />
              </div>
              <div className={styles.actions}>
                <Button
                  busy={busyAction === `group-${group.id}`}
                  onClick={() =>
                    run(`group-${group.id}`, async () => {
                      await setGroupPrices(business.id, group.id, {
                        default_normal_price: money(draft.normal),
                        default_wholesale_price: money(draft.wholesale),
                        default_pieces_per_pack: count(draft.pack),
                      });
                      await load(business.id);
                      setNotice({
                        message: `Everything under ${group.name} follows this now.`,
                        hint: "An item with its own price keeps it.",
                        tone: "good",
                      });
                    })
                  }
                >
                  Set this group
                </Button>
              </div>

              <h3 className={styles.subhead}>
                {members.length === 0
                  ? "Nothing under this group yet"
                  : `${members.length} under this group`}
              </h3>
              <ul className={styles.items}>
                {members.map((product) => (
                  <li key={product.id} className={styles.item}>
                    <div className={styles.itemWho}>
                      <span className={styles.itemName}>{product.name}</span>
                      <span className={styles.itemPrice}>
                        sells at {formatMoneyOrOnRequest(product.effective_normal_price)}
                        {product.effective_wholesale_price
                          ? `, list ${formatMoneyOrOnRequest(product.effective_wholesale_price)}`
                          : ""}
                      </span>
                    </div>
                    <Pill tone={product.normal_price_from_group ? "warn" : "good"}>
                      {product.normal_price_from_group ? "Follows the group" : "Its own price"}
                    </Pill>
                    <Select
                      label="Under"
                      id={`under_${product.id}`}
                      value={product.category_id ?? ""}
                      options={[
                        { value: "", label: "No group" },
                        ...groups.map((candidate) => ({
                          value: candidate.id,
                          label: candidate.name,
                        })),
                      ]}
                      onChange={(value) =>
                        run(`under-${product.id}`, async () => {
                          // Filing an item under a heading is what lets one price cover it, so this
                          // is the move that makes the whole price book worth having.
                          await moveItemToGroup(
                            business.id,
                            product.id,
                            value === "" ? null : value,
                          );
                          await load(business.id);
                          setNotice({
                            message:
                              value === ""
                                ? `${product.name} is not under a group any more.`
                                : `${product.name} follows ${groups.find((c) => c.id === value)?.name}.`,
                            tone: "good",
                          });
                        })
                      }
                    />
                    <div className={styles.itemActions}>
                      <button
                        className={styles.linkButton}
                        onClick={() =>
                          run(`clear-${product.id}`, async () => {
                            // Clearing the override is how an exception stops being one.
                            await setItemPrices(business.id, product.id, {
                              selling_price: null,
                              wholesale_price: null,
                            });
                            await load(business.id);
                            setNotice({
                              message: `${product.name} follows ${group.name} again.`,
                              tone: "good",
                            });
                          })
                        }
                      >
                        Follow the group
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          );
        })}
      </div>

      {notice ? (
        <Toast
          message={notice.message}
          hint={notice.hint}
          tone={notice.tone}
          onDismiss={() => setNotice(null)}
        />
      ) : null}

      {/* What everything costs is the one thing a tap can change and cost real money by the end of the
          day, so it asks who is holding the phone before it happens. */}
      <PinGate
        open={gated !== null}
        reason="change a price"
        onConfirmed={() => {
          gated?.run();
          setGated(null);
        }}
        onClose={() => setGated(null)}
      />
    </main>
  );
}
