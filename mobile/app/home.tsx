import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
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
  listProducts,
  publishProduct,
  sellOneProduct,
  unpublishProduct,
  workListLine,
  type CustomerList,
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

export default function Home() {
  const router = useRouter();

  const [businesses, setBusinesses] = useState<TenantSummary[] | null>(null);
  const [activeBusiness, setActiveBusiness] = useState<TenantSummary | null>(null);

  const [tab, setTab] = useState<"shelf" | "lists">("shelf");
  const [products, setProducts] = useState<Product[]>([]);
  const [customerLists, setCustomerLists] = useState<CustomerList[]>([]);
  const [searchQuery, setSearchQuery] = useState("");

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [pendingSyncCount, setPendingSyncCount] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(null), 3000);
  };

  const loadData = useCallback(async (tenantId: string) => {
    // 1. First paint from local SQLite cache
    const cached = getCachedProducts(tenantId);
    if (cached.length > 0) {
      setProducts(cached);
      setLoading(false);
    }

    const pending = getPendingSalesCount(tenantId);
    setPendingSyncCount(pending);

    // 2. Fetch fresh from API
    try {
      const [freshProducts, freshLists] = await Promise.all([
        listProducts(tenantId).catch(() => cached),
        listCustomerLists(tenantId).catch(() => []),
      ]);

      setProducts(freshProducts);
      cacheProducts(tenantId, freshProducts);
      setCustomerLists(freshLists);
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
      // Offline fallback: save to durable SQLite outbox
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

  const filteredProducts = products.filter((p) =>
    p.name.toLowerCase().includes(searchQuery.trim().toLowerCase()),
  );

  return (
    <SafeAreaView style={styles.safeArea}>
      {/* Top Header */}
      <View style={styles.header}>
        <View style={styles.headerTitleWrap}>
          <Text style={styles.appName}>AHIA</Text>
          <Text style={styles.shopName} numberOfLines={1}>
            {activeBusiness?.name ?? "My Shop"}
          </Text>
        </View>

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

      {/* Offline sync banner if sales are waiting */}
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
            Shelf ({products.length})
          </Text>
        </Pressable>
        <Pressable
          style={[styles.tab, tab === "lists" && styles.activeTab]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setTab("lists");
          }}
        >
          <Text style={[styles.tabText, tab === "lists" && styles.activeTabText]}>
            Customer Lists ({customerLists.length})
          </Text>
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
          {/* Search Bar */}
          <View style={styles.searchBar}>
            <TextInput
              style={styles.searchInput}
              placeholder="Search your items..."
              placeholderTextColor="#8b8377"
              value={searchQuery}
              onChangeText={setSearchQuery}
              clearButtonMode="while-editing"
            />
          </View>

          <FlatList
            data={filteredProducts}
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
            renderItem={({ item }) => (
              <View style={styles.productCard}>
                <View style={styles.productInfo}>
                  <Text style={styles.productName}>{item.name}</Text>
                  <Text style={styles.productPrice}>
                    {formatMoney(item.effective_normal_price ?? item.selling_price)}
                  </Text>
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
                </View>

                {/* Sell 1 Action Button */}
                <Pressable style={styles.sellBtn} onPress={() => void handleSellOne(item)}>
                  <Text style={styles.sellBtnText}>Sell 1</Text>
                </Pressable>
              </View>
            )}
            ListEmptyComponent={
              <View style={styles.emptyContainer}>
                <Text style={styles.emptyTitle}>No items on the shelf</Text>
                <Text style={styles.emptyDesc}>Items created in your shop will appear here.</Text>
              </View>
            }
          />
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
                <View style={styles.orderBadge}>
                  <Text style={styles.orderBadgeText}>{list.lines.length} lines</Text>
                </View>
              </View>

              {/* Order Lines */}
              <View style={styles.linesList}>
                {list.lines.map((line) => {
                  const isCannotGet = line.state === "cannot_get";
                  return (
                    <View
                      key={line.id}
                      style={[styles.lineItem, isCannotGet && styles.lineUnavailable]}
                    >
                      <View style={styles.lineMain}>
                        {line.group_name ? (
                          <Text style={styles.lineCategory}>{line.group_name}</Text>
                        ) : null}
                        <Text style={styles.lineName}>
                          {line.product_name ?? line.free_text ?? "Item"}
                        </Text>
                        <Text style={styles.lineQty}>
                          {Number(line.quantity)} pcs
                          {line.shop_price ? ` - ${formatMoney(line.shop_price)}` : ""}
                        </Text>
                      </View>

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
                  );
                })}
              </View>

              {list.priced_total ? (
                <View style={styles.orderTotalRow}>
                  <Text style={styles.orderTotalLabel}>Total:</Text>
                  <Text style={styles.orderTotalValue}>{formatMoney(list.priced_total)}</Text>
                </View>
              ) : null}
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
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderColor: "#e5ded3",
    backgroundColor: "#ffffff",
  },
  headerTitleWrap: {
    flex: 1,
  },
  appName: {
    fontSize: 12,
    fontWeight: "800",
    color: "#0b5d3b",
    letterSpacing: 0.5,
  },
  shopName: {
    fontSize: 18,
    fontWeight: "800",
    color: "#1e1b16",
  },
  signOutBtn: {
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  signOutText: {
    fontSize: 13,
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
  contentWrap: {
    flex: 1,
  },
  searchBar: {
    paddingHorizontal: 16,
    marginBottom: 8,
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
  listContainer: {
    paddingHorizontal: 16,
    paddingBottom: 24,
    gap: 10,
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
    marginBottom: 6,
  },
  pillRow: {
    flexDirection: "row",
    alignItems: "center",
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
  sellBtn: {
    backgroundColor: "#0b5d3b",
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 10,
    minWidth: 76,
    alignItems: "center",
  },
  sellBtnText: {
    color: "#ffffff",
    fontSize: 14,
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
  linesList: {
    gap: 8,
  },
  lineItem: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderColor: "#f4f0e8",
  },
  lineUnavailable: {
    opacity: 0.5,
  },
  lineMain: {
    flex: 1,
    marginRight: 8,
  },
  lineCategory: {
    fontSize: 11,
    fontWeight: "600",
    color: "#0b5d3b",
    marginBottom: 1,
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
  orderTotalRow: {
    flexDirection: "row",
    justifyContent: "flex-end",
    alignItems: "center",
    gap: 6,
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1,
    borderColor: "#f0eae0",
  },
  orderTotalLabel: {
    fontSize: 13,
    fontWeight: "600",
    color: "#5c5549",
  },
  orderTotalValue: {
    fontSize: 15,
    fontWeight: "800",
    color: "#0b5d3b",
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
});
