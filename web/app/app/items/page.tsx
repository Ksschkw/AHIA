"use client";

/**
 * Unified Shop Catalog: categories, products, and dual prices (retail & wholesale).
 *
 * Designed with a Samsung File Manager multi-select experience and genuine branching tree:
 * - Categories nest without limit: Root -> Parent -> Child -> Grandchild.
 * - Dual pricing: Wholesale and Retail prices defined at category level or overridden on items.
 * - Multi-select item checkboxes with a sticky bottom action bar (Copy to..., Move to..., Select All).
 * - Quick batch copying: duplicate entire product lines (e.g. Hot 8, Hot 9, Camon 30) across categories in one click.
 * - Copied items inherit destination category default prices automatically.
 * - Authentic visual family tree diagram with connecting stems, branch elbows, and leaves.
 * - Cache-first rendering with instant local search across all nesting levels.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  CheckMarkIcon,
  ChevronRightIcon,
  CloseIcon,
  CopyIcon,
  FolderIcon,
  FolderOpenIcon,
  ItemBoxIcon,
  PlusIcon,
  SearchIcon,
} from "@/components/icons";
import { EmptyShelfIllustration } from "@/components/illustrations";
import { Empty, Field, Loading, Toast } from "@/components/ui";
import {
  cachedRead,
  firstPaint,
  rememberedBusinessId,
  currentUser,
  getBusiness,
  listBusinesses,
  listCategories,
  createCategory,
  moveCategory,
  listProducts,
  createProduct,
  publishProduct,
  unpublishProduct,
  listStock,
  copyProducts,
  moveProductsBatch,
  type Category,
  type InventoryLevel,
  type Product,
  type Tenant,
} from "@/lib/api";
import { formatMoneyOrOnRequest, formatQuantity } from "@/lib/format";
import styles from "./items.module.css";

type Notice = { message: string; tone: "good" | "bad"; hint?: string };

interface BatchModalState {
  mode: "copy" | "move";
  productIds: string[];
  sourceName?: string;
}

export default function Items() {
  const [business, setBusiness] = useState<Tenant | null>(null);
  const [products, setProducts] = useState<Product[] | null>(() =>
    firstPaint<Product[]>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}/products`),
  );
  const [categories, setCategories] = useState<Category[]>(() => {
    const id = rememberedBusinessId();
    if (!id) return [];
    return cachedRead<Category[]>(`/api/v1/tenants/${id}/categories`) ?? [];
  });
  const [stock, setStock] = useState<InventoryLevel[]>([]);
  const [currency, setCurrency] = useState("NGN");
  const [query, setQuery] = useState("");
  const [currentCategoryId, setCurrentCategoryId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"folder" | "tree">("folder");
  const [state, setState] = useState<"loading" | "ready">(() =>
    rememberedBusinessId() ? "ready" : "loading",
  );
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  // Multi-selection state
  const [selectedProductIds, setSelectedProductIds] = useState<Set<string>>(new Set());
  const [batchModal, setBatchModal] = useState<BatchModalState | null>(null);
  const [busyBatch, setBusyBatch] = useState(false);

  // Moving category state
  const [movingCategory, setMovingCategory] = useState<Category | null>(null);
  const [busyMove, setBusyMove] = useState(false);

  // Forms state
  const [showAddCategory, setShowAddCategory] = useState(false);
  const [newCatName, setNewCatName] = useState("");
  const [newCatParentId, setNewCatParentId] = useState<string | null>(null);
  const [newCatNormalPrice, setNewCatNormalPrice] = useState("");
  const [newCatWholesalePrice, setNewCatWholesalePrice] = useState("");
  const [newCatPiecesPerPack, setNewCatPiecesPerPack] = useState("");

  const [showAddProduct, setShowAddProduct] = useState(false);
  const [newProdName, setNewProdName] = useState("");
  const [newProdSellingPrice, setNewProdSellingPrice] = useState("");
  const [newProdWholesalePrice, setNewProdWholesalePrice] = useState("");
  const [newProdPiecesPerPack, setNewProdPiecesPerPack] = useState("");
  const [newProdPublish, setNewProdPublish] = useState(true);

  const load = useCallback(async (tenantId: string) => {
    const [foundProducts, foundCategories, foundStock] = await Promise.all([
      listProducts(tenantId),
      listCategories(tenantId),
      listStock(tenantId),
    ]);
    setProducts(foundProducts);
    setCategories(foundCategories);
    setStock(foundStock);
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
        if (!chosen) return;
        const detail = await getBusiness(chosen.id);
        setBusiness(detail);
        setCurrency(detail.currency);

        const rememberedProducts = cachedRead<Product[]>(`/api/v1/tenants/${chosen.id}/products`);
        if (rememberedProducts) setProducts(rememberedProducts);

        const rememberedCats = cachedRead<Category[]>(`/api/v1/tenants/${chosen.id}/categories`);
        if (rememberedCats) setCategories(rememberedCats);

        await load(chosen.id);
      } catch {
        // Frame redirects to sign-in if unauthenticated
      }
    })();
  }, [load]);

  const level = (productId: string) => stock.find((entry) => entry.product_id === productId);

  // Category breadcrumb trail
  const breadcrumbs = useMemo(() => {
    const trail: Category[] = [];
    let currentId = currentCategoryId;
    while (currentId !== null) {
      const match = categories.find((c) => c.id === currentId);
      if (!match) break;
      trail.unshift(match);
      currentId = match.parent_id ?? null;
    }
    return trail;
  }, [categories, currentCategoryId]);

  // Current category entity (if drilled down)
  const currentCategory = useMemo(() => {
    if (!currentCategoryId) return null;
    return categories.find((c) => c.id === currentCategoryId) ?? null;
  }, [categories, currentCategoryId]);

  // Children of current category
  const currentSubcategories = useMemo(() => {
    return categories.filter((c) => (c.parent_id ?? null) === currentCategoryId);
  }, [categories, currentCategoryId]);

  // Products in current category
  const currentProducts = useMemo(() => {
    const all = products ?? [];
    if (currentCategoryId === null) {
      return all.filter((p) => p.category_id === null);
    }
    return all.filter((p) => p.category_id === currentCategoryId);
  }, [products, currentCategoryId]);

  // Search filtered products & categories
  const searchResults = useMemo(() => {
    const wanted = query.trim().toLowerCase();
    if (wanted.length < 2) return null;

    const matchedCats = categories.filter((c) => c.name.toLowerCase().includes(wanted));
    const matchedProds = (products ?? []).filter((p) => p.name.toLowerCase().includes(wanted));

    return { categories: matchedCats, products: matchedProds };
  }, [query, categories, products]);

  // Helper: count of products under a category including nested children
  const getCategoryStats = useCallback(
    (catId: string) => {
      const childCatIds = new Set<string>([catId]);
      let added = true;
      while (added) {
        added = false;
        for (const cat of categories) {
          if (cat.parent_id && childCatIds.has(cat.parent_id) && !childCatIds.has(cat.id)) {
            childCatIds.add(cat.id);
            added = true;
          }
        }
      }
      const directChildrenCount = categories.filter((c) => c.parent_id === catId).length;
      const prodsCount = (products ?? []).filter(
        (p) => p.category_id && childCatIds.has(p.category_id),
      ).length;
      return { subcategories: directChildrenCount, products: prodsCount };
    },
    [categories, products],
  );

  // Helper: find all recursive descendant IDs for a category (to prevent cyclic moves)
  const getDescendantCategoryIds = useCallback(
    (categoryId: string, allCategories: Category[]): Set<string> => {
      const descendants = new Set<string>();
      const queue = [categoryId];
      while (queue.length > 0) {
        const current = queue.shift();
        if (!current) continue;
        for (const cat of allCategories) {
          if (cat.parent_id === current && !descendants.has(cat.id)) {
            descendants.add(cat.id);
            queue.push(cat.id);
          }
        }
      }
      return descendants;
    },
    [],
  );

  // Helper: get human-readable breadcrumb path for a category
  const getCategoryPath = useCallback(
    (category: Category, allCategories: Category[]): string => {
      const parts: string[] = [category.name];
      let currentParentId = category.parent_id;
      while (currentParentId) {
        const parent = allCategories.find((c) => c.id === currentParentId);
        if (!parent) break;
        parts.unshift(parent.name);
        currentParentId = parent.parent_id;
      }
      return parts.join(" > ");
    },
    [],
  );

  // Eligible move targets for categories
  const eligibleMoveTargets = useMemo(() => {
    if (!movingCategory) return [];
    const descendantIds = getDescendantCategoryIds(movingCategory.id, categories);
    return categories
      .filter((cat) => cat.id !== movingCategory.id && !descendantIds.has(cat.id))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [movingCategory, categories, getDescendantCategoryIds]);

  // Multi-selection handlers
  const toggleSelectProduct = (productId: string) => {
    setSelectedProductIds((prev) => {
      const next = new Set(prev);
      if (next.has(productId)) {
        next.delete(productId);
      } else {
        next.add(productId);
      }
      return next;
    });
  };

  const handleToggleSelectAll = () => {
    const visibleIds = currentProducts.map((p) => p.id);
    if (visibleIds.length === 0) return;
    const allSelected = visibleIds.every((id) => selectedProductIds.has(id));
    if (allSelected) {
      setSelectedProductIds(new Set());
    } else {
      setSelectedProductIds(new Set([...selectedProductIds, ...visibleIds]));
    }
  };

  const openBatchModal = (mode: "copy" | "move", productIds: string[], sourceName?: string) => {
    if (productIds.length === 0) return;
    setBatchModal({ mode, productIds, sourceName });
  };

  async function handleExecuteMove(targetParentId: string | null) {
    if (!business || !movingCategory) return;
    if ((movingCategory.parent_id ?? null) === targetParentId) {
      setMovingCategory(null);
      return;
    }
    setBusyMove(true);
    try {
      const updated = await moveCategory(business.id, movingCategory.id, targetParentId);
      setCategories((current) =>
        current.map((c) => (c.id === updated.id ? updated : c)),
      );
      const targetName = targetParentId
        ? categories.find((c) => c.id === targetParentId)?.name ?? "selected folder"
        : "Shelf Root";
      setNotice({
        message: `Category "${movingCategory.name}" moved to ${targetName}.`,
        tone: "good",
      });
      setMovingCategory(null);
    } catch {
      setNotice({
        message: "Could not move category. Check that you are not creating a loop.",
        tone: "bad",
      });
    } finally {
      setBusyMove(false);
    }
  }

  async function handleExecuteBatch(targetCategoryId: string | null) {
    if (!business || !batchModal) return;
    setBusyBatch(true);
    const { mode, productIds } = batchModal;
    const targetName = targetCategoryId
      ? categories.find((c) => c.id === targetCategoryId)?.name ?? "selected folder"
      : "Shelf Root (Uncategorized)";

    try {
      if (mode === "copy") {
        const copied = await copyProducts(business.id, productIds, targetCategoryId);
        setProducts((current) => [...(current ?? []), ...copied]);
        setNotice({
          message: `Copied ${productIds.length} item${productIds.length > 1 ? "s" : ""} to "${targetName}". They inherited "${targetName}" default prices.`,
          tone: "good",
        });
      } else {
        const moved = await moveProductsBatch(business.id, productIds, targetCategoryId);
        const movedMap = new Map(moved.map((m) => [m.id, m]));
        setProducts((current) =>
          (current ?? []).map((p) => (movedMap.has(p.id) ? movedMap.get(p.id)! : p)),
        );
        setNotice({
          message: `Moved ${productIds.length} item${productIds.length > 1 ? "s" : ""} to "${targetName}".`,
          tone: "good",
        });
      }
      setSelectedProductIds(new Set());
      setBatchModal(null);
    } catch {
      setNotice({
        message: `Could not ${mode} items. Please try again.`,
        tone: "bad",
      });
    } finally {
      setBusyBatch(false);
    }
  }

  async function handleCreateCategory() {
    if (!business) return;
    const name = newCatName.trim();
    if (name.length < 2) {
      setNotice({ message: "Category name must be at least 2 characters.", tone: "bad" });
      return;
    }
    setBusyAction("add-cat");
    try {
      const packParsed = newCatPiecesPerPack.trim()
        ? parseInt(newCatPiecesPerPack.trim(), 10)
        : undefined;
      const created = await createCategory(business.id, {
        name,
        parent_id: newCatParentId,
        default_normal_price: newCatNormalPrice.trim() || undefined,
        default_wholesale_price: newCatWholesalePrice.trim() || undefined,
        default_pieces_per_pack: Number.isFinite(packParsed) ? packParsed : undefined,
      });
      setCategories((current) => [...current, created]);
      setNewCatName("");
      setNewCatNormalPrice("");
      setNewCatWholesalePrice("");
      setNewCatPiecesPerPack("");
      setShowAddCategory(false);
      setNotice({ message: `Category "${name}" created with price defaults.`, tone: "good" });
    } catch {
      setNotice({ message: "Could not create category. Please try again.", tone: "bad" });
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCreateProduct() {
    if (!business) return;
    const name = newProdName.trim();
    if (name.length < 2) {
      setNotice({ message: "Product name must be at least 2 characters.", tone: "bad" });
      return;
    }
    setBusyAction("add-prod");
    try {
      const packParsed = newProdPiecesPerPack.trim()
        ? parseInt(newProdPiecesPerPack.trim(), 10)
        : undefined;
      let created = await createProduct(business.id, {
        name,
        selling_price: newProdSellingPrice.trim() || undefined,
        wholesale_price: newProdWholesalePrice.trim() || undefined,
        pieces_per_pack: Number.isFinite(packParsed) ? packParsed : undefined,
        category_id: currentCategoryId,
      });
      if (newProdPublish) {
        created = await publishProduct(business.id, created.id);
      }
      setProducts((current) => [...(current ?? []), created]);
      setNewProdName("");
      setNewProdSellingPrice("");
      setNewProdWholesalePrice("");
      setNewProdPiecesPerPack("");
      setShowAddProduct(false);
      setNotice({ message: `Item "${name}" added to catalog.`, tone: "good" });
    } catch {
      setNotice({ message: "Could not add item. Please try again.", tone: "bad" });
    } finally {
      setBusyAction(null);
    }
  }

  async function handleTogglePublish(product: Product) {
    if (!business) return;
    setBusyAction(`pub-${product.id}`);
    try {
      const updated = product.is_published
        ? await unpublishProduct(business.id, product.id)
        : await publishProduct(business.id, product.id);
      setProducts((current) =>
        (current ?? []).map((p) => (p.id === updated.id ? updated : p)),
      );
      setNotice({
        message: updated.is_published
          ? `"${product.name}" is now visible in your public shop.`
          : `"${product.name}" is now hidden from your shop.`,
        tone: "good",
      });
    } catch {
      setNotice({ message: "Could not update publish state.", tone: "bad" });
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <div>
            <h1 className={styles.title}>Catalog</h1>
            <p style={{ fontSize: "13px", color: "var(--ink-2)", margin: "2px 0 0" }}>
              Categories, items, and dual prices (retail &amp; wholesale)
            </p>
          </div>
          <button
            type="button"
            className={styles.toggleViewBtn}
            onClick={() => setViewMode((m) => (m === "folder" ? "tree" : "folder"))}
          >
            {viewMode === "folder" ? "View Full Family Tree" : "View Folders"}
          </button>
        </div>

        {/* Breadcrumbs for navigation */}
        <nav className={styles.breadcrumbs} aria-label="Category hierarchy">
          <button
            type="button"
            className={styles.crumbLink}
            onClick={() => {
              setCurrentCategoryId(null);
              setQuery("");
            }}
          >
            <FolderOpenIcon size={16} />
            <span>Shelf Root</span>
          </button>
          {breadcrumbs.map((crumb, idx) => {
            const isLast = idx === breadcrumbs.length - 1;
            return (
              <span key={crumb.id} style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                <ChevronRightIcon size={13} className={styles.crumbSep} />
                {isLast ? (
                  <span className={styles.crumbCurrent}>{crumb.name}</span>
                ) : (
                  <button
                    type="button"
                    className={styles.crumbLink}
                    onClick={() => {
                      setCurrentCategoryId(crumb.id);
                      setQuery("");
                    }}
                  >
                    {crumb.name}
                  </button>
                )}
              </span>
            );
          })}
        </nav>
      </header>

      {/* Search and Action Toolbar */}
      <section className={styles.toolbar}>
        <div className={styles.searchWrap}>
          <SearchIcon size={18} className={styles.searchIcon} />
          <input
            className={styles.search}
            id="items_search"
            value={query}
            placeholder="Search items or categories across all levels..."
            aria-label="Search items or categories"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div className={styles.actionsRow}>
          <div className={styles.btnGroup}>
            <button
              type="button"
              className={styles.actionBtn}
              onClick={() => {
                setNewCatParentId(currentCategoryId);
                setShowAddCategory((prev) => !prev);
                setShowAddProduct(false);
              }}
            >
              <PlusIcon size={15} />
              <span>Add Category</span>
            </button>
            <button
              type="button"
              className={styles.actionBtnSecondary}
              onClick={() => {
                setShowAddProduct((prev) => !prev);
                setShowAddCategory(false);
              }}
            >
              <PlusIcon size={15} />
              <span>Add Item</span>
            </button>
          </div>

          {currentCategoryId && currentProducts.length > 0 ? (
            <button
              type="button"
              className={styles.copyAllBtn}
              onClick={() =>
                openBatchModal(
                  "copy",
                  currentProducts.map((p) => p.id),
                  breadcrumbs[breadcrumbs.length - 1]?.name,
                )
              }
            >
              <CopyIcon size={14} />
              <span>Copy All {currentProducts.length} Items to Another Folder...</span>
            </button>
          ) : null}
        </div>
      </section>

      {/* Add Category Form */}
      {showAddCategory ? (
        <section className={styles.formCard}>
          <h2 className={styles.formTitle}>
            Add Category {currentCategoryId ? `under "${breadcrumbs[breadcrumbs.length - 1]?.name}"` : "at Root"}
          </h2>
          <div className={styles.formGrid}>
            <Field
              label="Category name"
              id="new_category_name"
              value={newCatName}
              placeholder="e.g. Screenguards, 21D, Privacy, Silicone Cases"
              onChange={setNewCatName}
            />
            <Field
              label="Default Retail Price (optional)"
              id="new_category_normal_price"
              value={newCatNormalPrice}
              placeholder="e.g. 500 (covers all items inside)"
              inputMode="decimal"
              optional
              onChange={setNewCatNormalPrice}
            />
            <Field
              label="Default Wholesale Price (optional)"
              id="new_category_wholesale_price"
              value={newCatWholesalePrice}
              placeholder="e.g. 350 (bulk / trade price)"
              inputMode="decimal"
              optional
              onChange={setNewCatWholesalePrice}
            />
            <Field
              label="Default Pack Size (optional)"
              id="new_category_pack"
              value={newCatPiecesPerPack}
              placeholder="e.g. 10 or 25 pieces per pack"
              inputMode="numeric"
              optional
              onChange={setNewCatPiecesPerPack}
            />
          </div>
          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.actionBtn}
              disabled={busyAction === "add-cat" || newCatName.trim().length < 2}
              onClick={() => void handleCreateCategory()}
            >
              {busyAction === "add-cat" ? "Creating..." : "Save Category"}
            </button>
            <button
              type="button"
              className={styles.actionBtnSecondary}
              onClick={() => setShowAddCategory(false)}
            >
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      {/* Add Product Form */}
      {showAddProduct ? (
        <section className={styles.formCard}>
          <h2 className={styles.formTitle}>
            Add Item {currentCategoryId ? `to "${breadcrumbs[breadcrumbs.length - 1]?.name}"` : "at Root"}
          </h2>
          <div className={styles.formGrid}>
            <Field
              label="Item name"
              id="new_product_name"
              value={newProdName}
              placeholder="e.g. Hot 8, Hot 9, Camon 30"
              onChange={setNewProdName}
            />
            <Field
              label="Retail price (leave empty to follow category default)"
              id="new_product_price"
              value={newProdSellingPrice}
              placeholder={
                currentCategory?.default_normal_price
                  ? `Follows category default (${formatMoneyOrOnRequest(currentCategory.default_normal_price, currency)})`
                  : "e.g. 2500"
              }
              inputMode="decimal"
              optional
              onChange={setNewProdSellingPrice}
            />
            <Field
              label="Wholesale price (leave empty to follow category default)"
              id="new_product_wholesale"
              value={newProdWholesalePrice}
              placeholder={
                currentCategory?.default_wholesale_price
                  ? `Follows category default (${formatMoneyOrOnRequest(currentCategory.default_wholesale_price, currency)})`
                  : "e.g. 1800"
              }
              inputMode="decimal"
              optional
              onChange={setNewProdWholesalePrice}
            />
            <Field
              label="Pieces per pack (optional)"
              id="new_product_pack"
              value={newProdPiecesPerPack}
              placeholder="e.g. 10"
              inputMode="numeric"
              optional
              onChange={setNewProdPiecesPerPack}
            />
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={newProdPublish}
              onChange={(e) => setNewProdPublish(e.target.checked)}
            />
            Publish in public shop immediately
          </label>
          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.actionBtn}
              disabled={busyAction === "add-prod" || newProdName.trim().length < 2}
              onClick={() => void handleCreateProduct()}
            >
              {busyAction === "add-prod" ? "Adding..." : "Save Item"}
            </button>
            <button
              type="button"
              className={styles.actionBtnSecondary}
              onClick={() => setShowAddProduct(false)}
            >
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      {state === "loading" && (!products || products.length === 0) ? (
        <Loading label="Fetching your catalog..." />
      ) : null}

      {/* Search results mode */}
      {searchResults !== null ? (
        <section>
          <h2 className={styles.sectionTitle}>
            Search Results for &quot;{query}&quot; ({searchResults.categories.length} categories,{" "}
            {searchResults.products.length} items)
          </h2>

          {searchResults.categories.length > 0 ? (
            <div className={styles.folderGrid} style={{ marginBottom: "16px" }}>
              {searchResults.categories.map((cat) => {
                const stats = getCategoryStats(cat.id);
                return (
                  <div key={cat.id} className={styles.folderCard}>
                    <div
                      className={styles.folderCardMain}
                      onClick={() => {
                        setCurrentCategoryId(cat.id);
                        setQuery("");
                      }}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          setCurrentCategoryId(cat.id);
                          setQuery("");
                        }
                      }}
                    >
                      <span className={styles.folderMain}>
                        <span className={styles.folderIcon}>
                          <FolderIcon size={20} />
                        </span>
                        <div>
                          <span className={styles.folderName}>{cat.name}</span>
                          {cat.default_normal_price || cat.default_wholesale_price ? (
                            <div className={styles.catPriceDefaults}>
                              {cat.default_normal_price
                                ? `Retail: ${formatMoneyOrOnRequest(cat.default_normal_price, currency)}`
                                : ""}
                              {cat.default_normal_price && cat.default_wholesale_price ? " - " : ""}
                              {cat.default_wholesale_price
                                ? `Wholesale: ${formatMoneyOrOnRequest(cat.default_wholesale_price, currency)}`
                                : ""}
                            </div>
                          ) : null}
                        </div>
                      </span>
                      <span className={styles.folderCount}>
                        {stats.products} items
                      </span>
                      <ChevronRightIcon size={16} className={styles.folderChev} />
                    </div>
                    <button
                      type="button"
                      className={styles.moveFolderBtn}
                      title={`Move ${cat.name} into another folder`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setMovingCategory(cat);
                      }}
                    >
                      Move
                    </button>
                  </div>
                );
              })}
            </div>
          ) : null}

          {searchResults.products.length > 0 ? (
            <div className={styles.productsList}>
              {searchResults.products.map((prod) => {
                const curStock = level(prod.id);
                const cat = categories.find((c) => c.id === prod.category_id);
                const isSelected = selectedProductIds.has(prod.id);
                return (
                  <div
                    key={prod.id}
                    className={`${styles.productRow} ${isSelected ? styles.productRowSelected : ""}`}
                  >
                    <input
                      type="checkbox"
                      className={styles.itemCheckbox}
                      checked={isSelected}
                      onChange={() => toggleSelectProduct(prod.id)}
                      aria-label={`Select ${prod.name}`}
                    />
                    <div className={styles.productInfo}>
                      <span className={styles.productNameRow}>
                        <ItemBoxIcon size={16} className={styles.productIcon} />
                        <span className={styles.productName}>{prod.name}</span>
                      </span>
                      <div className={styles.pricesMeta}>
                        <span className={styles.retailBadge}>
                          Retail: {formatMoneyOrOnRequest(prod.effective_normal_price, currency)}
                        </span>
                        {prod.effective_wholesale_price ? (
                          <span className={styles.wholesaleBadge}>
                            Wholesale: {formatMoneyOrOnRequest(prod.effective_wholesale_price, currency)}
                            {prod.effective_pieces_per_pack ? ` (${prod.effective_pieces_per_pack}/pk)` : ""}
                          </span>
                        ) : null}
                        <span style={{ fontSize: "11px", color: "var(--ink-3)" }}>
                          - {formatQuantity(curStock?.available_quantity ?? "0")} in stock
                          {cat ? ` - in ${cat.name}` : ""}
                        </span>
                      </div>
                    </div>
                    <div className={styles.productActions}>
                      <button
                        type="button"
                        className={styles.copyItemBtn}
                        title={`Copy ${prod.name} into another folder`}
                        onClick={() => openBatchModal("copy", [prod.id], prod.name)}
                      >
                        Copy
                      </button>
                      <button
                        type="button"
                        className={styles.moveItemBtn}
                        title={`Move ${prod.name} into another folder or root`}
                        onClick={() => openBatchModal("move", [prod.id], prod.name)}
                      >
                        Move
                      </button>
                      <button
                        type="button"
                        className={`${styles.publishToggleBtn} ${prod.is_published ? styles.published : ""}`}
                        disabled={busyAction === `pub-${prod.id}`}
                        onClick={() => void handleTogglePublish(prod)}
                      >
                        {prod.is_published ? "In shop" : "Hidden"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}

          {searchResults.categories.length === 0 && searchResults.products.length === 0 ? (
            <Empty>Nothing matches &quot;{query}&quot;.</Empty>
          ) : null}
        </section>
      ) : viewMode === "tree" ? (
        /* Full Family Tree View (Genuine Branching Diagram) */
        <section className={styles.treeContainer}>
          <div style={{ marginBottom: "16px" }}>
            <h2 className={styles.sectionTitle} style={{ marginTop: 0 }}>
              Visual Category Family Tree
            </h2>
            <p style={{ fontSize: "12px", color: "var(--ink-3)", margin: "2px 0 0" }}>
              Interactive hierarchy with connecting branches, wholesale defaults, and quick copy/move actions
            </p>
          </div>
          <div className={styles.treeRoot}>
            <FamilyTreeRenderer
              categories={categories}
              products={products ?? []}
              stock={stock}
              currency={currency}
              parentId={null}
              onSelectCategory={(id) => {
                setCurrentCategoryId(id);
                setViewMode("folder");
              }}
              onStartMoveCategory={setMovingCategory}
              onStartBatchProduct={openBatchModal}
              onTogglePublish={handleTogglePublish}
              busyAction={busyAction}
            />
          </div>
        </section>
      ) : (
        /* Folder Drill-down View */
        <>
          {/* Subcategories folders */}
          {currentSubcategories.length > 0 ? (
            <section>
              <h2 className={styles.sectionTitle}>
                {currentCategoryId === null ? "Top Categories" : "Subcategories"} ({currentSubcategories.length})
              </h2>
              <div className={styles.folderGrid}>
                {currentSubcategories.map((cat) => {
                  const stats = getCategoryStats(cat.id);
                  return (
                    <div key={cat.id} className={styles.folderCard}>
                      <div
                        className={styles.folderCardMain}
                        onClick={() => setCurrentCategoryId(cat.id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            setCurrentCategoryId(cat.id);
                          }
                        }}
                      >
                        <span className={styles.folderMain}>
                          <span className={styles.folderIcon}>
                            <FolderIcon size={20} />
                          </span>
                          <div>
                            <span className={styles.folderName}>{cat.name}</span>
                            {cat.default_normal_price || cat.default_wholesale_price ? (
                              <div className={styles.catPriceDefaults}>
                                {cat.default_normal_price
                                  ? `Retail: ${formatMoneyOrOnRequest(cat.default_normal_price, currency)}`
                                  : ""}
                                {cat.default_normal_price && cat.default_wholesale_price ? " - " : ""}
                                {cat.default_wholesale_price
                                  ? `Wholesale: ${formatMoneyOrOnRequest(cat.default_wholesale_price, currency)}`
                                  : ""}
                                {cat.default_pieces_per_pack ? ` (${cat.default_pieces_per_pack}/pk)` : ""}
                              </div>
                            ) : null}
                          </div>
                        </span>
                        <span className={styles.folderCount}>
                          {stats.subcategories > 0 ? `${stats.subcategories} sub - ` : ""}
                          {stats.products} items
                        </span>
                        <ChevronRightIcon size={16} className={styles.folderChev} />
                      </div>
                      <button
                        type="button"
                        className={styles.moveFolderBtn}
                        title={`Move ${cat.name} into another folder`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setMovingCategory(cat);
                        }}
                      >
                        Move
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}

          {/* Products in this category */}
          <section>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "8px" }}>
              <h2 className={styles.sectionTitle}>
                {currentCategoryId === null ? "Items at Root / Uncategorized" : "Items in this category"} (
                {currentProducts.length})
              </h2>
              {currentProducts.length > 0 ? (
                <button
                  type="button"
                  style={{
                    background: "none",
                    border: "none",
                    color: "var(--leaf)",
                    fontWeight: 700,
                    fontSize: "12px",
                    cursor: "pointer",
                  }}
                  onClick={handleToggleSelectAll}
                >
                  {currentProducts.every((p) => selectedProductIds.has(p.id))
                    ? "Deselect All Visible"
                    : "Select All Visible"}
                </button>
              ) : null}
            </div>

            {currentProducts.length === 0 && currentSubcategories.length === 0 ? (
              <Empty
                illustration={<EmptyShelfIllustration size={110} />}
                action={
                  <div style={{ display: "flex", gap: "8px", justifyContent: "center", flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className={styles.actionBtn}
                      onClick={() => {
                        setNewCatParentId(currentCategoryId);
                        setShowAddCategory(true);
                        setShowAddProduct(false);
                      }}
                    >
                      <PlusIcon size={14} /> Add Category
                    </button>
                    <button
                      type="button"
                      className={styles.actionBtnSecondary}
                      onClick={() => {
                        setShowAddProduct(true);
                        setShowAddCategory(false);
                      }}
                    >
                      <PlusIcon size={14} /> Add Item
                    </button>
                  </div>
                }
              >
                {currentCategoryId
                  ? `"${breadcrumbs[breadcrumbs.length - 1]?.name ?? "This category"}" is empty.`
                  : "Your catalog is empty."}
                <br />
                Add categories with wholesale and retail prices, or add items directly.
              </Empty>
            ) : currentProducts.length === 0 ? (
              <p style={{ fontSize: "13px", color: "var(--ink-3)", padding: "8px 0" }}>
                No direct items here. Open a subcategory folder above or tap &quot;+ Add Item&quot;.
              </p>
            ) : (
              <div className={styles.productsList}>
                {currentProducts.map((prod) => {
                  const curStock = level(prod.id);
                  const isSelected = selectedProductIds.has(prod.id);
                  return (
                    <div
                      key={prod.id}
                      className={`${styles.productRow} ${isSelected ? styles.productRowSelected : ""}`}
                    >
                      <input
                        type="checkbox"
                        className={styles.itemCheckbox}
                        checked={isSelected}
                        onChange={() => toggleSelectProduct(prod.id)}
                        aria-label={`Select ${prod.name}`}
                      />
                      <div className={styles.productInfo}>
                        <span className={styles.productNameRow}>
                          <ItemBoxIcon size={16} className={styles.productIcon} />
                          <span className={styles.productName}>{prod.name}</span>
                        </span>
                        <div className={styles.pricesMeta}>
                          <span className={styles.retailBadge}>
                            Retail: {formatMoneyOrOnRequest(prod.effective_normal_price, currency)}
                          </span>
                          {prod.effective_wholesale_price ? (
                            <span className={styles.wholesaleBadge}>
                              Wholesale: {formatMoneyOrOnRequest(prod.effective_wholesale_price, currency)}
                              {prod.effective_pieces_per_pack ? ` (${prod.effective_pieces_per_pack}/pk)` : ""}
                            </span>
                          ) : null}
                          <span style={{ fontSize: "11px", color: "var(--ink-3)" }}>
                            - {formatQuantity(curStock?.available_quantity ?? "0")} in stock
                          </span>
                        </div>
                      </div>
                      <div className={styles.productActions}>
                        <button
                          type="button"
                          className={styles.copyItemBtn}
                          title={`Copy ${prod.name} into another folder`}
                          onClick={() => openBatchModal("copy", [prod.id], prod.name)}
                        >
                          Copy
                        </button>
                        <button
                          type="button"
                          className={styles.moveItemBtn}
                          title={`Move ${prod.name} into another folder or root`}
                          onClick={() => openBatchModal("move", [prod.id], prod.name)}
                        >
                          Move
                        </button>
                        <button
                          type="button"
                          className={`${styles.publishToggleBtn} ${prod.is_published ? styles.published : ""}`}
                          disabled={busyAction === `pub-${prod.id}`}
                          onClick={() => void handleTogglePublish(prod)}
                        >
                          {prod.is_published ? "In shop" : "Hidden"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}

      {/* Samsung File Manager Style Sticky Selection Toolbar */}
      {selectedProductIds.size > 0 ? (
        <div className={styles.selectionToolbar}>
          <div className={styles.selectionCountBadge}>
            <CheckMarkIcon size={16} />
            <span>{selectedProductIds.size} selected</span>
          </div>
          <div className={styles.selectionActions}>
            <button
              type="button"
              className={styles.selectionBtn}
              onClick={() => openBatchModal("copy", Array.from(selectedProductIds))}
            >
              <CopyIcon size={13} />
              <span>Copy to...</span>
            </button>
            <button
              type="button"
              className={styles.selectionBtn}
              onClick={() => openBatchModal("move", Array.from(selectedProductIds))}
            >
              <span>Move to...</span>
            </button>
            <button
              type="button"
              className={styles.selectionBtnSecondary}
              onClick={handleToggleSelectAll}
            >
              {currentProducts.every((p) => selectedProductIds.has(p.id))
                ? "Deselect All"
                : "Select All"}
            </button>
            <button
              type="button"
              className={styles.selectionBtnSecondary}
              onClick={() => setSelectedProductIds(new Set())}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {/* Batch Copy / Move Product Modal */}
      {batchModal !== null ? (
        <div
          className={styles.modalOverlay}
          role="dialog"
          aria-modal="true"
          aria-labelledby="batch-modal-title"
          onClick={() => !busyBatch && setBatchModal(null)}
        >
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div>
                <h2 id="batch-modal-title" className={styles.modalTitle}>
                  {batchModal.mode === "copy" ? "Copy" : "Move"}{" "}
                  {batchModal.productIds.length > 1
                    ? `${batchModal.productIds.length} items`
                    : `"${batchModal.sourceName ?? "item"}"`}
                </h2>
                <p className={styles.modalSubtitle}>
                  {batchModal.mode === "copy"
                    ? "Items will inherit destination folder's default prices unless they carry custom prices."
                    : "Choose destination folder or move out to Shelf Root."}
                </p>
              </div>
              <button
                type="button"
                className={styles.modalClose}
                aria-label="Close modal"
                disabled={busyBatch}
                onClick={() => setBatchModal(null)}
              >
                <CloseIcon size={16} />
              </button>
            </div>

            <div className={styles.modalBody}>
              {/* Shelf Root Option */}
              <button
                type="button"
                className={styles.moveOption}
                disabled={busyBatch}
                onClick={() => void handleExecuteBatch(null)}
              >
                <div className={styles.moveOptionMain}>
                  <FolderOpenIcon size={18} className={styles.moveOptionIcon} />
                  <div className={styles.moveOptionInfo}>
                    <span className={styles.moveOptionName}>Shelf Root (Uncategorized)</span>
                    <span className={styles.moveOptionPath}>Main shelf without folder grouping</span>
                  </div>
                </div>
                <span className={styles.selectMoveBtn}>
                  {busyBatch ? "Processing..." : batchModal.mode === "copy" ? "Copy Here" : "Move Here"}
                </span>
              </button>

              {/* All Categories */}
              {categories
                .slice()
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((target) => {
                  const fullPath = getCategoryPath(target, categories);
                  return (
                    <button
                      key={target.id}
                      type="button"
                      className={styles.moveOption}
                      disabled={busyBatch}
                      onClick={() => void handleExecuteBatch(target.id)}
                    >
                      <div className={styles.moveOptionMain}>
                        <FolderIcon size={18} className={styles.moveOptionIcon} />
                        <div className={styles.moveOptionInfo}>
                          <span className={styles.moveOptionName}>{target.name}</span>
                          <span className={styles.moveOptionPath}>
                            {fullPath}
                            {target.default_normal_price || target.default_wholesale_price
                              ? ` - Retail: ${formatMoneyOrOnRequest(target.default_normal_price, currency)} | Wholesale: ${formatMoneyOrOnRequest(target.default_wholesale_price, currency)}`
                              : ""}
                          </span>
                        </div>
                      </div>
                      <span className={styles.selectMoveBtn}>
                        {busyBatch ? "Processing..." : batchModal.mode === "copy" ? "Copy Here" : "Move Here"}
                      </span>
                    </button>
                  );
                })}
            </div>
          </div>
        </div>
      ) : null}

      {/* Move Category Modal */}
      {movingCategory !== null ? (
        <div
          className={styles.modalOverlay}
          role="dialog"
          aria-modal="true"
          aria-labelledby="move-category-title"
          onClick={() => !busyMove && setMovingCategory(null)}
        >
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div>
                <h2 id="move-category-title" className={styles.modalTitle}>
                  Move &quot;{movingCategory.name}&quot;
                </h2>
                <p className={styles.modalSubtitle}>
                  Choose a destination folder or move out to Shelf Root
                </p>
              </div>
              <button
                type="button"
                className={styles.modalClose}
                aria-label="Close modal"
                disabled={busyMove}
                onClick={() => setMovingCategory(null)}
              >
                <CloseIcon size={16} />
              </button>
            </div>

            <div className={styles.modalBody}>
              {/* Shelf Root Option */}
              <button
                type="button"
                className={`${styles.moveOption} ${movingCategory.parent_id === null ? styles.moveOptionCurrent : ""}`}
                disabled={busyMove || movingCategory.parent_id === null}
                onClick={() => void handleExecuteMove(null)}
              >
                <div className={styles.moveOptionMain}>
                  <FolderOpenIcon size={18} className={styles.moveOptionIcon} />
                  <div className={styles.moveOptionInfo}>
                    <span className={styles.moveOptionName}>Shelf Root (Top Level)</span>
                    <span className={styles.moveOptionPath}>Move out of all folders to main shelf</span>
                  </div>
                </div>
                {movingCategory.parent_id === null ? (
                  <span className={styles.currentBadge}>Current</span>
                ) : (
                  <span className={styles.selectMoveBtn}>Move Here</span>
                )}
              </button>

              {/* Other Eligible Categories */}
              {eligibleMoveTargets.map((target) => {
                const isCurrent = movingCategory.parent_id === target.id;
                const fullPath = getCategoryPath(target, categories);
                return (
                  <button
                    key={target.id}
                    type="button"
                    className={`${styles.moveOption} ${isCurrent ? styles.moveOptionCurrent : ""}`}
                    disabled={busyMove || isCurrent}
                    onClick={() => void handleExecuteMove(target.id)}
                  >
                    <div className={styles.moveOptionMain}>
                      <FolderIcon size={18} className={styles.moveOptionIcon} />
                      <div className={styles.moveOptionInfo}>
                        <span className={styles.moveOptionName}>{target.name}</span>
                        <span className={styles.moveOptionPath}>{fullPath}</span>
                      </div>
                    </div>
                    {isCurrent ? (
                      <span className={styles.currentBadge}>Current</span>
                    ) : (
                      <span className={styles.selectMoveBtn}>Move Here</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}

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

/** Authentic Visual Branching Tree Renderer for unlimited category depth */
function FamilyTreeRenderer({
  categories,
  products,
  stock,
  currency,
  parentId,
  onSelectCategory,
  onStartMoveCategory,
  onStartBatchProduct,
  onTogglePublish,
  busyAction,
}: {
  categories: Category[];
  products: Product[];
  stock: InventoryLevel[];
  currency: string;
  parentId: string | null;
  onSelectCategory: (id: string) => void;
  onStartMoveCategory?: (category: Category) => void;
  onStartBatchProduct: (mode: "copy" | "move", productIds: string[], sourceName?: string) => void;
  onTogglePublish: (prod: Product) => void;
  busyAction: string | null;
}) {
  const childCategories = categories.filter((c) => (c.parent_id ?? null) === parentId);
  const directProducts = products.filter((p) => (p.category_id ?? null) === parentId);

  if (childCategories.length === 0 && directProducts.length === 0) {
    return null;
  }

  return (
    <>
      {childCategories.map((cat) => {
        const catDirectProducts = products.filter((p) => p.category_id === cat.id);
        const subCats = categories.filter((c) => c.parent_id === cat.id);
        return (
          <div key={cat.id} className={styles.treeItemWrap}>
            {parentId !== null ? <div className={styles.treeConnectorElbow} /> : null}
            <div className={styles.treeCategoryCard} onClick={() => onSelectCategory(cat.id)}>
              <div className={styles.treeCategoryInfo}>
                <FolderIcon size={18} className={styles.treeFolderIcon} />
                <span className={styles.treeCategoryName}>{cat.name}</span>
                <span className={styles.treeCategoryMeta}>
                  ({catDirectProducts.length} items{subCats.length > 0 ? `, ${subCats.length} sub` : ""})
                </span>
                {cat.default_normal_price || cat.default_wholesale_price ? (
                  <span className={styles.catPriceDefaults}>
                    {cat.default_normal_price
                      ? `Retail: ${formatMoneyOrOnRequest(cat.default_normal_price, currency)}`
                      : ""}
                    {cat.default_normal_price && cat.default_wholesale_price ? " - " : ""}
                    {cat.default_wholesale_price
                      ? `Wholesale: ${formatMoneyOrOnRequest(cat.default_wholesale_price, currency)}`
                      : ""}
                  </span>
                ) : null}
              </div>
              <div className={styles.treeActions} onClick={(e) => e.stopPropagation()}>
                {catDirectProducts.length > 0 ? (
                  <button
                    type="button"
                    className={styles.copyItemBtn}
                    title={`Copy all ${catDirectProducts.length} items in ${cat.name} to another folder`}
                    onClick={() =>
                      onStartBatchProduct("copy", catDirectProducts.map((p) => p.id), `${cat.name} items`)
                    }
                  >
                    Copy All Items
                  </button>
                ) : null}
                {onStartMoveCategory ? (
                  <button
                    type="button"
                    className={styles.moveItemBtn}
                    title={`Move ${cat.name} folder`}
                    onClick={() => onStartMoveCategory(cat)}
                  >
                    Move
                  </button>
                ) : null}
                <ChevronRightIcon size={14} className={styles.treeChevIcon} />
              </div>
            </div>

            {/* Connecting branch for children */}
            {subCats.length > 0 || catDirectProducts.length > 0 ? (
              <div className={styles.treeBranch}>
                <FamilyTreeRenderer
                  categories={categories}
                  products={products}
                  stock={stock}
                  currency={currency}
                  parentId={cat.id}
                  onSelectCategory={onSelectCategory}
                  onStartMoveCategory={onStartMoveCategory}
                  onStartBatchProduct={onStartBatchProduct}
                  onTogglePublish={onTogglePublish}
                  busyAction={busyAction}
                />
              </div>
            ) : null}
          </div>
        );
      })}

      {directProducts.map((prod) => {
        const curStock = stock.find((s) => s.product_id === prod.id);
        return (
          <div key={prod.id} className={styles.treeItemWrap}>
            {parentId !== null ? <div className={styles.treeConnectorElbow} /> : null}
            <div className={styles.treeProductCard}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                <ItemBoxIcon size={15} className={styles.treeProductIcon} />
                <span className={styles.treeCategoryName}>{prod.name}</span>
                <div className={styles.pricesMeta}>
                  <span className={styles.retailBadge}>
                    Retail: {formatMoneyOrOnRequest(prod.effective_normal_price, currency)}
                  </span>
                  {prod.effective_wholesale_price ? (
                    <span className={styles.wholesaleBadge}>
                      Wholesale: {formatMoneyOrOnRequest(prod.effective_wholesale_price, currency)}
                      {prod.effective_pieces_per_pack ? ` (${prod.effective_pieces_per_pack}/pk)` : ""}
                    </span>
                  ) : null}
                  <span style={{ fontSize: "11px", color: "var(--ink-3)" }}>
                    - {formatQuantity(curStock?.available_quantity ?? "0")} in stock
                  </span>
                </div>
              </div>
              <div className={styles.treeActions}>
                <button
                  type="button"
                  className={styles.copyItemBtn}
                  onClick={() => onStartBatchProduct("copy", [prod.id], prod.name)}
                  title={`Copy ${prod.name} to another category`}
                >
                  Copy
                </button>
                <button
                  type="button"
                  className={styles.moveItemBtn}
                  onClick={() => onStartBatchProduct("move", [prod.id], prod.name)}
                  title={`Move ${prod.name} to another category`}
                >
                  Move
                </button>
                <button
                  type="button"
                  className={`${styles.publishToggleBtn} ${prod.is_published ? styles.published : ""}`}
                  disabled={busyAction === `pub-${prod.id}`}
                  onClick={() => onTogglePublish(prod)}
                >
                  {prod.is_published ? "In shop" : "Hidden"}
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}
