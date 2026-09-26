"use client";

/**
 * The price book: category group prices and item overrides.
 *
 * Market traders set prices by grade/category ("All 21D are 500 normal, 350 wholesale").
 * Every item under that category automatically uses that price unless specifically given an override.
 *
 * Built for clarity and low cognitive load:
 * - View mode by default: clean badges showing normal price, wholesale price, and pack size.
 * - Edit on demand: inputs and save actions only appear when the trader taps "Edit".
 * - Items under each group show their effective prices clearly with quick override options.
 * - Quick search to filter groups and items instantly.
 * - Protected by PIN gate for price changes that move money.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  CheckMarkIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  EditIcon,
  FolderIcon,
  ItemBoxIcon,
  PlusIcon,
  SearchIcon,
} from "@/components/icons";
import { EmptyShelfIllustration } from "@/components/illustrations";
import { PinGate } from "@/components/pin-gate";
import { Button, Card, Empty, Field, Loading, Pill, Select, Toast } from "@/components/ui";
import {
  cachedRead,
  createCategory,
  currentUser,
  firstPaint,
  getBusiness,
  listBusinesses,
  listCategories,
  listProducts,
  moveItemToGroup,
  rememberedBusinessId,
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

interface ItemDraft {
  normal: string;
  wholesale: string;
  groupId: string;
}

export default function Prices() {
  const router = useRouter();
  const [business, setBusiness] = useState<Tenant | null>(() =>
    firstPaint<Tenant>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}`),
  );
  const [groups, setGroups] = useState<Category[]>(() => {
    const id = rememberedBusinessId();
    if (!id) return [];
    return cachedRead<Category[]>(`/api/v1/tenants/${id}/categories`) ?? [];
  });
  const [items, setItems] = useState<Product[]>(() => {
    const id = rememberedBusinessId();
    if (!id) return [];
    return cachedRead<Product[]>(`/api/v1/tenants/${id}/products`) ?? [];
  });
  const [currency, setCurrency] = useState(() => {
    const id = rememberedBusinessId();
    if (!id) return "NGN";
    return cachedRead<Tenant>(`/api/v1/tenants/${id}`)?.currency ?? "NGN";
  });
  const [state, setState] = useState<"loading" | "ready">(() => {
    const id = rememberedBusinessId();
    if (!id) return "loading";
    const hasCached = cachedRead(`/api/v1/tenants/${id}/categories`) || cachedRead(`/api/v1/tenants/${id}/products`);
    return hasCached ? "ready" : "loading";
  });
  const [query, setQuery] = useState("");

  // Edit states
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
  const [groupDrafts, setGroupDrafts] = useState<Record<string, GroupDraft>>(() => {
    const id = rememberedBusinessId();
    if (!id) return {};
    const cachedCats = cachedRead<Category[]>(`/api/v1/tenants/${id}/categories`) ?? [];
    return Object.fromEntries(
      cachedCats.map((group) => [
        group.id,
        {
          normal: group.default_normal_price ?? "",
          wholesale: group.default_wholesale_price ?? "",
          pack: group.default_pieces_per_pack?.toString() ?? "",
        },
      ]),
    );
  });

  const [editingItemId, setEditingItemId] = useState<string | null>(null);
  const [itemDraft, setItemDraft] = useState<ItemDraft>({ normal: "", wholesale: "", groupId: "" });

  // Add group modal/card state
  const [showAddGroup, setShowAddGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupNormal, setNewGroupNormal] = useState("");
  const [newGroupWholesale, setNewGroupWholesale] = useState("");

  // Collapsible groups
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [gated, setGated] = useState<{ run: () => void } | null>(null);

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
    setGroupDrafts(
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
    setState("ready");
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
        const detail = await getBusiness(chosen.id);
        setBusiness(detail);
        setCurrency(detail.currency);

        const rememberedCats = cachedRead<Category[]>(`/api/v1/tenants/${chosen.id}/categories`);
        if (rememberedCats) {
          setGroups(rememberedCats);
          setGroupDrafts(
            Object.fromEntries(
              rememberedCats.map((group) => [
                group.id,
                {
                  normal: group.default_normal_price ?? "",
                  wholesale: group.default_wholesale_price ?? "",
                  pack: group.default_pieces_per_pack?.toString() ?? "",
                },
              ]),
            ),
          );
          setState("ready");
        }
        const rememberedProds = cachedRead<Product[]>(`/api/v1/tenants/${chosen.id}/products`);
        if (rememberedProds) {
          setItems(rememberedProds);
        }

        await load(chosen.id);
      } catch {
        router.replace("/start");
      }
    })();
  }, [load, router]);

  const money = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed === "" ? null : trimmed;
  };

  const count = (value: string): number | null => {
    const trimmed = value.trim();
    if (trimmed === "") return null;
    const parsed = Number.parseInt(trimmed, 10);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const toggleGroupExpanded = (groupId: string) => {
    setExpandedGroups((prev) => ({
      ...prev,
      [groupId]: prev[groupId] === undefined ? true : !prev[groupId],
    }));
  };

  const isGroupExpanded = (groupId: string): boolean => {
    return expandedGroups[groupId] ?? true; // expanded by default
  };

  // Filter groups and items
  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups.filter((g) => {
      if (g.name.toLowerCase().includes(q)) return true;
      const groupItems = items.filter((i) => i.category_id === g.id);
      return groupItems.some((i) => i.name.toLowerCase().includes(q));
    });
  }, [groups, items, query]);

  const ungrouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const raw = items.filter((product) => product.category_id === null);
    if (!q) return raw;
    return raw.filter((i) => i.name.toLowerCase().includes(q));
  }, [items, query]);

  if (!business) {
    return (
      <main className={styles.page}>
        <Loading label="Opening your price book..." />
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Price Book</h1>
        <p className={styles.lede}>
          Set standard prices by category. Items automatically follow their category price, with
          individual overrides available when a specific model differs.
        </p>
      </header>

      {/* Search and Action Toolbar */}
      <section className={styles.toolbar}>
        <div className={styles.searchWrap}>
          <SearchIcon size={18} className={styles.searchIcon} />
          <input
            className={styles.search}
            id="prices_search"
            value={query}
            placeholder="Search categories or items..."
            aria-label="Search categories or items"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <button
          type="button"
          className={styles.actionBtn}
          onClick={() => setShowAddGroup((prev) => !prev)}
        >
          <PlusIcon size={15} />
          <span>Add Category</span>
        </button>
      </section>

      {/* Add Category Form (expandable) */}
      {showAddGroup ? (
        <section className={styles.addGroupCard}>
          <h2 className={styles.addGroupTitle}>Add New Category Group</h2>
          <div className={styles.formGrid}>
            <Field
              label="Category name"
              id="new_group_name"
              value={newGroupName}
              placeholder="e.g. 21D, Privacy, Chargers"
              onChange={setNewGroupName}
            />
            <Field
              label="Normal price (optional)"
              id="new_group_normal"
              value={newGroupNormal}
              inputMode="decimal"
              placeholder="e.g. 500"
              optional
              onChange={setNewGroupNormal}
            />
            <Field
              label="Wholesale price (optional)"
              id="new_group_wholesale"
              value={newGroupWholesale}
              inputMode="decimal"
              placeholder="e.g. 350"
              optional
              onChange={setNewGroupWholesale}
            />
          </div>
          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.actionBtn}
              disabled={busyAction === "add-group" || newGroupName.trim().length < 1}
              onClick={() =>
                run("add-group", async () => {
                  await createCategory(business.id, {
                    name: newGroupName.trim(),
                    default_normal_price: money(newGroupNormal) ?? undefined,
                    default_wholesale_price: money(newGroupWholesale) ?? undefined,
                  });
                  setNewGroupName("");
                  setNewGroupNormal("");
                  setNewGroupWholesale("");
                  setShowAddGroup(false);
                  await load(business.id);
                  setNotice({ message: "Category created.", tone: "good" });
                })
              }
            >
              {busyAction === "add-group" ? "Saving..." : "Save Category"}
            </button>
            <button
              type="button"
              className={styles.actionBtnSecondary}
              onClick={() => setShowAddGroup(false)}
            >
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      {state === "loading" ? <Loading label="Loading prices..." /> : null}

      {state === "ready" && groups.length === 0 ? (
        <Empty
          illustration={<EmptyShelfIllustration size={110} />}
          action={
            <button
              type="button"
              className={styles.actionBtn}
              onClick={() => setShowAddGroup(true)}
            >
              <PlusIcon size={15} /> Add First Category
            </button>
          }
        >
          No price categories yet.
          <br />
          Create your first category (e.g. &quot;21D Screenguards&quot;) to set standard prices across
          multiple items at once.
        </Empty>
      ) : null}

      {/* Groups List */}
      {filteredGroups.map((group) => {
        const isEditing = editingGroupId === group.id;
        const draft = groupDrafts[group.id] ?? {
          normal: group.default_normal_price ?? "",
          wholesale: group.default_wholesale_price ?? "",
          pack: group.default_pieces_per_pack?.toString() ?? "",
        };
        const members = items.filter((product) => product.category_id === group.id);
        const expanded = isGroupExpanded(group.id);

        return (
          <section key={group.id} className={styles.groupCard}>
            <header className={styles.groupHeader}>
              <div className={styles.groupTitleRow}>
                <FolderIcon size={20} className={styles.groupIcon} />
                <h2 className={styles.groupTitle}>{group.name}</h2>
                <span className={styles.groupCount}>
                  {members.length} {members.length === 1 ? "item" : "items"}
                </span>
              </div>
              <button
                type="button"
                className={styles.editBtn}
                onClick={() => setEditingGroupId(isEditing ? null : group.id)}
              >
                <EditIcon size={14} />
                <span>{isEditing ? "Close" : "Edit Category Price"}</span>
              </button>
            </header>

            {/* View Mode: Clean, glanceable price summary badges */}
            {!isEditing ? (
              <div className={styles.priceBadges}>
                <div className={styles.priceBadge}>
                  <span className={styles.priceBadgeLabel}>Shop Normal</span>
                  <span className={styles.priceBadgeValue}>
                    {formatMoneyOrOnRequest(group.default_normal_price, currency)}
                  </span>
                </div>
                <div className={styles.priceBadge}>
                  <span className={styles.priceBadgeLabel}>Wholesale List</span>
                  <span className={styles.priceBadgeValue}>
                    {formatMoneyOrOnRequest(group.default_wholesale_price, currency)}
                  </span>
                </div>
                <div className={styles.priceBadge}>
                  <span className={styles.priceBadgeLabel}>Pack Size</span>
                  <span className={styles.priceBadgeValue}>
                    {group.default_pieces_per_pack
                      ? `${group.default_pieces_per_pack} pcs/pack`
                      : "Single piece"}
                  </span>
                </div>
              </div>
            ) : (
              /* Edit Mode: Compact form only visible when requested */
              <div className={styles.editModeBox}>
                <div className={styles.editGrid}>
                  <Field
                    label="Normal price (shop page)"
                    id={`normal_${group.id}`}
                    value={draft.normal}
                    onChange={(value) =>
                      setGroupDrafts((current) => ({
                        ...current,
                        [group.id]: { ...draft, normal: value },
                      }))
                    }
                    inputMode="decimal"
                    placeholder="e.g. 500"
                  />
                  <Field
                    label="Wholesale price (customer list)"
                    id={`wholesale_${group.id}`}
                    value={draft.wholesale}
                    onChange={(value) =>
                      setGroupDrafts((current) => ({
                        ...current,
                        [group.id]: { ...draft, wholesale: value },
                      }))
                    }
                    inputMode="decimal"
                    placeholder="e.g. 350"
                  />
                  <Field
                    label="Pieces in a pack"
                    id={`pack_${group.id}`}
                    value={draft.pack}
                    onChange={(value) =>
                      setGroupDrafts((current) => ({
                        ...current,
                        [group.id]: { ...draft, pack: value },
                      }))
                    }
                    inputMode="numeric"
                    optional
                    placeholder="e.g. 10"
                  />
                </div>
                <div className={styles.editActions}>
                  <button
                    type="button"
                    className={styles.actionBtn}
                    disabled={busyAction === `group-${group.id}`}
                    onClick={() =>
                      run(`group-${group.id}`, async () => {
                        await setGroupPrices(business.id, group.id, {
                          default_normal_price: money(draft.normal),
                          default_wholesale_price: money(draft.wholesale),
                          default_pieces_per_pack: count(draft.pack),
                        });
                        setEditingGroupId(null);
                        await load(business.id);
                        setNotice({
                          message: `Prices updated for ${group.name}.`,
                          tone: "good",
                        });
                      })
                    }
                  >
                    <CheckMarkIcon size={14} />
                    <span>{busyAction === `group-${group.id}` ? "Saving..." : "Save Category Prices"}</span>
                  </button>
                  <button
                    type="button"
                    className={styles.actionBtnSecondary}
                    onClick={() => setEditingGroupId(null)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Items inside this Category */}
            <div className={styles.itemsSection}>
              <div className={styles.itemsHeader}>
                <span className={styles.itemsTitle}>
                  Items in this category ({members.length})
                </span>
                {members.length > 0 ? (
                  <button
                    type="button"
                    className={styles.toggleItemsBtn}
                    onClick={() => toggleGroupExpanded(group.id)}
                  >
                    {expanded ? <ChevronDownIcon size={15} /> : <ChevronRightIcon size={15} />}
                    <span>{expanded ? "Collapse" : "Expand"}</span>
                  </button>
                ) : null}
              </div>

              {expanded && members.length > 0 ? (
                <ul className={styles.itemsList}>
                  {members.map((product) => {
                    const isItemEditing = editingItemId === product.id;
                    const hasOverride = !product.normal_price_from_group || !product.wholesale_price_from_group;

                    return (
                      <li key={product.id} className={styles.itemRow}>
                        <div className={styles.itemMain}>
                          <div className={styles.itemWho}>
                            <ItemBoxIcon size={16} className={styles.itemIcon} />
                            <span className={styles.itemName}>{product.name}</span>
                          </div>
                          <div className={styles.itemPricing}>
                            <Pill tone={hasOverride ? "warn" : "good"}>
                              {hasOverride
                                ? `Custom: ${formatMoneyOrOnRequest(product.effective_normal_price, currency)}`
                                : `Follows group (${formatMoneyOrOnRequest(product.effective_normal_price, currency)})`}
                            </Pill>
                            <button
                              type="button"
                              className={styles.itemEditBtn}
                              onClick={() => {
                                if (isItemEditing) {
                                  setEditingItemId(null);
                                } else {
                                  setEditingItemId(product.id);
                                  setItemDraft({
                                    normal: product.normal_price_from_group ? "" : (product.selling_price ?? ""),
                                    wholesale: product.wholesale_price_from_group ? "" : (product.effective_wholesale_price ?? ""),
                                    groupId: product.category_id ?? "",
                                  });
                                }
                              }}
                            >
                              <EditIcon size={12} />
                              <span>{isItemEditing ? "Close" : "Change Price"}</span>
                            </button>
                          </div>
                        </div>

                        {/* Individual Item Edit Form (only visible when requested) */}
                        {isItemEditing ? (
                          <div className={styles.itemEditForm}>
                            <div className={styles.itemEditGrid}>
                              <Field
                                label="Custom shop price (leave blank for group)"
                                id={`prod_normal_${product.id}`}
                                value={itemDraft.normal}
                                onChange={(value) =>
                                  setItemDraft((prev) => ({ ...prev, normal: value }))
                                }
                                inputMode="decimal"
                                placeholder={group.default_normal_price ?? "Group price"}
                                optional
                              />
                              <Field
                                label="Custom wholesale price"
                                id={`prod_wholesale_${product.id}`}
                                value={itemDraft.wholesale}
                                onChange={(value) =>
                                  setItemDraft((prev) => ({ ...prev, wholesale: value }))
                                }
                                inputMode="decimal"
                                placeholder={group.default_wholesale_price ?? "Group price"}
                                optional
                              />
                              <Select
                                label="Category"
                                id={`prod_cat_${product.id}`}
                                value={itemDraft.groupId}
                                options={[
                                  { value: "", label: "No category" },
                                  ...groups.map((c) => ({ value: c.id, label: c.name })),
                                ]}
                                onChange={(val) =>
                                  setItemDraft((prev) => ({ ...prev, groupId: val }))
                                }
                              />
                            </div>
                            <div className={styles.itemEditActions}>
                              <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                                <button
                                  type="button"
                                  className={styles.actionBtn}
                                  disabled={busyAction === `item-${product.id}`}
                                  onClick={() =>
                                    run(`item-${product.id}`, async () => {
                                      await setItemPrices(business.id, product.id, {
                                        selling_price: money(itemDraft.normal),
                                        wholesale_price: money(itemDraft.wholesale),
                                      });
                                      if (itemDraft.groupId !== (product.category_id ?? "")) {
                                        await moveItemToGroup(
                                          business.id,
                                          product.id,
                                          itemDraft.groupId || null,
                                        );
                                      }
                                      setEditingItemId(null);
                                      await load(business.id);
                                      setNotice({
                                        message: `Price updated for ${product.name}.`,
                                        tone: "good",
                                      });
                                    })
                                  }
                                >
                                  <CheckMarkIcon size={14} />
                                  <span>Save Item Price</span>
                                </button>
                                <button
                                  type="button"
                                  className={styles.actionBtnSecondary}
                                  onClick={() => setEditingItemId(null)}
                                >
                                  Cancel
                                </button>
                              </div>
                              {hasOverride ? (
                                <button
                                  type="button"
                                  className={styles.resetGroupBtn}
                                  onClick={() =>
                                    run(`clear-${product.id}`, async () => {
                                      await setItemPrices(business.id, product.id, {
                                        selling_price: null,
                                        wholesale_price: null,
                                      });
                                      setEditingItemId(null);
                                      await load(business.id);
                                      setNotice({
                                        message: `${product.name} now follows ${group.name} price.`,
                                        tone: "good",
                                      });
                                    })
                                  }
                                >
                                  Reset to Category Price
                                </button>
                              ) : null}
                            </div>
                          </div>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </div>
          </section>
        );
      })}

      {/* Ungrouped items */}
      {ungrouped.length > 0 ? (
        <Card title={`Uncategorized Items (${ungrouped.length})`}>
          <p className={styles.lede} style={{ marginBottom: "12px" }}>
            These items do not have a category yet. Assign them to a category to apply standard prices.
          </p>
          <ul className={styles.itemsList}>
            {ungrouped.map((product) => (
              <li key={product.id} className={styles.itemRow}>
                <div className={styles.itemMain}>
                  <div className={styles.itemWho}>
                    <ItemBoxIcon size={16} className={styles.itemIcon} />
                    <span className={styles.itemName}>{product.name}</span>
                  </div>
                  <div className={styles.itemPricing}>
                    <span className={styles.itemPriceText}>
                      {formatMoneyOrOnRequest(product.effective_normal_price, currency)}
                    </span>
                    <Select
                      label=""
                      id={`ungrouped_select_${product.id}`}
                      value=""
                      options={[
                        { value: "", label: "Assign category..." },
                        ...groups.map((c) => ({ value: c.id, label: c.name })),
                      ]}
                      onChange={(catId) => {
                        if (!catId) return;
                        void run(`move-${product.id}`, async () => {
                          await moveItemToGroup(business.id, product.id, catId);
                          await load(business.id);
                          setNotice({
                            message: `${product.name} assigned to category.`,
                            tone: "good",
                          });
                        });
                      }}
                    />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {notice ? (
        <Toast
          message={notice.message}
          hint={notice.hint}
          tone={notice.tone}
          onDismiss={() => setNotice(null)}
        />
      ) : null}

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
