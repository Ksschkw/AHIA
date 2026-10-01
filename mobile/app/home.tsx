import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  FlatList,
  Linking,
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  ArrowLeftIcon,
  BoxIcon,
  CannotGetIcon,
  CartIcon,
  CheckMarkIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ClockIcon,
  CloseIcon,
  CopyIcon,
  EditIcon,
  FolderIcon,
  FolderOpenIcon,
  ImageIcon,
  ItemBoxIcon,
  ListIcon,
  MoreIcon,
  PeopleIcon,
  PersonIcon,
  PhoneIcon,
  PlusIcon,
  ReceiptIcon,
  SearchIcon,
  ShareIcon,
  ShopIcon,
  SyncIcon,
  TagIcon,
  TrashIcon,
  TreeIcon,
  TruckIcon,
} from "@/components/icons";
import {
  ApiError,
  acceptInvitation,
  cancelSale,
  changeMemberRole,
  changeMemberStatus,
  changePassword,
  confirmCustomerList,
  copyProducts,
  createCategory,
  createProduct,
  currentUser,
  dailySales,
  deleteCategory,
  deleteCustomerList,
  deleteProduct,
  dispatchCustomerList,
  getBusiness,
  getStorefront,
  inviteMember,
  listBusinesses,
  listCategories,
  listCustomerLists,
  listExpenseCategories,
  listInvitations,
  listMembers,
  listMyInvitations,
  listProductImages,
  listProducts,
  listSales,
  makeProductImagePrimary,
  publishStorefront,
  receiveStock,
  recordExpense,
  recordSale,
  removeMember,
  removeProductImage,
  sellOneProduct,
  submitCustomerList,
  unpublishStorefront,
  updateBusiness,
  updateCategory,
  updateProduct,
  updateStorefront,
  workListLine,
  type Category,
  type CustomerList,
  type CustomerListLine,
  type DailySalesSummary,
  type ExpenseCategory,
  type Member,
  type MemberRole,
  type MembershipInvitation,
  type PendingInvitation,
  type Product,
  type ProductImage,
  type SaleSummary,
  type StorefrontDetails,
  type TenantDetails,
  type TenantSummary,
  type UserProfile,
} from "@/lib/api";
import {
  cacheCategories,
  cacheCustomerLists,
  cacheProducts,
  enqueueOfflineSale,
  flushOutbox,
  getCachedCategories,
  getCachedCustomerLists,
  getCachedProducts,
  getPendingSalesCount,
} from "@/lib/db";
import { forgetSession } from "@/lib/session";

type TabKey = "dashboard" | "shelf" | "lists" | "trading" | "more";

function formatMoney(amount: string | null | undefined): string {
  if (!amount) return "Price on request";
  const num = Number(amount);
  if (!Number.isFinite(num)) return `NGN ${amount}`;
  return `NGN ${num.toLocaleString("en-NG", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
}

function formatWaNumber(rawPhone: string | null | undefined): string | null {
  if (!rawPhone) return null;
  const digits = rawPhone.replace(/[^\d]/g, "");
  if (!digits) return null;
  if (digits.startsWith("234")) return digits;
  if (digits.startsWith("0")) return "234" + digits.slice(1);
  if (digits.length === 10 && (digits.startsWith("7") || digits.startsWith("8") || digits.startsWith("9"))) {
    return "234" + digits;
  }
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

function groupCustomerListLines(lines: CustomerListLine[]) {
  const rootMap = new Map<string, Map<string, CustomerListLine[]>>();

  for (const line of lines) {
    if (line.note === "heading") continue;

    const rawGroup = line.group_name?.trim();
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

export default function Home() {
  const router = useRouter();

  const [activeTab, setActiveTab] = useState<TabKey>("dashboard");
  const [businesses, setBusinesses] = useState<TenantSummary[] | null>(null);
  const [activeBusiness, setActiveBusiness] = useState<TenantSummary | null>(null);
  const [businessDetails, setBusinessDetails] = useState<TenantDetails | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);

  // Data states
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [customerLists, setCustomerLists] = useState<CustomerList[]>([]);
  const [sales, setSales] = useState<SaleSummary[]>([]);
  const [dailyStats, setDailyStats] = useState<DailySalesSummary | null>(null);
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<MembershipInvitation[]>([]);

  // Catalog / Shelf Hierarchy states
  const [currentCategoryId, setCurrentCategoryId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"folder" | "tree">("folder");
  const [selectedProductIds, setSelectedProductIds] = useState<Set<string>>(new Set());
  const [batchModal, setBatchModal] = useState<{ mode: "copy" | "move"; productIds: string[] } | null>(null);
  const [savingBatch, setSavingBatch] = useState(false);

  // Search & Filters
  const [searchQuery, setSearchQuery] = useState("");

  // Loading & Sync States
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [pendingSyncCount, setPendingSyncCount] = useState(0);
  const [isSyncing, setIsSyncing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // Modals
  const [showAddProductModal, setShowAddProductModal] = useState(false);
  const [newName, setNewName] = useState("");
  const [newPrice, setNewPrice] = useState("");
  const [newWholesale, setNewWholesale] = useState("");
  const [savingProduct, setSavingProduct] = useState(false);

  const [showAddCategoryModal, setShowAddCategoryModal] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [newCategoryNormalPrice, setNewCategoryNormalPrice] = useState("");
  const [newCategoryWholesalePrice, setNewCategoryWholesalePrice] = useState("");
  const [savingCategory, setSavingCategory] = useState(false);

  const [editingCategory, setEditingCategory] = useState<Category | null>(null);
  const [editCategoryName, setEditCategoryName] = useState("");
  const [editCategoryNormalPrice, setEditCategoryNormalPrice] = useState("");
  const [editCategoryWholesalePrice, setEditCategoryWholesalePrice] = useState("");
  const [savingEditCategory, setSavingEditCategory] = useState(false);

  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [editPrice, setEditPrice] = useState("");
  const [editWholesale, setEditWholesale] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  const [restockProduct, setRestockProduct] = useState<Product | null>(null);
  const [restockQty, setRestockQty] = useState("");
  const [savingRestock, setSavingRestock] = useState(false);

  // Product Gallery state
  const [galleryProduct, setGalleryProduct] = useState<Product | null>(null);
  const [galleryImages, setGalleryImages] = useState<ProductImage[]>([]);
  const [loadingGallery, setLoadingGallery] = useState(false);

  const [pricingLine, setPricingLine] = useState<{
    listId: string;
    lineId: string;
    itemName: string;
    currentShopPrice: string;
    currentCostPrice: string;
  } | null>(null);
  const [priceInput, setPriceInput] = useState("");
  const [costInput, setCostInput] = useState("");
  const [savingPrice, setSavingPrice] = useState(false);

  // Dispatch Waybill modal state
  const [dispatchModalList, setDispatchModalList] = useState<CustomerList | null>(null);
  const [transporterName, setTransporterName] = useState("");
  const [transporterPhone, setTransporterPhone] = useState("");
  const [waybillNumber, setWaybillNumber] = useState("");
  const [dispatchCost, setDispatchCost] = useState("");
  const [trackingUrl, setTrackingUrl] = useState("");
  const [savingDispatch, setSavingDispatch] = useState(false);

  // Security PIN Confirmation Modal for Customer Lists
  const [pinConfirmList, setPinConfirmList] = useState<CustomerList | null>(null);
  const [pinValue, setPinValue] = useState("");

  // Quick-Paste Customer Order Modal
  const [showQuickPasteModal, setShowQuickPasteModal] = useState(false);
  const [quickPastePhone, setQuickPastePhone] = useState("");
  const [quickPasteName, setQuickPasteName] = useState("");
  const [quickPasteText, setQuickPasteText] = useState("");
  const [savingQuickPaste, setSavingQuickPaste] = useState(false);

  // Trading Ledger states
  const [tradingSubTab, setTradingSubTab] = useState<"sales" | "expenses">("sales");
  const [showRecordSaleModal, setShowRecordSaleModal] = useState(false);
  const [saleProductId, setSaleProductId] = useState<string | null>(null);
  const [saleQuantity, setSaleQuantity] = useState("1");
  const [salePrice, setSalePrice] = useState("");
  const [salePaymentMethod, setSalePaymentMethod] = useState("cash");
  const [savingSale, setSavingSale] = useState(false);
  const [saleSearchQuery, setSaleSearchQuery] = useState("");

  const [showExpenseModal, setShowExpenseModal] = useState(false);
  const [expenseAmount, setExpenseAmount] = useState("");
  const [expenseDescription, setExpenseDescription] = useState("");
  const [expenseCategoryId, setExpenseCategoryId] = useState<string>("");
  const [expensePaymentMethod, setExpensePaymentMethod] = useState("cash");
  const [savingExpense, setSavingExpense] = useState(false);

  const [showInviteModal, setShowInviteModal] = useState(false);
  const [invitePhone, setInvitePhone] = useState("");
  const [inviteRole, setInviteRole] = useState<MemberRole>("SALES");
  const [savingInvite, setSavingInvite] = useState(false);

  const [storefrontDetails, setStorefrontDetails] = useState<StorefrontDetails | null>(null);
  const [showStorefrontModal, setShowStorefrontModal] = useState(false);
  const [storefrontHeadline, setStorefrontHeadline] = useState("");
  const [storefrontDesc, setStorefrontDesc] = useState("");
  const [storefrontPhone, setStorefrontPhone] = useState("");
  const [storefrontThemeColor, setStorefrontThemeColor] = useState("#084a2f");
  const [storefrontThemeBg, setStorefrontThemeBg] = useState("#fbf7f0");
  const [storefrontClosing, setStorefrontClosing] = useState("");
  const [savingStorefront, setSavingStorefront] = useState(false);

  const [myInvitations, setMyInvitations] = useState<PendingInvitation[]>([]);

  const [showBusinessModal, setShowBusinessModal] = useState(false);
  const [editBizName, setEditBizName] = useState("");
  const [editBizAddress, setEditBizAddress] = useState("");
  const [editBizPhone, setEditBizPhone] = useState("");
  const [savingBusiness, setSavingBusiness] = useState(false);

  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);

  const [showShopModal, setShowShopModal] = useState(false);

  const showToast = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(null), 3200);
  };

  const loadData = useCallback(async (tenantId: string) => {
    const cached = getCachedProducts(tenantId);
    const cachedCats = getCachedCategories(tenantId);
    const cachedLists = getCachedCustomerLists(tenantId);
    if (cached.length > 0) {
      setProducts(cached);
      setLoading(false);
    }
    if (cachedCats.length > 0) {
      setCategories(cachedCats);
    }
    if (cachedLists.length > 0) {
      setCustomerLists(cachedLists);
    }

    const pending = getPendingSalesCount(tenantId);
    setPendingSyncCount(pending);

    try {
      const [
        freshProducts,
        freshLists,
        freshCategories,
        freshSales,
        freshDaily,
        freshExpCats,
        freshMembers,
        freshInvs,
        myInvs,
        bDetails,
        uProfile,
        sDetails,
      ] = await Promise.all([
        listProducts(tenantId).catch(() => cached),
        listCustomerLists(tenantId).catch(() => cachedLists),
        listCategories(tenantId).catch(() => cachedCats),
        listSales(tenantId).catch(() => []),
        dailySales(tenantId).catch(() => null),
        listExpenseCategories(tenantId).catch(() => ({ categories: [] })),
        listMembers(tenantId).catch(() => []),
        listInvitations(tenantId).catch(() => []),
        listMyInvitations().catch(() => []),
        getBusiness(tenantId).catch(() => null),
        currentUser().catch(() => null),
        getStorefront(tenantId).catch(() => null),
      ]);

      setProducts(freshProducts);
      cacheProducts(tenantId, freshProducts);
      setCustomerLists(freshLists);
      cacheCustomerLists(tenantId, freshLists);
      setCategories(freshCategories);
      cacheCategories(tenantId, freshCategories);
      setSales(freshSales);
      setDailyStats(freshDaily);
      setExpenseCategories(freshExpCats.categories);
      if (freshExpCats.categories.length > 0 && !expenseCategoryId) {
        setExpenseCategoryId(freshExpCats.categories[0].id);
      }
      setMembers(freshMembers);
      setInvitations(freshInvs);
      setMyInvitations(myInvs);
      setBusinessDetails(bDetails);
      setProfile(uProfile);
      setStorefrontDetails(sDetails);
      if (sDetails) {
        setStorefrontHeadline(sDetails.headline ?? "");
        setStorefrontDesc(sDetails.description ?? "");
        setStorefrontPhone(sDetails.contact_phone ?? "");
        setStorefrontThemeColor(sDetails.theme_color ?? "#084a2f");
        setStorefrontThemeBg(sDetails.theme_bg_color ?? "#fbf7f0");
        setStorefrontClosing(sDetails.closing_statement ?? "");
      }
      setProblem(null);
    } catch {
      if (cached.length === 0) {
        setProblem("Could not connect. Showing offline data where available.");
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [expenseCategoryId]);

  useEffect(() => {
    void (async () => {
      try {
        const found = await listBusinesses();
        setBusinesses(found);
        if (found.length > 0) {
          const initial = found[0];
          setActiveBusiness(initial);
          await loadData(initial.id);
        } else {
          setLoading(false);
        }
      } catch (error) {
        setProblem(error instanceof ApiError ? error.message : "We could not load your shops.");
        setLoading(false);
      }
    })();
  }, [loadData]);

  // Foreground auto-sync: flush offline sales outbox when app returns to foreground
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (nextAppState) => {
      if (nextAppState === "active" && activeBusiness) {
        void flushOutbox(activeBusiness.id).then((synced) => {
          if (synced > 0) {
            setPendingSyncCount(getPendingSalesCount(activeBusiness.id));
            showToast(`Synced ${synced} offline sale(s).`);
          }
        });
      }
    });
    return () => {
      subscription.remove();
    };
  }, [activeBusiness]);

  // Hierarchical Breadcrumbs
  const breadcrumbs = useMemo(() => {
    const trail: Category[] = [];
    let curId = currentCategoryId;
    while (curId !== null) {
      const match = categories.find((c) => c.id === curId);
      if (!match) break;
      trail.unshift(match);
      curId = match.parent_id ?? null;
    }
    return trail;
  }, [categories, currentCategoryId]);

  const currentCategory = useMemo(() => {
    if (!currentCategoryId) return null;
    return categories.find((c) => c.id === currentCategoryId) ?? null;
  }, [categories, currentCategoryId]);

  const currentSubcategories = useMemo(() => {
    return categories.filter((c) => (c.parent_id ?? null) === currentCategoryId);
  }, [categories, currentCategoryId]);

  const currentProducts = useMemo(() => {
    if (searchQuery.trim().length >= 2) {
      const q = searchQuery.trim().toLowerCase();
      return products.filter((p) => p.name.toLowerCase().includes(q));
    }
    if (currentCategoryId === null) {
      return products.filter((p) => p.category_id === null);
    }
    return products.filter((p) => p.category_id === currentCategoryId);
  }, [products, currentCategoryId, searchQuery]);

  const handleSyncOutbox = async () => {
    if (!activeBusiness || isSyncing) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setIsSyncing(true);
    try {
      const synced = await flushOutbox(activeBusiness.id);
      const remaining = getPendingSalesCount(activeBusiness.id);
      setPendingSyncCount(remaining);
      await loadData(activeBusiness.id);
      if (synced > 0) {
        showToast(`Synced ${synced} offline sale(s).`);
      } else {
        showToast("Everything is up to date.");
      }
    } catch {
      showToast("Sync failed. Will retry automatically.");
    } finally {
      setIsSyncing(false);
    }
  };

  const handleSellOne = async (product: Product) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

    const price = product.effective_normal_price ?? product.selling_price ?? "0";

    try {
      await sellOneProduct(activeBusiness.id, product);
      showToast(`Sold 1 ${product.name}`);
      void loadData(activeBusiness.id);
    } catch {
      enqueueOfflineSale({
        tenantId: activeBusiness.id,
        productId: product.id,
        productName: product.name,
        quantity: "1.000",
        unitPrice: price,
        paymentMethod: "cash",
      });
      setPendingSyncCount(getPendingSalesCount(activeBusiness.id));
      showToast(`Saved offline: 1 ${product.name}`);
    }
  };

  const handleCreateProduct = async () => {
    if (!activeBusiness || !newName.trim()) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingProduct(true);
    try {
      const created = await createProduct(activeBusiness.id, {
        name: newName.trim(),
        selling_price: newPrice.trim() || null,
        wholesale_price: newWholesale.trim() || null,
        category_id: currentCategoryId,
      });
      setProducts((curr) => [...curr, created]);
      cacheProducts(activeBusiness.id, [...products, created]);
      setNewName("");
      setNewPrice("");
      setNewWholesale("");
      setShowAddProductModal(false);
      showToast(`Added ${created.name} to shelf!`);
    } catch {
      showToast("Could not save item. Check connection.");
    } finally {
      setSavingProduct(false);
    }
  };

  const handleCreateCategory = async () => {
    if (!activeBusiness || !newCategoryName.trim()) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingCategory(true);
    try {
      const created = await createCategory(activeBusiness.id, {
        name: newCategoryName.trim(),
        parent_id: currentCategoryId,
        default_normal_price: newCategoryNormalPrice.trim() || undefined,
        default_wholesale_price: newCategoryWholesalePrice.trim() || undefined,
      });
      setCategories((curr) => [...curr, created]);
      setNewCategoryName("");
      setNewCategoryNormalPrice("");
      setNewCategoryWholesalePrice("");
      setShowAddCategoryModal(false);
      showToast(`Created folder: ${created.name}`);
    } catch {
      showToast("Could not create folder.");
    } finally {
      setSavingCategory(false);
    }
  };

  const handleSaveCategoryEdit = async () => {
    if (!activeBusiness || !editingCategory) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingEditCategory(true);
    try {
      const updated = await updateCategory(activeBusiness.id, editingCategory.id, {
        name: editCategoryName.trim() || undefined,
        default_normal_price: editCategoryNormalPrice.trim() || null,
        default_wholesale_price: editCategoryWholesalePrice.trim() || null,
      });
      setCategories((curr) => curr.map((c) => (c.id === updated.id ? updated : c)));
      setEditingCategory(null);
      showToast(`Updated folder ${updated.name}`);
    } catch {
      showToast("Could not update category.");
    } finally {
      setSavingEditCategory(false);
    }
  };

  const handleDeleteCategory = (category: Category) => {
    if (!activeBusiness) return;
    Alert.alert(
      "Delete Folder?",
      `Are you sure you want to delete ${category.name}? Items inside will move up to parent folder.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            try {
              await deleteCategory(activeBusiness.id, category.id, "move_up");
              setCategories((curr) => curr.filter((c) => c.id !== category.id));
              if (currentCategoryId === category.id) {
                setCurrentCategoryId(category.parent_id ?? null);
              }
              showToast(`Deleted ${category.name}`);
              await loadData(activeBusiness.id);
            } catch {
              showToast("Could not delete category.");
            }
          },
        },
      ],
    );
  };

  const handleDeleteProduct = (product: Product) => {
    if (!activeBusiness) return;
    Alert.alert(
      "Delete Product?",
      `Are you sure you want to delete ${product.name}?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            try {
              await deleteProduct(activeBusiness.id, product.id);
              setProducts((curr) => curr.filter((p) => p.id !== product.id));
              cacheProducts(activeBusiness.id, products.filter((p) => p.id !== product.id));
              showToast(`Deleted ${product.name}`);
            } catch {
              showToast("Could not delete product.");
            }
          },
        },
      ],
    );
  };

  const handleToggleSelectProduct = (productId: string) => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
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

  const handleExecuteBatchAction = async (targetCategoryId: string | null) => {
    if (!activeBusiness || !batchModal) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingBatch(true);
    try {
      if (batchModal.mode === "copy") {
        await copyProducts(activeBusiness.id, batchModal.productIds, targetCategoryId);
        showToast(`Copied ${batchModal.productIds.length} item(s)`);
      } else {
        await Promise.all(
          batchModal.productIds.map((id) =>
            updateProduct(activeBusiness.id, id, { category_id: targetCategoryId }),
          ),
        );
        showToast(`Moved ${batchModal.productIds.length} item(s)`);
      }
      setBatchModal(null);
      setSelectedProductIds(new Set());
      await loadData(activeBusiness.id);
    } catch {
      showToast("Batch action failed.");
    } finally {
      setSavingBatch(false);
    }
  };

  const handleBatchDelete = () => {
    if (!activeBusiness || selectedProductIds.size === 0) return;
    Alert.alert(
      "Delete Selected Items?",
      `Are you sure you want to delete ${selectedProductIds.size} item(s)? This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete All",
          style: "destructive",
          onPress: async () => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
            try {
              const ids = Array.from(selectedProductIds);
              await Promise.all(ids.map((id) => deleteProduct(activeBusiness.id, id)));
              setProducts((curr) => curr.filter((p) => !selectedProductIds.has(p.id)));
              setSelectedProductIds(new Set());
              showToast(`Deleted ${ids.length} item(s)`);
              await loadData(activeBusiness.id);
            } catch {
              showToast("Batch deletion failed.");
            }
          },
        },
      ],
    );
  };

  const handleSaveProductEdit = async () => {
    if (!activeBusiness || !editingProduct) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingEdit(true);
    try {
      const updated = await updateProduct(activeBusiness.id, editingProduct.id, {
        selling_price: editPrice.trim() || null,
        wholesale_price: editWholesale.trim() || null,
      });
      setProducts((curr) => curr.map((p) => (p.id === updated.id ? updated : p)));
      cacheProducts(
        activeBusiness.id,
        products.map((p) => (p.id === updated.id ? updated : p)),
      );
      setEditingProduct(null);
      showToast(`Updated ${updated.name}`);
    } catch {
      showToast("Could not update item prices.");
    } finally {
      setSavingEdit(false);
    }
  };

  const handleReceiveStock = async () => {
    if (!activeBusiness || !restockProduct || !restockQty.trim()) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingRestock(true);
    try {
      await receiveStock(activeBusiness.id, restockProduct.id, restockQty.trim());
      setRestockProduct(null);
      setRestockQty("");
      showToast(`Received +${restockQty} of ${restockProduct.name}`);
      void loadData(activeBusiness.id);
    } catch {
      showToast("Could not receive stock.");
    } finally {
      setSavingRestock(false);
    }
  };

  const handleOpenGallery = async (product: Product) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setGalleryProduct(product);
    setLoadingGallery(true);
    try {
      const imgs = await listProductImages(activeBusiness.id, product.id);
      setGalleryImages(imgs);
    } catch {
      setGalleryImages([]);
    } finally {
      setLoadingGallery(false);
    }
  };

  const handleMakePrimaryImage = async (imageId: string) => {
    if (!activeBusiness || !galleryProduct) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      await makeProductImagePrimary(activeBusiness.id, galleryProduct.id, imageId);
      setGalleryImages((curr) =>
        curr.map((img) => ({ ...img, is_primary: img.id === imageId }))
      );
      showToast("Primary product photo updated!");
    } catch {
      showToast("Could not set primary photo.");
    }
  };

  const handleRemoveImage = async (imageId: string) => {
    if (!activeBusiness || !galleryProduct) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    try {
      await removeProductImage(activeBusiness.id, galleryProduct.id, imageId);
      setGalleryImages((curr) => curr.filter((img) => img.id !== imageId));
      showToast("Photo removed from gallery.");
    } catch {
      showToast("Could not remove photo.");
    }
  };

  const handleRecordExpense = async () => {
    if (!activeBusiness || !expenseAmount.trim() || !expenseCategoryId) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingExpense(true);
    try {
      await recordExpense(activeBusiness.id, {
        amount: expenseAmount.trim(),
        category_id: expenseCategoryId,
        description: expenseDescription.trim() || null,
        payment_method: expensePaymentMethod,
      });
      setExpenseAmount("");
      setExpenseDescription("");
      setShowExpenseModal(false);
      showToast("Expense logged successfully!");
      void loadData(activeBusiness.id);
    } catch {
      showToast("Could not record expense.");
    } finally {
      setSavingExpense(false);
    }
  };

  const handleInviteStaff = async () => {
    if (!activeBusiness || !invitePhone.trim()) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingInvite(true);
    try {
      const inv = await inviteMember(activeBusiness.id, {
        phone: invitePhone.trim(),
        role: inviteRole,
      });
      setInvitations((curr) => [...curr, inv]);
      setShowInviteModal(false);
      setInvitePhone("");

      const cleanNum = formatWaNumber(inv.phone);
      const msg = `Hello, you have been invited to join ${activeBusiness.name} on AHIA as ${inviteRole}. Open https://ahia.app to accept.`;
      const waUrl = cleanNum
        ? `https://wa.me/${cleanNum}?text=${encodeURIComponent(msg)}`
        : `https://wa.me/?text=${encodeURIComponent(msg)}`;
      void Linking.openURL(waUrl);

      showToast("Invitation created & sent via WhatsApp!");
    } catch {
      showToast("Could not create invitation.");
    } finally {
      setSavingInvite(false);
    }
  };

  const handleUpdateStorefront = async () => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingStorefront(true);
    try {
      const updated = await updateStorefront(activeBusiness.id, {
        headline: storefrontHeadline.trim() || null,
        description: storefrontDesc.trim() || null,
        contact_phone: storefrontPhone.trim() || null,
        theme_color: storefrontThemeColor || null,
        theme_bg_color: storefrontThemeBg || null,
        closing_statement: storefrontClosing.trim() || null,
      });
      setStorefrontDetails(updated);
      setShowStorefrontModal(false);
      showToast("Storefront appearance updated!");
    } catch {
      showToast("Could not update storefront.");
    } finally {
      setSavingStorefront(false);
    }
  };

  const handleToggleStorefrontPublish = async () => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingStorefront(true);
    try {
      if (storefrontDetails?.is_published) {
        const res = await unpublishStorefront(activeBusiness.id);
        setStorefrontDetails(res);
        showToast("Storefront is now private (unpublished).");
      } else {
        const res = await publishStorefront(activeBusiness.id, {
          headline: storefrontHeadline.trim() || undefined,
          description: storefrontDesc.trim() || undefined,
          contact_phone: storefrontPhone.trim() || undefined,
        });
        setStorefrontDetails(res);
        showToast("Storefront is now live and published!");
      }
    } catch {
      showToast("Could not change publication status.");
    } finally {
      setSavingStorefront(false);
    }
  };

  const handleToggleMemberStatus = async (member: Member) => {
    if (!activeBusiness) return;
    const newStatus = member.status === "active" ? "suspended" : "active";
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      const updated = await changeMemberStatus(activeBusiness.id, member.id, newStatus);
      setMembers((curr) => curr.map((m) => (m.id === updated.id ? updated : m)));
      showToast(`Staff member ${newStatus === "active" ? "reactivated" : "suspended"}.`);
    } catch {
      showToast("Could not update staff status.");
    }
  };

  const handleChangeMemberRole = async (member: Member) => {
    if (!activeBusiness) return;
    const roles: MemberRole[] = ["SALES", "INVENTORY", "MANAGER", "OWNER"];
    const currentIndex = roles.indexOf(member.role);
    const nextRole = roles[(currentIndex + 1) % roles.length];
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      const updated = await changeMemberRole(activeBusiness.id, member.id, nextRole);
      setMembers((curr) => curr.map((m) => (m.id === updated.id ? updated : m)));
      showToast(`Role changed to ${nextRole}`);
    } catch {
      showToast("Could not change member role.");
    }
  };

  const handleAcceptMyInvitation = async (inv: PendingInvitation) => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    try {
      await acceptInvitation(inv.id);
      showToast(`Joined ${inv.tenant_name}! Reloading shops...`);
      const found = await listBusinesses();
      setBusinesses(found);
      if (found.length > 0) {
        setActiveBusiness(found[0]);
        await loadData(found[0].id);
      }
    } catch {
      showToast("Could not accept invitation.");
    }
  };

  const handleShareWaybillReceipt = async (item: CustomerList) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const cleanPhone = formatWaNumber(item.customer_phone);
    const dateStr = new Date(item.created_at).toLocaleDateString([], {
      month: "short",
      day: "numeric",
      year: "numeric",
    });

    let linesText = "";
    item.lines.forEach((l, idx) => {
      const name = l.product_name || l.free_text || "Item";
      const priceStr = l.shop_price ? formatMoney(l.shop_price) : "Pending";
      linesText += `${idx + 1}. ${l.quantity}x ${name} - ${priceStr}\n`;
    });

    const waybillInfo = item.waybill_number
      ? `\nWAYBILL DETAILS:\nTransporter: ${item.transporter_name || "Courier"}\nWaybill #: ${item.waybill_number}${item.dispatch_cost ? `\nDispatch Cost: ${formatMoney(item.dispatch_cost)}` : ""}${item.tracking_url ? `\nTracking URL: ${item.tracking_url}` : ""}\n`
      : "";

    const receipt = `==============================\nWAYBILL & INVOICE\n${activeBusiness.name.toUpperCase()}\nDate: ${dateStr}\nCustomer: ${item.customer_name || item.customer_phone || "Customer"}\nPhone: ${item.customer_phone || "N/A"}\n==============================\nITEMS:\n${linesText}==============================${waybillInfo}TOTAL: ${item.priced_total ? formatMoney(item.priced_total) : "Incomplete"}\n\nThank you for doing business with us!\n==============================`;

    const waUrl = cleanPhone
      ? `https://wa.me/${cleanPhone}?text=${encodeURIComponent(receipt)}`
      : `https://wa.me/?text=${encodeURIComponent(receipt)}`;

    const canOpen = await Linking.canOpenURL(waUrl);
    if (canOpen) {
      await Linking.openURL(waUrl);
    } else {
      await Share.share({ message: receipt });
    }
  };

  const handleUpdateBusiness = async () => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingBusiness(true);
    try {
      const updated = await updateBusiness(activeBusiness.id, {
        name: editBizName.trim() || undefined,
        address: editBizAddress.trim() || undefined,
        phone: editBizPhone.trim() || undefined,
      });
      setBusinessDetails(updated);
      setShowBusinessModal(false);
      showToast("Business profile updated!");
    } catch {
      showToast("Could not update business details.");
    } finally {
      setSavingBusiness(false);
    }
  };

  const handleChangePassword = async () => {
    if (!oldPassword.trim() || !newPassword.trim()) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingPassword(true);
    try {
      await changePassword(oldPassword, newPassword);
      setShowPasswordModal(false);
      setOldPassword("");
      setNewPassword("");
      showToast("Password updated successfully!");
    } catch {
      showToast("Could not change password. Check old password.");
    } finally {
      setSavingPassword(false);
    }
  };

  const handleRemoveMember = (member: Member) => {
    if (!activeBusiness) return;
    Alert.alert(
      "Remove Staff Member?",
      `Are you sure you want to remove ${member.first_name} from the business?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: async () => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            try {
              await removeMember(activeBusiness.id, member.id);
              setMembers((curr) => curr.filter((m) => m.id !== member.id));
              showToast(`Removed ${member.first_name}`);
            } catch {
              showToast("Could not remove staff member.");
            }
          },
        },
      ],
    );
  };

  const handleSaveLinePrice = async () => {
    if (!activeBusiness || !pricingLine) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSavingPrice(true);
    try {
      const updatedList = await workListLine(activeBusiness.id, pricingLine.listId, pricingLine.lineId, {
        shop_price: priceInput.trim() || null,
        cost_price: costInput.trim() || null,
      });
      setCustomerLists((curr) => curr.map((l) => (l.id === updatedList.id ? updatedList : l)));
      setPricingLine(null);
      setPriceInput("");
      setCostInput("");
      showToast("Line prices & cost updated!");
    } catch {
      showToast("Could not update price.");
    } finally {
      setSavingPrice(false);
    }
  };

  const CYCLE_LINE_STATES: Array<"somewhere" | "have_it" | "buy_it" | "cannot_get"> = [
    "somewhere",
    "have_it",
    "buy_it",
    "cannot_get",
  ];

  const handleCycleLineState = async (listId: string, lineId: string, currentState: string) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const curIdx = CYCLE_LINE_STATES.indexOf(currentState as any);
    const nextIdx = (curIdx + 1) % CYCLE_LINE_STATES.length;
    const nextState = CYCLE_LINE_STATES[nextIdx];
    try {
      const updatedList = await workListLine(activeBusiness.id, listId, lineId, { state: nextState });
      setCustomerLists((current) =>
        current.map((l) => (l.id === updatedList.id ? updatedList : l)),
      );
      const label =
        nextState === "have_it"
          ? "On the shelf"
          : nextState === "buy_it"
          ? "Buy in market"
          : nextState === "cannot_get"
          ? "Cannot get"
          : "Not checked";
      showToast(`Status: ${label}`);
    } catch {
      showToast("Could not update line status.");
    }
  };

  const handleDispatchWaybill = async () => {
    if (!activeBusiness || !dispatchModalList) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingDispatch(true);
    try {
      const updated = await dispatchCustomerList(activeBusiness.id, dispatchModalList.id, {
        transporter_name: transporterName.trim() || null,
        transporter_phone: transporterPhone.trim() || null,
        waybill_number: waybillNumber.trim() || null,
        dispatch_cost: dispatchCost.trim() || null,
        tracking_url: trackingUrl.trim() || null,
      });
      setCustomerLists((curr) => curr.map((l) => (l.id === updated.id ? updated : l)));
      setDispatchModalList(null);
      setTransporterName("");
      setTransporterPhone("");
      setWaybillNumber("");
      setDispatchCost("");
      setTrackingUrl("");
      showToast("Waybill recorded and dispatched!");
    } catch {
      showToast("Could not record waybill dispatch.");
    } finally {
      setSavingDispatch(false);
    }
  };

  const handleExecutePinConfirm = async () => {
    if (!activeBusiness || !pinConfirmList) return;
    if (pinValue.trim().length < 4) {
      showToast("Enter a 4-digit security PIN");
      return;
    }
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    try {
      const confirmed = await confirmCustomerList(activeBusiness.id, pinConfirmList.id);
      setCustomerLists((curr) => curr.map((l) => (l.id === confirmed.id ? confirmed : l)));
      setPinConfirmList(null);
      setPinValue("");
      showToast(`Order from ${confirmed.customer_name || confirmed.customer_phone} confirmed!`);
    } catch {
      showToast("Could not confirm order. Make sure all items have prices.");
    }
  };

  const handleQuickPasteSubmit = async () => {
    if (!activeBusiness) return;
    if (!quickPastePhone.trim()) {
      showToast("Customer phone number is required.");
      return;
    }
    const parsed = parseQuickPaste(quickPasteText);
    if (parsed.length === 0) {
      showToast("Paste at least one line item (e.g. 2x 2.5mm cable).");
      return;
    }

    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingQuickPaste(true);
    try {
      const lines = parsed.map((item) => {
        const matchedProd = products.find(
          (p) => p.name.toLowerCase() === item.text.toLowerCase()
        );
        return {
          product_slug: matchedProd ? matchedProd.slug : null,
          free_text: matchedProd ? null : item.text,
          quantity: item.quantity,
          unit: "piece",
        };
      });

      await submitCustomerList(activeBusiness.slug, {
        customer_phone: quickPastePhone.trim(),
        customer_name: quickPasteName.trim() || null,
        lines,
      });

      setShowQuickPasteModal(false);
      setQuickPastePhone("");
      setQuickPasteName("");
      setQuickPasteText("");
      showToast(`Order created with ${parsed.length} items!`);
      await loadData(activeBusiness.id);
    } catch {
      showToast("Could not submit order. Check connection.");
    } finally {
      setSavingQuickPaste(false);
    }
  };

  const handleRecordCustomSale = async () => {
    if (!activeBusiness || !saleProductId || !saleQuantity.trim()) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingSale(true);
    try {
      const prod = products.find((p) => p.id === saleProductId);
      const unitPrice = salePrice.trim() || prod?.effective_normal_price || prod?.selling_price || "0";
      await recordSale(activeBusiness.id, {
        lines: [
          {
            product_id: saleProductId,
            quantity: saleQuantity.trim(),
            unit_price: unitPrice,
          },
        ],
        payment_method: salePaymentMethod,
      });
      setShowRecordSaleModal(false);
      setSaleProductId(null);
      setSaleQuantity("1");
      setSalePrice("");
      showToast("Sale recorded successfully!");
      await loadData(activeBusiness.id);
    } catch {
      showToast("Could not record sale. Check connection.");
    } finally {
      setSavingSale(false);
    }
  };

  const handleCancelSale = (sale: SaleSummary) => {
    if (!activeBusiness) return;
    Alert.alert(
      "Cancel / Void Sale?",
      `Are you sure you want to cancel receipt ${sale.receipt_number} (${formatMoney(sale.total_amount)})? This will restore inventory.`,
      [
        { text: "No", style: "cancel" },
        {
          text: "Cancel Sale",
          style: "destructive",
          onPress: async () => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
            try {
              await cancelSale(activeBusiness.id, sale.id, "Customer return / void");
              showToast(`Sale ${sale.receipt_number} voided.`);
              await loadData(activeBusiness.id);
            } catch {
              showToast("Could not cancel sale.");
            }
          },
        },
      ],
    );
  };

  const handleShareQuoteOnWhatsApp = (list: CustomerList) => {
    const rawNumber = list.customer_phone;
    const cleanNumber = formatWaNumber(rawNumber);
    const shopName = activeBusiness?.name ?? "Our Shop";

    const sections = groupCustomerListLines(list.lines);
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

    void Linking.openURL(waUrl);
  };

  const handleShareStorefront = () => {
    if (!activeBusiness) return;
    const storefrontUrl = `https://ahia.app/shop/${activeBusiness.slug}`;
    const msg = `Hello! Check out our catalog on AHIA: ${storefrontUrl}`;
    const waUrl = `https://wa.me/?text=${encodeURIComponent(msg)}`;
    void Linking.openURL(waUrl);
  };

  const handleDeleteList = (list: CustomerList) => {
    if (!activeBusiness) return;
    Alert.alert(
      "Delete Customer List?",
      `Are you sure you want to delete the list from ${list.customer_name ?? list.customer_phone}? This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            try {
              await deleteCustomerList(activeBusiness.id, list.id);
              setCustomerLists((current) => current.filter((l) => l.id !== list.id));
              showToast("Customer list deleted");
            } catch {
              showToast("Could not delete list");
            }
          },
        },
      ],
    );
  };

  const pendingListsCount = customerLists.filter((l) => l.status !== "confirmed").length;

  return (
    <SafeAreaView style={styles.safeArea}>
      {/* Top Header */}
      <View style={styles.header}>
        <Pressable
          style={styles.businessSelector}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setShowShopModal(true);
          }}
        >
          <View style={styles.businessBadge}>
            <Text style={styles.businessBadgeText}>
              {activeBusiness?.name ? activeBusiness.name.slice(0, 2).toUpperCase() : "AH"}
            </Text>
          </View>
          <View>
            <Text style={styles.businessName} numberOfLines={1}>
              {activeBusiness?.name ?? "AHIA Shop"}
            </Text>
            <Text style={styles.businessSub}>Switch Stall or Business</Text>
          </View>
        </Pressable>

        <Pressable
          style={[styles.syncButton, pendingSyncCount > 0 && styles.syncButtonPending]}
          onPress={handleSyncOutbox}
          disabled={isSyncing}
        >
          {isSyncing ? (
            <ActivityIndicator size="small" color="#084a2f" />
          ) : (
            <View style={styles.syncInner}>
              <SyncIcon size={14} color="#084a2f" />
              <Text style={styles.syncButtonText}>
                {pendingSyncCount > 0 ? `${pendingSyncCount} Sync` : "Online"}
              </Text>
            </View>
          )}
        </Pressable>
      </View>

      {/* Toast Notice */}
      {notice && (
        <View style={styles.toast}>
          <Text style={styles.toastText}>{notice}</Text>
        </View>
      )}

      {/* Main Content Area */}
      <View style={styles.mainContainer}>
        {activeTab === "dashboard" && (
          <ScrollView
            style={styles.scrollContent}
            refreshControl={
              <RefreshControl
                refreshing={refreshing}
                onRefresh={() => {
                  if (activeBusiness) {
                    setRefreshing(true);
                    void loadData(activeBusiness.id);
                  }
                }}
              />
            }
          >
            {/* KPI Cards */}
            <View style={styles.kpiRow}>
              <View style={[styles.kpiCard, styles.kpiCardHighlight]}>
                <Text style={styles.kpiLabel}>Today's Sales</Text>
                <Text style={styles.kpiValue}>
                  {formatMoney(dailyStats?.total_revenue ?? "0")}
                </Text>
                <Text style={styles.kpiMeta}>{dailyStats?.total_sales ?? 0} transaction(s)</Text>
              </View>

              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Pending Orders</Text>
                <Text style={styles.kpiValue}>{pendingListsCount}</Text>
                <Text style={styles.kpiMeta}>Customer Lists</Text>
              </View>
            </View>

            {/* Quick Actions Grid with Native SVG Icons */}
            <Text style={styles.sectionHeading}>Quick Actions</Text>
            <View style={styles.actionGrid}>
              <Pressable
                style={styles.actionTile}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setShowAddProductModal(true);
                }}
              >
                <View style={[styles.actionIconWrap, { backgroundColor: "#064e3b" }]}>
                  <PlusIcon size={20} color="#4ade80" />
                </View>
                <Text style={styles.actionTileTitle}>Add Product</Text>
                <Text style={styles.actionTileDesc}>New catalog item</Text>
              </Pressable>

              <Pressable
                style={styles.actionTile}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setShowExpenseModal(true);
                }}
              >
                <View style={[styles.actionIconWrap, { backgroundColor: "#78350f" }]}>
                  <ReceiptIcon size={20} color="#f59e0b" />
                </View>
                <Text style={styles.actionTileTitle}>Log Expense</Text>
                <Text style={styles.actionTileDesc}>Record market cost</Text>
              </Pressable>

              <Pressable
                style={styles.actionTile}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setShowAddCategoryModal(true);
                }}
              >
                <View style={[styles.actionIconWrap, { backgroundColor: "#1e3a8a" }]}>
                  <FolderIcon size={20} color="#60a5fa" />
                </View>
                <Text style={styles.actionTileTitle}>New Folder</Text>
                <Text style={styles.actionTileDesc}>Organize shelf</Text>
              </Pressable>

              <Pressable style={styles.actionTile} onPress={handleShareStorefront}>
                <View style={[styles.actionIconWrap, { backgroundColor: "#065f46" }]}>
                  <ShareIcon size={20} color="#34d399" />
                </View>
                <Text style={styles.actionTileTitle}>Share Shop</Text>
                <Text style={styles.actionTileDesc}>WhatsApp Catalog</Text>
              </Pressable>
            </View>

            {/* Recent Sales Overview */}
            <View style={styles.sectionHeaderRow}>
              <Text style={styles.sectionHeading}>Recent Sales</Text>
              <Pressable onPress={() => setActiveTab("trading")}>
                <Text style={styles.seeAllLink}>See All</Text>
              </Pressable>
            </View>

            {sales.length === 0 ? (
              <View style={styles.emptyBox}>
                <Text style={styles.emptyTitle}>No sales recorded yet</Text>
                <Text style={styles.emptySubtitle}>Tap Sell 1 on any shelf item to start.</Text>
              </View>
            ) : (
              sales.slice(0, 5).map((sale) => (
                <View key={sale.id} style={styles.saleRow}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                    <ReceiptIcon size={18} color="#4ade80" />
                    <View>
                      <Text style={styles.saleReceipt}>{sale.receipt_number}</Text>
                      <Text style={styles.saleDate}>{sale.payment_method.toUpperCase()}</Text>
                    </View>
                  </View>
                  <Text style={styles.saleAmount}>{formatMoney(sale.total_amount)}</Text>
                </View>
              ))
            )}
          </ScrollView>
        )}

        {/* Samsung File Manager-Style Shelf Catalog */}
        {activeTab === "shelf" && (
          <View style={styles.tabContainer}>
            {/* Top Search & Actions */}
            <View style={styles.shelfTopBar}>
              <View style={styles.searchBoxWrap}>
                <SearchIcon size={18} color="#8a928e" />
                <TextInput
                  style={styles.searchInputClean}
                  placeholder="Search products & folders..."
                  placeholderTextColor="#8a928e"
                  value={searchQuery}
                  onChangeText={setSearchQuery}
                />
                {searchQuery.length > 0 && (
                  <Pressable onPress={() => setSearchQuery("")}>
                    <CloseIcon size={16} color="#8a928e" />
                  </Pressable>
                )}
              </View>

              <Pressable
                style={[styles.modeToggleBtn, viewMode === "tree" && styles.modeToggleBtnActive]}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setViewMode(viewMode === "folder" ? "tree" : "folder");
                }}
              >
                {viewMode === "folder" ? (
                  <TreeIcon size={18} color="#f0f6fc" />
                ) : (
                  <FolderIcon size={18} color="#4ade80" />
                )}
              </Pressable>
            </View>

            {/* Breadcrumb Trail Bar */}
            <View style={styles.breadcrumbBar}>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.breadcrumbScroll}>
                <Pressable
                  style={styles.breadcrumbItem}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setCurrentCategoryId(null);
                  }}
                >
                  <Text style={[styles.breadcrumbText, currentCategoryId === null && styles.breadcrumbActive]}>
                    Catalog Root
                  </Text>
                </Pressable>

                {breadcrumbs.map((crumb, idx) => (
                  <View key={crumb.id} style={{ flexDirection: "row", alignItems: "center" }}>
                    <ChevronRightIcon size={14} color="#6e7681" />
                    <Pressable
                      style={styles.breadcrumbItem}
                      onPress={() => {
                        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                        setCurrentCategoryId(crumb.id);
                      }}
                    >
                      <Text
                        style={[
                          styles.breadcrumbText,
                          idx === breadcrumbs.length - 1 && styles.breadcrumbActive,
                        ]}
                      >
                        {crumb.name}
                      </Text>
                    </Pressable>
                  </View>
                ))}
              </ScrollView>

              {/* Up one level */}
              {currentCategoryId !== null && (
                <Pressable
                  style={styles.upLevelBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setCurrentCategoryId(currentCategory?.parent_id ?? null);
                  }}
                >
                  <ArrowLeftIcon size={16} color="#4ade80" />
                  <Text style={styles.upLevelText}>Up</Text>
                </Pressable>
              )}
            </View>

            {/* Folder Header Actions */}
            <View style={styles.folderActionBar}>
              <Pressable
                style={styles.folderActionBtn}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setShowAddCategoryModal(true);
                }}
              >
                <PlusIcon size={14} color="#60a5fa" />
                <Text style={[styles.folderActionText, { color: "#60a5fa" }]}>New Folder</Text>
              </Pressable>

              <Pressable
                style={styles.folderActionBtn}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setShowAddProductModal(true);
                }}
              >
                <PlusIcon size={14} color="#4ade80" />
                <Text style={[styles.folderActionText, { color: "#4ade80" }]}>Add Item</Text>
              </Pressable>

              {currentCategory && (
                <>
                  <Pressable
                    style={styles.folderActionBtn}
                    onPress={() => {
                      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      setEditingCategory(currentCategory);
                      setEditCategoryName(currentCategory.name);
                      setEditCategoryNormalPrice(currentCategory.default_normal_price ?? "");
                      setEditCategoryWholesalePrice(currentCategory.default_wholesale_price ?? "");
                    }}
                  >
                    <EditIcon size={14} color="#f59e0b" />
                    <Text style={[styles.folderActionText, { color: "#f59e0b" }]}>Edit</Text>
                  </Pressable>

                  <Pressable
                    style={styles.folderActionBtn}
                    onPress={() => handleDeleteCategory(currentCategory)}
                  >
                    <TrashIcon size={14} color="#f87171" />
                    <Text style={[styles.folderActionText, { color: "#f87171" }]}>Delete</Text>
                  </Pressable>
                </>
              )}
            </View>

            {/* View Mode: Tree View */}
            {viewMode === "tree" ? (
              <ScrollView style={styles.treeScroll}>
                <Text style={styles.treeHeading}>Catalog Hierarchy Tree</Text>
                {categories.length === 0 ? (
                  <View style={styles.emptyBox}>
                    <Text style={styles.emptyTitle}>No categories created</Text>
                    <Text style={styles.emptySubtitle}>Tap New Folder to create one.</Text>
                  </View>
                ) : (
                  categories
                    .filter((c) => c.parent_id === null)
                    .map((rootCat) => {
                      const childCats = categories.filter((c) => c.parent_id === rootCat.id);
                      const rootProds = products.filter((p) => p.category_id === rootCat.id);
                      return (
                        <View key={rootCat.id} style={styles.treeRootNode}>
                          <Pressable
                            style={styles.treeNodeHeader}
                            onPress={() => {
                              void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                              setCurrentCategoryId(rootCat.id);
                              setViewMode("folder");
                            }}
                          >
                            <FolderIcon size={18} color="#60a5fa" />
                            <Text style={styles.treeNodeName}>{rootCat.name}</Text>
                            <Text style={styles.treeNodeMeta}>
                              ({childCats.length} folders, {rootProds.length} items)
                            </Text>
                          </Pressable>

                          {childCats.map((child) => {
                            const childProds = products.filter((p) => p.category_id === child.id);
                            return (
                              <Pressable
                                key={child.id}
                                style={styles.treeChildNode}
                                onPress={() => {
                                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                  setCurrentCategoryId(child.id);
                                  setViewMode("folder");
                                }}
                              >
                                <Text style={styles.treeElbow}>|-- </Text>
                                <FolderOpenIcon size={16} color="#93c5fd" />
                                <Text style={styles.treeChildName}>{child.name}</Text>
                                <Text style={styles.treeNodeMeta}>({childProds.length} items)</Text>
                              </Pressable>
                            );
                          })}
                        </View>
                      );
                    })
                )}
              </ScrollView>
            ) : (
              /* Folder View */
              <ScrollView style={styles.scrollContent}>
                {/* Subcategories Folders Section */}
                {currentSubcategories.length > 0 && (
                  <View style={styles.foldersSection}>
                    <Text style={styles.subHeading}>Folders ({currentSubcategories.length})</Text>
                    <View style={styles.foldersGrid}>
                      {currentSubcategories.map((cat) => {
                        const childCount = categories.filter((c) => c.parent_id === cat.id).length;
                        const prodCount = products.filter((p) => p.category_id === cat.id).length;
                        return (
                          <Pressable
                            key={cat.id}
                            style={styles.folderCard}
                            onPress={() => {
                              void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                              setCurrentCategoryId(cat.id);
                            }}
                          >
                            <View style={styles.folderIconRow}>
                              <FolderIcon size={24} color="#60a5fa" />
                              <ChevronRightIcon size={16} color="#6e7681" />
                            </View>
                            <Text style={styles.folderName} numberOfLines={1}>{cat.name}</Text>
                            <Text style={styles.folderMeta}>
                              {childCount > 0 ? `${childCount} subfolders, ` : ""}{prodCount} item(s)
                            </Text>
                            {cat.default_normal_price && (
                              <Text style={styles.folderPrice}>
                                Def: {formatMoney(cat.default_normal_price)}
                              </Text>
                            )}
                          </Pressable>
                        );
                      })}
                    </View>
                  </View>
                )}

                {/* Items in Current Folder Section */}
                <View style={styles.itemsSection}>
                  <View style={styles.sectionHeaderRow}>
                    <Text style={styles.subHeading}>
                      Items in {currentCategory?.name ?? "Root"} ({currentProducts.length})
                    </Text>
                    {currentProducts.length > 0 && (
                      <Pressable
                        onPress={() => {
                          void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                          if (selectedProductIds.size === currentProducts.length) {
                            setSelectedProductIds(new Set());
                          } else {
                            setSelectedProductIds(new Set(currentProducts.map((p) => p.id)));
                          }
                        }}
                      >
                        <Text style={styles.selectAllLink}>
                          {selectedProductIds.size === currentProducts.length ? "Deselect All" : "Select All"}
                        </Text>
                      </Pressable>
                    )}
                  </View>

                  {currentProducts.length === 0 ? (
                    <View style={styles.emptyBox}>
                      <ItemBoxIcon size={32} color="#6e7681" />
                      <Text style={styles.emptyTitle}>No items in this folder</Text>
                      <Text style={styles.emptySubtitle}>Tap Add Item above to place items here.</Text>
                    </View>
                  ) : (
                    currentProducts.map((item) => {
                      const isSelected = selectedProductIds.has(item.id);
                      return (
                        <View key={item.id} style={[styles.productCard, isSelected && styles.productCardSelected]}>
                          <View style={styles.productCardTop}>
                            <Pressable
                              style={styles.checkboxTouch}
                              onPress={() => handleToggleSelectProduct(item.id)}
                            >
                              <View style={[styles.checkbox, isSelected && styles.checkboxActive]}>
                                {isSelected && <CheckMarkIcon size={12} color="#ffffff" />}
                              </View>
                            </Pressable>

                            <View style={styles.productInfo}>
                              <Text style={styles.productName}>{item.name}</Text>
                              <View style={styles.priceRow}>
                                <Text style={styles.normalPrice}>
                                  {formatMoney(item.effective_normal_price ?? item.selling_price)}
                                </Text>
                                {item.effective_wholesale_price && (
                                  <Text style={styles.wholesalePrice}>
                                    Wholesale: {formatMoney(item.effective_wholesale_price)}
                                  </Text>
                                )}
                              </View>
                            </View>
                          </View>

                          <View style={styles.productActions}>
                            <Pressable style={styles.sellOneBtn} onPress={() => handleSellOne(item)}>
                              <Text style={styles.sellOneBtnText}>Sell 1</Text>
                            </Pressable>

                            <Pressable
                              style={styles.stockBtn}
                              onPress={() => {
                                void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                setRestockProduct(item);
                              }}
                            >
                              <Text style={styles.stockBtnText}>Restock</Text>
                            </Pressable>

                            <Pressable
                              style={styles.photoBtn}
                              onPress={() => handleOpenGallery(item)}
                            >
                              <ImageIcon size={14} color="#60a5fa" />
                            </Pressable>

                            <Pressable
                              style={styles.editBtn}
                              onPress={() => {
                                void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                setEditingProduct(item);
                                setEditPrice(item.selling_price ?? "");
                                setEditWholesale(item.effective_wholesale_price ?? "");
                              }}
                            >
                              <EditIcon size={14} color="#8b949e" />
                            </Pressable>

                            <Pressable
                              style={styles.deleteBtn}
                              onPress={() => handleDeleteProduct(item)}
                            >
                              <TrashIcon size={14} color="#f87171" />
                            </Pressable>
                          </View>
                        </View>
                      );
                    })
                  )}
                </View>
              </ScrollView>
            )}

            {/* Sticky Multi-Select Batch Action Bar */}
            {selectedProductIds.size > 0 && (
              <View style={styles.batchActionBar}>
                <Text style={styles.batchCountText}>{selectedProductIds.size} selected</Text>
                <View style={styles.batchBtnRow}>
                  <Pressable
                    style={styles.batchBtn}
                    onPress={() =>
                      setBatchModal({ mode: "copy", productIds: Array.from(selectedProductIds) })
                    }
                  >
                    <CopyIcon size={14} color="#ffffff" />
                    <Text style={styles.batchBtnText}>Copy</Text>
                  </Pressable>

                  <Pressable
                    style={styles.batchBtn}
                    onPress={() =>
                      setBatchModal({ mode: "move", productIds: Array.from(selectedProductIds) })
                    }
                  >
                    <ChevronRightIcon size={14} color="#ffffff" />
                    <Text style={styles.batchBtnText}>Move</Text>
                  </Pressable>

                  <Pressable
                    style={[styles.batchBtn, styles.batchDeleteBtn]}
                    onPress={handleBatchDelete}
                  >
                    <TrashIcon size={14} color="#ffffff" />
                    <Text style={styles.batchBtnText}>Delete</Text>
                  </Pressable>
                </View>
              </View>
            )}
          </View>
        )}

        {/* Customer Lists / Waybills */}
        {activeTab === "lists" && (
          <FlatList
            data={customerLists}
            keyExtractor={(item) => item.id}
            contentContainerStyle={styles.listPadding}
            ListHeaderComponent={
              <View style={styles.listsHeaderWrap}>
                <View>
                  <Text style={styles.listsHeaderTitle}>Orders & Waybills</Text>
                  <Text style={styles.listsHeaderSubtitle}>
                    {customerLists.length} customer order{customerLists.length === 1 ? "" : "s"}
                  </Text>
                </View>
                <Pressable
                  style={styles.quickPasteBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setShowQuickPasteModal(true);
                  }}
                >
                  <PlusIcon size={12} color="#ffffff" />
                  <Text style={styles.quickPasteBtnText}>Quick-Paste</Text>
                </Pressable>
              </View>
            }
            ListEmptyComponent={
              <View style={styles.emptyBox}>
                <ListIcon size={32} color="#6e7681" />
                <Text style={styles.emptyTitle}>No customer orders yet</Text>
                <Text style={styles.emptySubtitle}>
                  Tap "Quick-Paste" above to paste a rough WhatsApp order note and generate an itemized quote.
                </Text>
              </View>
            }
            renderItem={({ item }) => {
              const sections = groupCustomerListLines(item.lines);
              const isConfirmed = item.status === "confirmed";
              return (
                <View style={styles.listCard}>
                  <View style={styles.listCardHeader}>
                    <View>
                      <Text style={styles.listCustomerName}>
                        {item.customer_name || item.customer_phone}
                      </Text>
                      <Text style={styles.listDate}>{item.lines.length} items requested</Text>
                    </View>
                    <View
                      style={[
                        styles.statusBadge,
                        isConfirmed ? styles.statusConfirmed : styles.statusPending,
                      ]}
                    >
                      <Text style={styles.statusBadgeText}>{item.status.toUpperCase()}</Text>
                    </View>
                  </View>

                  {/* Hierarchical Groupings */}
                  {sections.map((sec, idx) => (
                    <View key={idx} style={styles.sectionBox}>
                      <Text style={styles.sectionRootTitle}>{sec.root}</Text>
                      {sec.subs.map((sub, sIdx) => (
                        <View key={sIdx} style={styles.subSectionBox}>
                          {sub.sub && <Text style={styles.subTitle}>&gt; {sub.sub}</Text>}
                          {sub.lines.map((line) => {
                            const costNum = Number(line.cost_price ?? "0");
                            const shopNum = Number(line.shop_price ?? "0");
                            const hasBoth = Boolean(line.cost_price && line.shop_price && Number.isFinite(costNum) && Number.isFinite(shopNum));
                            const marginVal = shopNum - costNum;
                            const isPositive = marginVal >= 0;

                            return (
                              <View key={line.id} style={styles.lineItem}>
                                <View style={styles.lineMain}>
                                  <View style={styles.lineTitleRow}>
                                    <Text style={styles.lineName}>
                                      {line.quantity}x {line.product_name ?? line.free_text}
                                    </Text>
                                    <View
                                      style={[
                                        styles.lineStateBadge,
                                        line.state === "have_it" && styles.lineStateHaveIt,
                                        line.state === "buy_it" && styles.lineStateBuyIt,
                                        line.state === "cannot_get" && styles.lineStateCannotGet,
                                        line.state === "somewhere" && styles.lineStateSomewhere,
                                      ]}
                                    >
                                      <Text style={styles.lineStateBadgeText}>
                                        {line.state === "have_it"
                                          ? "On Shelf"
                                          : line.state === "buy_it"
                                          ? "In Market"
                                          : line.state === "cannot_get"
                                          ? "Cannot Get"
                                          : "Unchecked"}
                                      </Text>
                                    </View>
                                  </View>

                                  <View style={styles.linePriceDetailRow}>
                                    <Text style={styles.linePrice}>
                                      Charge: {line.shop_price ? formatMoney(line.shop_price) : "Set Price"}
                                    </Text>
                                    {line.cost_price && (
                                      <Text style={styles.lineCost}>
                                        Cost: {formatMoney(line.cost_price)}
                                      </Text>
                                    )}
                                    {hasBoth && (
                                      <Text
                                        style={[
                                          styles.lineMargin,
                                          isPositive ? styles.marginPositive : styles.marginNegative,
                                        ]}
                                      >
                                        Margin: {isPositive ? "+" : ""}{formatMoney(marginVal.toString())}
                                      </Text>
                                    )}
                                  </View>
                                </View>

                                <View style={styles.lineActions}>
                                  <Pressable
                                    style={[
                                      styles.lineStatusCycleBtn,
                                      line.state === "have_it" && styles.lineStatusBtnHaveIt,
                                      line.state === "buy_it" && styles.lineStatusBtnBuyIt,
                                      line.state === "cannot_get" && styles.lineStatusBtnUnavailable,
                                      line.state === "somewhere" && styles.lineStatusBtnSomewhere,
                                    ]}
                                    onPress={() =>
                                      handleCycleLineState(item.id, line.id, line.state)
                                    }
                                  >
                                    {line.state === "have_it" ? (
                                      <CheckMarkIcon size={14} color="#86efac" />
                                    ) : line.state === "buy_it" ? (
                                      <CartIcon size={14} color="#fde047" />
                                    ) : line.state === "cannot_get" ? (
                                      <CannotGetIcon size={14} color="#fca5a5" />
                                    ) : (
                                      <ClockIcon size={14} color="#94a3b8" />
                                    )}
                                  </Pressable>

                                  <Pressable
                                    style={styles.linePriceBtn}
                                    onPress={() => {
                                      setPricingLine({
                                        listId: item.id,
                                        lineId: line.id,
                                        itemName: line.product_name ?? line.free_text ?? "Item",
                                        currentShopPrice: line.shop_price ?? "",
                                        currentCostPrice: line.cost_price ?? "",
                                      });
                                      setPriceInput(line.shop_price ?? "");
                                      setCostInput(line.cost_price ?? "");
                                    }}
                                  >
                                    <EditIcon size={14} color="#8a928e" />
                                  </Pressable>
                                </View>
                              </View>
                            );
                          })}
                        </View>
                      ))}
                    </View>
                  ))}

                  {/* Waybill Tracking Banner */}
                  {item.waybill_number && (
                    <View style={styles.waybillBanner}>
                      <TruckIcon size={16} color="#4ade80" />
                      <Text style={styles.waybillBannerText}>
                        Dispatched: #{item.waybill_number} via {item.transporter_name ?? "Courier"}
                        {item.dispatch_cost ? ` (Cost: ${formatMoney(item.dispatch_cost)})` : ""}
                      </Text>
                    </View>
                  )}

                  {/* List Total & Actions */}
                  <View style={styles.listFooter}>
                    <View>
                      <Text style={styles.totalLabel}>Total Quoted</Text>
                      <Text style={styles.totalAmount}>
                        {item.priced_total ? formatMoney(item.priced_total) : "Incomplete"}
                      </Text>
                    </View>

                    <View style={styles.footerActions}>
                      <Pressable
                        style={styles.waBtn}
                        onPress={() => handleShareQuoteOnWhatsApp(item)}
                      >
                        <ShareIcon size={14} color="#ffffff" />
                        <Text style={styles.waBtnText}>WhatsApp</Text>
                      </Pressable>

                      <Pressable
                        style={styles.invoiceBtn}
                        onPress={() => handleShareWaybillReceipt(item)}
                      >
                        <ReceiptIcon size={14} color="#ffffff" />
                        <Text style={styles.invoiceBtnText}>Invoice</Text>
                      </Pressable>

                      {isConfirmed && !item.waybill_number && (
                        <Pressable
                          style={styles.dispatchBtn}
                          onPress={() => {
                            setDispatchModalList(item);
                            setTransporterName(item.transporter_name ?? "");
                            setTransporterPhone(item.transporter_phone ?? "");
                            setWaybillNumber(item.waybill_number ?? "");
                            setDispatchCost(item.dispatch_cost ?? "");
                            setTrackingUrl(item.tracking_url ?? "");
                          }}
                        >
                          <TruckIcon size={14} color="#ffffff" />
                          <Text style={styles.dispatchBtnText}>Waybill</Text>
                        </Pressable>
                      )}

                      {!isConfirmed && (
                        <Pressable
                          style={styles.confirmBtn}
                          onPress={() => {
                            setPinConfirmList(item);
                            setPinValue("");
                          }}
                        >
                          <CheckMarkIcon size={14} color="#ffffff" />
                          <Text style={styles.confirmBtnText}>Confirm</Text>
                        </Pressable>
                      )}

                      <Pressable
                        style={styles.deleteListBtn}
                        onPress={() => handleDeleteList(item)}
                      >
                        <TrashIcon size={14} color="#f87171" />
                      </Pressable>
                    </View>
                  </View>
                </View>
              );
            }}
          />
        )}

        {/* Trading Ledger & Sales Feed */}
        {activeTab === "trading" && (
          <ScrollView style={styles.scrollContent}>
            {/* Today's Gross Trading Banner */}
            <View style={styles.tradingSummaryCard}>
              <Text style={styles.tradingSummaryLabel}>Today's Gross Sales</Text>
              <Text style={styles.tradingSummaryAmount}>
                {formatMoney(dailyStats?.total_revenue ?? "0")}
              </Text>
              <Text style={styles.tradingSummaryMeta}>
                {dailyStats?.total_sales ?? 0} transaction(s) recorded today
              </Text>
            </View>

            {/* Sub-tab Pills & Header Actions */}
            <View style={styles.tradingSubTabRow}>
              <View style={styles.tradingPillsWrap}>
                <Pressable
                  style={[
                    styles.tradingPill,
                    tradingSubTab === "sales" && styles.tradingPillActive,
                  ]}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setTradingSubTab("sales");
                  }}
                >
                  <Text
                    style={[
                      styles.tradingPillText,
                      tradingSubTab === "sales" && styles.tradingPillTextActive,
                    ]}
                  >
                    Sales ({sales.length})
                  </Text>
                </Pressable>

                <Pressable
                  style={[
                    styles.tradingPill,
                    tradingSubTab === "expenses" && styles.tradingPillActive,
                  ]}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setTradingSubTab("expenses");
                  }}
                >
                  <Text
                    style={[
                      styles.tradingPillText,
                      tradingSubTab === "expenses" && styles.tradingPillTextActive,
                    ]}
                  >
                    Expenses
                  </Text>
                </Pressable>
              </View>

              <View style={{ flexDirection: "row", gap: 6 }}>
                <Pressable
                  style={styles.recordSaleBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setShowRecordSaleModal(true);
                  }}
                >
                  <PlusIcon size={12} color="#ffffff" />
                  <Text style={styles.recordSaleBtnText}>Sale</Text>
                </Pressable>

                <Pressable
                  style={styles.logExpenseBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setShowExpenseModal(true);
                  }}
                >
                  <PlusIcon size={12} color="#ffffff" />
                  <Text style={styles.logExpenseBtnText}>Expense</Text>
                </Pressable>
              </View>
            </View>

            {/* Sales Sub-tab */}
            {tradingSubTab === "sales" ? (
              <View>
                {sales.length === 0 ? (
                  <View style={styles.emptyBox}>
                    <ReceiptIcon size={32} color="#6e7681" />
                    <Text style={styles.emptyTitle}>No sales recorded yet</Text>
                    <Text style={styles.emptySubtitle}>
                      Tap "+ Sale" above or "Sell 1" on any catalog item to record your first transaction.
                    </Text>
                  </View>
                ) : (
                  sales.map((s) => {
                    const isCancelled = Boolean(s.cancelled_at);
                    return (
                      <View key={s.id} style={styles.saleRow}>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flex: 1 }}>
                          <ReceiptIcon
                            size={20}
                            color={isCancelled ? "#f87171" : "#4ade80"}
                          />
                          <View style={{ flex: 1 }}>
                            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                              <Text style={styles.saleReceipt}>{s.receipt_number}</Text>
                              <View
                                style={[
                                  styles.saleStatusPill,
                                  isCancelled ? styles.salePillCancelled : styles.salePillSuccess,
                                ]}
                              >
                                <Text style={styles.saleStatusText}>
                                  {isCancelled ? "VOID" : s.payment_status.toUpperCase()}
                                </Text>
                              </View>
                            </View>
                            <Text style={styles.saleDate}>
                              {new Date(s.created_at).toLocaleString([], {
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              })}{" "}
                              via {s.payment_method.toUpperCase()}
                            </Text>
                          </View>
                        </View>

                        <View style={{ alignItems: "flex-end", gap: 4 }}>
                          <Text
                            style={[
                              styles.saleAmount,
                              isCancelled && styles.saleAmountCancelled,
                            ]}
                          >
                            {formatMoney(s.total_amount)}
                          </Text>
                          {!isCancelled && (
                            <Pressable
                              style={styles.voidBtn}
                              onPress={() => handleCancelSale(s)}
                            >
                              <Text style={styles.voidBtnText}>Void</Text>
                            </Pressable>
                          )}
                        </View>
                      </View>
                    );
                  })
                )}
              </View>
            ) : (
              /* Expenses Sub-tab */
              <View>
                <Text style={styles.subHeading}>Market Expenses Categories</Text>
                <View style={styles.actionGrid}>
                  {expenseCategories.map((c) => (
                    <View key={c.id} style={styles.actionTile}>
                      <Text style={styles.actionTileTitle}>{c.name}</Text>
                      <Text style={styles.actionTileDesc}>{c.description || "General stall expense"}</Text>
                    </View>
                  ))}
                </View>
              </View>
            )}
          </ScrollView>
        )}

        {/* The Everything / More Tab */}
        {activeTab === "more" && (
          <ScrollView style={styles.scrollContent}>
            {/* User Profile Header */}
            <View style={styles.userProfileCard}>
              <View style={styles.userAvatar}>
                <Text style={styles.userAvatarText}>
                  {profile?.first_name ? profile.first_name.slice(0, 1).toUpperCase() : "U"}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.userProfileName}>
                  {profile?.first_name} {profile?.last_name ?? ""}
                </Text>
                <Text style={styles.userProfilePhone}>{profile?.phone ?? "No phone set"}</Text>
                <View style={styles.roleBadgeWrap}>
                  <Text style={styles.roleBadgeText}>
                    {activeBusiness?.name} - {businessDetails?.phone ? "Online Stall" : "Active Shop"}
                  </Text>
                </View>
              </View>
            </View>

            {/* Everything in AHIA Grid */}
            <Text style={styles.sectionHeading}>Everything in AHIA</Text>
            <View style={styles.everythingGrid}>
              <Pressable style={styles.everythingTile} onPress={() => setActiveTab("dashboard")}>
                <ShopIcon size={24} color="#4ade80" />
                <Text style={styles.everythingTileTitle}>The Shop</Text>
                <Text style={styles.everythingTileDesc}>Daily counter</Text>
              </Pressable>

              <Pressable style={styles.everythingTile} onPress={() => setActiveTab("shelf")}>
                <BoxIcon size={24} color="#60a5fa" />
                <Text style={styles.everythingTileTitle}>Catalog</Text>
                <Text style={styles.everythingTileDesc}>Folders & Items</Text>
              </Pressable>

              <Pressable style={styles.everythingTile} onPress={() => setActiveTab("lists")}>
                <ListIcon size={24} color="#f59e0b" />
                <Text style={styles.everythingTileTitle}>Waybills</Text>
                <Text style={styles.everythingTileDesc}>Customer lists</Text>
              </Pressable>

              <Pressable style={styles.everythingTile} onPress={() => setActiveTab("trading")}>
                <ReceiptIcon size={24} color="#a78bfa" />
                <Text style={styles.everythingTileTitle}>Trading</Text>
                <Text style={styles.everythingTileDesc}>Daily ledger</Text>
              </Pressable>

              <Pressable style={styles.everythingTile} onPress={() => setShowStorefrontModal(true)}>
                <ShareIcon size={24} color="#34d399" />
                <Text style={styles.everythingTileTitle}>Storefront</Text>
                <Text style={styles.everythingTileDesc}>WhatsApp link</Text>
              </Pressable>

              <Pressable style={styles.everythingTile} onPress={() => setShowInviteModal(true)}>
                <PeopleIcon size={24} color="#38bdf8" />
                <Text style={styles.everythingTileTitle}>Team</Text>
                <Text style={styles.everythingTileDesc}>Staff invites</Text>
              </Pressable>

              <Pressable style={styles.everythingTile} onPress={() => setShowBusinessModal(true)}>
                <TagIcon size={24} color="#fbbf24" />
                <Text style={styles.everythingTileTitle}>Stall Profile</Text>
                <Text style={styles.everythingTileDesc}>Address & name</Text>
              </Pressable>

              <Pressable style={styles.everythingTile} onPress={() => setShowPasswordModal(true)}>
                <PersonIcon size={24} color="#f472b6" />
                <Text style={styles.everythingTileTitle}>Security</Text>
                <Text style={styles.everythingTileDesc}>PIN & password</Text>
              </Pressable>
            </View>

            {/* Storefront Studio Card */}
            <View style={styles.moreCard}>
              <View style={styles.sectionHeaderRow}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <Text style={styles.moreCardTitle}>Storefront Studio</Text>
                  <View
                    style={[
                      styles.storefrontStatusPill,
                      storefrontDetails?.is_published
                        ? styles.storefrontStatusPublished
                        : styles.storefrontStatusDraft,
                    ]}
                  >
                    <Text style={styles.storefrontStatusText}>
                      {storefrontDetails?.is_published ? "PUBLISHED" : "DRAFT"}
                    </Text>
                  </View>
                </View>

                <View style={{ flexDirection: "row", gap: 6 }}>
                  <Pressable
                    style={styles.publishToggleBtn}
                    onPress={handleToggleStorefrontPublish}
                  >
                    <Text style={styles.publishToggleBtnText}>
                      {storefrontDetails?.is_published ? "Unpublish" : "Go Live"}
                    </Text>
                  </Pressable>
                  <Pressable
                    style={styles.addStaffBtn}
                    onPress={() => {
                      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      setStorefrontHeadline(storefrontDetails?.headline ?? "");
                      setStorefrontDesc(storefrontDetails?.description ?? "");
                      setStorefrontPhone(storefrontDetails?.contact_phone ?? "");
                      setStorefrontThemeColor(storefrontDetails?.theme_color ?? "#084a2f");
                      setStorefrontThemeBg(storefrontDetails?.theme_bg_color ?? "#fbf7f0");
                      setStorefrontClosing(storefrontDetails?.closing_statement ?? "");
                      setShowStorefrontModal(true);
                    }}
                  >
                    <Text style={styles.addStaffBtnText}>Edit</Text>
                  </Pressable>
                </View>
              </View>

              <Text style={styles.moreCardDesc}>
                {storefrontDetails?.headline || "Your public shop catalog is live on AHIA."}
              </Text>
              <Text style={styles.storefrontUrl}>
                https://ahia.app/shop/{activeBusiness?.slug ?? "stall"}
              </Text>
              <Pressable style={styles.storefrontShareBtn} onPress={handleShareStorefront}>
                <ShareIcon size={16} color="#ffffff" />
                <Text style={styles.storefrontShareBtnText}>Share Storefront Link</Text>
              </Pressable>
            </View>

            {/* Team Management */}
            <View style={styles.moreCard}>
              <View style={styles.sectionHeaderRow}>
                <Text style={styles.moreCardTitle}>Team & Staff ({members.length})</Text>
                <Pressable
                  style={styles.addStaffBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setShowInviteModal(true);
                  }}
                >
                  <Text style={styles.addStaffBtnText}>+ Invite</Text>
                </Pressable>
              </View>

              {/* Members List */}
              {members.map((m) => (
                <View key={m.id} style={styles.memberRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.memberName}>
                      {m.first_name} {m.last_name ?? ""}
                    </Text>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 }}>
                      <Pressable
                        style={styles.memberRoleBadge}
                        onPress={() => handleChangeMemberRole(m)}
                      >
                        <Text style={styles.memberRoleBadgeText}>{m.role}</Text>
                      </Pressable>
                      <Pressable
                        style={[
                          styles.memberStatusBadge,
                          m.status === "active" ? styles.memberStatusActive : styles.memberStatusSuspended,
                        ]}
                        onPress={() => handleToggleMemberStatus(m)}
                      >
                        <Text style={styles.memberStatusBadgeText}>
                          {m.status.toUpperCase()}
                        </Text>
                      </Pressable>
                    </View>
                  </View>

                  <Pressable
                    style={styles.removeStaffBtn}
                    onPress={() => handleRemoveMember(m)}
                  >
                    <Text style={styles.removeStaffBtnText}>Remove</Text>
                  </Pressable>
                </View>
              ))}

              {/* Sent Invitations */}
              {invitations.length > 0 && (
                <View style={{ marginTop: 12, borderTopWidth: 1, borderTopColor: "#21262d", paddingTop: 10 }}>
                  <Text style={styles.invitationSubHeading}>Sent Invitations ({invitations.length})</Text>
                  {invitations.map((inv) => (
                    <View key={inv.id} style={styles.invitationRow}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.invitationPhone}>{inv.phone || inv.email || "Invited"}</Text>
                        <Text style={styles.invitationMeta}>Role: {inv.role} - {inv.status.toUpperCase()}</Text>
                      </View>
                    </View>
                  ))}
                </View>
              )}

              {/* Pending Invitations Received by User */}
              {myInvitations.length > 0 && (
                <View style={{ marginTop: 12, borderTopWidth: 1, borderTopColor: "#084a2f", paddingTop: 10 }}>
                  <Text style={[styles.invitationSubHeading, { color: "#4ade80" }]}>
                    Invitations Waiting for You ({myInvitations.length})
                  </Text>
                  {myInvitations.map((inv) => (
                    <View key={inv.id} style={styles.invitationRow}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.invitationPhone}>{inv.tenant_name}</Text>
                        <Text style={styles.invitationMeta}>Role: {inv.role_name}</Text>
                      </View>
                      <Pressable
                        style={styles.acceptInviteBtn}
                        onPress={() => handleAcceptMyInvitation(inv)}
                      >
                        <Text style={styles.acceptInviteBtnText}>Accept</Text>
                      </Pressable>
                    </View>
                  ))}
                </View>
              )}
            </View>

            {/* Business Info */}
            <View style={styles.moreCard}>
              <View style={styles.sectionHeaderRow}>
                <Text style={styles.moreCardTitle}>Business Profile</Text>
                <Pressable
                  style={styles.addStaffBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setEditBizName(businessDetails?.name ?? activeBusiness?.name ?? "");
                    setEditBizAddress(businessDetails?.address ?? "");
                    setEditBizPhone(businessDetails?.phone ?? "");
                    setShowBusinessModal(true);
                  }}
                >
                  <Text style={styles.addStaffBtnText}>Edit</Text>
                </Pressable>
              </View>
              <Text style={styles.profileDetail}>Name: {businessDetails?.name ?? activeBusiness?.name}</Text>
              <Text style={styles.profileDetail}>Address: {businessDetails?.address ?? "Alaba International Market"}</Text>
              <Text style={styles.profileDetail}>Phone: {businessDetails?.phone ?? "Not set"}</Text>
            </View>

            {/* Sign Out Action */}
            <Pressable
              style={styles.signOutBtn}
              onPress={() => {
                Alert.alert(
                  "Sign Out of AHIA?",
                  "You can sign back in at any time with your phone number and password.",
                  [
                    { text: "Cancel", style: "cancel" },
                    {
                      text: "Sign Out",
                      style: "destructive",
                      onPress: async () => {
                        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                        await forgetSession();
                        router.replace("/sign-in");
                      },
                    },
                  ],
                );
              }}
            >
              <Text style={styles.signOutBtnText}>Sign Out of AHIA</Text>
            </Pressable>
          </ScrollView>
        )}
      </View>

      {/* Persistent Bottom Navigation Bar with Native SVG Icons */}
      <View style={styles.bottomNav}>
        <Pressable
          style={[styles.navItem, activeTab === "dashboard" && styles.navItemActive]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveTab("dashboard");
          }}
        >
          <ShopIcon size={22} color={activeTab === "dashboard" ? "#4ade80" : "#8b949e"} />
          <Text style={[styles.navText, activeTab === "dashboard" && styles.navTextActive]}>Shop</Text>
        </Pressable>

        <Pressable
          style={[styles.navItem, activeTab === "shelf" && styles.navItemActive]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveTab("shelf");
          }}
        >
          <BoxIcon size={22} color={activeTab === "shelf" ? "#4ade80" : "#8b949e"} />
          <Text style={[styles.navText, activeTab === "shelf" && styles.navTextActive]}>Catalog</Text>
        </Pressable>

        <Pressable
          style={[styles.navItem, activeTab === "lists" && styles.navItemActive]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveTab("lists");
          }}
        >
          <ListIcon size={22} color={activeTab === "lists" ? "#4ade80" : "#8b949e"} />
          <Text style={[styles.navText, activeTab === "lists" && styles.navTextActive]}>Lists</Text>
          {pendingListsCount > 0 && (
            <View style={styles.navBadge}>
              <Text style={styles.navBadgeText}>{pendingListsCount}</Text>
            </View>
          )}
        </Pressable>

        <Pressable
          style={[styles.navItem, activeTab === "trading" && styles.navItemActive]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveTab("trading");
          }}
        >
          <ReceiptIcon size={22} color={activeTab === "trading" ? "#4ade80" : "#8b949e"} />
          <Text style={[styles.navText, activeTab === "trading" && styles.navTextActive]}>Trading</Text>
        </Pressable>

        <Pressable
          style={[styles.navItem, activeTab === "more" && styles.navItemActive]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveTab("more");
          }}
        >
          <MoreIcon size={22} color={activeTab === "more" ? "#4ade80" : "#8b949e"} />
          <Text style={[styles.navText, activeTab === "more" && styles.navTextActive]}>More</Text>
        </Pressable>
      </View>

      {/* Add Product Modal */}
      <Modal visible={showAddProductModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Add Product to {currentCategory?.name ?? "Shelf"}</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Product Name"
              placeholderTextColor="#8a928e"
              value={newName}
              onChangeText={setNewName}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Normal Price (e.g. 15000)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={newPrice}
              onChangeText={setNewPrice}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Wholesale Price (optional)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={newWholesale}
              onChangeText={setNewWholesale}
            />
            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setShowAddProductModal(false)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleCreateProduct}
                disabled={savingProduct}
              >
                {savingProduct ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Save Item</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Add Category Folder Modal */}
      <Modal visible={showAddCategoryModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>
              New Folder under {currentCategory?.name ?? "Catalog Root"}
            </Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Folder Name (e.g. Armoured Cables)"
              placeholderTextColor="#8a928e"
              value={newCategoryName}
              onChangeText={setNewCategoryName}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Default Retail Price (optional)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={newCategoryNormalPrice}
              onChangeText={setNewCategoryNormalPrice}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Default Wholesale Price (optional)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={newCategoryWholesalePrice}
              onChangeText={setNewCategoryWholesalePrice}
            />
            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setShowAddCategoryModal(false)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleCreateCategory}
                disabled={savingCategory}
              >
                {savingCategory ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Create Folder</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Edit Category Modal */}
      <Modal visible={editingCategory !== null} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Edit Folder {editingCategory?.name}</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Folder Name"
              placeholderTextColor="#8a928e"
              value={editCategoryName}
              onChangeText={setEditCategoryName}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Default Retail Price"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={editCategoryNormalPrice}
              onChangeText={setEditCategoryNormalPrice}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Default Wholesale Price"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={editCategoryWholesalePrice}
              onChangeText={setEditCategoryWholesalePrice}
            />
            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setEditingCategory(null)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleSaveCategoryEdit}
                disabled={savingEditCategory}
              >
                {savingEditCategory ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Save Changes</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Batch Move / Copy Category Picker Modal */}
      <Modal visible={batchModal !== null} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>
              {batchModal?.mode === "copy" ? "Copy Items to Folder" : "Move Items to Folder"}
            </Text>
            <Text style={styles.modalSubtitle}>
              Select the destination folder for {batchModal?.productIds.length} item(s):
            </Text>
            <ScrollView style={{ maxHeight: 240, marginVertical: 10 }}>
              <Pressable
                style={styles.targetFolderOption}
                onPress={() => handleExecuteBatchAction(null)}
              >
                <FolderIcon size={18} color="#60a5fa" />
                <Text style={styles.targetFolderName}>[Catalog Root]</Text>
              </Pressable>
              {categories.map((c) => (
                <Pressable
                  key={c.id}
                  style={styles.targetFolderOption}
                  onPress={() => handleExecuteBatchAction(c.id)}
                >
                  <FolderIcon size={18} color="#60a5fa" />
                  <Text style={styles.targetFolderName}>{c.name}</Text>
                </Pressable>
              ))}
            </ScrollView>
            <Pressable style={styles.modalCancelBtn} onPress={() => setBatchModal(null)}>
              <Text style={styles.modalCancelText}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      {/* Edit Product Modal */}
      <Modal visible={editingProduct !== null} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Edit {editingProduct?.name}</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Normal Price"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={editPrice}
              onChangeText={setEditPrice}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Wholesale Price"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={editWholesale}
              onChangeText={setEditWholesale}
            />
            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setEditingProduct(null)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleSaveProductEdit}
                disabled={savingEdit}
              >
                {savingEdit ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Save</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Restock Modal */}
      <Modal visible={restockProduct !== null} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Receive Stock for {restockProduct?.name}</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Quantity Received (e.g. 50)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={restockQty}
              onChangeText={setRestockQty}
            />
            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setRestockProduct(null)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleReceiveStock}
                disabled={savingRestock}
              >
                {savingRestock ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Receive Stock</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Price & Cost Input Modal for Customer List Line Item */}
      <Modal visible={pricingLine !== null} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Price & Cost for {pricingLine?.itemName}</Text>
            <Text style={styles.modalSubtitle}>
              Write what it costs you in the market and what you charge the customer.
            </Text>

            <Text style={styles.modalFieldLabel}>Customer Selling Price (NGN)</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Selling Price (e.g. 15000)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={priceInput}
              onChangeText={setPriceInput}
              autoFocus
            />

            <Text style={styles.modalFieldLabel}>Market Cost Price (NGN)</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Cost Price (e.g. 12000)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={costInput}
              onChangeText={setCostInput}
            />

            {priceInput.trim() && costInput.trim() && (
              <View style={styles.marginPreviewBox}>
                <Text style={styles.marginPreviewLabel}>Expected Profit Margin:</Text>
                <Text
                  style={[
                    styles.marginPreviewValue,
                    Number(priceInput) >= Number(costInput) ? styles.marginPositive : styles.marginNegative,
                  ]}
                >
                  {Number(priceInput) >= Number(costInput) ? "+" : ""}
                  {formatMoney((Number(priceInput) - Number(costInput)).toString())}
                </Text>
              </View>
            )}

            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setPricingLine(null)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleSaveLinePrice}
                disabled={savingPrice}
              >
                {savingPrice ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Save Pricing</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Dispatch Waybill Modal */}
      <Modal visible={dispatchModalList !== null} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Dispatch Waybill</Text>
            <Text style={styles.modalSubtitle}>
              Record transportation details for {dispatchModalList?.customer_name || dispatchModalList?.customer_phone}
            </Text>

            <TextInput
              style={styles.modalInput}
              placeholder="Transporter Name (e.g. GIG Logistics, Young Shall Grow)"
              placeholderTextColor="#8a928e"
              value={transporterName}
              onChangeText={setTransporterName}
            />

            <TextInput
              style={styles.modalInput}
              placeholder="Transporter Phone (e.g. 08012345678)"
              placeholderTextColor="#8a928e"
              keyboardType="phone-pad"
              value={transporterPhone}
              onChangeText={setTransporterPhone}
            />

            <TextInput
              style={styles.modalInput}
              placeholder="Waybill / Receipt Number (e.g. WYB-98432)"
              placeholderTextColor="#8a928e"
              value={waybillNumber}
              onChangeText={setWaybillNumber}
            />

            <TextInput
              style={styles.modalInput}
              placeholder="Dispatch Cost (NGN, optional)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={dispatchCost}
              onChangeText={setDispatchCost}
            />

            <TextInput
              style={styles.modalInput}
              placeholder="Tracking Link (optional)"
              placeholderTextColor="#8a928e"
              value={trackingUrl}
              onChangeText={setTrackingUrl}
            />

            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setDispatchModalList(null)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleDispatchWaybill}
                disabled={savingDispatch}
              >
                {savingDispatch ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Record Dispatch</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Security PIN Gate Confirmation Modal */}
      <Modal visible={pinConfirmList !== null} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Confirm Customer Order</Text>
            <Text style={styles.modalSubtitle}>
              Confirming turns this quotation into an active sale and accounts for payout. Enter your 4-digit security PIN to proceed.
            </Text>

            <TextInput
              style={styles.modalInput}
              placeholder="Enter 4-digit PIN"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              secureTextEntry
              maxLength={6}
              value={pinValue}
              onChangeText={setPinValue}
              autoFocus
            />

            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setPinConfirmList(null)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleExecutePinConfirm}
              >
                <Text style={styles.modalSaveText}>Authorize & Confirm</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Quick-Paste Order Modal */}
      <Modal visible={showQuickPasteModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Quick-Paste Order</Text>
            <Text style={styles.modalSubtitle}>
              Paste a WhatsApp message or rough note. We will itemize each line automatically.
            </Text>

            <TextInput
              style={styles.modalInput}
              placeholder="Customer Phone (e.g. 08012345678)"
              placeholderTextColor="#8a928e"
              keyboardType="phone-pad"
              value={quickPastePhone}
              onChangeText={setQuickPastePhone}
            />

            <TextInput
              style={styles.modalInput}
              placeholder="Customer Name (optional)"
              placeholderTextColor="#8a928e"
              value={quickPasteName}
              onChangeText={setQuickPasteName}
            />

            <Text style={styles.modalFieldLabel}>Order Note / Message</Text>
            <TextInput
              style={[styles.modalInput, { height: 120, textAlignVertical: "top" }]}
              placeholder={"2x 2.5mm cable\n5x 16A breaker\n1 roll binding wire"}
              placeholderTextColor="#8a928e"
              multiline
              value={quickPasteText}
              onChangeText={setQuickPasteText}
            />

            {/* Live parse summary */}
            {quickPasteText.trim().length > 0 && (
              <View style={styles.quickPasteSummaryBox}>
                <Text style={styles.quickPasteSummaryText}>
                  Parsed: {parseQuickPaste(quickPasteText).length} item(s) found
                </Text>
              </View>
            )}

            <View style={styles.modalButtons}>
              <Pressable
                style={styles.modalCancelBtn}
                onPress={() => {
                  setShowQuickPasteModal(false);
                  setQuickPastePhone("");
                  setQuickPasteName("");
                  setQuickPasteText("");
                }}
              >
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[
                  styles.modalSaveBtn,
                  (!quickPastePhone.trim() || !quickPasteText.trim()) && { opacity: 0.5 },
                ]}
                onPress={handleQuickPasteSubmit}
                disabled={savingQuickPaste || !quickPastePhone.trim() || !quickPasteText.trim()}
              >
                {savingQuickPaste ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Create Order</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Record Custom Sale Modal */}
      <Modal visible={showRecordSaleModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Record Custom Sale</Text>
            <Text style={styles.modalSubtitle}>
              Select an inventory product and record a walk-in sale.
            </Text>

            {/* Product Search / Filter */}
            <TextInput
              style={styles.modalInput}
              placeholder="Search product..."
              placeholderTextColor="#8a928e"
              value={saleSearchQuery}
              onChangeText={setSaleSearchQuery}
            />

            {/* Product selection list */}
            <ScrollView style={{ maxHeight: 140, marginBottom: 10 }}>
              {products
                .filter((p) =>
                  p.name.toLowerCase().includes(saleSearchQuery.toLowerCase())
                )
                .slice(0, 15)
                .map((p) => {
                  const isSelected = saleProductId === p.id;
                  const price = p.effective_normal_price || p.selling_price || "0";
                  return (
                    <Pressable
                      key={p.id}
                      style={[
                        styles.productPickRow,
                        isSelected && styles.productPickRowActive,
                      ]}
                      onPress={() => {
                        setSaleProductId(p.id);
                        if (!salePrice) {
                          setSalePrice(price);
                        }
                      }}
                    >
                      <View style={{ flex: 1 }}>
                        <Text
                          style={[
                            styles.productPickName,
                            isSelected && styles.productPickNameActive,
                          ]}
                        >
                          {p.name}
                        </Text>
                        <Text style={styles.productPickMeta}>
                          Price: {formatMoney(price)}
                          {p.effective_wholesale_price
                            ? ` | Wholesale: ${formatMoney(p.effective_wholesale_price)}`
                            : ""}
                        </Text>
                      </View>
                      {isSelected && (
                        <CheckMarkIcon size={16} color="#4ade80" />
                      )}
                    </Pressable>
                  );
                })}
            </ScrollView>

            <View style={{ flexDirection: "row", gap: 10 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.modalFieldLabel}>Quantity</Text>
                <TextInput
                  style={styles.modalInput}
                  placeholder="1"
                  placeholderTextColor="#8a928e"
                  keyboardType="numeric"
                  value={saleQuantity}
                  onChangeText={setSaleQuantity}
                />
              </View>
              <View style={{ flex: 2 }}>
                <Text style={styles.modalFieldLabel}>Unit Price (NGN)</Text>
                <TextInput
                  style={styles.modalInput}
                  placeholder="e.g. 5000"
                  placeholderTextColor="#8a928e"
                  keyboardType="numeric"
                  value={salePrice}
                  onChangeText={setSalePrice}
                />
              </View>
            </View>

            {/* Payment Method Pills */}
            <Text style={styles.modalFieldLabel}>Payment Method</Text>
            <View style={styles.rolePickerRow}>
              {(["cash", "bank_transfer", "pos"] as const).map((method) => (
                <Pressable
                  key={method}
                  style={[
                    styles.rolePill,
                    salePaymentMethod === method && styles.rolePillActive,
                  ]}
                  onPress={() => setSalePaymentMethod(method)}
                >
                  <Text
                    style={[
                      styles.rolePillText,
                      salePaymentMethod === method && styles.rolePillTextActive,
                    ]}
                  >
                    {method === "bank_transfer"
                      ? "Transfer"
                      : method.toUpperCase()}
                  </Text>
                </Pressable>
              ))}
            </View>

            <View style={styles.modalButtons}>
              <Pressable
                style={styles.modalCancelBtn}
                onPress={() => {
                  setShowRecordSaleModal(false);
                  setSaleProductId(null);
                  setSaleQuantity("1");
                  setSalePrice("");
                  setSaleSearchQuery("");
                }}
              >
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[
                  styles.modalSaveBtn,
                  (!saleProductId || !saleQuantity.trim()) && { opacity: 0.5 },
                ]}
                onPress={handleRecordCustomSale}
                disabled={savingSale || !saleProductId || !saleQuantity.trim()}
              >
                {savingSale ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Record Sale</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Log Expense Modal */}
      <Modal visible={showExpenseModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Log Market Expense</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Amount (e.g. 2500)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={expenseAmount}
              onChangeText={setExpenseAmount}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Description (e.g. Generator Fuel, Offloading)"
              placeholderTextColor="#8a928e"
              value={expenseDescription}
              onChangeText={setExpenseDescription}
            />
            {/* Category selection */}
            <Text style={styles.modalFieldLabel}>Expense Category</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.modalPickerRow}>
              {expenseCategories.map((c) => (
                <Pressable
                  key={c.id}
                  style={[
                    styles.rolePill,
                    expenseCategoryId === c.id && styles.rolePillActive,
                  ]}
                  onPress={() => setExpenseCategoryId(c.id)}
                >
                  <Text
                    style={[
                      styles.rolePillText,
                      expenseCategoryId === c.id && styles.rolePillTextActive,
                    ]}
                  >
                    {c.name}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>

            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setShowExpenseModal(false)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleRecordExpense}
                disabled={savingExpense}
              >
                {savingExpense ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Record Expense</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Invite Staff Modal */}
      <Modal visible={showInviteModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Invite Staff Member</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Phone Number (e.g. 08012345678)"
              placeholderTextColor="#8a928e"
              keyboardType="phone-pad"
              value={invitePhone}
              onChangeText={setInvitePhone}
            />
            <Text style={styles.modalFieldLabel}>Select Role</Text>
            <View style={styles.rolePickerRow}>
              {(["SALES", "INVENTORY", "ADMIN"] as MemberRole[]).map((r) => (
                <Pressable
                  key={r}
                  style={[styles.rolePill, inviteRole === r && styles.rolePillActive]}
                  onPress={() => setInviteRole(r)}
                >
                  <Text style={[styles.rolePillText, inviteRole === r && styles.rolePillTextActive]}>
                    {r}
                  </Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setShowInviteModal(false)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleInviteStaff}
                disabled={savingInvite}
              >
                {savingInvite ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Send WhatsApp Invite</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Product Image Gallery Modal */}
      <Modal visible={galleryProduct !== null} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <View style={styles.sectionHeaderRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.modalTitle}>{galleryProduct?.name ?? "Product"}</Text>
                <Text style={styles.modalSubtitle}>Photo Gallery & Cover Image</Text>
              </View>
              <Pressable
                style={styles.closeModalBtn}
                onPress={() => setGalleryProduct(null)}
              >
                <CloseIcon size={18} color="#8b949e" />
              </Pressable>
            </View>

            {loadingGallery ? (
              <View style={{ padding: 40, alignItems: "center" }}>
                <ActivityIndicator color="#4ade80" size="large" />
              </View>
            ) : galleryImages.length === 0 ? (
              <View style={styles.emptyGalleryBox}>
                <ImageIcon size={36} color="#6e7681" />
                <Text style={styles.emptyTitle}>No photos attached yet</Text>
                <Text style={styles.emptySubtitle}>
                  Photos attached to this product appear here and on your public web storefront.
                </Text>
              </View>
            ) : (
              <ScrollView style={{ maxHeight: 280, marginBottom: 12 }}>
                {galleryImages.map((img) => (
                  <View key={img.id} style={styles.galleryImageRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.galleryImageUrl} numberOfLines={1}>
                        {img.delivery_url}
                      </Text>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 }}>
                        {img.is_primary && (
                          <View style={styles.primaryCoverBadge}>
                            <Text style={styles.primaryCoverBadgeText}>PRIMARY COVER</Text>
                          </View>
                        )}
                        <Text style={styles.galleryPositionText}>Position: {img.position}</Text>
                      </View>
                    </View>

                    <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
                      {!img.is_primary && (
                        <Pressable
                          style={styles.makePrimaryBtn}
                          onPress={() => handleMakePrimaryImage(img.id)}
                        >
                          <Text style={styles.makePrimaryBtnText}>Set Cover</Text>
                        </Pressable>
                      )}
                      <Pressable
                        style={styles.deletePhotoBtn}
                        onPress={() => handleRemoveImage(img.id)}
                      >
                        <TrashIcon size={14} color="#f87171" />
                      </Pressable>
                    </View>
                  </View>
                ))}
              </ScrollView>
            )}

            <View style={styles.modalButtons}>
              <Pressable
                style={styles.modalCancelBtn}
                onPress={() => setGalleryProduct(null)}
              >
                <Text style={styles.modalCancelText}>Close</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Storefront Customization Modal */}
      <Modal visible={showStorefrontModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Customize Storefront</Text>
            <Text style={styles.modalSubtitle}>
              Control how buyers experience your stall on WhatsApp and the web.
            </Text>

            <ScrollView style={{ maxHeight: 380 }}>
              <Text style={styles.modalFieldLabel}>Storefront Headline</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Headline (e.g. Best Electricals in Alaba)"
                placeholderTextColor="#8a928e"
                value={storefrontHeadline}
                onChangeText={setStorefrontHeadline}
              />

              <Text style={styles.modalFieldLabel}>About Your Shop</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Description (e.g. Wholesale generators, cables & fittings)"
                placeholderTextColor="#8a928e"
                value={storefrontDesc}
                onChangeText={setStorefrontDesc}
              />

              <Text style={styles.modalFieldLabel}>WhatsApp / Contact Phone</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="WhatsApp Phone Number"
                placeholderTextColor="#8a928e"
                keyboardType="phone-pad"
                value={storefrontPhone}
                onChangeText={setStorefrontPhone}
              />

              {/* Brand Accent Color */}
              <Text style={styles.modalFieldLabel}>Brand Theme Color</Text>
              <View style={styles.colorPillsRow}>
                {[
                  { hex: "#084a2f", name: "Forest" },
                  { hex: "#1e3a8a", name: "Navy" },
                  { hex: "#b45309", name: "Amber" },
                  { hex: "#7f1d1d", name: "Crimson" },
                  { hex: "#312e81", name: "Indigo" },
                ].map((c) => (
                  <Pressable
                    key={c.hex}
                    style={[
                      styles.colorPill,
                      { backgroundColor: c.hex },
                      storefrontThemeColor === c.hex && styles.colorPillSelected,
                    ]}
                    onPress={() => setStorefrontThemeColor(c.hex)}
                  >
                    {storefrontThemeColor === c.hex && (
                      <CheckMarkIcon size={12} color="#ffffff" />
                    )}
                  </Pressable>
                ))}
              </View>

              {/* Background Tone */}
              <Text style={styles.modalFieldLabel}>Background Tone</Text>
              <View style={styles.colorPillsRow}>
                {[
                  { hex: "#fbf7f0", name: "Warm Cream" },
                  { hex: "#ffffff", name: "Crisp White" },
                  { hex: "#f1f5f9", name: "Slate Gray" },
                  { hex: "#0d1117", name: "Dark" },
                ].map((c) => (
                  <Pressable
                    key={c.hex}
                    style={[
                      styles.colorPill,
                      { backgroundColor: c.hex, borderWidth: 1, borderColor: "#30363d" },
                      storefrontThemeBg === c.hex && styles.colorPillSelected,
                    ]}
                    onPress={() => setStorefrontThemeBg(c.hex)}
                  >
                    {storefrontThemeBg === c.hex && (
                      <CheckMarkIcon
                        size={12}
                        color={c.hex === "#0d1117" ? "#ffffff" : "#000000"}
                      />
                    )}
                  </Pressable>
                ))}
              </View>

              <Text style={styles.modalFieldLabel}>Closing Statement / Notice</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="e.g. Thanks for shopping! Deliveries dispatched daily by 4pm."
                placeholderTextColor="#8a928e"
                value={storefrontClosing}
                onChangeText={setStorefrontClosing}
              />
            </ScrollView>

            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setShowStorefrontModal(false)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleUpdateStorefront}
                disabled={savingStorefront}
              >
                {savingStorefront ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Save Storefront</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Edit Business Profile Modal */}
      <Modal visible={showBusinessModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Edit Business / Stall</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Shop Name"
              placeholderTextColor="#8a928e"
              value={editBizName}
              onChangeText={setEditBizName}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Market Stall / Address"
              placeholderTextColor="#8a928e"
              value={editBizAddress}
              onChangeText={setEditBizAddress}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Official Phone Number"
              placeholderTextColor="#8a928e"
              keyboardType="phone-pad"
              value={editBizPhone}
              onChangeText={setEditBizPhone}
            />
            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setShowBusinessModal(false)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleUpdateBusiness}
                disabled={savingBusiness}
              >
                {savingBusiness ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Update Stall</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Change Password Modal */}
      <Modal visible={showPasswordModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Update Security PIN / Password</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Current Password"
              placeholderTextColor="#8a928e"
              secureTextEntry
              value={oldPassword}
              onChangeText={setOldPassword}
              autoComplete="current-password"
              textContentType="password"
              importantForAutofill="yes"
            />
            <TextInput
              style={styles.modalInput}
              placeholder="New Password (min 8 chars)"
              placeholderTextColor="#8a928e"
              secureTextEntry
              value={newPassword}
              onChangeText={setNewPassword}
              autoComplete="new-password"
              textContentType="newPassword"
              importantForAutofill="yes"
            />

            {/* Password Strength Checklist */}
            {newPassword.length > 0 && (
              <View style={styles.passwordMeterBox}>
                <View style={styles.passwordStrengthRow}>
                  <Text style={styles.passwordStrengthLabel}>Strength:</Text>
                  <Text
                    style={[
                      styles.passwordStrengthValue,
                      newPassword.length >= 8 && /\d/.test(newPassword)
                        ? styles.strengthStrong
                        : newPassword.length >= 8
                        ? styles.strengthMedium
                        : styles.strengthWeak,
                    ]}
                  >
                    {newPassword.length >= 8 && /\d/.test(newPassword)
                      ? "Strong"
                      : newPassword.length >= 8
                      ? "Medium"
                      : "Too Short"}
                  </Text>
                </View>
                <View style={styles.strengthBarWrap}>
                  <View
                    style={[
                      styles.strengthBar,
                      newPassword.length >= 8 && /\d/.test(newPassword)
                        ? styles.barStrong
                        : newPassword.length >= 8
                        ? styles.barMedium
                        : styles.barWeak,
                    ]}
                  />
                </View>
                <Text style={styles.pwdChecklistText}>
                  {newPassword.length >= 8 ? "[OK]" : "[ ]"} Minimum 8 characters
                </Text>
                <Text style={styles.pwdChecklistText}>
                  {/\d/.test(newPassword) ? "[OK]" : "[ ]"} Contains a number
                </Text>
              </View>
            )}

            <View style={styles.modalButtons}>
              <Pressable style={styles.modalCancelBtn} onPress={() => setShowPasswordModal(false)}>
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleChangePassword}
                disabled={savingPassword}
              >
                {savingPassword ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Change Password</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Switch Business Modal */}
      <Modal visible={showShopModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Your Stalls & Businesses</Text>
            {businesses?.map((b) => (
              <Pressable
                key={b.id}
                style={[
                  styles.shopOption,
                  activeBusiness?.id === b.id && styles.shopOptionActive,
                ]}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setActiveBusiness(b);
                  setShowShopModal(false);
                  void loadData(b.id);
                }}
              >
                <Text
                  style={[
                    styles.shopOptionName,
                    activeBusiness?.id === b.id && styles.shopOptionNameActive,
                  ]}
                >
                  {b.name}
                </Text>
              </Pressable>
            ))}
            <Pressable
              style={[styles.modalSaveBtn, { marginTop: 12, marginBottom: 8 }]}
              onPress={() => {
                setShowShopModal(false);
                router.push("/join" as any);
              }}
            >
              <Text style={styles.modalSaveText}>+ Join with Invite Code</Text>
            </Pressable>
            <Pressable style={styles.modalCancelBtn} onPress={() => setShowShopModal(false)}>
              <Text style={styles.modalCancelText}>Close</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#0d1117",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
    backgroundColor: "#161b22",
  },
  businessSelector: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    flex: 1,
  },
  businessBadge: {
    width: 38,
    height: 38,
    borderRadius: 8,
    backgroundColor: "#084a2f",
    alignItems: "center",
    justifyContent: "center",
  },
  businessBadgeText: {
    color: "#ffffff",
    fontWeight: "800",
    fontSize: 16,
  },
  businessName: {
    color: "#f0f6fc",
    fontWeight: "700",
    fontSize: 15,
  },
  businessSub: {
    color: "#8b949e",
    fontSize: 11,
  },
  syncButton: {
    backgroundColor: "#4ade80",
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
  },
  syncButtonPending: {
    backgroundColor: "#f59e0b",
  },
  syncInner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  syncButtonText: {
    color: "#084a2f",
    fontWeight: "700",
    fontSize: 12,
  },
  toast: {
    backgroundColor: "#084a2f",
    padding: 10,
    alignItems: "center",
  },
  toastText: {
    color: "#ffffff",
    fontWeight: "600",
    fontSize: 13,
  },
  mainContainer: {
    flex: 1,
  },
  scrollContent: {
    flex: 1,
    padding: 16,
  },
  tabContainer: {
    flex: 1,
  },
  kpiRow: {
    flexDirection: "row",
    gap: 12,
    marginBottom: 20,
  },
  kpiCard: {
    flex: 1,
    backgroundColor: "#161b22",
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  kpiCardHighlight: {
    borderColor: "#084a2f",
  },
  kpiLabel: {
    color: "#8b949e",
    fontSize: 12,
    fontWeight: "600",
    marginBottom: 6,
  },
  kpiValue: {
    color: "#f0f6fc",
    fontSize: 20,
    fontWeight: "800",
    marginBottom: 4,
  },
  kpiMeta: {
    color: "#4ade80",
    fontSize: 11,
  },
  sectionHeading: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 12,
  },
  actionGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
    marginBottom: 24,
  },
  actionTile: {
    width: "48%",
    backgroundColor: "#161b22",
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#30363d",
    gap: 6,
  },
  actionIconWrap: {
    width: 36,
    height: 36,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 4,
  },
  actionTileTitle: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "700",
  },
  actionTileDesc: {
    color: "#8b949e",
    fontSize: 11,
  },
  sectionHeaderRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  seeAllLink: {
    color: "#4ade80",
    fontSize: 12,
    fontWeight: "600",
  },
  selectAllLink: {
    color: "#4ade80",
    fontSize: 12,
    fontWeight: "600",
  },
  emptyBox: {
    backgroundColor: "#161b22",
    borderRadius: 12,
    padding: 24,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#21262d",
    marginVertical: 12,
  },
  emptyTitle: {
    color: "#f0f6fc",
    fontSize: 15,
    fontWeight: "700",
    marginTop: 8,
    marginBottom: 4,
  },
  emptySubtitle: {
    color: "#8b949e",
    fontSize: 12,
    textAlign: "center",
  },
  saleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#161b22",
    padding: 14,
    borderRadius: 10,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "#21262d",
  },
  saleReceipt: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "600",
  },
  saleDate: {
    color: "#8b949e",
    fontSize: 11,
  },
  saleAmount: {
    color: "#4ade80",
    fontSize: 14,
    fontWeight: "700",
  },
  shelfTopBar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 10,
    backgroundColor: "#161b22",
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
    gap: 10,
  },
  searchBoxWrap: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#0d1117",
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#30363d",
    gap: 8,
    height: 42,
  },
  searchInputClean: {
    flex: 1,
    color: "#f0f6fc",
    fontSize: 13,
  },
  modeToggleBtn: {
    width: 42,
    height: 42,
    borderRadius: 8,
    backgroundColor: "#21262d",
    alignItems: "center",
    justifyContent: "center",
  },
  modeToggleBtnActive: {
    backgroundColor: "#084a2f",
  },
  breadcrumbBar: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#161b22",
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
    justifyContent: "space-between",
  },
  breadcrumbScroll: {
    alignItems: "center",
    gap: 6,
  },
  breadcrumbItem: {
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  breadcrumbText: {
    color: "#8b949e",
    fontSize: 12,
    fontWeight: "600",
  },
  breadcrumbActive: {
    color: "#4ade80",
    fontWeight: "700",
  },
  upLevelBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#21262d",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
    marginLeft: 8,
  },
  upLevelText: {
    color: "#4ade80",
    fontSize: 11,
    fontWeight: "700",
  },
  folderActionBar: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
    backgroundColor: "#0d1117",
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
  },
  folderActionBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#161b22",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  folderActionText: {
    fontSize: 12,
    fontWeight: "600",
  },
  subHeading: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "700",
    marginBottom: 10,
  },
  foldersSection: {
    marginBottom: 16,
  },
  foldersGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
  },
  folderCard: {
    width: "48%",
    backgroundColor: "#161b22",
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  folderIconRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  folderName: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "700",
    marginBottom: 2,
  },
  folderMeta: {
    color: "#8b949e",
    fontSize: 11,
  },
  folderPrice: {
    color: "#4ade80",
    fontSize: 11,
    marginTop: 4,
  },
  itemsSection: {
    marginBottom: 40,
  },
  productCard: {
    backgroundColor: "#161b22",
    padding: 14,
    borderRadius: 12,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  productCardSelected: {
    borderColor: "#4ade80",
    backgroundColor: "#0d281e",
  },
  productCardTop: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
    marginBottom: 10,
  },
  checkboxTouch: {
    paddingTop: 2,
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: "#8b949e",
    alignItems: "center",
    justifyContent: "center",
  },
  checkboxActive: {
    backgroundColor: "#084a2f",
    borderColor: "#4ade80",
  },
  productInfo: {
    flex: 1,
  },
  productName: {
    color: "#f0f6fc",
    fontSize: 15,
    fontWeight: "700",
  },
  priceRow: {
    flexDirection: "row",
    gap: 12,
    marginTop: 4,
  },
  normalPrice: {
    color: "#4ade80",
    fontSize: 14,
    fontWeight: "700",
  },
  wholesalePrice: {
    color: "#f59e0b",
    fontSize: 12,
  },
  productActions: {
    flexDirection: "row",
    gap: 8,
  },
  sellOneBtn: {
    flex: 1,
    backgroundColor: "#084a2f",
    paddingVertical: 8,
    borderRadius: 6,
    alignItems: "center",
  },
  sellOneBtnText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 13,
  },
  stockBtn: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: "#21262d",
    borderRadius: 6,
    alignItems: "center",
  },
  stockBtnText: {
    color: "#8b949e",
    fontWeight: "600",
    fontSize: 12,
  },
  editBtn: {
    paddingHorizontal: 10,
    paddingVertical: 8,
    backgroundColor: "#21262d",
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
  },
  deleteBtn: {
    paddingHorizontal: 10,
    paddingVertical: 8,
    backgroundColor: "#7f1d1d",
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
  },
  batchActionBar: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#161b22",
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: "#30363d",
  },
  batchCountText: {
    color: "#4ade80",
    fontSize: 13,
    fontWeight: "700",
  },
  batchBtnRow: {
    flexDirection: "row",
    gap: 8,
  },
  batchBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#084a2f",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
  },
  batchBtnText: {
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "700",
  },
  batchDeleteBtn: {
    backgroundColor: "#dc2626",
  },
  treeScroll: {
    flex: 1,
    padding: 16,
  },
  treeHeading: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 12,
  },
  treeRootNode: {
    marginBottom: 12,
    backgroundColor: "#161b22",
    borderRadius: 8,
    padding: 10,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  treeNodeHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  treeNodeName: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "700",
  },
  treeNodeMeta: {
    color: "#8b949e",
    fontSize: 11,
  },
  treeChildNode: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginLeft: 18,
    marginTop: 6,
  },
  treeElbow: {
    color: "#6e7681",
    fontFamily: "monospace",
  },
  treeChildName: {
    color: "#93c5fd",
    fontSize: 13,
  },
  targetFolderOption: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
  },
  targetFolderName: {
    color: "#f0f6fc",
    fontSize: 14,
  },
  listPadding: {
    padding: 16,
    paddingBottom: 80,
  },
  listsHeaderWrap: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 14,
  },
  listsHeaderTitle: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
  },
  listsHeaderSubtitle: {
    color: "#8b949e",
    fontSize: 12,
    marginTop: 2,
  },
  quickPasteBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#084a2f",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
  },
  quickPasteBtnText: {
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "700",
  },
  quickPasteSummaryBox: {
    backgroundColor: "#0d281e",
    borderWidth: 1,
    borderColor: "#084a2f",
    padding: 8,
    borderRadius: 6,
    marginBottom: 10,
  },
  quickPasteSummaryText: {
    color: "#4ade80",
    fontSize: 12,
    fontWeight: "600",
  },
  listCard: {
    backgroundColor: "#161b22",
    borderRadius: 12,
    padding: 14,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  listCardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  listCustomerName: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
  },
  listDate: {
    color: "#8b949e",
    fontSize: 12,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  statusConfirmed: {
    backgroundColor: "#084a2f",
  },
  statusPending: {
    backgroundColor: "#b45309",
  },
  statusBadgeText: {
    color: "#ffffff",
    fontSize: 10,
    fontWeight: "800",
  },
  sectionBox: {
    backgroundColor: "#0d1117",
    borderRadius: 8,
    padding: 10,
    marginBottom: 8,
  },
  sectionRootTitle: {
    color: "#4ade80",
    fontSize: 12,
    fontWeight: "700",
    marginBottom: 6,
    textTransform: "uppercase",
  },
  subSectionBox: {
    marginLeft: 4,
    marginBottom: 6,
  },
  subTitle: {
    color: "#8b949e",
    fontSize: 11,
    fontStyle: "italic",
    marginBottom: 4,
  },
  lineItem: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
  },
  lineMain: {
    flex: 1,
    paddingRight: 8,
  },
  lineTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
    marginBottom: 4,
  },
  lineName: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "600",
  },
  lineStateBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  lineStateHaveIt: {
    backgroundColor: "#064e3b",
  },
  lineStateBuyIt: {
    backgroundColor: "#78350f",
  },
  lineStateCannotGet: {
    backgroundColor: "#7f1d1d",
  },
  lineStateSomewhere: {
    backgroundColor: "#21262d",
  },
  lineStateBadgeText: {
    color: "#ffffff",
    fontSize: 10,
    fontWeight: "700",
  },
  linePriceDetailRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    flexWrap: "wrap",
  },
  linePrice: {
    color: "#4ade80",
    fontSize: 12,
    fontWeight: "600",
  },
  lineCost: {
    color: "#8b949e",
    fontSize: 12,
  },
  lineMargin: {
    fontSize: 11,
    fontWeight: "700",
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 3,
  },
  marginPositive: {
    color: "#4ade80",
    backgroundColor: "#064e3b",
  },
  marginNegative: {
    color: "#f87171",
    backgroundColor: "#7f1d1d",
  },
  lineActions: {
    flexDirection: "row",
    gap: 6,
    alignItems: "center",
  },
  lineStatusCycleBtn: {
    width: 32,
    height: 32,
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
  },
  lineStatusBtnHaveIt: {
    backgroundColor: "#064e3b",
  },
  lineStatusBtnBuyIt: {
    backgroundColor: "#78350f",
  },
  lineStatusBtnUnavailable: {
    backgroundColor: "#7f1d1d",
  },
  lineStatusBtnSomewhere: {
    backgroundColor: "#21262d",
  },
  linePriceBtn: {
    width: 32,
    height: 32,
    borderRadius: 6,
    backgroundColor: "#21262d",
    alignItems: "center",
    justifyContent: "center",
  },
  waybillBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "#0d281e",
    borderWidth: 1,
    borderColor: "#084a2f",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 6,
    marginTop: 8,
    marginBottom: 4,
  },
  waybillBannerText: {
    color: "#4ade80",
    fontSize: 12,
    fontWeight: "600",
    flex: 1,
  },
  listFooter: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: "#21262d",
    paddingTop: 10,
    marginTop: 6,
  },
  totalLabel: {
    color: "#8b949e",
    fontSize: 10,
  },
  totalAmount: {
    color: "#4ade80",
    fontSize: 14,
    fontWeight: "700",
  },
  footerActions: {
    flexDirection: "row",
    gap: 6,
    alignItems: "center",
  },
  waBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#25d366",
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 6,
  },
  waBtnText: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "700",
  },
  dispatchBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#2563eb",
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 6,
  },
  dispatchBtnText: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "700",
  },
  confirmBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#084a2f",
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 6,
  },
  confirmBtnText: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "700",
  },
  marginPreviewBox: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#0d1117",
    padding: 10,
    borderRadius: 6,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  marginPreviewLabel: {
    color: "#8b949e",
    fontSize: 12,
    fontWeight: "600",
  },
  marginPreviewValue: {
    fontSize: 14,
    fontWeight: "700",
  },
  deleteListBtn: {
    padding: 6,
    backgroundColor: "#7f1d1d",
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
  },
  tradingSummaryCard: {
    backgroundColor: "#161b22",
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#084a2f",
    marginBottom: 20,
  },
  tradingSummaryLabel: {
    color: "#8b949e",
    fontSize: 12,
    fontWeight: "600",
    marginBottom: 6,
  },
  tradingSummaryAmount: {
    color: "#4ade80",
    fontSize: 26,
    fontWeight: "800",
    marginBottom: 4,
  },
  tradingSummaryMeta: {
    color: "#8b949e",
    fontSize: 12,
  },
  logExpenseBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#78350f",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 6,
  },
  logExpenseBtnText: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "700",
  },
  tradingSubTabRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 16,
  },
  tradingPillsWrap: {
    flexDirection: "row",
    gap: 6,
  },
  tradingPill: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
    backgroundColor: "#21262d",
  },
  tradingPillActive: {
    backgroundColor: "#084a2f",
  },
  tradingPillText: {
    color: "#8b949e",
    fontSize: 12,
    fontWeight: "600",
  },
  tradingPillTextActive: {
    color: "#ffffff",
    fontWeight: "700",
  },
  recordSaleBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#084a2f",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 6,
  },
  recordSaleBtnText: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "700",
  },
  saleStatusPill: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  salePillSuccess: {
    backgroundColor: "#064e3b",
  },
  salePillCancelled: {
    backgroundColor: "#7f1d1d",
  },
  saleStatusText: {
    color: "#ffffff",
    fontSize: 9,
    fontWeight: "800",
  },
  saleAmountCancelled: {
    textDecorationLine: "line-through",
    color: "#6e7681",
  },
  voidBtn: {
    backgroundColor: "#21262d",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  voidBtnText: {
    color: "#f87171",
    fontSize: 11,
    fontWeight: "600",
  },
  productPickRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 6,
    backgroundColor: "#0d1117",
    marginBottom: 6,
    borderWidth: 1,
    borderColor: "#21262d",
  },
  productPickRowActive: {
    borderColor: "#4ade80",
    backgroundColor: "#0d281e",
  },
  productPickName: {
    color: "#f0f6fc",
    fontSize: 13,
    fontWeight: "600",
  },
  productPickNameActive: {
    color: "#4ade80",
  },
  productPickMeta: {
    color: "#8b949e",
    fontSize: 11,
  },
  userProfileCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    backgroundColor: "#161b22",
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#30363d",
    marginBottom: 18,
  },
  userAvatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "#084a2f",
    alignItems: "center",
    justifyContent: "center",
  },
  userAvatarText: {
    color: "#ffffff",
    fontSize: 20,
    fontWeight: "800",
  },
  userProfileName: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 2,
  },
  userProfilePhone: {
    color: "#8b949e",
    fontSize: 12,
    marginBottom: 4,
  },
  roleBadgeWrap: {
    alignSelf: "flex-start",
    backgroundColor: "#064e3b",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
  },
  roleBadgeText: {
    color: "#4ade80",
    fontSize: 11,
    fontWeight: "700",
  },
  everythingGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    marginBottom: 20,
  },
  everythingTile: {
    width: "48%",
    backgroundColor: "#161b22",
    padding: 14,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#30363d",
    alignItems: "flex-start",
    gap: 4,
  },
  everythingTileTitle: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "700",
    marginTop: 4,
  },
  everythingTileDesc: {
    color: "#8b949e",
    fontSize: 11,
  },
  moreCard: {
    backgroundColor: "#161b22",
    borderRadius: 12,
    padding: 14,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  moreCardTitle: {
    color: "#f0f6fc",
    fontSize: 15,
    fontWeight: "700",
  },
  moreCardDesc: {
    color: "#8b949e",
    fontSize: 12,
    marginTop: 4,
    marginBottom: 8,
  },
  storefrontUrl: {
    color: "#4ade80",
    fontSize: 12,
    marginBottom: 10,
  },
  storefrontShareBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#25d366",
    padding: 10,
    borderRadius: 6,
  },
  storefrontShareBtnText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 13,
  },
  addStaffBtn: {
    backgroundColor: "#084a2f",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 4,
  },
  addStaffBtnText: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "700",
  },
  memberRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
  },
  memberName: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "600",
  },
  memberRole: {
    color: "#8b949e",
    fontSize: 12,
  },
  removeStaffBtn: {
    backgroundColor: "#7f1d1d",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  removeStaffBtnText: {
    color: "#fca5a5",
    fontSize: 11,
    fontWeight: "700",
  },
  profileDetail: {
    color: "#8b949e",
    fontSize: 13,
    marginBottom: 4,
  },
  signOutBtn: {
    backgroundColor: "#dc2626",
    padding: 14,
    borderRadius: 8,
    alignItems: "center",
    marginBottom: 40,
    marginTop: 10,
  },
  signOutBtnText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 14,
  },
  bottomNav: {
    flexDirection: "row",
    backgroundColor: "#161b22",
    borderTopWidth: 1,
    borderTopColor: "#21262d",
    paddingBottom: 6,
    paddingTop: 8,
  },
  navItem: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
  },
  navItemActive: {},
  navText: {
    fontSize: 10,
    color: "#8b949e",
    marginTop: 3,
    fontWeight: "500",
  },
  navTextActive: {
    color: "#4ade80",
    fontWeight: "700",
  },
  navBadge: {
    position: "absolute",
    top: -2,
    right: 18,
    backgroundColor: "#dc2626",
    borderRadius: 8,
    paddingHorizontal: 4,
    paddingVertical: 1,
  },
  navBadgeText: {
    color: "#ffffff",
    fontSize: 9,
    fontWeight: "800",
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.75)",
    justifyContent: "flex-end",
  },
  modalCard: {
    backgroundColor: "#161b22",
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: 20,
    maxHeight: "85%",
  },
  modalTitle: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 4,
  },
  modalSubtitle: {
    color: "#8b949e",
    fontSize: 12,
    marginBottom: 10,
  },
  modalFieldLabel: {
    color: "#8b949e",
    fontSize: 12,
    fontWeight: "600",
    marginBottom: 6,
    marginTop: 4,
  },
  modalPickerRow: {
    flexDirection: "row",
    marginBottom: 10,
  },
  modalInput: {
    backgroundColor: "#0d1117",
    color: "#f0f6fc",
    padding: 12,
    borderRadius: 8,
    marginBottom: 10,
    fontSize: 14,
  },
  modalButtons: {
    flexDirection: "row",
    gap: 10,
    marginTop: 10,
  },
  modalCancelBtn: {
    flex: 1,
    backgroundColor: "#21262d",
    padding: 12,
    borderRadius: 8,
    alignItems: "center",
  },
  modalCancelText: {
    color: "#8b949e",
    fontWeight: "600",
  },
  modalSaveBtn: {
    flex: 1,
    backgroundColor: "#084a2f",
    padding: 12,
    borderRadius: 8,
    alignItems: "center",
  },
  modalSaveText: {
    color: "#ffffff",
    fontWeight: "700",
  },
  rolePickerRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 12,
  },
  rolePill: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: "#21262d",
    borderRadius: 6,
    alignItems: "center",
    marginRight: 6,
  },
  rolePillActive: {
    backgroundColor: "#084a2f",
  },
  rolePillText: {
    color: "#8b949e",
    fontSize: 12,
    fontWeight: "600",
  },
  rolePillTextActive: {
    color: "#ffffff",
  },
  storefrontStatusPill: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  storefrontStatusPublished: {
    backgroundColor: "#064e3b",
  },
  storefrontStatusDraft: {
    backgroundColor: "#21262d",
  },
  storefrontStatusText: {
    color: "#ffffff",
    fontSize: 9,
    fontWeight: "800",
  },
  publishToggleBtn: {
    backgroundColor: "#21262d",
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  publishToggleBtnText: {
    color: "#f0f6fc",
    fontSize: 11,
    fontWeight: "600",
  },
  memberRoleBadge: {
    backgroundColor: "#084a2f",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  memberRoleBadgeText: {
    color: "#4ade80",
    fontSize: 10,
    fontWeight: "700",
  },
  memberStatusBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  memberStatusActive: {
    backgroundColor: "#166534",
  },
  memberStatusSuspended: {
    backgroundColor: "#7f1d1d",
  },
  memberStatusBadgeText: {
    color: "#ffffff",
    fontSize: 9,
    fontWeight: "700",
  },
  invitationSubHeading: {
    color: "#8b949e",
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
    marginBottom: 6,
  },
  invitationRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
  },
  invitationPhone: {
    color: "#f0f6fc",
    fontSize: 13,
    fontWeight: "600",
  },
  invitationMeta: {
    color: "#8b949e",
    fontSize: 11,
  },
  acceptInviteBtn: {
    backgroundColor: "#084a2f",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 6,
  },
  acceptInviteBtnText: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "700",
  },
  photoBtn: {
    padding: 6,
    backgroundColor: "#1e3a8a",
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
  },
  invoiceBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#4338ca",
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 6,
  },
  invoiceBtnText: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "700",
  },
  closeModalBtn: {
    padding: 4,
  },
  emptyGalleryBox: {
    alignItems: "center",
    paddingVertical: 30,
    paddingHorizontal: 20,
  },
  galleryImageRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: "#0d1117",
    padding: 10,
    borderRadius: 8,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "#21262d",
  },
  galleryImageUrl: {
    color: "#f0f6fc",
    fontSize: 12,
  },
  primaryCoverBadge: {
    backgroundColor: "#084a2f",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  primaryCoverBadgeText: {
    color: "#4ade80",
    fontSize: 9,
    fontWeight: "800",
  },
  galleryPositionText: {
    color: "#8b949e",
    fontSize: 11,
  },
  makePrimaryBtn: {
    backgroundColor: "#21262d",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  makePrimaryBtnText: {
    color: "#4ade80",
    fontSize: 11,
    fontWeight: "600",
  },
  deletePhotoBtn: {
    padding: 6,
    backgroundColor: "#21262d",
    borderRadius: 4,
  },
  colorPillsRow: {
    flexDirection: "row",
    gap: 10,
    marginBottom: 12,
  },
  colorPill: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
  },
  colorPillSelected: {
    borderWidth: 3,
    borderColor: "#4ade80",
  },
  passwordMeterBox: {
    backgroundColor: "#0d1117",
    padding: 10,
    borderRadius: 8,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "#21262d",
  },
  passwordStrengthRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 6,
  },
  passwordStrengthLabel: {
    color: "#8b949e",
    fontSize: 11,
    fontWeight: "600",
  },
  passwordStrengthValue: {
    fontSize: 11,
    fontWeight: "800",
  },
  strengthStrong: {
    color: "#4ade80",
  },
  strengthMedium: {
    color: "#fde047",
  },
  strengthWeak: {
    color: "#f87171",
  },
  strengthBarWrap: {
    height: 4,
    backgroundColor: "#21262d",
    borderRadius: 2,
    marginBottom: 8,
    overflow: "hidden",
  },
  strengthBar: {
    height: 4,
    borderRadius: 2,
  },
  barStrong: {
    width: "100%",
    backgroundColor: "#4ade80",
  },
  barMedium: {
    width: "60%",
    backgroundColor: "#fde047",
  },
  barWeak: {
    width: "25%",
    backgroundColor: "#f87171",
  },
  pwdChecklistText: {
    color: "#8b949e",
    fontSize: 11,
    marginTop: 2,
  },
  shopOption: {
    padding: 14,
    backgroundColor: "#0d1117",
    borderRadius: 8,
    marginBottom: 8,
  },
  shopOptionActive: {
    borderColor: "#084a2f",
    borderWidth: 1,
  },
  shopOptionName: {
    color: "#f0f6fc",
    fontSize: 14,
  },
  shopOptionNameActive: {
    color: "#4ade80",
    fontWeight: "700",
  },
});
