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
  type Category,
  type CustomerList,
  type CustomerListLine,
  type Product,
  type TenantSummary,
} from "@/lib/api";
import {
  cacheProducts,
  enqueueOfflineSale,
  flushOutbox,
  getCachedProducts,
  getPendingSalesCount,
} from "@/lib/db";
import { forgetSession } from "@/lib/session";

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

  const [businesses, setBusinesses] = useState<TenantSummary[] | null>(null);
  const [activeBusiness, setActiveBusiness] = useState<TenantSummary | null>(null);

  const [tab, setTab] = useState<"shelf" | "lists">("shelf");
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [customerLists, setCustomerLists] = useState<CustomerList[]>([]);
  const [searchQuery, setSearchQuery] = useState("");

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [pendingSyncCount, setPendingSyncCount] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // Add Item Modal State
  const [showAddModal, setShowAddModal] = useState(false);
  const [newName, setNewName] = useState("");
  const [newPrice, setNewPrice] = useState("");
  const [newWholesale, setNewWholesale] = useState("");
  const [newCategoryId, setNewCategoryId] = useState<string | null>(null);
  const [savingProduct, setSavingProduct] = useState(false);

  // Edit Product Modal State
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [editPrice, setEditPrice] = useState("");
  const [editWholesale, setEditWholesale] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  // Price Line Modal State
  const [pricingLine, setPricingLine] = useState<{
    listId: string;
    lineId: string;
    itemName: string;
    currentPrice: string;
  } | null>(null);
  const [priceInput, setPriceInput] = useState("");
  const [savingPrice, setSavingPrice] = useState(false);

  // Storefront & Shop Switcher Modal
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
      const [freshProducts, freshLists, freshCategories] = await Promise.all([
        listProducts(tenantId).catch(() => cached),
        listCustomerLists(tenantId).catch(() => []),
        listCategories(tenantId).catch(() => []),
      ]);

      setProducts(freshProducts);
      cacheProducts(tenantId, freshProducts);
      setCustomerLists(freshLists);
      setCategories(freshCategories);
      setProblem(null);
    } catch {
      if (cached.length === 0) {
        setProblem("Could not connect. Showing offline data where available.");
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

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
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      const synced = await flushOutbox(activeBusiness.id);
      const remaining = getPendingSalesCount(activeBusiness.id);
      setPendingSyncCount(remaining);
      if (synced > 0) {
        showToast(`Synced ${synced} offline sale(s).`);
      }
    } catch {
      showToast("Sync failed. Will retry automatically.");
    }
  };

  const handleSellOne = async (product: Product) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

    const price = product.effective_normal_price ?? product.selling_price ?? "0";

    try {
      await sellOneProduct(activeBusiness.id, product);
      showToast(`Sold 1 ${product.name}`);
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
      if (editingProduct && editingProduct.id === updated.id) {
        setEditingProduct((curr) => (curr ? { ...curr, is_published: updated.is_published } : null));
      }
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
        category_id: newCategoryId,
      });
      setProducts((curr) => [...curr, created]);
      cacheProducts(activeBusiness.id, [...products, created]);
      setNewName("");
      setNewPrice("");
      setNewWholesale("");
      setNewCategoryId(null);
      setShowAddModal(false);
      showToast(`Added ${created.name} to stock!`);
    } catch {
      showToast("Could not save item. Check connection.");
    } finally {
      setSavingProduct(false);
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

  const unansweredCount = customerLists.filter((l) => l.status !== "confirmed").length;

  const filteredProducts = products.filter((p) =>
    p.name.toLowerCase().includes(searchQuery.trim().toLowerCase()),
  );

  const categoryById = new Map(categories.map((c) => [c.id, c]));
  type ShelfGroup = { categoryId: string | null; label: string; items: Product[] };
  const shelfGroups: ShelfGroup[] = [];

  if (!searchQuery.trim()) {
    const grouped = new Map<string | null, Product[]>();
    for (const p of products) {
      const key = p.category_id ?? null;
      const list = grouped.get(key);
      if (list) list.push(p);
      else grouped.set(key, [p]);
    }
    const sortedKeys = [...grouped.keys()].sort((a, b) => {
      const nameA = a ? (categoryById.get(a)?.name ?? "Unknown") : "zzz";
      const nameB = b ? (categoryById.get(b)?.name ?? "Unknown") : "zzz";
      return nameA.localeCompare(nameB);
    });
    for (const key of sortedKeys) {
      const label = key ? (categoryById.get(key)?.name ?? "Unknown") : "Uncategorised";
      shelfGroups.push({
        categoryId: key,
        label,
        items: (grouped.get(key) ?? []).sort((a, b) => a.name.localeCompare(b.name)),
      });
    }
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable
          style={styles.headerTitleWrap}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setShowShopModal(true);
          }}
        >
          <Text style={styles.appName}>AHIA</Text>
          <View style={styles.shopSelectorPill}>
            <Text style={styles.shopName} numberOfLines={1}>
              {activeBusiness?.name ?? "My Shop"}
            </Text>
            <Text style={styles.shopSelectorChevron}>v</Text>
          </View>
        </Pressable>

        <View style={styles.headerRightActions}>
          <Pressable
            accessibilityRole="button"
            style={styles.shareStorefrontBtn}
            onPress={handleShareStorefront}
          >
            <Text style={styles.shareStorefrontText}>Share Shop</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            style={styles.signOutBtn}
            onPress={() => {
              void (async () => {
                await forgetSession();
                router.replace("/");
              })();
            }}
          >
            <Text style={styles.signOutText}>Sign out</Text>
          </Pressable>
        </View>
      </View>

      {/* Offline sync banner */}
      {pendingSyncCount > 0 ? (
        <Pressable style={styles.syncBanner} onPress={() => void handleSyncOutbox()}>
          <Text style={styles.syncBannerText}>
            {pendingSyncCount} offline {pendingSyncCount === 1 ? "sale" : "sales"} waiting to sync
          </Text>
          <Text style={styles.syncActionText}>Sync Now</Text>
        </Pressable>
      ) : null}

      {/* Toast Notice */}
      {notice ? (
        <View style={styles.toast}>
          <Text style={styles.toastText}>{notice}</Text>
        </View>
      ) : null}

      {/* Tabs */}
      <View style={styles.tabBar}>
        <Pressable
          style={[styles.tab, tab === "shelf" && styles.activeTab]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setTab("shelf");
          }}
        >
          <Text style={[styles.tabText, tab === "shelf" && styles.activeTabText]}>
            Stock ({products.length})
          </Text>
        </Pressable>
        <Pressable
          style={[styles.tab, tab === "lists" && styles.activeTab]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setTab("lists");
          }}
        >
          <View style={styles.tabWithBadge}>
            <Text style={[styles.tabText, tab === "lists" && styles.activeTabText]}>
              Customer Lists ({customerLists.length})
            </Text>
            {unansweredCount > 0 ? (
              <View style={styles.tabHoverBadge}>
                <Text style={styles.tabHoverBadgeText}>{unansweredCount}</Text>
              </View>
            ) : null}
          </View>
        </Pressable>
      </View>

      {problem ? (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{problem}</Text>
        </View>
      ) : null}

      {loading ? (
        <View style={styles.centerContainer}>
          <ActivityIndicator size="large" color="#0b5d3b" />
        </View>
      ) : tab === "shelf" ? (
        <View style={styles.contentWrap}>
          {/* Unanswered lists callout banner */}
          {unansweredCount > 0 ? (
            <Pressable
              style={styles.unansweredCallout}
              onPress={() => {
                void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                setTab("lists");
              }}
            >
              <View style={styles.unansweredBadge}>
                <Text style={styles.unansweredBadgeText}>{unansweredCount}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.unansweredTitle}>
                  {unansweredCount === 1 ? "1 customer list waiting" : `${unansweredCount} customer lists waiting`}
                </Text>
                <Text style={styles.unansweredSub}>Orders waiting for your review</Text>
              </View>
              <Text style={styles.unansweredAction}>Open</Text>
            </Pressable>
          ) : null}

          {/* Search Bar & Quick Add Button */}
          <View style={styles.searchRow}>
            <View style={styles.searchInputWrap}>
              <TextInput
                style={styles.searchInput}
                placeholder="Search items, models, packs..."
                placeholderTextColor="#8b8377"
                value={searchQuery}
                onChangeText={setSearchQuery}
                clearButtonMode="while-editing"
              />
            </View>
            <Pressable
              style={styles.addItemHeaderBtn}
              onPress={() => {
                void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                setShowAddModal(true);
              }}
            >
              <Text style={styles.addItemHeaderBtnText}>+ Add Item</Text>
            </Pressable>
          </View>

          {searchQuery.trim() ? (
            /* Flat search results */
            <FlatList
              data={filteredProducts}
              keyExtractor={(item) => item.id}
              contentContainerStyle={styles.listContainer}
              renderItem={({ item }) => (
                <View style={styles.productCard}>
                  <Pressable
                    style={styles.productInfo}
                    onPress={() => {
                      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      setEditingProduct(item);
                      setEditPrice(item.selling_price ?? item.effective_normal_price ?? "");
                      setEditWholesale(item.effective_wholesale_price ?? "");
                    }}
                  >
                    <Text style={styles.productName}>{item.name}</Text>
                    <Text style={styles.productPrice}>
                      Retail: {formatMoney(item.selling_price ?? item.effective_normal_price)}
                    </Text>
                    {item.effective_wholesale_price ? (
                      <Text style={styles.productWholesalePrice}>
                        Wholesale: {formatMoney(item.effective_wholesale_price)}
                      </Text>
                    ) : null}
                    <View style={styles.pillRow}>
                      <Pressable
                        style={[styles.statusPill, item.is_published ? styles.livePill : styles.hiddenPill]}
                        onPress={() => void handleTogglePublish(item)}
                      >
                        <Text
                          style={[
                            styles.statusPillText,
                            item.is_published ? styles.livePillText : styles.hiddenPillText,
                          ]}
                        >
                          {item.is_published ? "Live" : "Hidden"}
                        </Text>
                      </Pressable>
                      <Text style={styles.tapToEditHint}>Tap to edit price</Text>
                    </View>
                  </Pressable>

                  <View style={styles.cardActions}>
                    <Pressable style={styles.copyBtn} onPress={() => void handleCopyProduct(item)}>
                      <Text style={styles.copyBtnText}>Copy</Text>
                    </Pressable>
                    <Pressable style={styles.sellBtn} onPress={() => void handleSellOne(item)}>
                      <Text style={styles.sellBtnText}>Sell 1</Text>
                    </Pressable>
                  </View>
                </View>
              )}
              ListEmptyComponent={
                <View style={styles.emptyContainer}>
                  <Text style={styles.emptyTitle}>Nothing matches &ldquo;{searchQuery}&rdquo;</Text>
                  <Pressable
                    style={styles.emptyAddBtn}
                    onPress={() => {
                      setNewName(searchQuery);
                      setShowAddModal(true);
                    }}
                  >
                    <Text style={styles.emptyAddBtnText}>+ Add &ldquo;{searchQuery}&rdquo; as new item</Text>
                  </Pressable>
                </View>
              }
            />
          ) : (
            /* Category Grouped Shelf */
            <FlatList
              data={shelfGroups}
              keyExtractor={(group) => group.categoryId ?? "__none__"}
              refreshControl={
                <RefreshControl
                  refreshing={refreshing}
                  onRefresh={() => {
                    if (activeBusiness) {
                      setRefreshing(true);
                      void loadData(activeBusiness.id);
                    }
                  }}
                  colors={["#0b5d3b"]}
                />
              }
              contentContainerStyle={styles.listContainer}
              renderItem={({ item: group }) => (
                <View style={styles.groupSection}>
                  <View style={styles.groupHeader}>
                    <Text style={styles.groupTitle}>{group.label}</Text>
                    <View style={styles.groupCountBadge}>
                      <Text style={styles.groupCountText}>{group.items.length}</Text>
                    </View>
                  </View>
                  {group.items.map((item) => (
                    <View key={item.id} style={styles.productCard}>
                      <Pressable
                        style={styles.productInfo}
                        onPress={() => {
                          void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                          setEditingProduct(item);
                          setEditPrice(item.selling_price ?? item.effective_normal_price ?? "");
                          setEditWholesale(item.effective_wholesale_price ?? "");
                        }}
                      >
                        <Text style={styles.productName}>{item.name}</Text>
                        <Text style={styles.productPrice}>
                          Retail: {formatMoney(item.selling_price ?? item.effective_normal_price)}
                        </Text>
                        {item.effective_wholesale_price ? (
                          <Text style={styles.productWholesalePrice}>
                            Wholesale: {formatMoney(item.effective_wholesale_price)}
                          </Text>
                        ) : null}
                        <View style={styles.pillRow}>
                          <Pressable
                            style={[styles.statusPill, item.is_published ? styles.livePill : styles.hiddenPill]}
                            onPress={() => void handleTogglePublish(item)}
                          >
                            <Text
                              style={[
                                styles.statusPillText,
                                item.is_published ? styles.livePillText : styles.hiddenPillText,
                              ]}
                            >
                              {item.is_published ? "Live" : "Hidden"}
                            </Text>
                          </Pressable>
                        </View>
                      </Pressable>

                      <View style={styles.cardActions}>
                        <Pressable style={styles.copyBtn} onPress={() => void handleCopyProduct(item)}>
                          <Text style={styles.copyBtnText}>Copy</Text>
                        </Pressable>
                        <Pressable style={styles.sellBtn} onPress={() => void handleSellOne(item)}>
                          <Text style={styles.sellBtnText}>Sell 1</Text>
                        </Pressable>
                      </View>
                    </View>
                  ))}
                </View>
              )}
              ListEmptyComponent={
                <View style={styles.emptyContainer}>
                  <Text style={styles.emptyTitle}>No items on the shelf</Text>
                  <Text style={styles.emptyDesc}>Add your first item using the button above.</Text>
                </View>
              }
            />
          )}
        </View>
      ) : (
        <FlatList
          data={customerLists}
          keyExtractor={(item) => item.id}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                if (activeBusiness) {
                  setRefreshing(true);
                  void loadData(activeBusiness.id);
                }
              }}
              colors={["#0b5d3b"]}
            />
          }
          contentContainerStyle={styles.listContainer}
          renderItem={({ item: list }) => (
            <View style={styles.orderCard}>
              <View style={styles.orderHeader}>
                <View>
                  <Text style={styles.customerName}>
                    {list.customer_name ? list.customer_name : list.customer_phone}
                  </Text>
                  <Text style={styles.customerPhone}>{list.customer_phone}</Text>
                </View>
                <View style={styles.orderBadgeRow}>
                  <View
                    style={[
                      styles.orderBadge,
                      list.status === "confirmed" ? styles.orderConfirmedBadge : null,
                    ]}
                  >
                    <Text
                      style={[
                        styles.orderBadgeText,
                        list.status === "confirmed" ? styles.orderConfirmedBadgeText : null,
                      ]}
                    >
                      {list.status === "confirmed" ? "Confirmed" : `${list.lines.length} lines`}
                    </Text>
                  </View>
                  {list.status !== "confirmed" ? (
                    <Pressable
                      style={styles.deleteListBtn}
                      onPress={() => handleDeleteList(list)}
                    >
                      <Text style={styles.deleteListBtnText}>Delete</Text>
                    </Pressable>
                  ) : null}
                </View>
              </View>

              {/* Hierarchical Order Lines */}
              <View style={styles.linesList}>
                {groupCustomerListLines(list.lines).map((sec) => (
                  <View key={sec.root} style={styles.orderCategoryGroup}>
                    <View style={styles.orderCategoryHeader}>
                      <Text style={styles.orderCategoryTitle}>{sec.root.toUpperCase()}</Text>
                    </View>
                    {sec.subs.map((subGroup) => (
                      <View key={subGroup.sub || "__direct__"} style={styles.orderSubCategoryGroup}>
                        {subGroup.sub ? (
                          <View style={styles.orderSubCategoryHeader}>
                            <Text style={styles.orderSubCategoryIcon}>&rsaquo;</Text>
                            <Text style={styles.orderSubCategoryTitle}>{subGroup.sub}</Text>
                          </View>
                        ) : null}
                        {subGroup.lines.map((line) => {
                          const isCannotGet = line.state === "cannot_get";
                          return (
                            <View
                              key={line.id}
                              style={[
                                styles.lineItem,
                                subGroup.sub ? styles.lineItemIndented : null,
                                isCannotGet && styles.lineUnavailable,
                              ]}
                            >
                              <View style={styles.lineMain}>
                                <Text style={styles.lineName}>
                                  {line.product_name ?? line.free_text ?? "Item"}
                                </Text>
                                <Text style={styles.lineQty}>
                                  {Number(line.quantity)} pcs
                                  {line.shop_price ? ` - ${formatMoney(line.shop_price)}` : " (Unpriced)"}
                                </Text>
                              </View>

                              <View style={styles.lineActionCol}>
                                <Pressable
                                  style={styles.priceLineBtn}
                                  onPress={() => {
                                    setPricingLine({
                                      listId: list.id,
                                      lineId: line.id,
                                      itemName: line.product_name ?? line.free_text ?? "Item",
                                      currentPrice: line.shop_price ?? "",
                                    });
                                    setPriceInput(line.shop_price ?? "");
                                  }}
                                >
                                  <Text style={styles.priceLineBtnText}>
                                    {line.shop_price ? "Price" : "+ Price"}
                                  </Text>
                                </Pressable>

                                <Pressable
                                  style={[styles.cannotGetBtn, isCannotGet && styles.cannotGetActive]}
                                  onPress={() => void handleToggleCannotGet(list.id, line.id, line.state)}
                                >
                                  <Text
                                    style={[
                                      styles.cannotGetBtnText,
                                      isCannotGet && styles.cannotGetActiveText,
                                    ]}
                                  >
                                    {isCannotGet ? "Cannot get" : "Cannot get?"}
                                  </Text>
                                </Pressable>
                              </View>
                            </View>
                          );
                        })}
                      </View>
                    ))}
                  </View>
                ))}
              </View>

              {/* Order Footer & Actions */}
              <View style={styles.orderFooter}>
                {list.priced_total ? (
                  <View style={styles.orderTotalRow}>
                    <Text style={styles.orderTotalLabel}>Total:</Text>
                    <Text style={styles.orderTotalValue}>{formatMoney(list.priced_total)}</Text>
                  </View>
                ) : null}

                <View style={styles.orderActionButtons}>
                  <Pressable
                    style={styles.orderWhatsAppBtn}
                    onPress={() => handleShareQuoteOnWhatsApp(list)}
                  >
                    <Text style={styles.orderWhatsAppBtnText}>Send Quote on WhatsApp</Text>
                  </Pressable>

                  {list.status !== "confirmed" ? (
                    <Pressable
                      style={styles.orderConfirmBtn}
                      onPress={() => void handleConfirmList(list)}
                    >
                      <Text style={styles.orderConfirmBtnText}>Confirm Order</Text>
                    </Pressable>
                  ) : null}
                </View>
              </View>
            </View>
          )}
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyTitle}>No customer lists yet</Text>
              <Text style={styles.emptyDesc}>
                Lists sent by customers through your shop link will appear here.
              </Text>
            </View>
          }
        />
      )}

      {/* Add Product Modal */}
      <Modal visible={showAddModal} animationType="slide" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Add Item to Stock</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Item name (e.g. iPhone 15 Privacy Screen)"
              placeholderTextColor="#8b8377"
              value={newName}
              onChangeText={setNewName}
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Retail Selling Price in NGN (e.g. 2500)"
              placeholderTextColor="#8b8377"
              value={newPrice}
              onChangeText={setNewPrice}
              keyboardType="numeric"
            />
            <TextInput
              style={styles.modalInput}
              placeholder="Wholesale Price in NGN (optional)"
              placeholderTextColor="#8b8377"
              value={newWholesale}
              onChangeText={setNewWholesale}
              keyboardType="numeric"
            />

            {categories.length > 0 ? (
              <View style={styles.modalCategoryWrap}>
                <Text style={styles.modalCategoryLabel}>Category:</Text>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.modalCategoryScroll}>
                  <Pressable
                    style={[styles.catChip, newCategoryId === null && styles.catChipActive]}
                    onPress={() => setNewCategoryId(null)}
                  >
                    <Text style={[styles.catChipText, newCategoryId === null && styles.catChipActiveText]}>
                      None
                    </Text>
                  </Pressable>
                  {categories.map((c) => (
                    <Pressable
                      key={c.id}
                      style={[styles.catChip, newCategoryId === c.id && styles.catChipActive]}
                      onPress={() => setNewCategoryId(c.id)}
                    >
                      <Text style={[styles.catChipText, newCategoryId === c.id && styles.catChipActiveText]}>
                        {c.name}
                      </Text>
                    </Pressable>
                  ))}
                </ScrollView>
              </View>
            ) : null}

            <View style={styles.modalActions}>
              <Pressable
                style={styles.modalCancelBtn}
                onPress={() => {
                  setShowAddModal(false);
                  setNewName("");
                  setNewPrice("");
                  setNewWholesale("");
                }}
              >
                <Text style={styles.modalCancelBtnText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.modalSubmitBtn, (!newName.trim() || savingProduct) && styles.btnDisabled]}
                disabled={!newName.trim() || savingProduct}
                onPress={() => void handleCreateProduct()}
              >
                <Text style={styles.modalSubmitBtnText}>
                  {savingProduct ? "Saving..." : "Save Item"}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Edit Product Modal */}
      <Modal visible={editingProduct !== null} animationType="fade" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Edit Item Price</Text>
            <Text style={styles.modalSubTitle}>{editingProduct?.name}</Text>

            <Text style={styles.modalFieldLabel}>Retail Selling Price (NGN):</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="e.g. 3500"
              placeholderTextColor="#8b8377"
              value={editPrice}
              onChangeText={setEditPrice}
              keyboardType="numeric"
            />

            <Text style={styles.modalFieldLabel}>Wholesale Price (NGN):</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="e.g. 2800"
              placeholderTextColor="#8b8377"
              value={editWholesale}
              onChangeText={setEditWholesale}
              keyboardType="numeric"
            />

            <View style={styles.modalActions}>
              <Pressable
                style={styles.modalCancelBtn}
                onPress={() => setEditingProduct(null)}
              >
                <Text style={styles.modalCancelBtnText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.modalSubmitBtn, savingEdit && styles.btnDisabled]}
                disabled={savingEdit}
                onPress={() => void handleSaveProductEdit()}
              >
                <Text style={styles.modalSubmitBtnText}>
                  {savingEdit ? "Updating..." : "Update Price"}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Price Line Modal */}
      <Modal visible={pricingLine !== null} animationType="fade" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Set Item Price</Text>
            <Text style={styles.modalSubTitle}>{pricingLine?.itemName}</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Unit price in NGN (e.g. 2000)"
              placeholderTextColor="#8b8377"
              value={priceInput}
              onChangeText={setPriceInput}
              keyboardType="numeric"
              autoFocus
            />
            <View style={styles.modalActions}>
              <Pressable
                style={styles.modalCancelBtn}
                onPress={() => setPricingLine(null)}
              >
                <Text style={styles.modalCancelBtnText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.modalSubmitBtn, savingPrice && styles.btnDisabled]}
                disabled={savingPrice}
                onPress={() => void handleSaveLinePrice()}
              >
                <Text style={styles.modalSubmitBtnText}>
                  {savingPrice ? "Saving..." : "Save Price"}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Shop Selector & Share Modal */}
      <Modal visible={showShopModal} animationType="slide" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Your Shops & Storefront</Text>

            {businesses && businesses.length > 1 ? (
              <View style={{ marginBottom: 16 }}>
                <Text style={styles.modalFieldLabel}>Switch Active Shop:</Text>
                {businesses.map((b) => (
                  <Pressable
                    key={b.id}
                    style={[
                      styles.businessOption,
                      activeBusiness?.id === b.id && styles.businessOptionActive,
                    ]}
                    onPress={() => {
                      setActiveBusiness(b);
                      setShowShopModal(false);
                      void loadData(b.id);
                    }}
                  >
                    <Text
                      style={[
                        styles.businessOptionText,
                        activeBusiness?.id === b.id && styles.businessOptionActiveText,
                      ]}
                    >
                      {b.name}
                    </Text>
                    {activeBusiness?.id === b.id ? (
                      <Text style={styles.businessActiveCheck}>Active</Text>
                    ) : null}
                  </Pressable>
                ))}
              </View>
            ) : null}

            <View style={styles.storefrontShareCard}>
              <Text style={styles.storefrontLabel}>Your Public Catalog Link:</Text>
              <Text style={styles.storefrontUrl}>
                https://ahia.app/shop/{activeBusiness?.slug}
              </Text>
              <Pressable
                style={styles.shareStorefrontActionBtn}
                onPress={() => {
                  setShowShopModal(false);
                  handleShareStorefront();
                }}
              >
                <Text style={styles.shareStorefrontActionBtnText}>
                  Share on WhatsApp
                </Text>
              </Pressable>
            </View>

            <Pressable
              style={styles.modalCloseFullBtn}
              onPress={() => setShowShopModal(false)}
            >
              <Text style={styles.modalCloseFullBtnText}>Close</Text>
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
    backgroundColor: "#f7f3ec",
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 10,
    backgroundColor: "#ffffff",
    borderBottomWidth: 1,
    borderColor: "#e5ded3",
  },
  headerTitleWrap: {
    flex: 1,
    marginRight: 8,
  },
  appName: {
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 1.5,
    color: "#0b5d3b",
  },
  shopSelectorPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: 1,
  },
  shopName: {
    fontSize: 16,
    fontWeight: "800",
    color: "#1e1b16",
    maxWidth: 160,
  },
  shopSelectorChevron: {
    fontSize: 10,
    color: "#8b8377",
  },
  headerRightActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  shareStorefrontBtn: {
    paddingVertical: 5,
    paddingHorizontal: 10,
    borderRadius: 6,
    backgroundColor: "#e8f4ed",
  },
  shareStorefrontText: {
    fontSize: 12,
    fontWeight: "700",
    color: "#0b5d3b",
  },
  signOutBtn: {
    paddingVertical: 5,
    paddingHorizontal: 8,
  },
  signOutText: {
    fontSize: 12,
    fontWeight: "700",
    color: "#a3372b",
  },
  syncBanner: {
    backgroundColor: "#e8f4ed",
    borderBottomWidth: 1,
    borderColor: "#b6ddc7",
    paddingVertical: 10,
    paddingHorizontal: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  syncBannerText: {
    fontSize: 13,
    fontWeight: "700",
    color: "#0b5d3b",
  },
  syncActionText: {
    fontSize: 13,
    fontWeight: "800",
    color: "#0b5d3b",
    textDecorationLine: "underline",
  },
  toast: {
    position: "absolute",
    top: 60,
    left: 20,
    right: 20,
    backgroundColor: "#0b5d3b",
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    zIndex: 999,
    alignItems: "center",
    shadowColor: "#000",
    shadowOpacity: 0.15,
    shadowRadius: 8,
    elevation: 6,
  },
  toastText: {
    color: "#ffffff",
    fontSize: 14,
    fontWeight: "700",
  },
  tabBar: {
    flexDirection: "row",
    backgroundColor: "#ece6db",
    marginHorizontal: 16,
    marginTop: 12,
    marginBottom: 8,
    borderRadius: 10,
    padding: 3,
  },
  tab: {
    flex: 1,
    paddingVertical: 8,
    alignItems: "center",
    borderRadius: 8,
  },
  activeTab: {
    backgroundColor: "#ffffff",
    shadowColor: "#000",
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  tabText: {
    fontSize: 13,
    fontWeight: "700",
    color: "#5c5549",
  },
  activeTabText: {
    color: "#0b5d3b",
  },
  tabWithBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  tabHoverBadge: {
    backgroundColor: "#c2571f",
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 999,
  },
  tabHoverBadgeText: {
    color: "#ffffff",
    fontSize: 10,
    fontWeight: "800",
  },
  contentWrap: {
    flex: 1,
  },
  unansweredCallout: {
    backgroundColor: "#ffffff",
    marginHorizontal: 16,
    marginBottom: 10,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: "#c2571f",
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  unansweredBadge: {
    backgroundColor: "#c2571f",
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  unansweredBadgeText: {
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "900",
  },
  unansweredTitle: {
    fontSize: 13,
    fontWeight: "800",
    color: "#1e1b16",
  },
  unansweredSub: {
    fontSize: 11,
    color: "#5c5549",
  },
  unansweredAction: {
    fontSize: 12,
    fontWeight: "800",
    color: "#c2571f",
    textTransform: "uppercase",
  },
  searchRow: {
    flexDirection: "row",
    paddingHorizontal: 16,
    marginBottom: 8,
    gap: 8,
    alignItems: "center",
  },
  searchInputWrap: {
    flex: 1,
  },
  searchInput: {
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#d8d0c2",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 14,
    color: "#1e1b16",
  },
  addItemHeaderBtn: {
    backgroundColor: "#0b5d3b",
    paddingVertical: 9,
    paddingHorizontal: 14,
    borderRadius: 10,
  },
  addItemHeaderBtnText: {
    color: "#ffffff",
    fontWeight: "800",
    fontSize: 13,
  },
  listContainer: {
    paddingHorizontal: 16,
    paddingBottom: 24,
    gap: 10,
  },
  groupSection: {
    marginBottom: 12,
    gap: 8,
  },
  groupHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: "#e5ded3",
    marginBottom: 2,
  },
  groupTitle: {
    fontSize: 13,
    fontWeight: "800",
    color: "#5c5549",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  groupCountBadge: {
    backgroundColor: "#ece6db",
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 999,
  },
  groupCountText: {
    fontSize: 11,
    fontWeight: "700",
    color: "#5c5549",
  },
  productCard: {
    backgroundColor: "#ffffff",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#e5ded3",
    padding: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  productInfo: {
    flex: 1,
    marginRight: 12,
  },
  productName: {
    fontSize: 15,
    fontWeight: "700",
    color: "#1e1b16",
    marginBottom: 2,
  },
  productPrice: {
    fontSize: 14,
    fontWeight: "800",
    color: "#0b5d3b",
    marginBottom: 2,
  },
  productWholesalePrice: {
    fontSize: 12,
    fontWeight: "700",
    color: "#2563eb",
    marginBottom: 6,
  },
  pillRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  statusPill: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
  },
  statusPillText: {
    fontSize: 11,
    fontWeight: "700",
  },
  livePill: {
    backgroundColor: "#e8f4ed",
  },
  livePillText: {
    fontSize: 11,
    fontWeight: "700",
    color: "#0b5d3b",
  },
  hiddenPill: {
    backgroundColor: "#f5e8e8",
  },
  hiddenPillText: {
    fontSize: 11,
    fontWeight: "700",
    color: "#a3372b",
  },
  tapToEditHint: {
    fontSize: 11,
    color: "#8b8377",
    fontStyle: "italic",
  },
  cardActions: {
    flexDirection: "column",
    gap: 6,
    alignItems: "stretch",
  },
  copyBtn: {
    backgroundColor: "#f4f0e8",
    borderWidth: 1,
    borderColor: "#d8d0c2",
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    alignItems: "center",
  },
  copyBtnText: {
    color: "#5c5549",
    fontSize: 12,
    fontWeight: "700",
  },
  sellBtn: {
    backgroundColor: "#0b5d3b",
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 8,
    minWidth: 76,
    alignItems: "center",
  },
  sellBtnText: {
    color: "#ffffff",
    fontSize: 13,
    fontWeight: "800",
  },
  orderCard: {
    backgroundColor: "#ffffff",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#e5ded3",
    padding: 14,
  },
  orderHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: 10,
    paddingBottom: 8,
    borderBottomWidth: 1,
    borderColor: "#f0eae0",
  },
  customerName: {
    fontSize: 15,
    fontWeight: "800",
    color: "#1e1b16",
  },
  customerPhone: {
    fontSize: 13,
    color: "#5c5549",
    marginTop: 1,
  },
  orderBadgeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  orderBadge: {
    backgroundColor: "#e8f4ed",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  orderBadgeText: {
    fontSize: 11,
    fontWeight: "700",
    color: "#0b5d3b",
  },
  orderConfirmedBadge: {
    backgroundColor: "#edf7ed",
    borderWidth: 1,
    borderColor: "#a3d9a5",
  },
  orderConfirmedBadgeText: {
    color: "#1b5e20",
    fontWeight: "800",
  },
  deleteListBtn: {
    backgroundColor: "#fdf2f2",
    borderWidth: 1,
    borderColor: "#f8b4b4",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  deleteListBtnText: {
    fontSize: 11,
    fontWeight: "700",
    color: "#a3372b",
  },
  linesList: {
    gap: 8,
  },
  orderCategoryGroup: {
    marginBottom: 8,
    backgroundColor: "#fbf9f5",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#ede5d8",
    overflow: "hidden",
  },
  orderCategoryHeader: {
    backgroundColor: "#e8f4ed",
    borderBottomWidth: 1,
    borderBottomColor: "#d2e8db",
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  orderCategoryTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: "#084a2f",
    letterSpacing: 0.5,
  },
  orderSubCategoryGroup: {
    paddingHorizontal: 8,
  },
  orderSubCategoryHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingTop: 6,
    paddingBottom: 2,
    borderBottomWidth: 1,
    borderBottomColor: "#f0eae0",
  },
  orderSubCategoryIcon: {
    fontSize: 14,
    fontWeight: "800",
    color: "#c2571f",
  },
  orderSubCategoryTitle: {
    fontSize: 12,
    fontWeight: "700",
    color: "#4a4237",
  },
  lineItem: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderColor: "#f4f0e8",
  },
  lineItemIndented: {
    paddingLeft: 8,
  },
  lineUnavailable: {
    opacity: 0.5,
  },
  lineMain: {
    flex: 1,
    marginRight: 8,
  },
  lineName: {
    fontSize: 14,
    fontWeight: "700",
    color: "#1e1b16",
  },
  lineQty: {
    fontSize: 12,
    color: "#5c5549",
    marginTop: 1,
  },
  lineActionCol: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  priceLineBtn: {
    borderWidth: 1,
    borderColor: "#0b5d3b",
    backgroundColor: "#e8f4ed",
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  priceLineBtnText: {
    fontSize: 11,
    fontWeight: "800",
    color: "#0b5d3b",
  },
  cannotGetBtn: {
    borderWidth: 1,
    borderColor: "#d8d0c2",
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  cannotGetActive: {
    backgroundColor: "#f5e8e8",
    borderColor: "#a3372b",
  },
  cannotGetBtnText: {
    fontSize: 11,
    fontWeight: "700",
    color: "#5c5549",
  },
  cannotGetActiveText: {
    color: "#a3372b",
  },
  orderFooter: {
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1,
    borderColor: "#f0eae0",
  },
  orderTotalRow: {
    flexDirection: "row",
    justifyContent: "flex-end",
    alignItems: "center",
    gap: 6,
    marginBottom: 8,
  },
  orderTotalLabel: {
    fontSize: 13,
    fontWeight: "600",
    color: "#5c5549",
  },
  orderTotalValue: {
    fontSize: 16,
    fontWeight: "900",
    color: "#0b5d3b",
  },
  orderActionButtons: {
    flexDirection: "row",
    gap: 8,
  },
  orderWhatsAppBtn: {
    flex: 1,
    backgroundColor: "#25D366",
    paddingVertical: 9,
    borderRadius: 8,
    alignItems: "center",
  },
  orderWhatsAppBtnText: {
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "800",
  },
  orderConfirmBtn: {
    flex: 1,
    backgroundColor: "#0b5d3b",
    paddingVertical: 9,
    borderRadius: 8,
    alignItems: "center",
  },
  orderConfirmBtnText: {
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "800",
  },
  centerContainer: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },
  emptyContainer: {
    alignItems: "center",
    paddingVertical: 40,
    paddingHorizontal: 20,
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: "700",
    color: "#1e1b16",
    marginBottom: 4,
  },
  emptyDesc: {
    fontSize: 13,
    color: "#5c5549",
    textAlign: "center",
  },
  emptyAddBtn: {
    marginTop: 12,
    paddingVertical: 8,
    paddingHorizontal: 16,
    backgroundColor: "#0b5d3b",
    borderRadius: 8,
  },
  emptyAddBtnText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 13,
  },
  errorBox: {
    backgroundColor: "#fdf2f2",
    marginHorizontal: 16,
    marginBottom: 8,
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#f8b4b4",
  },
  errorText: {
    color: "#a3372b",
    fontSize: 13,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center",
    padding: 20,
  },
  modalCard: {
    backgroundColor: "#ffffff",
    borderRadius: 16,
    padding: 20,
    shadowColor: "#000",
    shadowOpacity: 0.15,
    shadowRadius: 10,
    elevation: 8,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: "#1e1b16",
    marginBottom: 4,
  },
  modalSubTitle: {
    fontSize: 14,
    fontWeight: "700",
    color: "#0b5d3b",
    marginBottom: 12,
  },
  modalFieldLabel: {
    fontSize: 12,
    fontWeight: "700",
    color: "#5c5549",
    marginBottom: 4,
    marginTop: 6,
  },
  modalInput: {
    backgroundColor: "#f9f7f4",
    borderWidth: 1,
    borderColor: "#d8d0c2",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    color: "#1e1b16",
    marginBottom: 10,
  },
  modalCategoryWrap: {
    marginBottom: 12,
  },
  modalCategoryLabel: {
    fontSize: 12,
    fontWeight: "700",
    color: "#5c5549",
    marginBottom: 6,
  },
  modalCategoryScroll: {
    flexDirection: "row",
  },
  catChip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: "#f4f0e8",
    borderWidth: 1,
    borderColor: "#d8d0c2",
    marginRight: 6,
  },
  catChipActive: {
    backgroundColor: "#0b5d3b",
    borderColor: "#0b5d3b",
  },
  catChipText: {
    fontSize: 12,
    fontWeight: "700",
    color: "#5c5549",
  },
  catChipActiveText: {
    color: "#ffffff",
  },
  modalActions: {
    flexDirection: "row",
    gap: 10,
    marginTop: 8,
  },
  modalCancelBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: "#f4f0e8",
    alignItems: "center",
  },
  modalCancelBtnText: {
    fontSize: 14,
    fontWeight: "700",
    color: "#5c5549",
  },
  modalSubmitBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: "#0b5d3b",
    alignItems: "center",
  },
  modalSubmitBtnText: {
    fontSize: 14,
    fontWeight: "800",
    color: "#ffffff",
  },
  btnDisabled: {
    opacity: 0.5,
  },
  businessOption: {
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#e5ded3",
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  businessOptionActive: {
    backgroundColor: "#e8f4ed",
    borderColor: "#0b5d3b",
  },
  businessOptionText: {
    fontSize: 14,
    fontWeight: "700",
    color: "#1e1b16",
  },
  businessOptionActiveText: {
    color: "#0b5d3b",
    fontWeight: "800",
  },
  businessActiveCheck: {
    fontSize: 12,
    fontWeight: "800",
    color: "#0b5d3b",
  },
  storefrontShareCard: {
    backgroundColor: "#f9f7f4",
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#d8d0c2",
    marginBottom: 14,
  },
  storefrontLabel: {
    fontSize: 12,
    fontWeight: "700",
    color: "#5c5549",
    marginBottom: 2,
  },
  storefrontUrl: {
    fontSize: 13,
    fontWeight: "800",
    color: "#0b5d3b",
    marginBottom: 10,
  },
  shareStorefrontActionBtn: {
    backgroundColor: "#25D366",
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: "center",
  },
  shareStorefrontActionBtnText: {
    color: "#ffffff",
    fontWeight: "800",
    fontSize: 13,
  },
  modalCloseFullBtn: {
    paddingVertical: 10,
    borderRadius: 10,
    backgroundColor: "#f4f0e8",
    alignItems: "center",
  },
  modalCloseFullBtnText: {
    fontSize: 13,
    fontWeight: "700",
    color: "#5c5549",
  },
});
