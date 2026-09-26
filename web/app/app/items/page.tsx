"use client";

/**
 * Everything on the shelf: categories and items with unlimited nesting.
 *
 * Rebuilt to support an arbitrary-depth category family tree:
 * - Categories nest without limit: Root -> Parent -> Child -> Grandchild -> Great-grandchild.
 * - Drill-down folder browsing with clickable breadcrumb trail ("All > Phones > Screenguards > 21D").
 * - Create subcategories under any existing folder or at root.
 * - Add products directly into any category or at root.
 * - Toggle products between published ("In shop") and unpublished ("Hidden").
 * - Switch between Folder drill-down view and Full Family Tree view.
 * - Instant search across all products and categories.
 * - Cache-first rendering with zero spinner flash.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

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
  listProducts,
  createProduct,
  publishProduct,
  unpublishProduct,
  listStock,
  type Category,
  type InventoryLevel,
  type Product,
  type Tenant,
} from "@/lib/api";
import { formatMoneyOrOnRequest, formatQuantity } from "@/lib/format";
import styles from "./items.module.css";

type Notice = { message: string; tone: "good" | "bad"; hint?: string };

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

  // Forms state
  const [showAddCategory, setShowAddCategory] = useState(false);
  const [newCatName, setNewCatName] = useState("");
  const [newCatParentId, setNewCatParentId] = useState<string | null>(null);
  const [newCatPrice, setNewCatPrice] = useState("");

  const [showAddProduct, setShowAddProduct] = useState(false);
  const [newProdName, setNewProdName] = useState("");
  const [newProdPrice, setNewProdPrice] = useState("");
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

  // Children of current category
  const currentSubcategories = useMemo(() => {
    return categories.filter((c) => (c.parent_id ?? null) === currentCategoryId);
  }, [categories, currentCategoryId]);

  // Products in current category
  const currentProducts = useMemo(() => {
    const all = products ?? [];
    if (currentCategoryId === null) {
      // At root, show uncategorized products or products explicitly at root
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

  async function handleCreateCategory() {
    if (!business) return;
    const name = newCatName.trim();
    if (name.length < 2) {
      setNotice({ message: "Category name must be at least 2 characters.", tone: "bad" });
      return;
    }
    setBusyAction("add-cat");
    try {
      const created = await createCategory(business.id, {
        name,
        parent_id: newCatParentId,
        default_normal_price: newCatPrice.trim() || undefined,
      });
      setCategories((current) => [...current, created]);
      setNewCatName("");
      setNewCatPrice("");
      setShowAddCategory(false);
      setNotice({ message: `Category "${name}" created.`, tone: "good" });
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
      let created = await createProduct(business.id, {
        name,
        selling_price: newProdPrice.trim() || undefined,
        category_id: currentCategoryId,
      });
      if (newProdPublish) {
        created = await publishProduct(business.id, created.id);
      }
      setProducts((current) => [...(current ?? []), created]);
      setNewProdName("");
      setNewProdPrice("");
      setShowAddProduct(false);
      setNotice({ message: `Item "${name}" added to shelf.`, tone: "good" });
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
          <h1 className={styles.title}>Shelf &amp; Categories</h1>
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
            Shelf Root
          </button>
          {breadcrumbs.map((crumb, idx) => {
            const isLast = idx === breadcrumbs.length - 1;
            return (
              <span key={crumb.id} style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                <span className={styles.crumbSep}>/</span>
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
        <input
          className={styles.search}
          id="items_search"
          value={query}
          placeholder="Search items or categories across all levels..."
          aria-label="Search items or categories"
          onChange={(event) => setQuery(event.target.value)}
        />

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
              + Add Category
            </button>
            <button
              type="button"
              className={styles.actionBtnSecondary}
              onClick={() => {
                setShowAddProduct((prev) => !prev);
                setShowAddCategory(false);
              }}
            >
              + Add Item
            </button>
          </div>
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
              placeholder="e.g. Screenguards, 21D, Chargers"
              onChange={setNewCatName}
            />
            <Field
              label="Default price (optional)"
              id="new_category_price"
              value={newCatPrice}
              placeholder="e.g. 1500"
              inputMode="decimal"
              optional
              onChange={setNewCatPrice}
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
              placeholder="e.g. Hot 8, Camon 30, Type C Fast Charger"
              onChange={setNewProdName}
            />
            <Field
              label="Selling price"
              id="new_product_price"
              value={newProdPrice}
              placeholder="e.g. 2500"
              inputMode="decimal"
              optional
              onChange={setNewProdPrice}
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
        <Loading label="Fetching your shelf..." />
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
                  <button
                    key={cat.id}
                    type="button"
                    className={styles.folderCard}
                    onClick={() => {
                      setCurrentCategoryId(cat.id);
                      setQuery("");
                    }}
                  >
                    <span className={styles.folderMain}>
                      <span className={styles.folderIcon}>[DIR]</span>
                      <span className={styles.folderName}>{cat.name}</span>
                    </span>
                    <span className={styles.folderCount}>
                      {stats.products} items
                    </span>
                  </button>
                );
              })}
            </div>
          ) : null}

          {searchResults.products.length > 0 ? (
            <div className={styles.productsList}>
              {searchResults.products.map((prod) => {
                const curStock = level(prod.id);
                const cat = categories.find((c) => c.id === prod.category_id);
                return (
                  <div key={prod.id} className={styles.productRow}>
                    <div className={styles.productInfo}>
                      <span className={styles.productName}>{prod.name}</span>
                      <span className={styles.productMeta}>
                        <span className={styles.productPrice}>
                          {formatMoneyOrOnRequest(prod.effective_normal_price, currency)}
                        </span>
                        <span>-</span>
                        <span>{formatQuantity(curStock?.available_quantity ?? "0")} in stock</span>
                        {cat ? <span>- in {cat.name}</span> : null}
                      </span>
                    </div>
                    <div className={styles.productActions}>
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
        /* Full Family Tree View (Recursive unlimited nesting) */
        <section className={styles.treeContainer}>
          <h2 className={styles.sectionTitle} style={{ marginTop: 0 }}>
            Complete Category Family Tree
          </h2>
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
            onTogglePublish={handleTogglePublish}
            busyAction={busyAction}
          />
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
                    <button
                      key={cat.id}
                      type="button"
                      className={styles.folderCard}
                      onClick={() => setCurrentCategoryId(cat.id)}
                    >
                      <span className={styles.folderMain}>
                        <span className={styles.folderIcon}>[DIR]</span>
                        <span className={styles.folderName}>{cat.name}</span>
                      </span>
                      <span className={styles.folderCount}>
                        {stats.subcategories > 0 ? `${stats.subcategories} sub - ` : ""}
                        {stats.products} items
                      </span>
                      <span className={styles.folderChev} aria-hidden>
                        &gt;
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>
          ) : null}

          {/* Products in this category */}
          <section>
            <h2 className={styles.sectionTitle}>
              {currentCategoryId === null ? "Items at Root / Uncategorized" : "Items in this category"} (
              {currentProducts.length})
            </h2>

            {currentProducts.length === 0 && currentSubcategories.length === 0 ? (
              <Empty>
                This category is empty. Tap &quot;+ Add Category&quot; to add a subcategory or &quot;+ Add Item&quot;
                to add products here.
              </Empty>
            ) : currentProducts.length === 0 ? (
              <p style={{ fontSize: "13px", color: "var(--ink-3)", padding: "8px 0" }}>
                No direct items here. Open a subcategory folder above or tap &quot;+ Add Item&quot;.
              </p>
            ) : (
              <div className={styles.productsList}>
                {currentProducts.map((prod) => {
                  const curStock = level(prod.id);
                  return (
                    <div key={prod.id} className={styles.productRow}>
                      <div className={styles.productInfo}>
                        <span className={styles.productName}>{prod.name}</span>
                        <span className={styles.productMeta}>
                          <span className={styles.productPrice}>
                            {formatMoneyOrOnRequest(prod.effective_normal_price, currency)}
                          </span>
                          <span>-</span>
                          <span>{formatQuantity(curStock?.available_quantity ?? "0")} in stock</span>
                        </span>
                      </div>
                      <div className={styles.productActions}>
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

/** Recursive family tree component to render arbitrary-depth nesting */
function FamilyTreeRenderer({
  categories,
  products,
  stock,
  currency,
  parentId,
  onSelectCategory,
  onTogglePublish,
  busyAction,
}: {
  categories: Category[];
  products: Product[];
  stock: InventoryLevel[];
  currency: string;
  parentId: string | null;
  onSelectCategory: (id: string) => void;
  onTogglePublish: (prod: Product) => void;
  busyAction: string | null;
}) {
  const childCategories = categories.filter((c) => (c.parent_id ?? null) === parentId);
  const directProducts = products.filter((p) => (p.category_id ?? null) === parentId);

  if (childCategories.length === 0 && directProducts.length === 0) {
    return null;
  }

  return (
    <div className={parentId === null ? undefined : styles.treeNode}>
      {childCategories.map((cat) => (
        <div key={cat.id} style={{ marginBottom: "6px" }}>
          <div className={styles.treeRow} onClick={() => onSelectCategory(cat.id)}>
            <span>[dir]</span>
            <span className={styles.treeNodeName}>{cat.name}</span>
            <span className={styles.treeNodeMeta}>(tap to enter folder)</span>
          </div>
          <FamilyTreeRenderer
            categories={categories}
            products={products}
            stock={stock}
            currency={currency}
            parentId={cat.id}
            onSelectCategory={onSelectCategory}
            onTogglePublish={onTogglePublish}
            busyAction={busyAction}
          />
        </div>
      ))}

      {directProducts.map((prod) => {
        const curStock = stock.find((s) => s.product_id === prod.id);
        return (
          <div
            key={prod.id}
            className={styles.treeRow}
            style={{ paddingLeft: "16px", justifyContent: "space-between" }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span>[item]</span>
              <span className={styles.treeNodeName}>{prod.name}</span>
              <span className={styles.treeNodeMeta}>
                {formatMoneyOrOnRequest(prod.effective_normal_price, currency)} -{" "}
                {formatQuantity(curStock?.available_quantity ?? "0")} in stock
              </span>
            </div>
            <button
              type="button"
              className={`${styles.publishToggleBtn} ${prod.is_published ? styles.published : ""}`}
              disabled={busyAction === `pub-${prod.id}`}
              onClick={() => onTogglePublish(prod)}
            >
              {prod.is_published ? "In shop" : "Hidden"}
            </button>
          </div>
        );
      })}
    </div>
  );
}
