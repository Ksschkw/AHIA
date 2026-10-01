import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Linking,
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
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
  CheckMarkIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CloseIcon,
  CopyIcon,
  EditIcon,
  FolderIcon,
  FolderOpenIcon,
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
} from "@/components/icons";
import {
  ApiError,
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
  getBusiness,
  getStorefront,
  inviteMember,
  listBusinesses,
  listCategories,
  listCustomerLists,
  listExpenseCategories,
  listInvitations,
  listMembers,
  listProducts,
  listSales,
  receiveStock,
  recordExpense,
  removeMember,
  sellOneProduct,
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
  type Product,
  type SaleSummary,
  type StorefrontDetails,
  type TenantDetails,
  type TenantSummary,
  type UserProfile,
} from "@/lib/api";
import {
  cacheProducts,
  enqueueOfflineSale,
  flushOutbox,
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

  const [pricingLine, setPricingLine] = useState<{
    listId: string;
    lineId: string;
    itemName: string;
    currentPrice: string;
  } | null>(null);
  const [priceInput, setPriceInput] = useState("");
  const [savingPrice, setSavingPrice] = useState(false);

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
  const [savingStorefront, setSavingStorefront] = useState(false);

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
    if (cached.length > 0) {
      setProducts(cached);
      setLoading(false);
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
        bDetails,
        uProfile,
        sDetails,
      ] = await Promise.all([
        listProducts(tenantId).catch(() => cached),
        listCustomerLists(tenantId).catch(() => []),
        listCategories(tenantId).catch(() => []),
        listSales(tenantId).catch(() => []),
        dailySales(tenantId).catch(() => null),
        listExpenseCategories(tenantId).catch(() => ({ categories: [] })),
        listMembers(tenantId).catch(() => []),
        listInvitations(tenantId).catch(() => []),
        getBusiness(tenantId).catch(() => null),
        currentUser().catch(() => null),
        getStorefront(tenantId).catch(() => null),
      ]);

      setProducts(freshProducts);
      cacheProducts(tenantId, freshProducts);
      setCustomerLists(freshLists);
      setCategories(freshCategories);
      setSales(freshSales);
      setDailyStats(freshDaily);
      setExpenseCategories(freshExpCats.categories);
      if (freshExpCats.categories.length > 0 && !expenseCategoryId) {
        setExpenseCategoryId(freshExpCats.categories[0].id);
      }
      setMembers(freshMembers);
      setInvitations(freshInvs);
      setBusinessDetails(bDetails);
      setProfile(uProfile);
      setStorefrontDetails(sDetails);
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
        shop_price: priceInput.trim() || undefined,
      });
      setCustomerLists((curr) => curr.map((l) => (l.id === updatedList.id ? updatedList : l)));
      setPricingLine(null);
      setPriceInput("");
      showToast("Line price updated!");
    } catch {
      showToast("Could not update price.");
    } finally {
      setSavingPrice(false);
    }
  };

  const handleToggleCannotGet = async (listId: string, lineId: string, currentState: string) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const nextState = currentState === "cannot_get" ? "have_it" : "cannot_get";
    try {
      const updatedList = await workListLine(activeBusiness.id, listId, lineId, { state: nextState });
      setCustomerLists((current) =>
        current.map((l) => (l.id === updatedList.id ? updatedList : l)),
      );
      showToast(nextState === "cannot_get" ? "Marked as cannot get" : "Marked as available");
    } catch {
      showToast("Could not update line status.");
    }
  };

  const handleConfirmList = async (list: CustomerList) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    try {
      const confirmed = await confirmCustomerList(activeBusiness.id, list.id);
      setCustomerLists((curr) => curr.map((l) => (l.id === confirmed.id ? confirmed : l)));
      showToast(`Order from ${list.customer_name || list.customer_phone} confirmed!`);
    } catch {
      showToast("Could not confirm order. Make sure all items have prices.");
    }
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
                          {sub.lines.map((line) => (
                            <View key={line.id} style={styles.lineItem}>
                              <View style={styles.lineMain}>
                                <Text style={styles.lineName}>
                                  {line.quantity}x {line.product_name ?? line.free_text}
                                </Text>
                                <Text style={styles.linePrice}>
                                  {line.shop_price ? formatMoney(line.shop_price) : "Set Price"}
                                </Text>
                              </View>

                              <View style={styles.lineActions}>
                                <Pressable
                                  style={[
                                    styles.lineStatusBtn,
                                    line.state === "cannot_get" && styles.lineStatusBtnUnavailable,
                                  ]}
                                  onPress={() =>
                                    handleToggleCannotGet(item.id, line.id, line.state)
                                  }
                                >
                                  {line.state === "cannot_get" ? (
                                    <CannotGetIcon size={14} color="#fca5a5" />
                                  ) : (
                                    <CheckMarkIcon size={14} color="#86efac" />
                                  )}
                                </Pressable>

                                <Pressable
                                  style={styles.linePriceBtn}
                                  onPress={() => {
                                    setPricingLine({
                                      listId: item.id,
                                      lineId: line.id,
                                      itemName: line.product_name ?? line.free_text ?? "Item",
                                      currentPrice: line.shop_price ?? "",
                                    });
                                    setPriceInput(line.shop_price ?? "");
                                  }}
                                >
                                  <EditIcon size={14} color="#8a928e" />
                                </Pressable>
                              </View>
                            </View>
                          ))}
                        </View>
                      ))}
                    </View>
                  ))}

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
                        <Text style={styles.waBtnText}>WhatsApp Quote</Text>
                      </Pressable>

                      {!isConfirmed && (
                        <Pressable
                          style={styles.confirmBtn}
                          onPress={() => handleConfirmList(item)}
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

        {/* Trading Ledger Tab */}
        {activeTab === "trading" && (
          <ScrollView style={styles.scrollContent}>
            <View style={styles.tradingSummaryCard}>
              <Text style={styles.tradingSummaryLabel}>Today's Gross Sales</Text>
              <Text style={styles.tradingSummaryAmount}>
                {formatMoney(dailyStats?.total_revenue ?? "0")}
              </Text>
              <Text style={styles.tradingSummaryMeta}>
                {dailyStats?.total_sales ?? 0} transaction(s) recorded today
              </Text>
            </View>

            <View style={styles.sectionHeaderRow}>
              <Text style={styles.sectionHeading}>Sales Transactions</Text>
              <Pressable
                style={styles.logExpenseBtn}
                onPress={() => setShowExpenseModal(true)}
              >
                <PlusIcon size={12} color="#ffffff" />
                <Text style={styles.logExpenseBtnText}>Expense</Text>
              </Pressable>
            </View>

            {sales.map((s) => (
              <View key={s.id} style={styles.saleRow}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                  <ReceiptIcon size={18} color="#4ade80" />
                  <View>
                    <Text style={styles.saleReceipt}>{s.receipt_number}</Text>
                    <Text style={styles.saleDate}>
                      {new Date(s.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} - {s.payment_method.toUpperCase()}
                    </Text>
                  </View>
                </View>
                <Text style={styles.saleAmount}>{formatMoney(s.total_amount)}</Text>
              </View>
            ))}
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
                <Text style={styles.moreCardTitle}>Storefront Studio</Text>
                <Pressable
                  style={styles.addStaffBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setStorefrontHeadline(storefrontDetails?.headline ?? "");
                    setStorefrontDesc(storefrontDetails?.description ?? "");
                    setStorefrontPhone(storefrontDetails?.contact_phone ?? "");
                    setShowStorefrontModal(true);
                  }}
                >
                  <Text style={styles.addStaffBtnText}>Edit</Text>
                </Pressable>
              </View>
              <Text style={styles.moreCardDesc}>
                {storefrontDetails?.headline || "Your public shop catalog is live on AHIA."}
              </Text>
              <Text style={styles.storefrontUrl}>
                https://ahia.app/shop/{activeBusiness?.slug ?? "stall"}
              </Text>
              <Pressable style={styles.storefrontShareBtn} onPress={handleShareStorefront}>
                <ShareIcon size={16} color="#ffffff" />
                <Text style={styles.storefrontShareBtnText}>Share on WhatsApp</Text>
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
              {members.map((m) => (
                <View key={m.id} style={styles.memberRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.memberName}>{m.first_name} {m.last_name ?? ""}</Text>
                    <Text style={styles.memberRole}>{m.role} - {m.status.toUpperCase()}</Text>
                  </View>
                  <Pressable
                    style={styles.removeStaffBtn}
                    onPress={() => handleRemoveMember(m)}
                  >
                    <Text style={styles.removeStaffBtnText}>Remove</Text>
                  </Pressable>
                </View>
              ))}
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

      {/* Price Input Modal for Line Item */}
      <Modal visible={pricingLine !== null} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Set Price for {pricingLine?.itemName}</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Price (NGN)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={priceInput}
              onChangeText={setPriceInput}
              autoFocus
            />
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
                  <Text style={styles.modalSaveText}>Save Price</Text>
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

      {/* Storefront Customization Modal */}
      <Modal visible={showStorefrontModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Customize Storefront</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Headline (e.g. Best Electricals in Alaba)"
              placeholderTextColor="#8a928e"
              value={storefrontHeadline}
              onChangeText={setStorefrontHeadline}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Description (e.g. Wholesale generators, cables & fittings)"
              placeholderTextColor="#8a928e"
              value={storefrontDesc}
              onChangeText={setStorefrontDesc}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="WhatsApp / Contact Phone"
              placeholderTextColor="#8a928e"
              keyboardType="phone-pad"
              value={storefrontPhone}
              onChangeText={setStorefrontPhone}
            />
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
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: "#161b22",
  },
  lineMain: {
    flex: 1,
  },
  lineName: {
    color: "#f0f6fc",
    fontSize: 13,
  },
  linePrice: {
    color: "#8b949e",
    fontSize: 11,
  },
  lineActions: {
    flexDirection: "row",
    gap: 6,
  },
  lineStatusBtn: {
    width: 28,
    height: 28,
    borderRadius: 6,
    backgroundColor: "#064e3b",
    alignItems: "center",
    justifyContent: "center",
  },
  lineStatusBtnUnavailable: {
    backgroundColor: "#7f1d1d",
  },
  linePriceBtn: {
    width: 28,
    height: 28,
    borderRadius: 6,
    backgroundColor: "#21262d",
    alignItems: "center",
    justifyContent: "center",
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
