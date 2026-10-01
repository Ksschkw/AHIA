import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
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
  ApiError,
  listBusinesses,
  listCustomerLists,
  deleteCustomerList,
  confirmCustomerList,
  createProduct,
  updateProduct,
  copyProducts,
  listProducts,
  publishProduct,
  sellOneProduct,
  unpublishProduct,
  workListLine,
  listCategories,
  createCategory,
  listSales,
  dailySales,
  recordExpense,
  listExpenseCategories,
  receiveStock,
  listMembers,
  listInvitations,
  inviteMember,
  removeMember,
  currentUser,
  getBusiness,
  updateBusiness,
  getStorefront,
  updateStorefront,
  changePassword,
  type Category,
  type CustomerList,
  type CustomerListLine,
  type Product,
  type TenantSummary,
  type TenantDetails,
  type StorefrontDetails,
  type SaleSummary,
  type DailySalesSummary,
  type ExpenseCategory,
  type Member,
  type MembershipInvitation,
  type MemberRole,
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
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [customerLists, setCustomerLists] = useState<CustomerList[]>([]);
  const [sales, setSales] = useState<SaleSummary[]>([]);
  const [dailyStats, setDailyStats] = useState<DailySalesSummary | null>(null);
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<MembershipInvitation[]>([]);

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
  const [newCategoryId, setNewCategoryId] = useState<string | null>(null);
  const [savingProduct, setSavingProduct] = useState(false);

  const [showAddCategoryModal, setShowAddCategoryModal] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [newCategoryParentId, setNewCategoryParentId] = useState<string | null>(null);
  const [savingCategory, setSavingCategory] = useState(false);

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

  const handleTogglePublish = async (product: Product) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      const updated = product.is_published
        ? await unpublishProduct(activeBusiness.id, product.id)
        : await publishProduct(activeBusiness.id, product.id);

      setProducts((current) =>
        current.map((p) => (p.id === updated.id ? { ...p, is_published: updated.is_published } : p)),
      );
      showToast(updated.is_published ? `${product.name} is now Live` : `${product.name} is now Hidden`);
    } catch {
      showToast("Could not update item status.");
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
        category_id: newCategoryId || selectedCategory,
      });
      setProducts((curr) => [...curr, created]);
      cacheProducts(activeBusiness.id, [...products, created]);
      setNewName("");
      setNewPrice("");
      setNewWholesale("");
      setNewCategoryId(null);
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
        parent_id: newCategoryParentId,
      });
      setCategories((curr) => [...curr, created]);
      setNewCategoryName("");
      setNewCategoryParentId(null);
      setShowAddCategoryModal(false);
      showToast(`Created category: ${created.name}`);
    } catch {
      showToast("Could not create category.");
    } finally {
      setSavingCategory(false);
    }
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

  const handleCopyProduct = async (product: Product) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await copyProducts(activeBusiness.id, [product.id], product.category_id);
      await loadData(activeBusiness.id);
      showToast(`Copied ${product.name}`);
    } catch {
      showToast("Could not copy item");
    }
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

  const filteredProducts = products.filter((p) => {
    const matchesSearch = p.name.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesCategory = selectedCategory ? p.category_id === selectedCategory : true;
    return matchesSearch && matchesCategory;
  });

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
            <Text style={styles.syncButtonText}>
              {pendingSyncCount > 0 ? `${pendingSyncCount} Sync` : "Online"}
            </Text>
          )}
        </Pressable>
      </View>

      {/* Toast Notice */}
      {notice && (
        <View style={styles.toast}>
          <Text style={styles.toastText}>{notice}</Text>
        </View>
      )}

      {/* Main Content Area based on Active Tab */}
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

            {/* Quick Actions Grid */}
            <Text style={styles.sectionHeading}>Quick Actions</Text>
            <View style={styles.actionGrid}>
              <Pressable
                style={styles.actionTile}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setShowAddProductModal(true);
                }}
              >
                <Text style={styles.actionTileIcon}>[+ Item]</Text>
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
                <Text style={styles.actionTileIcon}>[- Exp]</Text>
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
                <Text style={styles.actionTileIcon}>[Cat]</Text>
                <Text style={styles.actionTileTitle}>New Category</Text>
                <Text style={styles.actionTileDesc}>Organize shelf</Text>
              </Pressable>

              <Pressable style={styles.actionTile} onPress={handleShareStorefront}>
                <Text style={styles.actionTileIcon}>[Share]</Text>
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
                <Text style={styles.emptySubtitle}>Tap Sell One on any shelf item to start.</Text>
              </View>
            ) : (
              sales.slice(0, 5).map((sale) => (
                <View key={sale.id} style={styles.saleRow}>
                  <View>
                    <Text style={styles.saleReceipt}>{sale.receipt_number}</Text>
                    <Text style={styles.saleDate}>{sale.payment_method.toUpperCase()}</Text>
                  </View>
                  <Text style={styles.saleAmount}>{formatMoney(sale.total_amount)}</Text>
                </View>
              ))
            )}
          </ScrollView>
        )}

        {activeTab === "shelf" && (
          <View style={styles.tabContainer}>
            {/* Search & Action Bar */}
            <View style={styles.shelfTopBar}>
              <TextInput
                style={styles.searchInput}
                placeholder="Search products..."
                placeholderTextColor="#8a928e"
                value={searchQuery}
                onChangeText={setSearchQuery}
              />
              <Pressable
                style={styles.iconAddBtn}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setShowAddProductModal(true);
                }}
              >
                <Text style={styles.iconAddBtnText}>+ Item</Text>
              </Pressable>
            </View>

            {/* Category Filter Pills */}
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.categoryScroll}>
              <Pressable
                style={[styles.categoryPill, selectedCategory === null && styles.categoryPillActive]}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setSelectedCategory(null);
                }}
              >
                <Text
                  style={[
                    styles.categoryPillText,
                    selectedCategory === null && styles.categoryPillTextActive,
                  ]}
                >
                  All ({products.length})
                </Text>
              </Pressable>
              {categories.map((cat) => {
                const count = products.filter((p) => p.category_id === cat.id).length;
                return (
                  <Pressable
                    key={cat.id}
                    style={[styles.categoryPill, selectedCategory === cat.id && styles.categoryPillActive]}
                    onPress={() => {
                      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      setSelectedCategory(cat.id);
                    }}
                  >
                    <Text
                      style={[
                        styles.categoryPillText,
                        selectedCategory === cat.id && styles.categoryPillTextActive,
                      ]}
                    >
                      {cat.name} ({count})
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>

            {/* Products List */}
            <FlatList
              data={filteredProducts}
              keyExtractor={(item) => item.id}
              contentContainerStyle={styles.listPadding}
              renderItem={({ item }) => (
                <View style={styles.productCard}>
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
                      <Text style={styles.editBtnText}>Edit</Text>
                    </Pressable>
                  </View>
                </View>
              )}
            />
          </View>
        )}

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
                                  {line.shop_price ? formatMoney(line.shop_price) : "Price not set"}
                                </Text>
                              </View>

                              <View style={styles.lineButtons}>
                                <Pressable
                                  style={styles.setPriceBtn}
                                  onPress={() => {
                                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                    setPricingLine({
                                      listId: item.id,
                                      lineId: line.id,
                                      itemName: line.product_name ?? line.free_text ?? "Item",
                                      currentPrice: line.shop_price ?? "",
                                    });
                                    setPriceInput(line.shop_price ?? "");
                                  }}
                                >
                                  <Text style={styles.setPriceBtnText}>Set Price</Text>
                                </Pressable>

                                <Pressable
                                  style={[
                                    styles.cannotGetBtn,
                                    line.state === "cannot_get" && styles.cannotGetActive,
                                  ]}
                                  onPress={() => handleToggleCannotGet(item.id, line.id, line.state)}
                                >
                                  <Text style={styles.cannotGetText}>
                                    {line.state === "cannot_get" ? "Unavailable" : "Have It"}
                                  </Text>
                                </Pressable>
                              </View>
                            </View>
                          ))}
                        </View>
                      ))}
                    </View>
                  ))}

                  {/* Order Footer & Actions */}
                  <View style={styles.listFooter}>
                    <Text style={styles.totalPrice}>
                      Total: {formatMoney(item.priced_total ?? "0")}
                    </Text>
                    <View style={styles.listActionRow}>
                      <Pressable
                        style={styles.waQuoteBtn}
                        onPress={() => handleShareQuoteOnWhatsApp(item)}
                      >
                        <Text style={styles.waQuoteBtnText}>Share Quote</Text>
                      </Pressable>

                      {!isConfirmed && (
                        <Pressable
                          style={styles.confirmBtn}
                          onPress={() => handleConfirmList(item)}
                        >
                          <Text style={styles.confirmBtnText}>Confirm Order</Text>
                        </Pressable>
                      )}
                    </View>
                  </View>
                </View>
              );
            }}
          />
        )}

        {activeTab === "trading" && (
          <ScrollView style={styles.scrollContent}>
            {/* Today's Summary Card */}
            <View style={styles.tradingSummaryCard}>
              <Text style={styles.tradingLabel}>Trading Summary</Text>
              <Text style={styles.tradingTotal}>
                {formatMoney(dailyStats?.total_revenue ?? "0")}
              </Text>
              <Text style={styles.tradingCount}>{dailyStats?.total_sales ?? 0} completed sales</Text>
            </View>

            <View style={styles.tradingButtonRow}>
              <Pressable
                style={styles.primaryTradingBtn}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setShowExpenseModal(true);
                }}
              >
                <Text style={styles.primaryTradingBtnText}>+ Log Expense</Text>
              </Pressable>
            </View>

            {/* Sales Ledger */}
            <Text style={styles.sectionHeading}>Sales Ledger</Text>
            {sales.map((s) => (
              <View key={s.id} style={styles.ledgerRow}>
                <View>
                  <Text style={styles.ledgerReceipt}>{s.receipt_number}</Text>
                  <Text style={styles.ledgerDate}>
                    {new Date(s.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} - {s.payment_method.toUpperCase()}
                  </Text>
                </View>
                <Text style={styles.ledgerAmount}>{formatMoney(s.total_amount)}</Text>
              </View>
            ))}
          </ScrollView>
        )}

        {activeTab === "more" && (
          <ScrollView style={styles.scrollContent}>
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

            {/* User Account & Security */}
            <View style={styles.moreCard}>
              <View style={styles.sectionHeaderRow}>
                <Text style={styles.moreCardTitle}>Account & Security</Text>
                <Pressable
                  style={styles.addStaffBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setShowPasswordModal(true);
                  }}
                >
                  <Text style={styles.addStaffBtnText}>Change PIN</Text>
                </Pressable>
              </View>
              <Text style={styles.profileDetail}>User: {profile?.first_name} {profile?.last_name ?? ""}</Text>
              <Text style={styles.profileDetail}>Phone: {profile?.phone ?? "Not set"}</Text>
            </View>

            {/* Sign Out Action */}
            <Pressable
              style={styles.signOutBtn}
              onPress={async () => {
                void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                await forgetSession();
                router.replace("/sign-in");
              }}
            >
              <Text style={styles.signOutBtnText}>Sign Out</Text>
            </Pressable>
          </ScrollView>
        )}
      </View>

      {/* Bottom Navigation Bar */}
      <View style={styles.bottomNav}>
        <Pressable
          style={[styles.navItem, activeTab === "dashboard" && styles.navItemActive]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveTab("dashboard");
          }}
        >
          <Text style={[styles.navIcon, activeTab === "dashboard" && styles.navIconActive]}>[H]</Text>
          <Text style={[styles.navText, activeTab === "dashboard" && styles.navTextActive]}>Home</Text>
        </Pressable>

        <Pressable
          style={[styles.navItem, activeTab === "shelf" && styles.navItemActive]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveTab("shelf");
          }}
        >
          <Text style={[styles.navIcon, activeTab === "shelf" && styles.navIconActive]}>[S]</Text>
          <Text style={[styles.navText, activeTab === "shelf" && styles.navTextActive]}>Shelf</Text>
        </Pressable>

        <Pressable
          style={[styles.navItem, activeTab === "lists" && styles.navItemActive]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveTab("lists");
          }}
        >
          <Text style={[styles.navIcon, activeTab === "lists" && styles.navIconActive]}>[L]</Text>
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
          <Text style={[styles.navIcon, activeTab === "trading" && styles.navIconActive]}>[T]</Text>
          <Text style={[styles.navText, activeTab === "trading" && styles.navTextActive]}>Trading</Text>
        </Pressable>

        <Pressable
          style={[styles.navItem, activeTab === "more" && styles.navItemActive]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveTab("more");
          }}
        >
          <Text style={[styles.navIcon, activeTab === "more" && styles.navIconActive]}>[M]</Text>
          <Text style={[styles.navText, activeTab === "more" && styles.navTextActive]}>More</Text>
        </Pressable>
      </View>

      {/* Add Product Modal */}
      <Modal visible={showAddProductModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Add Product to Shelf</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Product Name"
              placeholderTextColor="#8a928e"
              value={newName}
              onChangeText={setNewName}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Retail Price (e.g. 15000)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={newPrice}
              onChangeText={setNewPrice}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Wholesale Price (e.g. 13500)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={newWholesale}
              onChangeText={setNewWholesale}
            />

            <View style={styles.modalButtons}>
              <Pressable
                style={styles.modalCancelBtn}
                onPress={() => setShowAddProductModal(false)}
              >
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

      {/* Add Category Modal */}
      <Modal visible={showAddCategoryModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Create New Category</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Category Name (e.g. Generators, Lighting)"
              placeholderTextColor="#8a928e"
              value={newCategoryName}
              onChangeText={setNewCategoryName}
            />
            <View style={styles.modalButtons}>
              <Pressable
                style={styles.modalCancelBtn}
                onPress={() => setShowAddCategoryModal(false)}
              >
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
                  <Text style={styles.modalSaveText}>Create</Text>
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
            <Text style={styles.modalTitle}>Receive Stock: {restockProduct?.name}</Text>
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
                  <Text style={styles.modalSaveText}>Receive</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Record Expense Modal */}
      <Modal visible={showExpenseModal} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Record Expense</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Amount (e.g. 3500)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={expenseAmount}
              onChangeText={setExpenseAmount}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Description / Note (e.g. Generator Fuel)"
              placeholderTextColor="#8a928e"
              value={expenseDescription}
              onChangeText={setExpenseDescription}
            />

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
                  <Text style={styles.modalSaveText}>Record</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Set Line Price Modal */}
      <Modal visible={pricingLine !== null} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Set Price: {pricingLine?.itemName}</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Unit Price in NGN"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={priceInput}
              onChangeText={setPriceInput}
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
                  <Text style={styles.modalSaveText}>Send Invite</Text>
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
            />
            <TextInput
              style={styles.modalInput}
              placeholder="New Password (min 8 chars)"
              placeholderTextColor="#8a928e"
              secureTextEntry
              value={newPassword}
              onChangeText={setNewPassword}
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
    gap: 10,
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
    color: "#4ade80",
    fontWeight: "700",
    fontSize: 16,
  },
  businessName: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
  },
  businessSub: {
    color: "#8b949e",
    fontSize: 12,
  },
  syncButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: "#21262d",
  },
  syncButtonPending: {
    backgroundColor: "#d97706",
  },
  syncButtonText: {
    color: "#4ade80",
    fontSize: 12,
    fontWeight: "600",
  },
  toast: {
    backgroundColor: "#084a2f",
    padding: 10,
    alignItems: "center",
  },
  toastText: {
    color: "#f0f6fc",
    fontSize: 13,
    fontWeight: "500",
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
    marginBottom: 16,
  },
  kpiCard: {
    flex: 1,
    backgroundColor: "#161b22",
    borderRadius: 12,
    padding: 14,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  kpiCardHighlight: {
    borderColor: "#084a2f",
    backgroundColor: "#0d281e",
  },
  kpiLabel: {
    color: "#8b949e",
    fontSize: 12,
    marginBottom: 4,
  },
  kpiValue: {
    color: "#f0f6fc",
    fontSize: 18,
    fontWeight: "800",
  },
  kpiMeta: {
    color: "#4ade80",
    fontSize: 11,
    marginTop: 4,
  },
  sectionHeading: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
    marginVertical: 12,
  },
  sectionHeaderRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  seeAllLink: {
    color: "#4ade80",
    fontSize: 13,
    fontWeight: "600",
  },
  actionGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    marginBottom: 16,
  },
  actionTile: {
    width: "48%",
    backgroundColor: "#161b22",
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  actionTileIcon: {
    fontSize: 22,
    marginBottom: 6,
  },
  actionTileTitle: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "700",
  },
  actionTileDesc: {
    color: "#8b949e",
    fontSize: 11,
    marginTop: 2,
  },
  saleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#161b22",
    padding: 12,
    borderRadius: 8,
    marginBottom: 8,
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
    fontSize: 15,
    fontWeight: "700",
  },
  emptyBox: {
    padding: 24,
    alignItems: "center",
    backgroundColor: "#161b22",
    borderRadius: 12,
  },
  emptyTitle: {
    color: "#f0f6fc",
    fontSize: 15,
    fontWeight: "600",
  },
  emptySubtitle: {
    color: "#8b949e",
    fontSize: 13,
    marginTop: 4,
  },
  shelfTopBar: {
    flexDirection: "row",
    padding: 12,
    gap: 8,
    backgroundColor: "#161b22",
  },
  searchInput: {
    flex: 1,
    backgroundColor: "#0d1117",
    color: "#f0f6fc",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
    fontSize: 14,
  },
  iconAddBtn: {
    backgroundColor: "#084a2f",
    paddingHorizontal: 14,
    justifyContent: "center",
    borderRadius: 8,
  },
  iconAddBtnText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 13,
  },
  categoryScroll: {
    maxHeight: 44,
    paddingHorizontal: 12,
    backgroundColor: "#161b22",
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
  },
  categoryPill: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: "#21262d",
    marginRight: 8,
    alignSelf: "center",
  },
  categoryPillActive: {
    backgroundColor: "#084a2f",
  },
  categoryPillText: {
    color: "#8b949e",
    fontSize: 12,
    fontWeight: "600",
  },
  categoryPillTextActive: {
    color: "#ffffff",
  },
  listPadding: {
    padding: 12,
    paddingBottom: 80,
  },
  productCard: {
    backgroundColor: "#161b22",
    padding: 14,
    borderRadius: 12,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  productInfo: {
    marginBottom: 10,
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
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: "#21262d",
    borderRadius: 6,
    alignItems: "center",
  },
  editBtnText: {
    color: "#8b949e",
    fontWeight: "600",
    fontSize: 12,
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
    backgroundColor: "#d97706",
  },
  statusBadgeText: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "700",
  },
  sectionBox: {
    backgroundColor: "#0d1117",
    padding: 10,
    borderRadius: 8,
    marginBottom: 10,
  },
  sectionRootTitle: {
    color: "#4ade80",
    fontSize: 13,
    fontWeight: "700",
    marginBottom: 6,
  },
  subSectionBox: {
    paddingLeft: 6,
  },
  subTitle: {
    color: "#8b949e",
    fontSize: 11,
    marginBottom: 4,
  },
  lineItem: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
  },
  lineMain: {
    flex: 1,
  },
  lineName: {
    color: "#f0f6fc",
    fontSize: 13,
  },
  linePrice: {
    color: "#4ade80",
    fontSize: 12,
    fontWeight: "600",
  },
  lineButtons: {
    flexDirection: "row",
    gap: 6,
  },
  setPriceBtn: {
    backgroundColor: "#21262d",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  setPriceBtnText: {
    color: "#f0f6fc",
    fontSize: 11,
  },
  cannotGetBtn: {
    backgroundColor: "#21262d",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  cannotGetActive: {
    backgroundColor: "#dc2626",
  },
  cannotGetText: {
    color: "#ffffff",
    fontSize: 11,
  },
  listFooter: {
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: "#21262d",
  },
  totalPrice: {
    color: "#4ade80",
    fontSize: 16,
    fontWeight: "800",
    marginBottom: 10,
  },
  listActionRow: {
    flexDirection: "row",
    gap: 8,
  },
  waQuoteBtn: {
    flex: 1,
    backgroundColor: "#25d366",
    paddingVertical: 8,
    borderRadius: 6,
    alignItems: "center",
  },
  waQuoteBtnText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 13,
  },
  confirmBtn: {
    flex: 1,
    backgroundColor: "#084a2f",
    paddingVertical: 8,
    borderRadius: 6,
    alignItems: "center",
  },
  confirmBtnText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 13,
  },
  tradingSummaryCard: {
    backgroundColor: "#084a2f",
    padding: 16,
    borderRadius: 12,
    marginBottom: 14,
  },
  tradingLabel: {
    color: "#86efac",
    fontSize: 13,
  },
  tradingTotal: {
    color: "#ffffff",
    fontSize: 24,
    fontWeight: "800",
    marginVertical: 4,
  },
  tradingCount: {
    color: "#bbf7d0",
    fontSize: 12,
  },
  tradingButtonRow: {
    marginBottom: 14,
  },
  primaryTradingBtn: {
    backgroundColor: "#161b22",
    padding: 12,
    borderRadius: 8,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#30363d",
  },
  primaryTradingBtnText: {
    color: "#4ade80",
    fontWeight: "700",
    fontSize: 14,
  },
  ledgerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#161b22",
    padding: 12,
    borderRadius: 8,
    marginBottom: 8,
  },
  ledgerReceipt: {
    color: "#f0f6fc",
    fontSize: 14,
    fontWeight: "600",
  },
  ledgerDate: {
    color: "#8b949e",
    fontSize: 11,
  },
  ledgerAmount: {
    color: "#4ade80",
    fontSize: 15,
    fontWeight: "700",
  },
  moreCard: {
    backgroundColor: "#161b22",
    padding: 16,
    borderRadius: 12,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  moreCardTitle: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 6,
  },
  moreCardDesc: {
    color: "#8b949e",
    fontSize: 13,
    marginBottom: 10,
    lineHeight: 18,
  },
  storefrontUrl: {
    color: "#4ade80",
    fontSize: 12,
    marginBottom: 10,
  },
  storefrontShareBtn: {
    backgroundColor: "#25d366",
    padding: 10,
    borderRadius: 6,
    alignItems: "center",
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
  navIcon: {
    fontSize: 18,
    color: "#8b949e",
  },
  navIconActive: {
    color: "#4ade80",
  },
  navText: {
    fontSize: 10,
    color: "#8b949e",
    marginTop: 2,
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
  },
  modalTitle: {
    color: "#f0f6fc",
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 14,
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
    flex: 1,
    backgroundColor: "#21262d",
    paddingVertical: 8,
    borderRadius: 6,
    alignItems: "center",
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
