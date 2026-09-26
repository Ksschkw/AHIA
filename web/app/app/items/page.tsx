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
  EditIcon,
  FolderIcon,
  FolderOpenIcon,
  ItemBoxIcon,
  PlusIcon,
  SearchIcon,
  TrashIcon,
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
  updateCategory,
  deleteCategory,
  moveCategory,
  listProducts,
  createProduct,
  updateProduct,
  deleteProduct,
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

  // Editing category state
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);
  const [editCatName, setEditCatName] = useState("");
  const [editCatParentId, setEditCatParentId] = useState<string | null>(null);
  const [editCatNormalPrice, setEditCatNormalPrice] = useState("");
  const [editCatWholesalePrice, setEditCatWholesalePrice] = useState("");
  const [editCatPiecesPerPack, setEditCatPiecesPerPack] = useState("");
  const [busyEditCat, setBusyEditCat] = useState(false);

  // Deleting category state
  const [deletingCategory, setDeletingCategory] = useState<Category | null>(null);
  const [deleteCatStrategy, setDeleteCatStrategy] = useState<"move_up" | "hide" | "cascade">("move_up");
  const [busyDeleteCat, setBusyDeleteCat] = useState(false);

  // Editing product state
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [editProdName, setEditProdName] = useState("");
  const [editProdDescription, setEditProdDescription] = useState("");
  const [editProdSellingPrice, setEditProdSellingPrice] = useState("");
  const [editProdWholesalePrice, setEditProdWholesalePrice] = useState("");
  const [editProdPiecesPerPack, setEditProdPiecesPerPack] = useState("");
  const [editProdCategoryId, setEditProdCategoryId] = useState<string | null>(null);
  const [editProdPublish, setEditProdPublish] = useState(false);
  const [busyEditProd, setBusyEditProd] = useState(false);

  // Deleting product state
  const [deletingProduct, setDeletingProduct] = useState<Product | null>(null);
  const [busyDeleteProd, setBusyDeleteProd] = useState(false);

  // Batch delete confirm state
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false);
  const [busyBatchDelete, setBusyBatchDelete] = useState(false);

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

  // Open and update category
  const openEditCategory = (cat: Category) => {
    setEditingCategory(cat);
    setEditCatName(cat.name);
    setEditCatParentId(cat.parent_id ?? null);
    setEditCatNormalPrice(cat.default_normal_price ?? "");
    setEditCatWholesalePrice(cat.default_wholesale_price ?? "");
    setEditCatPiecesPerPack(cat.default_pieces_per_pack ? String(cat.default_pieces_per_pack) : "");
  };

  const isEditCatDirty = useMemo(() => {
    if (!editingCategory) return false;
    return (
      editCatName.trim() !== editingCategory.name ||
      (editCatParentId ?? null) !== (editingCategory.parent_id ?? null) ||
      editCatNormalPrice.trim() !== (editingCategory.default_normal_price ?? "") ||
      editCatWholesalePrice.trim() !== (editingCategory.default_wholesale_price ?? "") ||
      editCatPiecesPerPack.trim() !== (editingCategory.default_pieces_per_pack ? String(editingCategory.default_pieces_per_pack) : "")
    );
  }, [editingCategory, editCatName, editCatParentId, editCatNormalPrice, editCatWholesalePrice, editCatPiecesPerPack]);

  const eligibleEditCatParents = useMemo(() => {
    if (!editingCategory) return [];
    const descendantIds = getDescendantCategoryIds(editingCategory.id, categories);
    return categories
      .filter((cat) => cat.id !== editingCategory.id && !descendantIds.has(cat.id))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [editingCategory, categories, getDescendantCategoryIds]);

  async function handleUpdateCategory() {
    if (!business || !editingCategory || editCatName.trim().length < 1) return;
    setBusyEditCat(true);
    try {
      const packParsed = editCatPiecesPerPack.trim()
        ? parseInt(editCatPiecesPerPack.trim(), 10)
        : null;
      await updateCategory(business.id, editingCategory.id, {
        name: editCatName.trim(),
        parent_id: editCatParentId,
        default_normal_price: editCatNormalPrice.trim() || null,
        default_wholesale_price: editCatWholesalePrice.trim() || null,
        default_pieces_per_pack: Number.isFinite(packParsed) ? packParsed : null,
      });
      await load(business.id);
      setEditingCategory(null);
      setNotice({ message: `Category "${editCatName.trim()}" updated.`, tone: "good" });
    } catch {
      setNotice({ message: "Could not update category. Please check your values.", tone: "bad" });
    } finally {
      setBusyEditCat(false);
    }
  }

  // Open and update product
  const openEditProduct = (prod: Product) => {
    setEditingProduct(prod);
    setEditProdName(prod.name);
    setEditProdDescription(prod.description ?? "");
    setEditProdSellingPrice(prod.selling_price ?? "");
    setEditProdWholesalePrice(
      !prod.wholesale_price_from_group ? (prod.effective_wholesale_price ?? "") : "",
    );
    setEditProdPiecesPerPack(
      !prod.wholesale_price_from_group && prod.effective_pieces_per_pack
        ? String(prod.effective_pieces_per_pack)
        : "",
    );
    setEditProdCategoryId(prod.category_id ?? null);
    setEditProdPublish(prod.is_published);
  };

  const isEditProdDirty = useMemo(() => {
    if (!editingProduct) return false;
    const currentWholesale = !editingProduct.wholesale_price_from_group
      ? (editingProduct.effective_wholesale_price ?? "")
      : "";
    const currentPieces =
      !editingProduct.wholesale_price_from_group && editingProduct.effective_pieces_per_pack
        ? String(editingProduct.effective_pieces_per_pack)
        : "";

    return (
      editProdName.trim() !== editingProduct.name ||
      editProdDescription.trim() !== (editingProduct.description ?? "") ||
      editProdSellingPrice.trim() !== (editingProduct.selling_price ?? "") ||
      editProdWholesalePrice.trim() !== currentWholesale ||
      editProdPiecesPerPack.trim() !== currentPieces ||
      (editProdCategoryId ?? null) !== (editingProduct.category_id ?? null) ||
      editProdPublish !== editingProduct.is_published
    );
  }, [editingProduct, editProdName, editProdDescription, editProdSellingPrice, editProdWholesalePrice, editProdPiecesPerPack, editProdCategoryId, editProdPublish]);

  async function handleUpdateProduct() {
    if (!business || !editingProduct || editProdName.trim().length < 1) return;
    setBusyEditProd(true);
    try {
      const packParsed = editProdPiecesPerPack.trim()
        ? parseInt(editProdPiecesPerPack.trim(), 10)
        : null;
      await updateProduct(business.id, editingProduct.id, {
        name: editProdName.trim(),
        description: editProdDescription.trim() || null,
        selling_price: editProdSellingPrice.trim() || null,
        wholesale_price: editProdWholesalePrice.trim() || null,
        pieces_per_pack: Number.isFinite(packParsed) ? packParsed : null,
        category_id: editProdCategoryId,
      });

      if (editProdPublish && !editingProduct.is_published) {
        await publishProduct(business.id, editingProduct.id);
      } else if (!editProdPublish && editingProduct.is_published) {
        await unpublishProduct(business.id, editingProduct.id);
      }

      await load(business.id);
      setEditingProduct(null);
      setNotice({ message: `Item "${editProdName.trim()}" updated.`, tone: "good" });
    } catch {
      setNotice({ message: "Could not update item. Please check your values.", tone: "bad" });
    } finally {
      setBusyEditProd(false);
    }
  }

  // Deleting category with confirmation safeguards
  async function handleConfirmDeleteCategory() {
    if (!business || !deletingCategory) return;
    setBusyDeleteCat(true);
    try {
      const childCats = categories.filter((c) => c.parent_id === deletingCategory.id);
      const catProds = (products ?? []).filter((p) => p.category_id === deletingCategory.id);
      const hasContents = childCats.length > 0 || catProds.length > 0;

      if (hasContents && deleteCatStrategy === "hide") {
        const publishedProds = catProds.filter((p) => p.is_published);
        for (const p of publishedProds) {
          await unpublishProduct(business.id, p.id);
        }
        await load(business.id);
        setDeletingCategory(null);
        setNotice({
          message: `Unpublished ${publishedProds.length} product(s) in "${deletingCategory.name}". Category is hidden from customers.`,
          tone: "good",
        });
        return;
      }

      const strategyToUse: "move_up" | "cascade" | "restrict" = hasContents
        ? (deleteCatStrategy === "cascade" ? "cascade" : "move_up")
        : "restrict";
      await deleteCategory(business.id, deletingCategory.id, strategyToUse);

      if (currentCategoryId === deletingCategory.id) {
        setCurrentCategoryId(deletingCategory.parent_id ?? null);
      }

      await load(business.id);
      setDeletingCategory(null);
      setNotice({
        message: strategyToUse === "move_up"
          ? `Deleted "${deletingCategory.name}". Contents moved up to parent.`
          : `Deleted "${deletingCategory.name}".`,
        tone: "good",
      });
    } catch {
      setNotice({ message: "Could not delete category. Please try again.", tone: "bad" });
    } finally {
      setBusyDeleteCat(false);
    }
  }

  // Deleting single product
  async function handleConfirmDeleteProduct() {
    if (!business || !deletingProduct) return;
    setBusyDeleteProd(true);
    try {
      await deleteProduct(business.id, deletingProduct.id);
      setSelectedProductIds((prev) => {
        const next = new Set(prev);
        next.delete(deletingProduct.id);
        return next;
      });
      await load(business.id);
      setDeletingProduct(null);
      setNotice({ message: `Removed "${deletingProduct.name}" from catalog.`, tone: "good" });
    } catch {
      setNotice({ message: "Could not remove item. Please try again.", tone: "bad" });
    } finally {
      setBusyDeleteProd(false);
    }
  }

  // Batch delete selected products
  async function handleExecuteBatchDelete() {
    if (!business || selectedProductIds.size === 0) return;
    setBusyBatchDelete(true);
    try {
      const ids = Array.from(selectedProductIds);
      for (const id of ids) {
        await deleteProduct(business.id, id);
      }
      setSelectedProductIds(new Set());
      await load(business.id);
      setConfirmBatchDelete(false);
      setNotice({ message: `Removed ${ids.length} selected items from catalog.`, tone: "good" });
    } catch {
      setNotice({ message: "Could not delete all selected items.", tone: "bad" });
    } finally {
      setBusyBatchDelete(false);
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

          {currentCategory ? (
            <div className={styles.currentCategoryHeaderActions}>
              <button
                type="button"
                className={styles.folderEditBtn}
                title={`Edit "${currentCategory.name}" name and price defaults`}
                onClick={() => openEditCategory(currentCategory)}
              >
                Edit Folder
              </button>
              <button
                type="button"
                className={styles.folderDeleteBtn}
                title={`Delete "${currentCategory.name}"`}
                onClick={() => setDeletingCategory(currentCategory)}
              >
                Delete Folder
              </button>
            </div>
          ) : null}
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
                    <div className={styles.folderBtnGroup} onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className={styles.folderEditBtn}
                        title={`Edit "${cat.name}"`}
                        onClick={() => openEditCategory(cat)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className={styles.moveFolderBtn}
                        title={`Move "${cat.name}" into another folder`}
                        onClick={() => setMovingCategory(cat)}
                      >
                        Move
                      </button>
                      <button
                        type="button"
                        className={styles.folderDeleteBtn}
                        title={`Delete "${cat.name}"`}
                        onClick={() => setDeletingCategory(cat)}
                      >
                        Delete
                      </button>
                    </div>
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
                        className={styles.itemEditBtn}
                        title={`Edit "${prod.name}"`}
                        onClick={() => openEditProduct(prod)}
                      >
                        Edit
                      </button>
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
                      <button
                        type="button"
                        className={styles.itemDeleteBtn}
                        title={`Delete "${prod.name}"`}
                        onClick={() => setDeletingProduct(prod)}
                      >
                        Delete
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
              onStartEditCategory={openEditCategory}
              onStartDeleteCategory={setDeletingCategory}
              onStartMoveCategory={setMovingCategory}
              onStartEditProduct={openEditProduct}
              onStartDeleteProduct={setDeletingProduct}
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
                      <div className={styles.folderBtnGroup} onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className={styles.folderEditBtn}
                          title={`Edit "${cat.name}"`}
                          onClick={() => openEditCategory(cat)}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className={styles.moveFolderBtn}
                          title={`Move "${cat.name}" into another folder`}
                          onClick={() => setMovingCategory(cat)}
                        >
                          Move
                        </button>
                        <button
                          type="button"
                          className={styles.folderDeleteBtn}
                          title={`Delete "${cat.name}"`}
                          onClick={() => setDeletingCategory(cat)}
                        >
                          Delete
                        </button>
                      </div>
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
                          className={styles.itemEditBtn}
                          title={`Edit "${prod.name}"`}
                          onClick={() => openEditProduct(prod)}
                        >
                          Edit
                        </button>
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
                        <button
                          type="button"
                          className={styles.itemDeleteBtn}
                          title={`Delete "${prod.name}"`}
                          onClick={() => setDeletingProduct(prod)}
                        >
                          Delete
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
              className={styles.selectionBtnDanger}
              onClick={() => setConfirmBatchDelete(true)}
            >
              <TrashIcon size={13} />
              <span>Delete selected ({selectedProductIds.size})</span>
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

      {/* Edit Category Modal */}
      {editingCategory !== null ? (
        <div
          className={styles.modalOverlay}
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-category-title"
          onClick={() => !busyEditCat && setEditingCategory(null)}
        >
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div>
                <h2 id="edit-category-title" className={styles.modalTitle}>
                  Edit Category &quot;{editingCategory.name}&quot;
                </h2>
                <p className={styles.modalSubtitle}>
                  Update category name, parent folder, and price defaults
                </p>
              </div>
              <button
                type="button"
                className={styles.modalClose}
                aria-label="Close modal"
                disabled={busyEditCat}
                onClick={() => setEditingCategory(null)}
              >
                <CloseIcon size={16} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <Field
                label="Category name"
                id="edit_category_name"
                value={editCatName}
                placeholder="e.g. Screenguards, Cases"
                onChange={setEditCatName}
              />

              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="edit_category_parent" style={{ fontSize: "12px", fontWeight: 700, color: "var(--ink-2)" }}>
                  Parent Folder
                </label>
                <select
                  id="edit_category_parent"
                  value={editCatParentId ?? ""}
                  onChange={(e) => setEditCatParentId(e.target.value ? e.target.value : null)}
                  style={{
                    padding: "8px 12px",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--line-strong)",
                    background: "var(--card)",
                    color: "var(--ink)",
                    fontSize: "13px",
                  }}
                >
                  <option value="">Shelf Root (Top Level)</option>
                  {eligibleEditCatParents.map((parent) => (
                    <option key={parent.id} value={parent.id}>
                      {getCategoryPath(parent, categories)}
                    </option>
                  ))}
                </select>
              </div>

              <Field
                label="Default Retail Price"
                id="edit_category_normal_price"
                value={editCatNormalPrice}
                placeholder="e.g. 500"
                inputMode="decimal"
                optional
                onChange={setEditCatNormalPrice}
              />

              <Field
                label="Default Wholesale Price"
                id="edit_category_wholesale_price"
                value={editCatWholesalePrice}
                placeholder="e.g. 350"
                inputMode="decimal"
                optional
                onChange={setEditCatWholesalePrice}
              />

              <Field
                label="Default Pack Size"
                id="edit_category_pack"
                value={editCatPiecesPerPack}
                placeholder="e.g. 10"
                inputMode="numeric"
                optional
                onChange={setEditCatPiecesPerPack}
              />

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "12px" }}>
                <button
                  type="button"
                  className={styles.actionBtnSecondary}
                  disabled={busyEditCat}
                  onClick={() => setEditingCategory(null)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className={styles.actionBtn}
                  disabled={busyEditCat || !isEditCatDirty || editCatName.trim().length < 1}
                  onClick={() => void handleUpdateCategory()}
                >
                  {busyEditCat ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Delete Category Safeguard Modal */}
      {deletingCategory !== null ? (() => {
        const childCats = categories.filter((c) => c.parent_id === deletingCategory.id);
        const catProds = (products ?? []).filter((p) => p.category_id === deletingCategory.id);
        const hasContents = childCats.length > 0 || catProds.length > 0;
        const parentName = deletingCategory.parent_id
          ? categories.find((c) => c.id === deletingCategory.parent_id)?.name ?? "Parent folder"
          : "Shelf Root (Top Level)";

        return (
          <div
            className={styles.modalOverlay}
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-category-title"
            onClick={() => !busyDeleteCat && setDeletingCategory(null)}
          >
            <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
              <div className={styles.modalHeader}>
                <div>
                  <h2 id="delete-category-title" className={styles.modalTitle}>
                    Delete Category &quot;{deletingCategory.name}&quot;
                  </h2>
                  <p className={styles.modalSubtitle}>
                    {hasContents
                      ? `This folder contains ${childCats.length} subcategories and ${catProds.length} items.`
                      : "This folder is currently empty."}
                  </p>
                </div>
                <button
                  type="button"
                  className={styles.modalClose}
                  aria-label="Close modal"
                  disabled={busyDeleteCat}
                  onClick={() => setDeletingCategory(null)}
                >
                  <CloseIcon size={16} />
                </button>
              </div>

              <div className={styles.modalBody}>
                {hasContents ? (
                  <>
                    <p style={{ fontSize: "13px", color: "var(--ink-2)", margin: "0 0 4px" }}>
                      Choose how you want to handle the contents inside this folder:
                    </p>

                    <div
                      className={`${styles.strategyCard} ${deleteCatStrategy === "move_up" ? styles.strategyCardSelected : ""}`}
                      onClick={() => setDeleteCatStrategy("move_up")}
                      role="radio"
                      aria-checked={deleteCatStrategy === "move_up"}
                      tabIndex={0}
                    >
                      <div className={styles.strategyHeader}>
                        <span className={styles.strategyTitle}>Move contents up (Keep everything)</span>
                        <span className={styles.recommendedPill}>Recommended</span>
                      </div>
                      <span className={styles.strategyDesc}>
                        Keep all {childCats.length} subcategories and {catProds.length} items by moving them directly up to &quot;{parentName}&quot;. Nothing is lost.
                      </span>
                    </div>

                    <div
                      className={`${styles.strategyCard} ${deleteCatStrategy === "hide" ? styles.strategyCardSelected : ""}`}
                      onClick={() => setDeleteCatStrategy("hide")}
                      role="radio"
                      aria-checked={deleteCatStrategy === "hide"}
                      tabIndex={0}
                    >
                      <div className={styles.strategyHeader}>
                        <span className={styles.strategyTitle}>Hide folder instead</span>
                      </div>
                      <span className={styles.strategyDesc}>
                        Do not delete. Unpublishes all {catProds.length} items inside so customers cannot see them in your public shop, preserving your structure.
                      </span>
                    </div>

                    <div
                      className={`${styles.strategyCard} ${deleteCatStrategy === "cascade" ? styles.strategyCardSelected : ""}`}
                      onClick={() => setDeleteCatStrategy("cascade")}
                      role="radio"
                      aria-checked={deleteCatStrategy === "cascade"}
                      tabIndex={0}
                    >
                      <div className={styles.strategyHeader}>
                        <span className={styles.strategyTitle} style={{ color: "var(--danger)" }}>
                          Delete category and all contents
                        </span>
                      </div>
                      <span className={styles.strategyDesc}>
                        Permanently deletes this category, all its {childCats.length} subfolders, and all {catProds.length} items inside. This cannot be undone.
                      </span>
                    </div>
                  </>
                ) : (
                  <p style={{ fontSize: "13px", color: "var(--ink)", margin: "8px 0" }}>
                    Are you sure you want to delete &quot;{deletingCategory.name}&quot;? Since it contains no items or subfolders, it will be safely removed.
                  </p>
                )}

                <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "12px" }}>
                  <button
                    type="button"
                    className={styles.actionBtnSecondary}
                    disabled={busyDeleteCat}
                    onClick={() => setDeletingCategory(null)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className={styles.dangerBtn}
                    disabled={busyDeleteCat}
                    onClick={() => void handleConfirmDeleteCategory()}
                  >
                    {busyDeleteCat
                      ? "Processing..."
                      : deleteCatStrategy === "hide" && hasContents
                        ? "Hide Items"
                        : "Delete Category"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })() : null}

      {/* Edit Product Modal */}
      {editingProduct !== null ? (
        <div
          className={styles.modalOverlay}
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-product-title"
          onClick={() => !busyEditProd && setEditingProduct(null)}
        >
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div>
                <h2 id="edit-product-title" className={styles.modalTitle}>
                  Edit Item &quot;{editingProduct.name}&quot;
                </h2>
                <p className={styles.modalSubtitle}>
                  Update item details, prices, folder location, and publication status
                </p>
              </div>
              <button
                type="button"
                className={styles.modalClose}
                aria-label="Close modal"
                disabled={busyEditProd}
                onClick={() => setEditingProduct(null)}
              >
                <CloseIcon size={16} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <Field
                label="Item name"
                id="edit_product_name"
                value={editProdName}
                placeholder="e.g. Hot 8, Hot 9, Camon 30"
                onChange={setEditProdName}
              />

              <Field
                label="Description (optional)"
                id="edit_product_description"
                value={editProdDescription}
                placeholder="Item notes or customer information"
                optional
                onChange={setEditProdDescription}
              />

              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="edit_product_category" style={{ fontSize: "12px", fontWeight: 700, color: "var(--ink-2)" }}>
                  Category Folder
                </label>
                <select
                  id="edit_product_category"
                  value={editProdCategoryId ?? ""}
                  onChange={(e) => setEditProdCategoryId(e.target.value ? e.target.value : null)}
                  style={{
                    padding: "8px 12px",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--line-strong)",
                    background: "var(--card)",
                    color: "var(--ink)",
                    fontSize: "13px",
                  }}
                >
                  <option value="">Shelf Root (Uncategorized)</option>
                  {categories
                    .slice()
                    .sort((a, b) => a.name.localeCompare(b.name))
                    .map((cat) => (
                      <option key={cat.id} value={cat.id}>
                        {getCategoryPath(cat, categories)}
                      </option>
                    ))}
                </select>
              </div>

              <Field
                label="Retail Price (leave empty to follow category default)"
                id="edit_product_selling_price"
                value={editProdSellingPrice}
                placeholder="e.g. 2500"
                inputMode="decimal"
                optional
                onChange={setEditProdSellingPrice}
              />

              <Field
                label="Wholesale Price (leave empty to follow category default)"
                id="edit_product_wholesale_price"
                value={editProdWholesalePrice}
                placeholder="e.g. 1800"
                inputMode="decimal"
                optional
                onChange={setEditProdWholesalePrice}
              />

              <Field
                label="Pieces per pack (optional)"
                id="edit_product_pack"
                value={editProdPiecesPerPack}
                placeholder="e.g. 10"
                inputMode="numeric"
                optional
                onChange={setEditProdPiecesPerPack}
              />

              <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", cursor: "pointer", marginTop: "4px" }}>
                <input
                  type="checkbox"
                  checked={editProdPublish}
                  onChange={(e) => setEditProdPublish(e.target.checked)}
                />
                Publish in public shop
              </label>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "12px" }}>
                <button
                  type="button"
                  className={styles.actionBtnSecondary}
                  disabled={busyEditProd}
                  onClick={() => setEditingProduct(null)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className={styles.actionBtn}
                  disabled={busyEditProd || !isEditProdDirty || editProdName.trim().length < 1}
                  onClick={() => void handleUpdateProduct()}
                >
                  {busyEditProd ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Delete Product Confirmation Modal */}
      {deletingProduct !== null ? (
        <div
          className={styles.modalOverlay}
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-product-title"
          onClick={() => !busyDeleteProd && setDeletingProduct(null)}
        >
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div>
                <h2 id="delete-product-title" className={styles.modalTitle}>
                  Remove &quot;{deletingProduct.name}&quot;?
                </h2>
                <p className={styles.modalSubtitle}>
                  This item will be deleted from your catalog
                </p>
              </div>
              <button
                type="button"
                className={styles.modalClose}
                aria-label="Close modal"
                disabled={busyDeleteProd}
                onClick={() => setDeletingProduct(null)}
              >
                <CloseIcon size={16} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <p style={{ fontSize: "13px", color: "var(--ink)", margin: "4px 0 12px" }}>
                Are you sure you want to remove &quot;{deletingProduct.name}&quot; from your catalog? Existing sales receipts and history will keep their recorded sales lines, but this item will no longer appear on your shelves.
              </p>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
                <button
                  type="button"
                  className={styles.actionBtnSecondary}
                  disabled={busyDeleteProd}
                  onClick={() => setDeletingProduct(null)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className={styles.dangerBtn}
                  disabled={busyDeleteProd}
                  onClick={() => void handleConfirmDeleteProduct()}
                >
                  {busyDeleteProd ? "Removing..." : "Delete Item"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Batch Delete Confirmation Modal */}
      {confirmBatchDelete ? (
        <div
          className={styles.modalOverlay}
          role="dialog"
          aria-modal="true"
          aria-labelledby="batch-delete-title"
          onClick={() => !busyBatchDelete && setConfirmBatchDelete(false)}
        >
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div>
                <h2 id="batch-delete-title" className={styles.modalTitle}>
                  Delete {selectedProductIds.size} Selected Items?
                </h2>
                <p className={styles.modalSubtitle}>
                  Batch removal confirmation
                </p>
              </div>
              <button
                type="button"
                className={styles.modalClose}
                aria-label="Close modal"
                disabled={busyBatchDelete}
                onClick={() => setConfirmBatchDelete(false)}
              >
                <CloseIcon size={16} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <p style={{ fontSize: "13px", color: "var(--ink)", margin: "4px 0 12px" }}>
                Are you sure you want to permanently remove {selectedProductIds.size} selected items from your catalog? This action cannot be undone.
              </p>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
                <button
                  type="button"
                  className={styles.actionBtnSecondary}
                  disabled={busyBatchDelete}
                  onClick={() => setConfirmBatchDelete(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className={styles.dangerBtn}
                  disabled={busyBatchDelete}
                  onClick={() => void handleExecuteBatchDelete()}
                >
                  {busyBatchDelete ? "Deleting..." : `Delete ${selectedProductIds.size} Items`}
                </button>
              </div>
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
  onStartEditCategory,
  onStartDeleteCategory,
  onStartMoveCategory,
  onStartEditProduct,
  onStartDeleteProduct,
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
  onStartEditCategory?: (category: Category) => void;
  onStartDeleteCategory?: (category: Category) => void;
  onStartMoveCategory?: (category: Category) => void;
  onStartEditProduct?: (product: Product) => void;
  onStartDeleteProduct?: (product: Product) => void;
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
                {onStartEditCategory ? (
                  <button
                    type="button"
                    className={styles.folderEditBtn}
                    title={`Edit ${cat.name}`}
                    onClick={() => onStartEditCategory(cat)}
                  >
                    Edit
                  </button>
                ) : null}
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
                {onStartDeleteCategory ? (
                  <button
                    type="button"
                    className={styles.folderDeleteBtn}
                    title={`Delete ${cat.name} folder`}
                    onClick={() => onStartDeleteCategory(cat)}
                  >
                    Delete
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
                  onStartEditCategory={onStartEditCategory}
                  onStartDeleteCategory={onStartDeleteCategory}
                  onStartMoveCategory={onStartMoveCategory}
                  onStartEditProduct={onStartEditProduct}
                  onStartDeleteProduct={onStartDeleteProduct}
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
                {onStartEditProduct ? (
                  <button
                    type="button"
                    className={styles.itemEditBtn}
                    onClick={() => onStartEditProduct(prod)}
                    title={`Edit ${prod.name}`}
                  >
                    Edit
                  </button>
                ) : null}
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
                {onStartDeleteProduct ? (
                  <button
                    type="button"
                    className={styles.itemDeleteBtn}
                    onClick={() => onStartDeleteProduct(prod)}
                    title={`Delete ${prod.name}`}
                  >
                    Delete
                  </button>
                ) : null}
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}
