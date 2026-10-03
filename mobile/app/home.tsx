import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  FlatList,
  Image,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  cacheBusinesses,
  cacheCategories,
  cacheCustomerLists,
  cacheProducts,
  cacheProfile,
  getCachedProfile,
  cacheBusinessDetails,
  getCachedBusinessDetails,
  cacheDailyStats,
  getCachedDailyStats,
  cacheSales,
  getCachedSales,
  setAppSetting,
  getAppSetting,
  clearLocalDatabase,
  createLocalCategory,
  createLocalProduct,
  deleteLocalCategory,
  deleteLocalProduct,
  updateCachedBusiness,
  enqueueOfflineSale,
  flushSyncOutbox,
  getCachedBusinesses,
  getCachedCategories,
  getCachedCustomerLists,
  getCachedProducts,
  getPendingOutboxCount,
  updateCachedCustomerList,
  updateLocalCategory,
  updateLocalProduct,
} from "@/lib/db";
import { forgetSession } from "@/lib/session";
import { getTheme, getSavedThemeMode, saveThemeMode, type ThemeMode, type ThemePalette } from "@/lib/theme";
import { hasBusinessPin, setBusinessPin, verifyBusinessPin } from "@/lib/pin";
import { useAppLifecycle } from "@/lib/lifecycle";
import { fetchUnreadCount } from "@/lib/notifications";
import {
  ArrowLeftIcon,
  BoxIcon,
  CameraIcon,
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
  LockIcon,
  MoreIcon,
  PeopleIcon,
  PersonIcon,
  PhoneIcon,
  PlusIcon,
  ReceiptIcon,
  SearchIcon,
  ShareIcon,
  ShopIcon,
  SparklesIcon,
  SyncIcon,
  TagIcon,
  TrashIcon,
  TreeIcon,
  TruckIcon,
} from "@/components/icons";
import { PinPad } from "@/components/pin-pad";
import { generateAndSharePdfInvoice, printInvoice } from "@/lib/invoice";
import {
  type ListPayment,
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
  attachProductImageUrl,
  listProductImages,
  listProducts,
  listSales,
  lowStock,
  makeProductImagePrimary,
  productShareSheet,
  publishProduct,
  publishStorefront,
  receiveStock,
  recordExpense,
  recordSale,
  removeMember,
  removeProductImage,
  sellOneProduct,
  submitCustomerList,
  unpublishProduct,
  unpublishStorefront,
  updateBusiness,
  updateCategory,
  updateProduct,
  updateProfile,
  updateStorefront,
  workListLine,
  type Category,
  type CustomerList,
  type CustomerListLine,
  type DailySalesSummary,
  type ExpenseCategory,
  type LowStockProduct,
  type Member,
  type MemberRole,
  type MembershipInvitation,
  type PendingInvitation,
  type Product,
  type ProductImage,
  type ProductShareSheet,
  type SaleSummary,
  type StorefrontDetails,
  type TenantDetails,
  type TenantSummary,
  type UserProfile,
} from "@/lib/api";

type TabKey = "dashboard" | "shelf" | "lists" | "trading" | "more";

const DEFAULT_EXPENSE_CATEGORIES: ExpenseCategory[] = [
  { value: "STOCK_PURCHASE", label: "Stock Purchase", is_known_spending: true },
  { value: "TRANSPORT", label: "Transport & Logistics", is_known_spending: true },
  { value: "RENT", label: "Stall Rent & Space", is_known_spending: true },
  { value: "UTILITIES", label: "Generator Fuel & Light", is_known_spending: true },
  { value: "SALARIES", label: "Staff & Apprentice Pay", is_known_spending: true },
  { value: "PACKAGING", label: "Nylon & Packaging", is_known_spending: true },
  { value: "MARKETING", label: "Marketing & Ads", is_known_spending: true },
  { value: "MAINTENANCE", label: "Repairs & Maintenance", is_known_spending: true },
  { value: "FEES_AND_LEVIES", label: "Market Toll & Levies", is_known_spending: true },
  { value: "OTHER", label: "Other Miscellaneous", is_known_spending: false },
];

function formatMoney(amount: string | null | undefined): string {
  if (!amount) return "Price on request";
  const num = Number(amount);
  if (!Number.isFinite(num)) return `NGN ${amount}`;
  return `NGN ${num.toLocaleString("en-NG", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
}

function formatWaNumber(rawPhone: string | null | undefined): string | null {
  if (!rawPhone) return null;
  const digits = rawPhone.replace(/[^\d]/g, "");
  if (!digits || digits.length < 7) return null;
  if (digits.startsWith("00234")) return digits.slice(2);
  if (digits.startsWith("234")) return digits;
  if (digits.startsWith("0")) return "234" + digits.slice(1);
  if (digits.length === 10) return "234" + digits;
  return digits;
}

function getInvitationStatus(
  inv: MembershipInvitation,
  activeMembers: Member[]
): "ACCEPTED" | "REVOKED" | "EXPIRED" | "PENDING" {
  if (inv.accepted_at) return "ACCEPTED";
  if (inv.revoked_at) return "REVOKED";
  if (inv.expires_at && new Date(inv.expires_at).getTime() < Date.now()) return "EXPIRED";
  const invDigits = inv.phone ? inv.phone.replace(/[^\d]/g, "").slice(-10) : null;
  if (
    invDigits &&
    invDigits.length >= 7 &&
    activeMembers.some((m) => m.phone && m.phone.replace(/[^\d]/g, "").slice(-10) === invDigits)
  ) {
    return "ACCEPTED";
  }
  return (inv.status ? inv.status.toUpperCase() : "PENDING") as any;
}

function getCategoryDescendantIds(catId: string, allCats: Category[]): Set<string> {
  const result = new Set<string>([catId]);
  const queue = [catId];
  while (queue.length > 0) {
    const parent = queue.shift()!;
    for (const c of allCats) {
      if (c.parent_id === parent && !result.has(c.id)) {
        result.add(c.id);
        queue.push(c.id);
      }
    }
  }
  return result;
}

function countCategoryProducts(
  catId: string,
  allCats: Category[],
  allProds: Product[]
): { direct: number; total: number } {
  const descendantIds = getCategoryDescendantIds(catId, allCats);
  let direct = 0;
  let total = 0;
  for (const p of allProds) {
    if (p.category_id === catId) direct++;
    if (p.category_id && descendantIds.has(p.category_id)) total++;
  }
  return { direct, total };
}

function getEffectiveCategoryPrice(
  categoryId: string | null,
  allCats: Category[]
): { normal: string | null; wholesale: string | null } {
  let currId = categoryId;
  let normal: string | null = null;
  let wholesale: string | null = null;
  const visited = new Set<string>();

  while (currId && !visited.has(currId)) {
    visited.add(currId);
    const cat = allCats.find((c) => c.id === currId);
    if (!cat) break;
    if (!normal && cat.default_normal_price) {
      normal = cat.default_normal_price;
    }
    if (!wholesale && cat.default_wholesale_price) {
      wholesale = cat.default_wholesale_price;
    }
    if (normal && wholesale) break;
    currId = cat.parent_id;
  }
  return { normal, wholesale };
}

function findBestPricesForLine(
  line: CustomerListLine,
  allProducts: Product[],
  allCats: Category[]
): { normal: string | null; wholesale: string | null; source: string | null } {
  if (line.product_id) {
    const prod = allProducts.find((p) => p.id === line.product_id);
    if (prod) {
      const normal = prod.effective_normal_price || prod.selling_price || null;
      const wholesale = prod.effective_wholesale_price || null;
      if (normal || wholesale) {
        return { normal, wholesale, source: prod.name };
      }
      if (prod.category_id) {
        const catPrices = getEffectiveCategoryPrice(prod.category_id, allCats);
        if (catPrices.normal || catPrices.wholesale) {
          return { normal: catPrices.normal, wholesale: catPrices.wholesale, source: "Category" };
        }
      }
    }
  }

  const nameToMatch = (line.product_name || line.free_text || "").toLowerCase().trim();
  if (nameToMatch) {
    const matched = allProducts.find(
      (p) => p.name.toLowerCase() === nameToMatch || nameToMatch.includes(p.name.toLowerCase())
    );
    if (matched) {
      const normal = matched.effective_normal_price || matched.selling_price || null;
      const wholesale = matched.effective_wholesale_price || null;
      if (normal || wholesale) {
        return { normal, wholesale, source: matched.name };
      }
      if (matched.category_id) {
        const catPrices = getEffectiveCategoryPrice(matched.category_id, allCats);
        if (catPrices.normal || catPrices.wholesale) {
          return { normal: catPrices.normal, wholesale: catPrices.wholesale, source: "Category" };
        }
      }
    }

    for (const cat of allCats) {
      if (nameToMatch.includes(cat.name.toLowerCase()) || (cat.slug && nameToMatch.includes(cat.slug.toLowerCase()))) {
        const catPrices = getEffectiveCategoryPrice(cat.id, allCats);
        if (catPrices.normal || catPrices.wholesale) {
          return { normal: catPrices.normal, wholesale: catPrices.wholesale, source: cat.name };
        }
      }
    }
  }

  return { normal: null, wholesale: null, source: null };
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
  const [businesses, setBusinesses] = useState<TenantSummary[] | null>(() => {
    try {
      const b = getCachedBusinesses();
      return b.length > 0 ? b : null;
    } catch {
      return null;
    }
  });
  const [activeBusiness, setActiveBusiness] = useState<TenantSummary | null>(() => {
    try {
      const lastActiveId = getAppSetting("last_active_tenant_id");
      const b = getCachedBusinesses();
      if (b.length > 0) {
        return (lastActiveId ? b.find((x) => x.id === lastActiveId) : null) ?? b[0];
      }
      return null;
    } catch {
      return null;
    }
  });
  const [businessDetails, setBusinessDetails] = useState<TenantDetails | null>(() => {
    try {
      const lastActiveId = getAppSetting("last_active_tenant_id");
      const b = getCachedBusinesses();
      const target = (lastActiveId ? b.find((x) => x.id === lastActiveId) : null) ?? b[0];
      return target ? getCachedBusinessDetails(target.id) : null;
    } catch {
      return null;
    }
  });
  const [profile, setProfile] = useState<UserProfile | null>(() => {
    try {
      return getCachedProfile();
    } catch {
      return null;
    }
  });

  // Data states
  const [products, setProducts] = useState<Product[]>(() => {
    try {
      const lastActiveId = getAppSetting("last_active_tenant_id");
      const b = getCachedBusinesses();
      const target = (lastActiveId ? b.find((x) => x.id === lastActiveId) : null) ?? b[0];
      return target ? getCachedProducts(target.id) : [];
    } catch {
      return [];
    }
  });
  const [categories, setCategories] = useState<Category[]>(() => {
    try {
      const lastActiveId = getAppSetting("last_active_tenant_id");
      const b = getCachedBusinesses();
      const target = (lastActiveId ? b.find((x) => x.id === lastActiveId) : null) ?? b[0];
      return target ? getCachedCategories(target.id) : [];
    } catch {
      return [];
    }
  });
  const [customerLists, setCustomerLists] = useState<CustomerList[]>(() => {
    try {
      const lastActiveId = getAppSetting("last_active_tenant_id");
      const b = getCachedBusinesses();
      const target = (lastActiveId ? b.find((x) => x.id === lastActiveId) : null) ?? b[0];
      return target ? getCachedCustomerLists(target.id) : [];
    } catch {
      return [];
    }
  });
  const [sales, setSales] = useState<SaleSummary[]>(() => {
    try {
      const lastActiveId = getAppSetting("last_active_tenant_id");
      const b = getCachedBusinesses();
      const target = (lastActiveId ? b.find((x) => x.id === lastActiveId) : null) ?? b[0];
      return target ? getCachedSales(target.id) : [];
    } catch {
      return [];
    }
  });
  const [dailyStats, setDailyStats] = useState<DailySalesSummary | null>(() => {
    try {
      const lastActiveId = getAppSetting("last_active_tenant_id");
      const b = getCachedBusinesses();
      const target = (lastActiveId ? b.find((x) => x.id === lastActiveId) : null) ?? b[0];
      return target ? getCachedDailyStats(target.id) : null;
    } catch {
      return null;
    }
  });
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>(DEFAULT_EXPENSE_CATEGORIES);
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<MembershipInvitation[]>([]);
  const [runningOut, setRunningOut] = useState<LowStockProduct[]>([]);

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
  // Image & Logo States
  const [newProductImage, setNewProductImage] = useState("");
  const [editProductImage, setEditProductImage] = useState("");
  const [newCategoryIcon, setNewCategoryIcon] = useState("");
  const [editCategoryIcon, setEditCategoryIcon] = useState("");
  const [newPhotoUrl, setNewPhotoUrl] = useState("");
  const [attachingPhoto, setAttachingPhoto] = useState(false);
  const [editBizLogo, setEditBizLogo] = useState("");
  const [editAvatarUrl, setEditAvatarUrl] = useState("");

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
  const [applyPriceToAll, setApplyPriceToAll] = useState(false);
  const [savingPrice, setSavingPrice] = useState(false);
  const [autoPricingListId, setAutoPricingListId] = useState<string | null>(null);

  const pricingLineCategoryName = useMemo(() => {
    if (!pricingLine) return null;
    const targetList = customerLists.find((l) => l.id === pricingLine.listId);
    const line = targetList?.lines.find((ln) => ln.id === pricingLine.lineId);
    if (!line) return null;
    if (line.group_name && line.group_name.trim()) {
      return line.group_name.trim();
    }
    if (line.product_id) {
      const prod = products.find((p) => p.id === line.product_id);
      if (prod?.category_id) {
        const cat = categories.find((c) => c.id === prod.category_id);
        if (cat) return cat.name;
      }
    }
    return null;
  }, [pricingLine, customerLists, products, categories]);

  // Official Invoice modal state
  const [invoiceModalList, setInvoiceModalList] = useState<CustomerList | null>(null);
  const [exportingPdf, setExportingPdf] = useState(false);

  // Dispatch Waybill modal state
  const [dispatchModalList, setDispatchModalList] = useState<CustomerList | null>(null);
  const [transporterName, setTransporterName] = useState("");
  const [transporterPhone, setTransporterPhone] = useState("");
  const [waybillNumber, setWaybillNumber] = useState("");
  const [dispatchCost, setDispatchCost] = useState("");
  const [trackingUrl, setTrackingUrl] = useState("");
  const [savingDispatch, setSavingDispatch] = useState(false);

  const [pinConfirmList, setPinConfirmList] = useState<CustomerList | null>(null);
  const [pinValue, setPinValue] = useState("");
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [savingConfirm, setSavingConfirm] = useState(false);

  // Quick-Paste Customer Order Modal
  const [showQuickPasteModal, setShowQuickPasteModal] = useState(false);
  const [quickPastePhone, setQuickPastePhone] = useState("");
  const [quickPasteName, setQuickPasteName] = useState("");
  const [quickPasteText, setQuickPasteText] = useState("");
  const [savingQuickPaste, setSavingQuickPaste] = useState(false);

  // Collapsible list cards
  const [expandedListIds, setExpandedListIds] = useState<Set<string>>(() => new Set());

  // Customer List Part Payment / Advance Payment modal state
  const [paymentModalList, setPaymentModalList] = useState<CustomerList | null>(null);
  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("transfer");
  const [paymentNote, setPaymentNote] = useState("");
  const [savingPayment, setSavingPayment] = useState(false);

  // Stall Security PIN Setup states (with PinPad)
  const [pinSetupStep, setPinSetupStep] = useState<1 | 2>(1);
  const [pinSetupFirst, setPinSetupFirst] = useState("");
  const [pinSetupError, setPinSetupError] = useState<string | null>(null);

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
  const [expenseCategoryId, setExpenseCategoryId] = useState<string>("STOCK_PURCHASE");
  const [expensePaymentMethod, setExpensePaymentMethod] = useState("cash");
  const [expenseError, setExpenseError] = useState<string | null>(null);
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
  const [securityTab, setSecurityTab] = useState<"password" | "pin">("password");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [hasPin, setHasPin] = useState(false);
  const [businessPinInput, setBusinessPinInput] = useState("");
  const [businessPinConfirm, setBusinessPinConfirm] = useState("");
  const [savingPin, setSavingPin] = useState(false);

  const [showShopModal, setShowShopModal] = useState(false);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showSignOutModal, setShowSignOutModal] = useState(false);
  const [activeSubView, setActiveSubView] = useState<"team" | null>(null);
  const [unreadCount, setUnreadCount] = useState<number>(0);

  const [themeMode, setThemeMode] = useState<ThemeMode>("light");
  const theme = useMemo(() => getTheme(themeMode), [themeMode]);
  const styles = useMemo(() => createStyles(theme), [theme]);

  useEffect(() => {
    void getSavedThemeMode().then((mode) => setThemeMode(mode));
  }, []);

  const handleToggleTheme = (mode: ThemeMode) => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setThemeMode(mode);
    void saveThemeMode(mode);
    showToast(mode === "light" ? "Switched to Light Ivory Theme" : "Switched to Dark Theme");
  };

  const userRole = (activeBusiness?.role_name ?? "OWNER").toUpperCase();
  const isOwner = userRole === "OWNER";
  const isOwnerOrManager = userRole === "OWNER" || userRole === "MANAGER";
  const isInventoryStaff = userRole === "INVENTORY";

  const [editFirstName, setEditFirstName] = useState("");
  const [editLastName, setEditLastName] = useState("");
  const [editPhone, setEditPhone] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);

  const showToast = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(null), 3200);
  };

  useAppLifecycle({
    onResume: () => {
      if (activeBusiness) {
        setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
        void flushSyncOutbox(activeBusiness.id).then((res) => {
          if (res.sales > 0 || res.mutations > 0) {
            void loadData(activeBusiness.id);
          }
          setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
        });
        void fetchUnreadCount(activeBusiness.id).then((count) => {
          setUnreadCount(count);
        });
      }
    },
  });

  const loadData = useCallback(async (tenantId: string) => {
    // 1. Immediately hydrate all available data from SQLite so nothing is a placeholder
    const cached = getCachedProducts(tenantId);
    const cachedCats = getCachedCategories(tenantId);
    const cachedLists = getCachedCustomerLists(tenantId);
    const cachedSales = getCachedSales(tenantId);
    const cachedStats = getCachedDailyStats(tenantId);
    const cachedDetails = getCachedBusinessDetails(tenantId);

    setProducts(cached);
    setCategories(cachedCats);
    setCustomerLists(cachedLists);
    setSales(cachedSales);
    if (cachedStats) {
      setDailyStats(cachedStats);
    }
    if (cachedDetails) {
      setBusinessDetails(cachedDetails);
    }
    setLoading(false);

    const pending = getPendingOutboxCount(tenantId);
    setPendingSyncCount(pending);
    void hasBusinessPin(tenantId).then((has) => setHasPin(has));
    void fetchUnreadCount(tenantId).then((count) => setUnreadCount(count));

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
        freshLowStock,
      ] = await Promise.all([
        listProducts(tenantId).catch(() => cached),
        listCustomerLists(tenantId).catch(() => cachedLists),
        listCategories(tenantId).catch(() => cachedCats),
        listSales(tenantId).catch(() => cachedSales),
        dailySales(tenantId).catch(() => cachedStats),
        listExpenseCategories(tenantId).catch(() => ({ categories: [] })),
        listMembers(tenantId).catch(() => []),
        listInvitations(tenantId).catch(() => []),
        listMyInvitations().catch(() => []),
        getBusiness(tenantId).catch(() => cachedDetails),
        currentUser().catch(() => null),
        getStorefront(tenantId).catch(() => null),
        lowStock(tenantId).catch(() => []),
      ]);

      if (freshProducts.length > 0 || cached.length === 0) {
        setProducts(freshProducts);
        cacheProducts(tenantId, freshProducts);
      }
      if (freshLists.length > 0 || cachedLists.length === 0) {
        setCustomerLists(freshLists);
        cacheCustomerLists(tenantId, freshLists);
      }
      if (freshCategories.length > 0 || cachedCats.length === 0) {
        setCategories(freshCategories);
        cacheCategories(tenantId, freshCategories);
      }
      if (freshSales.length > 0 || cachedSales.length === 0) {
        setSales(freshSales);
        cacheSales(tenantId, freshSales);
      }
      if (freshDaily) {
        setDailyStats(freshDaily);
        cacheDailyStats(tenantId, freshDaily);
      }
      if (bDetails) {
        setBusinessDetails(bDetails);
        cacheBusinessDetails(tenantId, bDetails);
      }
      if (uProfile) {
        setProfile(uProfile);
        cacheProfile(uProfile);
      }

      setRunningOut(freshLowStock);
      const loadedExpCats = freshExpCats?.categories?.length ? freshExpCats.categories : DEFAULT_EXPENSE_CATEGORIES;
      setExpenseCategories(loadedExpCats);
      if (loadedExpCats.length > 0 && !expenseCategoryId) {
        setExpenseCategoryId(loadedExpCats[0].value || loadedExpCats[0].id || "STOCK_PURCHASE");
      }
      setMembers(freshMembers);
      setInvitations(freshInvs);
      setMyInvitations(myInvs);
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
  }, []);

  useEffect(() => {
    // 1. Immediately hydrate from local SQLite so the UI is NEVER blank or placeholder
    const lastActiveId = getAppSetting("last_active_tenant_id");
    const cachedBiz = getCachedBusinesses();
    const cachedProf = getCachedProfile();
    if (cachedProf) {
      setProfile(cachedProf);
    }

    if (cachedBiz.length > 0) {
      setBusinesses(cachedBiz);
      const initial = (lastActiveId ? cachedBiz.find((b) => b.id === lastActiveId) : null) ?? cachedBiz[0];
      setActiveBusiness(initial);

      const cachedDetails = getCachedBusinessDetails(initial.id);
      if (cachedDetails) {
        setBusinessDetails(cachedDetails);
      }
      const cachedStats = getCachedDailyStats(initial.id);
      if (cachedStats) {
        setDailyStats(cachedStats);
      }

      void loadData(initial.id);
    }

    // 2. Refresh from network in background (if online)
    void (async () => {
      try {
        const [found, freshProfile] = await Promise.all([
          listBusinesses().catch(() => null),
          currentUser().catch(() => null),
        ]);

        if (freshProfile) {
          setProfile(freshProfile);
          cacheProfile(freshProfile);
        }

        if (found && found.length > 0) {
          setBusinesses(found);
          cacheBusinesses(found);
          const currentId = activeBusiness?.id ?? lastActiveId ?? cachedBiz[0]?.id;
          const initial = found.find((b) => b.id === currentId) ?? found[0];
          setActiveBusiness(initial);
          setAppSetting("last_active_tenant_id", initial.id);
          await loadData(initial.id);
        } else {
          setLoading(false);
        }
      } catch (error) {
        if (cachedBiz.length === 0) {
          setProblem(error instanceof ApiError ? error.message : "We could not load your shops.");
        }
        setLoading(false);
      }
    })();
  }, [loadData]);

  // Periodic background auto-sync every 15 seconds
  useEffect(() => {
    if (!activeBusiness) return;
    const interval = setInterval(() => {
      void (async () => {
        try {
          const pending = getPendingOutboxCount(activeBusiness.id);
          if (pending > 0) {
            const res = await flushSyncOutbox(activeBusiness.id);
            if (res.sales > 0 || res.mutations > 0) {
              setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
              const freshP = getCachedProducts(activeBusiness.id);
              const freshC = getCachedCategories(activeBusiness.id);
              setProducts(freshP);
              setCategories(freshC);
            }
          }
        } catch {
          // Offline, non-fatal background poll
        }
      })();
    }, 15000);

    return () => clearInterval(interval);
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
      const res = await flushSyncOutbox(activeBusiness.id);
      const remaining = getPendingOutboxCount(activeBusiness.id);
      setPendingSyncCount(remaining);
      await loadData(activeBusiness.id);
      if (res.sales > 0 || res.mutations > 0) {
        showToast(`Synced ${res.sales} sales & ${res.mutations} updates!`);
      } else if (remaining === 0) {
        showToast("Everything is up to date.");
      } else {
        showToast("Saved safely on device. Will sync once connected.");
      }
    } catch {
      showToast("Saved safely on device. Will sync once connected.");
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
      setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
      showToast(`Saved offline: 1 ${product.name}`);
    }
  };

  const handleCreateProduct = async () => {
    if (!activeBusiness || !newName.trim()) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingProduct(true);
    try {
      const inheritedPrices = getEffectiveCategoryPrice(currentCategoryId, categories);
      const finalSellingPrice = newPrice.trim() || inheritedPrices.normal || null;
      const finalWholesalePrice = newWholesale.trim() || inheritedPrices.wholesale || null;

      const created = createLocalProduct(activeBusiness.id, {
        name: newName.trim(),
        selling_price: finalSellingPrice,
        wholesale_price: finalWholesalePrice,
        category_id: currentCategoryId,
        image_url: newProductImage.trim() || null,
      });
      setProducts((curr) => [...curr, created]);
      setNewName("");
      setNewPrice("");
      setNewWholesale("");
      setNewProductImage("");
      setShowAddProductModal(false);
      showToast(`Added ${created.name} to shelf!`);
      setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
      void flushSyncOutbox(activeBusiness.id).then(() => {
        setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
      });
    } catch {
      showToast("Could not save item.");
    } finally {
      setSavingProduct(false);
    }
  };

  const handleCreateCategory = async () => {
    if (!activeBusiness || !newCategoryName.trim()) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingCategory(true);
    try {
      const created = createLocalCategory(activeBusiness.id, {
        name: newCategoryName.trim(),
        parent_id: currentCategoryId,
        default_normal_price: newCategoryNormalPrice.trim() || undefined,
        default_wholesale_price: newCategoryWholesalePrice.trim() || undefined,
        image_url: newCategoryIcon.trim() || null,
      });
      setCategories((curr) => [...curr, created]);
      setNewCategoryName("");
      setNewCategoryNormalPrice("");
      setNewCategoryWholesalePrice("");
      setNewCategoryIcon("");
      setShowAddCategoryModal(false);
      showToast(`Created category: ${created.name}`);
      setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
      void flushSyncOutbox(activeBusiness.id).then(() => {
        setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
      });
    } catch {
      showToast("Could not create category.");
    } finally {
      setSavingCategory(false);
    }
  };

  const handleSaveCategoryEdit = async () => {
    if (!activeBusiness || !editingCategory) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingEditCategory(true);
    try {
      updateLocalCategory(activeBusiness.id, editingCategory.id, {
        name: editCategoryName.trim() || undefined,
        default_normal_price: editCategoryNormalPrice.trim() || null,
        default_wholesale_price: editCategoryWholesalePrice.trim() || null,
        image_url: editCategoryIcon.trim() || null,
      });
      setCategories((curr) =>
        curr.map((c) =>
          c.id === editingCategory.id
            ? {
                ...c,
                name: editCategoryName.trim() || c.name,
                default_normal_price: editCategoryNormalPrice.trim() || c.default_normal_price,
                default_wholesale_price: editCategoryWholesalePrice.trim() || c.default_wholesale_price,
                image_url: editCategoryIcon.trim() || c.image_url,
              }
            : c,
        ),
      );
      setEditingCategory(null);
      setEditCategoryIcon("");
      showToast(`Updated category ${editCategoryName.trim() || editingCategory.name}`);
      setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
      void flushSyncOutbox(activeBusiness.id).then(() => {
        setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
      });
    } catch {
      showToast("Could not update category.");
    } finally {
      setSavingEditCategory(false);
    }
  };

  const handleDeleteCategory = (category: Category) => {
    if (!activeBusiness) return;
    Alert.alert(
      "Delete Category?",
      `Are you sure you want to delete ${category.name}? Items inside will move up to parent category.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            deleteLocalCategory(activeBusiness.id, category.id);
            setCategories((curr) => curr.filter((c) => c.id !== category.id));
    if (activeBusiness) void flushSyncOutbox(activeBusiness.id).catch(() => {});
            if (currentCategoryId === category.id) {
              setCurrentCategoryId(category.parent_id ?? null);
            }
            showToast(`Deleted ${category.name}`);
            setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
            void flushSyncOutbox(activeBusiness.id).then(() => {
              setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
            });
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
          onPress: () => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            deleteLocalProduct(activeBusiness.id, product.id);
            setProducts((curr) => curr.filter((p) => p.id !== product.id));
            showToast(`Deleted ${product.name}`);
            setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
            void flushSyncOutbox(activeBusiness.id).then(() => {
              setPendingSyncCount(getPendingOutboxCount(activeBusiness.id));
            });
          },
        },
      ],
    );
  };

  const handleSaveBusinessPin = async () => {
    if (!activeBusiness || !isOwner) return;
    if (businessPinInput.trim().length < 4) {
      showToast("Security PIN must be at least 4 digits.");
      return;
    }
    if (businessPinInput !== businessPinConfirm) {
      showToast("PINs do not match.");
      return;
    }
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingPin(true);
    try {
      await setBusinessPin(activeBusiness.id, businessPinInput.trim());
      setHasPin(true);
      setBusinessPinInput("");
      setBusinessPinConfirm("");
      showToast("Stall Security PIN set successfully!");
      setShowPasswordModal(false);
    } catch {
      showToast("Could not save Security PIN.");
    } finally {
      setSavingPin(false);
    }
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

  const handleBatchPublish = async (shouldPublish: boolean) => {
    if (!activeBusiness || selectedProductIds.size === 0) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingBatch(true);
    try {
      const ids = Array.from(selectedProductIds);
      for (const id of ids) {
        if (shouldPublish) {
          await publishProduct(activeBusiness.id, id);
        } else {
          await unpublishProduct(activeBusiness.id, id);
        }
      }
      const refreshed = await listProducts(activeBusiness.id);
      setProducts(refreshed);
      cacheProducts(activeBusiness.id, refreshed);
      setSelectedProductIds(new Set());
      showToast(`${shouldPublish ? "Published" : "Unpublished"} ${ids.length} item(s).`);
    } catch {
      showToast("Could not update batch visibility.");
    } finally {
      setSavingBatch(false);
    }
  };

  const handleToggleProductPublish = async (product: Product) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      const updated = product.is_published
        ? await unpublishProduct(activeBusiness.id, product.id)
        : await publishProduct(activeBusiness.id, product.id);
      setProducts((current) => current.map((p) => (p.id === updated.id ? updated : p)));
      cacheProducts(
        activeBusiness.id,
        products.map((p) => (p.id === updated.id ? updated : p)),
      );
      showToast(
        updated.is_published
          ? `"${product.name}" is now live in your shop.`
          : `"${product.name}" is now hidden from shop.`,
      );
    } catch {
      showToast("Could not update item visibility.");
    }
  };

  const handleShareProduct = async (product: Product) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const priceStr = formatMoney(product.effective_normal_price ?? product.selling_price);
    try {
      const sheet = await productShareSheet(activeBusiness.id, product.id);
      const shareUrl = sheet.public_url || sheet.whatsapp_url;
      const message = `Check out ${product.name} at ${activeBusiness.name}: ${priceStr}${shareUrl ? `\n${shareUrl}` : ""}`;
      await Share.share({
        title: product.name,
        message,
        url: sheet.public_url || undefined,
      });
    } catch {
      const message = `${product.name} at ${activeBusiness.name}: ${priceStr}`;
      await Share.share({ message });
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
        image_url: editProductImage.trim() || null,
      });
      const prodWithImg: Product = {
        ...updated,
        image_url: editProductImage.trim() || updated.image_url || null,
      };
      setProducts((curr) => curr.map((p) => (p.id === updated.id ? prodWithImg : p)));
      cacheProducts(
        activeBusiness.id,
        products.map((p) => (p.id === updated.id ? prodWithImg : p)),
      );
      setEditingProduct(null);
      setEditProductImage("");
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

  const handlePickDeviceImage = async (onSelected: (uri: string) => void) => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      const permissionResult = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permissionResult.granted) {
        showToast("Photo library access is needed to select images.");
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        allowsEditing: true,
        aspect: [1, 1],
        quality: 0.8,
      });
      if (!result.canceled && result.assets[0]?.uri) {
        onSelected(result.assets[0].uri);
        showToast("Photo selected from device.");
      }
    } catch {
      showToast("Could not open photo library.");
    }
  };

  const handleAttachPhoto = async () => {
    if (!activeBusiness || !galleryProduct || !newPhotoUrl.trim()) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setAttachingPhoto(true);
    try {
      const img = await attachProductImageUrl(activeBusiness.id, galleryProduct.id, newPhotoUrl.trim());
      setGalleryImages((curr) => [...curr, img]);
      setProducts((curr) =>
        curr.map((p) => (p.id === galleryProduct.id ? { ...p, image_url: newPhotoUrl.trim() } : p))
      );
      cacheProducts(
        activeBusiness.id,
        products.map((p) => (p.id === galleryProduct.id ? { ...p, image_url: newPhotoUrl.trim() } : p))
      );
      setNewPhotoUrl("");
      showToast("Photo attached to product!");
    } catch {
      showToast("Could not attach photo.");
    } finally {
      setAttachingPhoto(false);
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
    if (!activeBusiness) return;
    const cleanAmount = expenseAmount.trim().replace(/,/g, "");
    if (!cleanAmount || isNaN(Number(cleanAmount)) || Number(cleanAmount) <= 0) {
      setExpenseError("Please enter a valid expense amount in Naira.");
      return;
    }
    const targetCat = (expenseCategoryId || (expenseCategories[0]?.value ?? expenseCategories[0]?.id ?? "OTHER")).toUpperCase();
    setExpenseError(null);
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingExpense(true);
    try {
      await recordExpense(activeBusiness.id, {
        amount: cleanAmount,
        category: targetCat,
        description: expenseDescription.trim() || null,
        payment_method: (expensePaymentMethod || "CASH").toUpperCase(),
      });
      setExpenseAmount("");
      setExpenseDescription("");
      setShowExpenseModal(false);
      showToast("Expense logged successfully!");
      void loadData(activeBusiness.id);
    } catch (err: any) {
      setExpenseError(err?.message || "Could not record expense. Please verify amount and category.");
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
      const msg = `Hello, you have been invited to join ${activeBusiness.name} on AHIA as ${inviteRole}. Open https://useahia-hazel.vercel.app to accept.`;
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

  const handleShareReceiptText = async (item: CustomerList) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      const cleanPhone = formatWaNumber(item.customer_phone);
      const dateStr = new Date(item.created_at).toLocaleDateString([], {
        month: "short",
        day: "numeric",
        year: "numeric",
      });

      let runningSubtotal = 0;
      let linesText = "";
      item.lines.forEach((l, idx) => {
        const name = l.product_name || l.free_text || "Item";
        const qty = Number(l.quantity) || 1;
        const unit = Number(l.shop_price ?? "0");
        const hasPrice = Boolean(l.shop_price && Number.isFinite(unit));
        if (hasPrice) {
          runningSubtotal += unit * qty;
        }
        const priceStr = hasPrice
          ? `${formatMoney(l.shop_price)} (Total: ${formatMoney((unit * qty).toString())})`
          : "(Awaiting price)";
        linesText += `${idx + 1}. ${qty}x ${name} - ${priceStr}\n`;
      });

      const dispatchCostNum = Number(item.dispatch_cost ?? "0");
      const computedTotal = runningSubtotal + dispatchCostNum;
      const totalDisplay = item.priced_total
        ? formatMoney(item.priced_total)
        : runningSubtotal > 0
        ? `${formatMoney(computedTotal.toString())} (Partial)`
        : "Pending pricing";

      const waybillInfo = item.waybill_number
        ? `\nWAYBILL DETAILS:\nTransporter: ${item.transporter_name || "Courier"}\nWaybill #: ${item.waybill_number}${item.dispatch_cost ? `\nDispatch Cost: ${formatMoney(item.dispatch_cost)}` : ""}${item.tracking_url ? `\nTracking URL: ${item.tracking_url}` : ""}\n`
        : "";

      const receipt = `==============================\nOFFICIAL INVOICE\n${activeBusiness.name.toUpperCase()}\nDate: ${dateStr}\nCustomer: ${item.customer_name || item.customer_phone || "Customer"}\nPhone: ${item.customer_phone || "N/A"}\nStatus: ${item.status.toUpperCase()}\n==============================\nITEMS:\n${linesText}==============================${waybillInfo}TOTAL: ${totalDisplay}\n\nThank you for doing business with us!\n==============================`;

      const waUrl = cleanPhone
        ? `https://wa.me/${cleanPhone}?text=${encodeURIComponent(receipt)}`
        : `https://wa.me/?text=${encodeURIComponent(receipt)}`;

      const canOpen = await Linking.canOpenURL(waUrl);
      if (canOpen) {
        await Linking.openURL(waUrl);
      } else {
        await Share.share({ message: receipt });
      }
    } catch {
      showToast("Could not share invoice.");
    }
  };

  const handleExportPdfInvoice = async (item: CustomerList) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setExportingPdf(true);
    showToast("Generating official business invoice PDF...");
    try {
      await generateAndSharePdfInvoice(activeBusiness, businessDetails, item);
      showToast("Invoice PDF generated and shared!");
    } catch (err: any) {
      showToast(err?.message || "Could not export PDF.");
    } finally {
      setExportingPdf(false);
    }
  };

  const handlePrintPdfInvoice = async (item: CustomerList) => {
    if (!activeBusiness) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await printInvoice(activeBusiness, businessDetails, item);
    } catch (err: any) {
      showToast(err?.message || "Could not open print/save dialog.");
    }
  };

  const handleRecordPayment = async () => {
    if (!activeBusiness || !paymentModalList) return;
    const amt = Number(paymentAmount.trim());
    if (!Number.isFinite(amt) || amt <= 0) {
      showToast("Please enter a valid payment amount.");
      return;
    }
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingPayment(true);
    try {
      const paymentRecord: ListPayment = {
        id: `pay-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        amount: amt.toString(),
        date: new Date().toISOString(),
        note: paymentNote.trim() || "Order Payment",
        payment_method: paymentMethod,
      };

      const existingPayments = paymentModalList.payments ?? [];
      const updatedPayments = [...existingPayments, paymentRecord];
      const newTotalPaid = updatedPayments.reduce(
        (sum, p) => sum + (Number(p.amount) || 0),
        0
      );

      const updatedList: CustomerList = {
        ...paymentModalList,
        payments: updatedPayments,
        amount_paid: newTotalPaid.toString(),
      };

      setCustomerLists((curr) => curr.map((l) => (l.id === updatedList.id ? updatedList : l)));
      updateCachedCustomerList(activeBusiness.id, updatedList);

      const customerName = paymentModalList.customer_name || paymentModalList.customer_phone;
      const paymentSale: SaleSummary = {
        id: `sale-${paymentRecord.id}`,
        receipt_number: `PAY-${Date.now().toString().slice(-6)}`,
        created_at: paymentRecord.date,
        total_amount: amt.toFixed(2),
        payment_method: paymentMethod,
        payment_status: "paid",
      };

      setSales((prev) => [paymentSale, ...prev]);
      cacheSales(activeBusiness.id, [paymentSale, ...sales]);

      setDailyStats((prev) => {
        const todayStr = new Date().toISOString().slice(0, 10);
        if (!prev) {
          return {
            date: todayStr,
            total_revenue: amt.toFixed(2),
            total_sales: 1,
          };
        }
        const updatedTotal = (Number(prev.total_revenue || "0") + amt).toFixed(2);
        return {
          ...prev,
          total_revenue: updatedTotal,
          total_sales: prev.total_sales + 1,
        };
      });

      showToast(`Recorded payment of ${formatMoney(amt.toString())}!`);
      setPaymentModalList(null);
      setPaymentAmount("");
      setPaymentNote("");
    } catch {
      showToast("Could not record payment.");
    } finally {
      setSavingPayment(false);
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
        logo_url: editBizLogo.trim() || undefined,
      });
      setBusinessDetails(updated);
      if (editBizLogo.trim()) {
        updateCachedBusiness(activeBusiness.id, {
          name: editBizName.trim() || undefined,
          logo_url: editBizLogo.trim(),
        });
        setActiveBusiness((curr) => (curr ? { ...curr, logo_url: editBizLogo.trim() } : curr));
      }
      setShowBusinessModal(false);
      showToast("Business profile updated!");
    } catch {
      showToast("Could not update business details.");
    } finally {
      setSavingBusiness(false);
    }
  };

  const handleUpdateProfile = async () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSavingProfile(true);
    try {
      const updated = await updateProfile({
        first_name: editFirstName.trim(),
        last_name: editLastName.trim() || undefined,
        phone: editPhone.trim() || undefined,
        email: editEmail.trim() || undefined,
        avatar_url: editAvatarUrl.trim() || undefined,
      });
      setProfile(updated);
      setShowProfileModal(false);
      showToast("Profile updated successfully!");
    } catch {
      showToast("Could not update profile.");
    } finally {
      setSavingProfile(false);
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

    const handleShareInviteWhatsApp = async (inv: MembershipInvitation) => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const shopName = activeBusiness?.name ?? "our stall";
    const inviteMsg = `Hello! You have been invited to join ${shopName} on AHIA as a ${inv.role}. Download AHIA or sign in at https://useahia-hazel.vercel.app to accept!`;
    const targetPhone = inv.phone ? formatWaNumber(inv.phone) : null;
    const waUrl = targetPhone
      ? `whatsapp://send?phone=${targetPhone}&text=${encodeURIComponent(inviteMsg)}`
      : `whatsapp://send?text=${encodeURIComponent(inviteMsg)}`;

    try {
      const supported = await Linking.canOpenURL(waUrl);
      if (supported) {
        await Linking.openURL(waUrl);
      } else {
        await Share.share({ message: inviteMsg });
      }
    } catch {
      await Share.share({ message: inviteMsg });
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
      const cleanShopPrice = priceInput.trim() || null;
      const cleanCostPrice = costInput.trim() || null;

      let updatedList = await workListLine(activeBusiness.id, pricingLine.listId, pricingLine.lineId, {
        shop_price: cleanShopPrice,
        cost_price: cleanCostPrice,
      });

      if (applyPriceToAll && cleanShopPrice) {
        const targetList = customerLists.find((l) => l.id === pricingLine.listId);
        if (targetList) {
          const currentLine = targetList.lines.find((l) => l.id === pricingLine.lineId);
          const currentGroup = currentLine?.group_name?.trim();
          let currentCatId: string | null = null;
          if (currentLine?.product_id) {
            currentCatId = products.find((p) => p.id === currentLine.product_id)?.category_id ?? null;
          }

          const otherUnpriced = targetList.lines.filter((l) => {
            if (l.id === pricingLine.lineId || l.shop_price || l.note === "heading") {
              return false;
            }
            if (currentGroup && l.group_name && l.group_name.trim() === currentGroup) {
              return true;
            }
            if (currentCatId && l.product_id) {
              const otherProdCat = products.find((p) => p.id === l.product_id)?.category_id ?? null;
              if (otherProdCat === currentCatId) return true;
            }
            if (!currentGroup && !currentCatId) {
              const otherProdCat = l.product_id ? products.find((p) => p.id === l.product_id)?.category_id : null;
              return !l.group_name && !otherProdCat;
            }
            return false;
          });

          for (const otherLine of otherUnpriced) {
            try {
              updatedList = await workListLine(activeBusiness.id, pricingLine.listId, otherLine.id, {
                shop_price: cleanShopPrice,
                cost_price: cleanCostPrice,
              });
            } catch {
              // skip single line error
            }
          }
        }
      }

      setCustomerLists((curr) => curr.map((l) => (l.id === updatedList.id ? updatedList : l)));
      setPricingLine(null);
      setPriceInput("");
      setCostInput("");
      setApplyPriceToAll(false);
      showToast(
        applyPriceToAll
          ? `Applied prices to other unpriced items in ${pricingLineCategoryName ?? "category"}!`
          : "Line prices & cost updated!"
      );
    } catch {
      showToast("Could not update price.");
    } finally {
      setSavingPrice(false);
    }
  };

  const handleAutoPriceList = async (list: CustomerList) => {
    if (!activeBusiness) return;
    const unpriced = list.lines.filter((l) => !l.shop_price && l.note !== "heading");
    if (unpriced.length === 0) {
      showToast("All items in this list already have prices!");
      return;
    }

    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setAutoPricingListId(list.id);
    try {
      let updated = list;
      let pricedCount = 0;

      for (const line of unpriced) {
        const matched = findBestPricesForLine(line, products, categories);
        if (matched.normal || matched.wholesale) {
          try {
            updated = await workListLine(activeBusiness.id, list.id, line.id, {
              shop_price: matched.normal,
              cost_price: matched.wholesale,
            });
            pricedCount++;
          } catch {
            // skip on single line error
          }
        }
      }

      if (pricedCount > 0) {
        setCustomerLists((curr) => curr.map((l) => (l.id === updated.id ? updated : l)));
        showToast(`Auto-priced ${pricedCount} item(s) from catalogue & categories!`);
      } else {
        showToast("No catalogue matches found. Tap edit on any item to set prices.");
      }
    } catch {
      showToast("Could not auto-price list.");
    } finally {
      setAutoPricingListId(null);
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

    // Optimistic UI update instantly!
    setCustomerLists((current) =>
      current.map((l) =>
        l.id === listId
          ? {
              ...l,
              lines: l.lines.map((ln) =>
                ln.id === lineId ? { ...ln, state: nextState } : ln
              ),
            }
          : l
      )
    );

    const label =
      nextState === "have_it"
        ? "Gotten (on shelf)"
        : nextState === "buy_it"
        ? "Buy in market"
        : nextState === "cannot_get"
        ? "Cannot get"
        : "Unchecked";
    showToast(`Status: ${label}`);

    try {
      const updatedList = await workListLine(activeBusiness.id, listId, lineId, { state: nextState });
      setCustomerLists((current) =>
        current.map((l) => (l.id === updatedList.id ? updatedList : l)),
      );
    } catch {
      // Revert if network call failed
      setCustomerLists((current) =>
        current.map((l) =>
          l.id === listId
            ? {
                ...l,
                lines: l.lines.map((ln) =>
                  ln.id === lineId ? { ...ln, state: currentState as any } : ln
                ),
              }
            : l
        )
      );
      showToast("Could not sync line status to cloud.");
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

  const handleExecutePinConfirm = async (providedPin?: string) => {
    if (!activeBusiness || !pinConfirmList) return;
    setSavingConfirm(true);
    setConfirmError(null);

    // Retrieve fresh list reference to prevent stale line checks
    const currentList = customerLists.find((l) => l.id === pinConfirmList.id) || pinConfirmList;

    // Check if any product line is unpriced (excluding headings)
    const unpricedLines = currentList.lines.filter((l) => !l.shop_price && l.note !== "heading");
    if (unpricedLines.length > 0) {
      setSavingConfirm(false);
      const sampleItem = unpricedLines[0].product_name || unpricedLines[0].free_text || "Item";
      setConfirmError(
        `Cannot confirm order: ${unpricedLines.length} item(s) (including "${sampleItem}") are unpriced.`
      );
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      return;
    }

    // Verify PIN if the business has configured one
    if (hasPin) {
      const pinToCheck = providedPin || pinValue;
      if (!pinToCheck || pinToCheck.length < 4) {
        setSavingConfirm(false);
        setConfirmError("Enter your 4-digit security PIN");
        return;
      }
      const isValid = await verifyBusinessPin(activeBusiness.id, pinToCheck);
      if (!isValid) {
        setSavingConfirm(false);
        setConfirmError("Incorrect business security PIN. Please try again.");
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        return;
      }
    }

    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    try {
      const confirmed = await confirmCustomerList(activeBusiness.id, currentList.id);
      setCustomerLists((curr) => curr.map((l) => (l.id === confirmed.id ? confirmed : l)));
      setPinConfirmList(null);
      setPinValue("");
      showToast(`Order from ${confirmed.customer_name || confirmed.customer_phone} confirmed!`);
    } catch (err: any) {
      const msg = err?.message || "Could not confirm order. Make sure all items have prices.";
      setConfirmError(msg);
    } finally {
      setSavingConfirm(false);
    }
  };

  const handlePriceRemainingLinesZeroAndConfirm = async () => {
    if (!activeBusiness || !pinConfirmList) return;
    const currentList = customerLists.find((l) => l.id === pinConfirmList.id) || pinConfirmList;
    const unpricedLines = currentList.lines.filter((l) => !l.shop_price && l.note !== "heading");
    setSavingConfirm(true);
    try {
      let updated = currentList;
      for (const line of unpricedLines) {
        try {
          updated = await workListLine(activeBusiness.id, currentList.id, line.id, {
            shop_price: "0",
            cost_price: "0",
          });
        } catch {
          // ignore single line error
        }
      }
      setCustomerLists((curr) => curr.map((l) => (l.id === updated.id ? updated : l)));
      setPinConfirmList(updated);
      setConfirmError(null);
      const confirmed = await confirmCustomerList(activeBusiness.id, updated.id);
      setCustomerLists((curr) => curr.map((l) => (l.id === confirmed.id ? confirmed : l)));
      setPinConfirmList(null);
      setPinValue("");
      showToast("Order confirmed successfully!");
    } catch (err: any) {
      setConfirmError(err?.message || "Could not confirm order.");
    } finally {
      setSavingConfirm(false);
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
    const storefrontUrl = `https://useahia-hazel.vercel.app/shop/${activeBusiness.slug}`;
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
              {isOwnerOrManager ? (
                <View style={[styles.kpiCard, styles.kpiCardHighlight]}>
                  <Text style={styles.kpiLabel}>Today's Sales</Text>
                  <Text style={styles.kpiValue}>
                    {formatMoney(dailyStats?.total_revenue ?? "0")}
                  </Text>
                  <Text style={styles.kpiMeta}>{dailyStats?.total_sales ?? 0} transaction(s)</Text>
                </View>
              ) : (
                <View style={[styles.kpiCard, styles.kpiCardHighlight]}>
                  <Text style={styles.kpiLabel}>Recent Sales</Text>
                  <Text style={styles.kpiValue}>{sales.length}</Text>
                  <Text style={styles.kpiMeta}>Recorded by staff</Text>
                </View>
              )}

              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>On the Shelf</Text>
                <Text style={styles.kpiValue}>{products.length}</Text>
                <Text style={styles.kpiMeta}>Catalog Items</Text>
              </View>
            </View>

            <View style={styles.kpiRow}>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Pending Orders</Text>
                <Text style={styles.kpiValue}>{pendingListsCount}</Text>
                <Text style={styles.kpiMeta}>Customer Lists</Text>
              </View>

              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Shelf Categories</Text>
                <Text style={styles.kpiValue}>{categories.length}</Text>
                <Text style={styles.kpiMeta}>Product Groups</Text>
              </View>
            </View>

            {/* Quick Actions Grid with Native SVG Icons */}
            <Text style={styles.sectionHeading}>Quick Actions</Text>
            <View style={styles.actionGrid}>
              {(isOwnerOrManager || isInventoryStaff) && (
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
              )}

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

              {isOwnerOrManager && (
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
                  <Text style={styles.actionTileTitle}>New Category</Text>
                  <Text style={styles.actionTileDesc}>Organize shelf</Text>
                </Pressable>
              )}

              {isOwnerOrManager && (
                <Pressable style={styles.actionTile} onPress={handleShareStorefront}>
                  <View style={[styles.actionIconWrap, { backgroundColor: "#065f46" }]}>
                    <ShareIcon size={20} color="#34d399" />
                  </View>
                  <Text style={styles.actionTileTitle}>Share Shop</Text>
                  <Text style={styles.actionTileDesc}>WhatsApp Catalog</Text>
                </Pressable>
              )}
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
                  placeholder="Search products & categories..."
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

            {/* Category Header Actions */}
            <View style={styles.folderActionBar}>
              {isOwnerOrManager && (
                <Pressable
                  style={styles.folderActionBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setShowAddCategoryModal(true);
                  }}
                >
                  <PlusIcon size={14} color="#60a5fa" />
                  <Text style={[styles.folderActionText, { color: "#60a5fa" }]}>New Category</Text>
                </Pressable>
              )}

              {(isOwnerOrManager || isInventoryStaff) && (
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
              )}

              {currentCategory && isOwnerOrManager && (
                <>
                  <Pressable
                    style={styles.folderActionBtn}
                    onPress={() => {
                      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      setEditingCategory(currentCategory);
                      setEditCategoryName(currentCategory.name);
                      setEditCategoryNormalPrice(currentCategory.default_normal_price ?? "");
                      setEditCategoryWholesalePrice(currentCategory.default_wholesale_price ?? "");
                      setEditCategoryIcon(currentCategory.image_url ?? "");
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
                    <Text style={styles.emptySubtitle}>Tap New Category to create one.</Text>
                  </View>
                ) : (
                  categories
                    .filter((c) => c.parent_id === null)
                    .map((rootCat) => {
                      const childCats = categories.filter((c) => c.parent_id === rootCat.id);
                      const { total: rootTotal } = countCategoryProducts(rootCat.id, categories, products);
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
                              ({childCats.length} categories, {rootTotal} items)
                            </Text>
                          </Pressable>

                          {childCats.map((child) => {
                            const { total: childTotal } = countCategoryProducts(child.id, categories, products);
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
                                <Text style={styles.treeNodeMeta}>({childTotal} items)</Text>
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
                {/* Subcategories Section */}
                {currentSubcategories.length > 0 && (
                  <View style={styles.foldersSection}>
                    <Text style={styles.subHeading}>Categories ({currentSubcategories.length})</Text>
                    <View style={styles.foldersGrid}>
                      {currentSubcategories.map((cat) => {
                        const childCount = categories.filter((c) => c.parent_id === cat.id).length;
                        const { total: prodCount } = countCategoryProducts(cat.id, categories, products);
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
                              {childCount > 0 ? `${childCount} subcategories, ` : ""}{prodCount} item{prodCount === 1 ? "" : "s"}
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

                {/* Items in Current Category Section */}
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
                      <Text style={styles.emptyTitle}>No items in this category</Text>
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
                              <View style={styles.productNameRow}>
                                <Text style={styles.productName}>{item.name}</Text>
                                <Pressable
                                  style={[
                                    styles.itemPublishBadge,
                                    item.is_published ? styles.itemPublishLive : styles.itemPublishDraft,
                                  ]}
                                  onPress={() => handleToggleProductPublish(item)}
                                >
                                  <Text
                                    style={[
                                      styles.itemPublishBadgeText,
                                      item.is_published
                                        ? styles.itemPublishBadgeTextLive
                                        : styles.itemPublishBadgeTextDraft,
                                    ]}
                                  >
                                    {item.is_published ? "LIVE" : "DRAFT"}
                                  </Text>
                                </Pressable>
                              </View>
                              {(() => {
                                const inherited = getEffectiveCategoryPrice(item.category_id, categories);
                                const normalVal = item.effective_normal_price ?? item.selling_price ?? inherited.normal;
                                const wholesaleVal = item.effective_wholesale_price ?? inherited.wholesale;
                                return (
                                  <View style={styles.priceRow}>
                                    <Text style={styles.normalPrice}>
                                      {formatMoney(normalVal)}
                                    </Text>
                                    {wholesaleVal && (
                                      <Text style={styles.wholesalePrice}>
                                        Wholesale: {formatMoney(wholesaleVal)}
                                      </Text>
                                    )}
                                  </View>
                                );
                              })()}
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
                              style={styles.shareBtn}
                              onPress={() => handleShareProduct(item)}
                            >
                              <ShareIcon size={14} color="#38bdf8" />
                            </Pressable>

                            <Pressable
                              style={styles.photoBtn}
                              onPress={() => handleOpenGallery(item)}
                            >
                              <ImageIcon size={14} color="#60a5fa" />
                            </Pressable>

                            {isOwnerOrManager && (
                              <Pressable
                                style={styles.editBtn}
                                onPress={() => {
                                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                  setEditingProduct(item);
                                  setEditPrice(item.selling_price ?? "");
                                  setEditWholesale(item.effective_wholesale_price ?? "");
                                  setEditProductImage(item.image_url ?? "");
                                }}
                              >
                                <EditIcon size={14} color="#8b949e" />
                              </Pressable>
                            )}

                            {isOwnerOrManager && (
                              <Pressable
                                style={styles.deleteBtn}
                                onPress={() => handleDeleteProduct(item)}
                              >
                                <TrashIcon size={14} color="#f87171" />
                              </Pressable>
                            )}
                          </View>
                        </View>
                      );
                    })
                  )}
                </View>
              </ScrollView>
            )}

            {/* Sticky Multi-Select Batch Action Bar */}
            {selectedProductIds.size > 0 && isOwnerOrManager && (
              <View style={styles.batchActionBar}>
                <Text style={styles.batchCountText}>{selectedProductIds.size} selected</Text>
                <View style={styles.batchBtnRow}>
                  <Pressable
                    style={styles.batchBtn}
                    onPress={() => handleBatchPublish(true)}
                  >
                    <Text style={styles.batchBtnText}>Publish</Text>
                  </Pressable>

                  <Pressable
                    style={styles.batchBtn}
                    onPress={() => handleBatchPublish(false)}
                  >
                    <Text style={styles.batchBtnText}>Hide</Text>
                  </Pressable>

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
              const isExpanded = expandedListIds.has(item.id);
              const unpricedCount = item.lines.filter((l) => !l.shop_price && l.note !== "heading").length;
              const totalPaid = (item.payments ?? []).reduce(
                (acc, p) => acc + (Number(p.amount) || 0),
                Number(item.amount_paid ?? item.advance_payment ?? 0)
              );
              const grandTotalNum = (Number(item.priced_total) || 0) + (Number(item.dispatch_cost) || 0);
              const remainingBal = Math.max(0, grandTotalNum - totalPaid);
              const isFullyPaid = grandTotalNum > 0 && totalPaid >= grandTotalNum;
              const isPartPaid = totalPaid > 0 && totalPaid < grandTotalNum;
              const fulfillmentMode = item.fulfillment_type ?? (item.waybill_number ? "waybill" : "pickup");

              return (
                <View style={styles.listCard}>
                  <Pressable
                    style={styles.listCardHeader}
                    onPress={() => {
                      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      setExpandedListIds((prev) => {
                        const next = new Set(prev);
                        if (next.has(item.id)) {
                          next.delete(item.id);
                        } else {
                          next.add(item.id);
                        }
                        return next;
                      });
                    }}
                  >
                    <View style={{ flex: 1, paddingRight: 8 }}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 4 }}>
                        <Text style={styles.listCustomerName}>
                          {item.customer_name || item.customer_phone}
                        </Text>
                        <View
                          style={[
                            styles.badgeSmall,
                            fulfillmentMode === "waybill" ? styles.badgeWaybill : styles.badgePickup,
                          ]}
                        >
                          <Text
                            style={[
                              styles.badgeSmallText,
                              { color: fulfillmentMode === "waybill" ? "#f59e0b" : "#38bdf8" },
                            ]}
                          >
                            {fulfillmentMode === "waybill" ? "Waybill" : "Pickup"}
                          </Text>
                        </View>
                        <View
                          style={[
                            styles.badgeSmall,
                            isFullyPaid
                              ? styles.badgePaid
                              : isPartPaid
                              ? styles.badgePartPaid
                              : styles.badgeUnpaid,
                          ]}
                        >
                          <Text
                            style={[
                              styles.badgeSmallText,
                              {
                                color: isFullyPaid
                                  ? "#4ade80"
                                  : isPartPaid
                                  ? "#fb923c"
                                  : "#94a3b8",
                              },
                            ]}
                          >
                            {isFullyPaid
                              ? "Paid Full"
                              : isPartPaid
                              ? `Part Paid (-${formatMoney(remainingBal.toString())})`
                              : "Unpaid"}
                          </Text>
                        </View>
                      </View>
                      <Text style={styles.listDate}>
                        {item.lines.length} items | {item.priced_total ? formatMoney(item.priced_total) : "Unpriced"}
                        {unpricedCount > 0 ? ` | ${unpricedCount} unpriced` : ""}
                      </Text>
                    </View>

                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <View
                        style={[
                          styles.statusBadge,
                          isConfirmed ? styles.statusConfirmed : styles.statusPending,
                        ]}
                      >
                        <Text style={styles.statusBadgeText}>{item.status.toUpperCase()}</Text>
                      </View>
                      <View style={{ transform: [{ rotate: isExpanded ? "180deg" : "0deg" }] }}>
                        <ChevronDownIcon size={16} color="#8a928e" />
                      </View>
                    </View>
                  </Pressable>

                  {isExpanded && (
                    <>
                      {/* Fulfillment Type Bar */}
                      <View style={styles.fulfillmentRow}>
                        <Text style={styles.fulfillmentLabel}>Fulfillment Mode:</Text>
                        <View style={styles.fulfillmentToggleBox}>
                          <Pressable
                            style={[
                              styles.fulfillmentOption,
                              fulfillmentMode === "pickup" && styles.fulfillmentOptionActive,
                            ]}
                            onPress={() => {
                              void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                              const updated: CustomerList = { ...item, fulfillment_type: "pickup" };
                              setCustomerLists((curr) => curr.map((l) => (l.id === item.id ? updated : l)));
                              if (activeBusiness?.id) {
                                updateCachedCustomerList(activeBusiness.id, updated);
                              }
                            }}
                          >
                            <Text
                              style={[
                                styles.fulfillmentOptionText,
                                fulfillmentMode === "pickup" && styles.fulfillmentOptionTextActive,
                              ]}
                            >
                              In-Shop Pickup
                            </Text>
                          </Pressable>

                          <Pressable
                            style={[
                              styles.fulfillmentOption,
                              fulfillmentMode === "waybill" && styles.fulfillmentOptionActive,
                            ]}
                            onPress={() => {
                              void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                              const updated: CustomerList = { ...item, fulfillment_type: "waybill" };
                              setCustomerLists((curr) => curr.map((l) => (l.id === item.id ? updated : l)));
                              if (activeBusiness?.id) {
                                updateCachedCustomerList(activeBusiness.id, updated);
                              }
                            }}
                          >
                            <Text
                              style={[
                                styles.fulfillmentOptionText,
                                fulfillmentMode === "waybill" && styles.fulfillmentOptionTextActive,
                              ]}
                            >
                              Waybill / Delivery
                            </Text>
                          </Pressable>
                        </View>
                      </View>

                      {/* Payment & Ledger Tracker Card */}
                      <View style={styles.paymentSummaryCard}>
                        <View style={styles.paymentSummaryRow}>
                          <View>
                            <Text style={styles.paymentLabel}>TOTAL ORDER</Text>
                            <Text style={styles.paymentVal}>{formatMoney(grandTotalNum.toString())}</Text>
                          </View>
                          <View>
                            <Text style={styles.paymentLabel}>PAID SO FAR</Text>
                            <Text style={[styles.paymentVal, { color: "#4ade80" }]}>
                              {formatMoney(totalPaid.toString())}
                            </Text>
                          </View>
                          <View>
                            <Text style={styles.paymentLabel}>BALANCE DUE</Text>
                            <Text style={[styles.paymentVal, { color: remainingBal > 0 ? "#f87171" : "#4ade80" }]}>
                              {formatMoney(remainingBal.toString())}
                            </Text>
                          </View>
                        </View>

                        <Pressable
                          style={styles.recordPaymentBtn}
                          onPress={() => {
                            setPaymentModalList(item);
                            setPaymentAmount(remainingBal > 0 ? remainingBal.toString() : "");
                            setPaymentNote("");
                          }}
                        >
                          <ReceiptIcon size={14} color="#084a2f" />
                          <Text style={styles.recordPaymentBtnText}>
                            {totalPaid === 0 ? "Record Advance Deposit / Payment" : "Add Part Payment"}
                          </Text>
                        </Pressable>
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
                                      Price: {line.shop_price ? formatMoney(line.shop_price) : "Set Price"}
                                    </Text>
                                    {line.cost_price && (
                                      <Text style={styles.lineCost}>
                                        Market Buy: {formatMoney(line.cost_price)}
                                      </Text>
                                    )}
                                    {hasBoth && (
                                      <Text
                                        style={[
                                          styles.lineMargin,
                                          isPositive ? styles.marginPositive : styles.marginNegative,
                                        ]}
                                      >
                                        Profit: {isPositive ? "+" : ""}{formatMoney(marginVal.toString())}
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
                                      <CheckMarkIcon size={14} color="#64748b" />
                                    )}
                                  </Pressable>

                                  <Pressable
                                    style={styles.linePriceBtn}
                                    onPress={() => {
                                      const best = findBestPricesForLine(line, products, categories);
                                      const initialShop = line.shop_price ?? best.normal ?? "";
                                      const initialCost = line.cost_price ?? best.wholesale ?? "";
                                      setPricingLine({
                                        listId: item.id,
                                        lineId: line.id,
                                        itemName: line.product_name ?? line.free_text ?? "Item",
                                        currentShopPrice: line.shop_price ?? "",
                                        currentCostPrice: line.cost_price ?? "",
                                      });
                                      setPriceInput(initialShop);
                                      setCostInput(initialCost);
                                      setApplyPriceToAll(false);
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
                    <View style={styles.listFooterTop}>
                      <View style={{ flex: 1, paddingRight: 8 }}>
                        <Text style={styles.totalLabel}>Total Quoted</Text>
                        <Text style={styles.totalAmount} numberOfLines={1}>
                          {item.priced_total
                            ? formatMoney(item.priced_total)
                            : (() => {
                                const pricedSum = item.lines.reduce((acc, l) => {
                                  const p = Number(l.shop_price ?? "0");
                                  const q = Number(l.quantity) || 1;
                                  return acc + (l.shop_price && Number.isFinite(p) ? p * q : 0);
                                }, 0);
                                return pricedSum > 0
                                  ? `${formatMoney(pricedSum.toString())} (Partial)`
                                  : "Pending Pricing";
                              })()}
                        </Text>
                      </View>
                      <View
                        style={[
                          styles.statusPill,
                          isConfirmed ? styles.statusPillConfirmed : styles.statusPillDraft,
                        ]}
                      >
                        <Text
                          style={[
                            styles.statusPillText,
                            isConfirmed ? styles.statusPillTextConfirmed : styles.statusPillTextDraft,
                          ]}
                        >
                          {isConfirmed ? "Confirmed" : "Draft"}
                        </Text>
                      </View>
                    </View>

                    <View style={styles.footerActions}>
                      {item.lines.some((l) => !l.shop_price && l.note !== "heading") && !isConfirmed && (
                        <Pressable
                          style={styles.autoPriceBtn}
                          onPress={() => handleAutoPriceList(item)}
                          disabled={autoPricingListId === item.id}
                        >
                          {autoPricingListId === item.id ? (
                            <ActivityIndicator size="small" color="#084a2f" />
                          ) : (
                            <>
                              <SparklesIcon size={14} color="#084a2f" />
                              <Text style={styles.autoPriceBtnText}>Auto-Price</Text>
                            </>
                          )}
                        </Pressable>
                      )}

                      <Pressable
                        style={styles.waBtn}
                        onPress={() => handleShareQuoteOnWhatsApp(item)}
                      >
                        <ShareIcon size={14} color="#ffffff" />
                        <Text style={styles.waBtnText}>WhatsApp</Text>
                      </Pressable>

                      <Pressable
                        style={styles.invoiceBtn}
                        onPress={() => setInvoiceModalList(item)}
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
                            setConfirmError(null);
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
                </>
              )}
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
                  {expenseCategories.map((c) => {
                    const key = c.value || c.id || "OTHER";
                    const title = c.label || c.name || "Expense";
                    return (
                      <View key={key} style={styles.actionTile}>
                        <Text style={styles.actionTileTitle}>{title}</Text>
                        <Text style={styles.actionTileDesc}>{c.description || (c.is_known_spending ? "Standard business expense" : "General expense")}</Text>
                      </View>
                    );
                  })}
                </View>
              </View>
            )}
          </ScrollView>
        )}

        {/* The Everything / More Tab */}
        {activeTab === "more" && (
          activeSubView === "team" ? (
            <ScrollView style={styles.scrollContent}>
              {/* Back Bar */}
              <View style={styles.teamTopBar}>
                <Pressable
                  style={styles.teamBackBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setActiveSubView(null);
                  }}
                >
                  <ArrowLeftIcon size={18} color={theme.text} />
                  <Text style={styles.teamBackBtnText}>Back to More</Text>
                </Pressable>

                <Pressable
                  style={styles.teamInviteTopBtn}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setShowInviteModal(true);
                  }}
                >
                  <PlusIcon size={16} color="#ffffff" />
                  <Text style={styles.teamInviteTopBtnText}>Invite Staff</Text>
                </Pressable>
              </View>

              {/* Team Banner */}
              <View style={styles.teamBannerCard}>
                <View style={styles.teamBannerIconWrap}>
                  <PeopleIcon size={26} color="#4ade80" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.teamBannerTitle}>Team & Staff Management</Text>
                  <Text style={styles.teamBannerSub}>
                    {activeBusiness?.name} - Manage staff members, send WhatsApp invitations, and configure role permissions.
                  </Text>
                </View>
              </View>

              {/* Quick stats row */}
              <View style={styles.teamStatsRow}>
                <View style={styles.teamStatBox}>
                  <Text style={styles.teamStatValue}>{members.length}</Text>
                  <Text style={styles.teamStatLabel}>Staff Members</Text>
                </View>
                <View style={styles.teamStatBox}>
                  <Text style={styles.teamStatValue}>
                    {members.filter((m) => m.status === "active").length}
                  </Text>
                  <Text style={styles.teamStatLabel}>Active Staff</Text>
                </View>
                <View style={styles.teamStatBox}>
                  <Text style={styles.teamStatValue}>{invitations.length}</Text>
                  <Text style={styles.teamStatLabel}>Sent Invites</Text>
                </View>
              </View>

              {/* Active Members Section */}
              <View style={styles.moreCard}>
                <View style={styles.sectionHeaderRow}>
                  <Text style={styles.moreCardTitle}>Staff Members ({members.length})</Text>
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
                <Text style={styles.moreCardDesc}>
                  Tap any staff member's role badge to cycle their permission level, or tap status to toggle Active / Suspended.
                </Text>

                {members.length === 0 ? (
                  <Text style={styles.emptySubtitle}>No staff members added yet.</Text>
                ) : (
                  members.map((m) => {
                    const displayName = m.full_name || `${m.first_name ?? ""} ${m.last_name ?? ""}`.trim() || m.phone || "Staff Member";
                    const displayRole = (m.role_name || m.role || "SALES").toUpperCase();
                    const initial = (m.full_name || m.first_name || m.phone || "S").slice(0, 1).toUpperCase();
                    return (
                      <View key={m.id} style={styles.teamMemberCard}>
                        <View style={styles.teamMemberAvatar}>
                          <Text style={styles.teamMemberAvatarText}>{initial}</Text>
                        </View>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.teamMemberName}>{displayName}</Text>
                          <Text style={styles.teamMemberMeta}>
                            {m.phone || m.email || "No contact info"}
                          </Text>
                          <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 }}>
                            <Pressable
                              style={styles.memberRoleBadge}
                              onPress={() => handleChangeMemberRole(m)}
                            >
                              <Text style={styles.memberRoleBadgeText}>{displayRole}</Text>
                            </Pressable>
                            <Pressable
                              style={[
                                styles.memberStatusBadge,
                                m.status === "active" ? styles.memberStatusActive : styles.memberStatusSuspended,
                              ]}
                              onPress={() => handleToggleMemberStatus(m)}
                            >
                              <Text style={styles.memberStatusBadgeText}>
                                {(m.status ?? "ACTIVE").toUpperCase()}
                              </Text>
                            </Pressable>
                          </View>
                        </View>
                        {isOwner && displayRole !== "OWNER" && (
                          <Pressable
                            style={styles.removeStaffBtn}
                            onPress={() => handleRemoveMember(m)}
                          >
                            <Text style={styles.removeStaffBtnText}>Remove</Text>
                          </Pressable>
                        )}
                      </View>
                    );
                  })
                )}
              </View>

              {/* Sent Invitations Section */}
              <View style={styles.moreCard}>
                <View style={styles.sectionHeaderRow}>
                  <Text style={styles.moreCardTitle}>Sent Invitations ({invitations.length})</Text>
                  <Pressable
                    style={styles.addStaffBtn}
                    onPress={() => {
                      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      setShowInviteModal(true);
                    }}
                  >
                    <Text style={styles.addStaffBtnText}>+ Send New</Text>
                  </Pressable>
                </View>
                <Text style={styles.moreCardDesc}>
                  Track invitations sent to staff. Tap Share to send their invite link directly via WhatsApp.
                </Text>

                {invitations.length === 0 ? (
                  <View style={styles.emptyInviteBox}>
                    <Text style={styles.emptySubtitle}>No pending staff invitations.</Text>
                    <Pressable
                      style={styles.emptyInviteBtn}
                      onPress={() => setShowInviteModal(true)}
                    >
                      <Text style={styles.emptyInviteBtnText}>Invite your first staff member</Text>
                    </Pressable>
                  </View>
                ) : (
                  invitations.map((inv) => {
                    const status = getInvitationStatus(inv, members);
                    const isAccepted = status === "ACCEPTED";
                    const roleLabel = (inv.role_name || inv.role || "STAFF").toUpperCase();
                    return (
                      <View key={inv.id} style={styles.sentInviteCard}>
                        <View style={{ flex: 1 }}>
                          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                            <Text style={styles.sentInviteTarget}>
                              {inv.phone || inv.email || "Invited Staff"}
                            </Text>
                            <View style={styles.sentInviteRolePill}>
                              <Text style={styles.sentInviteRolePillText}>{roleLabel}</Text>
                            </View>
                          </View>
                          <Text style={[styles.sentInviteStatus, isAccepted && { color: "#4ade80" }]}>
                            Status: {status} - Created: {new Date(inv.created_at).toLocaleDateString()}
                          </Text>
                        </View>

                        {!isAccepted && (
                          <Pressable
                            style={styles.inviteShareWhatsAppBtn}
                            onPress={() => handleShareInviteWhatsApp(inv)}
                          >
                            <ShareIcon size={14} color="#ffffff" />
                            <Text style={styles.inviteShareWhatsAppBtnText}>Share</Text>
                          </Pressable>
                        )}
                      </View>
                    );
                  })
                )}
              </View>

              {/* Invitations Waiting For You */}
              {myInvitations.length > 0 && (
                <View style={styles.moreCard}>
                  <Text style={[styles.moreCardTitle, { color: "#4ade80" }]}>
                    Invitations Waiting for You ({myInvitations.length})
                  </Text>
                  <Text style={styles.moreCardDesc}>
                    Other businesses have invited you to join their team on AHIA:
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

              {/* Role Permissions Guide */}
              <View style={styles.moreCard}>
                <Text style={styles.moreCardTitle}>Role Permissions Guide</Text>
                <Text style={styles.moreCardDesc}>
                  Summary of privileges for each stall role:
                </Text>
                <View style={styles.roleGuideList}>
                  <View style={styles.roleGuideItem}>
                    <Text style={styles.roleGuideName}>Owner</Text>
                    <Text style={styles.roleGuideDesc}>
                      Full stall ownership, financial records, team management, business security PIN, and storefront settings.
                    </Text>
                  </View>
                  <View style={styles.roleGuideItem}>
                    <Text style={styles.roleGuideName}>Manager</Text>
                    <Text style={styles.roleGuideDesc}>
                      Sales recording, inventory & shelf categories, order lists, and staff management.
                    </Text>
                  </View>
                  <View style={styles.roleGuideItem}>
                    <Text style={styles.roleGuideName}>Sales / Cashier</Text>
                    <Text style={styles.roleGuideDesc}>
                      Record customer sales, print/send customer WhatsApp receipts, search products and prices.
                    </Text>
                  </View>
                  <View style={styles.roleGuideItem}>
                    <Text style={styles.roleGuideName}>Inventory</Text>
                    <Text style={styles.roleGuideDesc}>
                      Manage categories and products, update stock quantities, view stock alerts.
                    </Text>
                  </View>
                </View>
              </View>

              <View style={{ height: 40 }} />
            </ScrollView>
          ) : (
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
                {profile?.email && (
                  <Text style={styles.userProfileEmail}>{profile.email}</Text>
                )}
                <View style={styles.roleBadgeWrap}>
                  <Text style={styles.roleBadgeText}>
                    {activeBusiness?.name} - Role: {userRole}
                  </Text>
                </View>
              </View>
              <Pressable
                style={styles.editProfileBtn}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setEditFirstName(profile?.first_name ?? "");
                  setEditLastName(profile?.last_name ?? "");
                  setEditPhone(profile?.phone ?? "");
                  setEditEmail(profile?.email ?? "");
                  setEditAvatarUrl(profile?.avatar_url ?? "");
                  setShowProfileModal(true);
                }}
              >
                <Text style={styles.editProfileBtnText}>Edit</Text>
              </Pressable>
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

              {isOwnerOrManager && (
                <Pressable style={styles.everythingTile} onPress={() => setShowStorefrontModal(true)}>
                  <ShareIcon size={24} color="#34d399" />
                  <Text style={styles.everythingTileTitle}>Storefront</Text>
                  <Text style={styles.everythingTileDesc}>WhatsApp link</Text>
                </Pressable>
              )}

              {isOwnerOrManager && (
                <Pressable
                  style={styles.everythingTile}
                  onPress={() => {
                    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setActiveSubView("team");
                  }}
                >
                  <PeopleIcon size={24} color="#38bdf8" />
                  <Text style={styles.everythingTileTitle}>Team & Staff</Text>
                  <Text style={styles.everythingTileDesc}>Manage team & invites</Text>
                </Pressable>
              )}

              {isOwnerOrManager && (
                <Pressable
                  style={styles.everythingTile}
                  onPress={() => {
                    setEditBizName(businessDetails?.name ?? activeBusiness?.name ?? "");
                    setEditBizAddress(businessDetails?.address ?? "");
                    setEditBizPhone(businessDetails?.phone ?? "");
                    setEditBizLogo(businessDetails?.logo_url ?? activeBusiness?.logo_url ?? "");
                    setShowBusinessModal(true);
                  }}
                >
                  <TagIcon size={24} color="#fbbf24" />
                  <Text style={styles.everythingTileTitle}>Stall Profile</Text>
                  <Text style={styles.everythingTileDesc}>Address & name</Text>
                </Pressable>
              )}

              <Pressable style={styles.everythingTile} onPress={() => setShowPasswordModal(true)}>
                <PersonIcon size={24} color="#f472b6" />
                <Text style={styles.everythingTileTitle}>Security</Text>
                <Text style={styles.everythingTileDesc}>PIN & password</Text>
              </Pressable>
            </View>

            {/* Storefront Studio Card */}
            {isOwnerOrManager && (
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
                  https://useahia-hazel.vercel.app/shop/{activeBusiness?.slug ?? "stall"}
                </Text>
                <Pressable style={styles.storefrontShareBtn} onPress={handleShareStorefront}>
                  <ShareIcon size={16} color="#ffffff" />
                  <Text style={styles.storefrontShareBtnText}>Share Storefront Link</Text>
                </Pressable>
              </View>
            )}

            {/* Team Management */}
            {isOwnerOrManager && (
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
                {members.map((m) => {
                  const displayName = m.full_name || `${m.first_name ?? ""} ${m.last_name ?? ""}`.trim() || m.phone || "Staff Member";
                  const displayRole = (m.role_name || m.role || "SALES").toUpperCase();
                  return (
                  <View key={m.id} style={styles.memberRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.memberName}>{displayName}</Text>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 }}>
                        <Pressable
                          style={styles.memberRoleBadge}
                          onPress={() => handleChangeMemberRole(m)}
                        >
                          <Text style={styles.memberRoleBadgeText}>{displayRole}</Text>
                        </Pressable>
                        <Pressable
                          style={[
                            styles.memberStatusBadge,
                            m.status === "active" ? styles.memberStatusActive : styles.memberStatusSuspended,
                          ]}
                          onPress={() => handleToggleMemberStatus(m)}
                        >
                          <Text style={styles.memberStatusBadgeText}>
                            {(m.status ?? "ACTIVE").toUpperCase()}
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
                  );
                })}

                {/* Sent Invitations */}
                {invitations.length > 0 && (
                  <View style={{ marginTop: 12, borderTopWidth: 1, borderTopColor: "#21262d", paddingTop: 10 }}>
                    <Text style={styles.invitationSubHeading}>Sent Invitations ({invitations.length})</Text>
                    {invitations.map((inv) => {
                      const status = getInvitationStatus(inv, members);
                      const isAccepted = status === "ACCEPTED";
                      const roleLabel = (inv.role_name || inv.role || "STAFF").toUpperCase();
                      return (
                        <View key={inv.id} style={styles.invitationRow}>
                          <View style={{ flex: 1 }}>
                            <Text style={styles.invitationPhone}>{inv.phone || inv.email || "Invited"}</Text>
                            <Text style={[styles.invitationMeta, isAccepted && { color: "#4ade80" }]}>
                              Role: {roleLabel} - {status}
                            </Text>
                          </View>
                        </View>
                      );
                    })}
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
            )}

            {/* Business Info */}
            <View style={styles.moreCard}>
              <View style={styles.sectionHeaderRow}>
                <Text style={styles.moreCardTitle}>Business Profile</Text>
                {isOwnerOrManager && (
                  <Pressable
                    style={styles.addStaffBtn}
                    onPress={() => {
                      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      setEditBizName(businessDetails?.name ?? activeBusiness?.name ?? "");
                      setEditBizAddress(businessDetails?.address ?? "");
                      setEditBizPhone(businessDetails?.phone ?? "");
                      setEditBizLogo(businessDetails?.logo_url ?? activeBusiness?.logo_url ?? "");
                      setShowBusinessModal(true);
                    }}
                  >
                    <Text style={styles.addStaffBtnText}>Edit</Text>
                  </Pressable>
                )}
              </View>
              <Text style={styles.profileDetail}>Name: {businessDetails?.name ?? activeBusiness?.name}</Text>
              <Text style={styles.profileDetail}>Address: {businessDetails?.address ?? "Alaba International Market"}</Text>
              <Text style={styles.profileDetail}>Phone: {businessDetails?.phone ?? "Not set"}</Text>
            </View>

            {/* App Appearance / Theme Selector */}
            <View style={styles.moreCard}>
              <View style={styles.sectionHeaderRow}>
                <Text style={styles.moreCardTitle}>App Appearance</Text>
              </View>
              <Text style={styles.moreCardDesc}>
                Choose your preferred visual theme for the market floor.
              </Text>
              <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
                <Pressable
                  style={[
                    styles.themeToggleBtn,
                    themeMode === "light" && styles.themeToggleBtnActive,
                  ]}
                  onPress={() => handleToggleTheme("light")}
                >
                  <Text
                    style={[
                      styles.themeToggleBtnText,
                      themeMode === "light" && styles.themeToggleBtnTextActive,
                    ]}
                  >
                    Light Ivory (Default)
                  </Text>
                </Pressable>
                <Pressable
                  style={[
                    styles.themeToggleBtn,
                    themeMode === "dark" && styles.themeToggleBtnActive,
                  ]}
                  onPress={() => handleToggleTheme("dark")}
                >
                  <Text
                    style={[
                      styles.themeToggleBtnText,
                      themeMode === "dark" && styles.themeToggleBtnTextActive,
                    ]}
                  >
                    Dark Theme
                  </Text>
                </Pressable>
              </View>
            </View>

            {/* Sign Out Action */}
            <Pressable
              style={styles.signOutBtn}
              onPress={() => {
                void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                setShowSignOutModal(true);
              }}
            >
              <Text style={styles.signOutBtnText}>Sign Out of AHIA</Text>
            </Pressable>
          </ScrollView>
          )
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
            setActiveSubView(null);
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
            setActiveSubView(null);
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
            setActiveSubView(null);
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
      <Modal statusBarTranslucent visible={showAddProductModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
            <View style={styles.modalCard}>
              <Text style={styles.modalTitle}>Add Product to {currentCategory?.name ?? "Shelf"}</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Product Name"
                placeholderTextColor="#8a928e"
                value={newName}
                onChangeText={setNewName}
              />
              {(() => {
                const inherited = getEffectiveCategoryPrice(currentCategoryId, categories);
                return (
                  <>
                    <TextInput
                      style={styles.modalInput}
                      placeholder={
                        inherited.normal
                          ? `Selling Price (inherits ${formatMoney(inherited.normal)})`
                          : "Selling Price (NGN, optional)"
                      }
                      placeholderTextColor="#8a928e"
                      keyboardType="numeric"
                      value={newPrice}
                      onChangeText={setNewPrice}
                    />
                    <TextInput
                      style={styles.modalInput}
                      placeholder={
                        inherited.wholesale
                          ? `Wholesale Price (inherits ${formatMoney(inherited.wholesale)})`
                          : "Wholesale Price (optional)"
                      }
                      placeholderTextColor="#8a928e"
                      keyboardType="numeric"
                      value={newWholesale}
                      onChangeText={setNewWholesale}
                    />
                  </>
                );
              })()}
              <Text style={styles.modalFieldLabel}>Product Photo (optional)</Text>
              {newProductImage ? (
                <View style={styles.imagePickerPreviewBox}>
                  <Image source={{ uri: newProductImage }} style={styles.imagePickerThumb} />
                  <View style={{ flex: 1, gap: 4 }}>
                    <Text style={styles.imagePickerSelectedText} numberOfLines={1}>
                      {newProductImage.startsWith("file://") ? "Selected from Device" : newProductImage}
                    </Text>
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      <Pressable
                        style={styles.imagePickerActionBtn}
                        onPress={() => handlePickDeviceImage((uri) => setNewProductImage(uri))}
                      >
                        <Text style={styles.imagePickerActionBtnText}>Change</Text>
                      </Pressable>
                      <Pressable
                        style={[styles.imagePickerActionBtn, styles.imagePickerRemoveBtn]}
                        onPress={() => setNewProductImage("")}
                      >
                        <Text style={[styles.imagePickerActionBtnText, { color: "#f87171" }]}>Remove</Text>
                      </Pressable>
                    </View>
                  </View>
                </View>
              ) : (
                <Pressable
                  style={styles.imagePickerButton}
                  onPress={() => handlePickDeviceImage((uri) => setNewProductImage(uri))}
                >
                  <CameraIcon size={20} color="#4ade80" />
                  <Text style={styles.imagePickerButtonText}>Choose Photo from Phone</Text>
                </Pressable>
              )}
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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Add Category Modal */}
      <Modal statusBarTranslucent visible={showAddCategoryModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
            <View style={styles.modalCard}>
              <Text style={styles.modalTitle}>
                New Category under {currentCategory?.name ?? "Catalog Root"}
              </Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Category Name (e.g. Armoured Cables)"
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
              <Text style={styles.modalFieldLabel}>Category Icon / Photo (optional)</Text>
              {newCategoryIcon ? (
                <View style={styles.imagePickerPreviewBox}>
                  <Image source={{ uri: newCategoryIcon }} style={styles.imagePickerThumb} />
                  <View style={{ flex: 1, gap: 4 }}>
                    <Text style={styles.imagePickerSelectedText} numberOfLines={1}>
                      {newCategoryIcon.startsWith("file://") ? "Selected from Device" : newCategoryIcon}
                    </Text>
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      <Pressable
                        style={styles.imagePickerActionBtn}
                        onPress={() => handlePickDeviceImage((uri) => setNewCategoryIcon(uri))}
                      >
                        <Text style={styles.imagePickerActionBtnText}>Change</Text>
                      </Pressable>
                      <Pressable
                        style={[styles.imagePickerActionBtn, styles.imagePickerRemoveBtn]}
                        onPress={() => setNewCategoryIcon("")}
                      >
                        <Text style={[styles.imagePickerActionBtnText, { color: "#f87171" }]}>Remove</Text>
                      </Pressable>
                    </View>
                  </View>
                </View>
              ) : (
                <Pressable
                  style={styles.imagePickerButton}
                  onPress={() => handlePickDeviceImage((uri) => setNewCategoryIcon(uri))}
                >
                  <CameraIcon size={20} color="#4ade80" />
                  <Text style={styles.imagePickerButtonText}>Choose Category Icon / Photo</Text>
                </Pressable>
              )}
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
                    <Text style={styles.modalSaveText}>Create Category</Text>
                  )}
                </Pressable>
              </View>
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Edit Category Modal */}
      <Modal statusBarTranslucent visible={editingCategory !== null} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
            <View style={styles.modalCard}>
              <Text style={styles.modalTitle}>Edit Category {editingCategory?.name}</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Category Name"
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
              <Text style={styles.modalFieldLabel}>Category Icon / Photo</Text>
              {editCategoryIcon ? (
                <View style={styles.imagePickerPreviewBox}>
                  <Image source={{ uri: editCategoryIcon }} style={styles.imagePickerThumb} />
                  <View style={{ flex: 1, gap: 4 }}>
                    <Text style={styles.imagePickerSelectedText} numberOfLines={1}>
                      {editCategoryIcon.startsWith("file://") ? "Selected from Device" : editCategoryIcon}
                    </Text>
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      <Pressable
                        style={styles.imagePickerActionBtn}
                        onPress={() => handlePickDeviceImage((uri) => setEditCategoryIcon(uri))}
                      >
                        <Text style={styles.imagePickerActionBtnText}>Change</Text>
                      </Pressable>
                      <Pressable
                        style={[styles.imagePickerActionBtn, styles.imagePickerRemoveBtn]}
                        onPress={() => setEditCategoryIcon("")}
                      >
                        <Text style={[styles.imagePickerActionBtnText, { color: "#f87171" }]}>Remove</Text>
                      </Pressable>
                    </View>
                  </View>
                </View>
              ) : (
                <Pressable
                  style={styles.imagePickerButton}
                  onPress={() => handlePickDeviceImage((uri) => setEditCategoryIcon(uri))}
                >
                  <CameraIcon size={20} color="#4ade80" />
                  <Text style={styles.imagePickerButtonText}>Choose Category Icon / Photo</Text>
                </Pressable>
              )}
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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Batch Move / Copy Category Picker Modal */}
      <Modal statusBarTranslucent visible={batchModal !== null} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>
              {batchModal?.mode === "copy" ? "Copy Items to Category" : "Move Items to Category"}
            </Text>
            <Text style={styles.modalSubtitle}>
              Select the destination category for {batchModal?.productIds.length} item(s):
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
      <Modal statusBarTranslucent visible={editingProduct !== null} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
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
              <Text style={styles.modalFieldLabel}>Product Photo</Text>
              {editProductImage ? (
                <View style={styles.imagePickerPreviewBox}>
                  <Image source={{ uri: editProductImage }} style={styles.imagePickerThumb} />
                  <View style={{ flex: 1, gap: 4 }}>
                    <Text style={styles.imagePickerSelectedText} numberOfLines={1}>
                      {editProductImage.startsWith("file://") ? "Selected from Device" : editProductImage}
                    </Text>
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      <Pressable
                        style={styles.imagePickerActionBtn}
                        onPress={() => handlePickDeviceImage((uri) => setEditProductImage(uri))}
                      >
                        <Text style={styles.imagePickerActionBtnText}>Change</Text>
                      </Pressable>
                      <Pressable
                        style={[styles.imagePickerActionBtn, styles.imagePickerRemoveBtn]}
                        onPress={() => setEditProductImage("")}
                      >
                        <Text style={[styles.imagePickerActionBtnText, { color: "#f87171" }]}>Remove</Text>
                      </Pressable>
                    </View>
                  </View>
                </View>
              ) : (
                <Pressable
                  style={styles.imagePickerButton}
                  onPress={() => handlePickDeviceImage((uri) => setEditProductImage(uri))}
                >
                  <CameraIcon size={20} color="#4ade80" />
                  <Text style={styles.imagePickerButtonText}>Choose Photo from Phone</Text>
                </Pressable>
              )}
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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Restock Modal */}
      <Modal statusBarTranslucent visible={restockProduct !== null} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Price & Cost Input Modal for Customer List Line Item */}
      <Modal statusBarTranslucent visible={pricingLine !== null} transparent animationType="fade">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
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

              {/* Quick Fill Category Chips */}
              {categories.filter((c) => {
                const p = getEffectiveCategoryPrice(c.id, categories);
                return Boolean(p.normal || p.wholesale);
              }).length > 0 && (
                <View style={{ marginBottom: 12 }}>
                  <Text style={styles.modalFieldLabel}>Quick Fill from Category Default</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexDirection: "row", marginTop: 4 }}>
                    {categories
                      .filter((c) => {
                        const p = getEffectiveCategoryPrice(c.id, categories);
                        return Boolean(p.normal || p.wholesale);
                      })
                      .map((cat) => {
                        const prices = getEffectiveCategoryPrice(cat.id, categories);
                        return (
                          <Pressable
                            key={cat.id}
                            style={styles.categoryPricePill}
                            onPress={() => {
                              if (prices.normal) setPriceInput(prices.normal);
                              if (prices.wholesale) setCostInput(prices.wholesale);
                            }}
                          >
                            <Text style={styles.categoryPricePillName}>{cat.name}</Text>
                            <Text style={styles.categoryPricePillPrices}>
                              {prices.normal ? `Sell: NGN ${prices.normal}` : ""}
                              {prices.normal && prices.wholesale ? " | " : ""}
                              {prices.wholesale ? `Cost: NGN ${prices.wholesale}` : ""}
                            </Text>
                          </Pressable>
                        );
                      })}
                  </ScrollView>
                </View>
              )}

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

              <Pressable
                style={styles.applyAllCheckboxRow}
                onPress={() => setApplyPriceToAll(!applyPriceToAll)}
              >
                <View style={[styles.checkboxBox, applyPriceToAll && styles.checkboxBoxChecked]}>
                  {applyPriceToAll && <CheckMarkIcon size={12} color="#ffffff" />}
                </View>
                <Text style={styles.applyAllCheckboxLabel}>
                  {pricingLineCategoryName
                    ? `Apply these prices to other unpriced items in "${pricingLineCategoryName}" in this list`
                    : "Apply these prices to other unpriced items in this list"}
                </Text>
              </Pressable>

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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Dispatch Waybill Modal */}
      <Modal statusBarTranslucent visible={dispatchModalList !== null} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Security PIN Gate Confirmation Modal */}
      <Modal statusBarTranslucent visible={pinConfirmList !== null} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Confirm Customer Order</Text>

            {hasPin ? (
              <>
                <Text style={styles.modalSubtitle}>
                  Confirming converts this quote for {pinConfirmList?.customer_name || pinConfirmList?.customer_phone} into an active sale. Enter your 4-digit security PIN to authorize.
                </Text>

                <PinPad
                  length={4}
                  loading={savingConfirm}
                  loadingMessage="Verifying PIN & confirming order..."
                  onComplete={(pin) => {
                    setPinValue(pin);
                    void handleExecutePinConfirm(pin);
                  }}
                  error={confirmError}
                  disabled={savingConfirm}
                />

                {confirmError && (
                  <View style={{ marginTop: 12, alignItems: "center" }}>
                    <Pressable
                      style={styles.zeroPriceBypassBtn}
                      onPress={handlePriceRemainingLinesZeroAndConfirm}
                      disabled={savingConfirm}
                    >
                      <Text style={styles.zeroPriceBypassText}>
                        Price Remaining Items as NGN 0 & Confirm
                      </Text>
                    </Pressable>
                  </View>
                )}

                <View style={styles.modalButtons}>
                  <Pressable
                    style={styles.modalCancelBtn}
                    onPress={() => {
                      setPinConfirmList(null);
                      setConfirmError(null);
                      setPinValue("");
                    }}
                    disabled={savingConfirm}
                  >
                    <Text style={styles.modalCancelText}>Cancel</Text>
                  </Pressable>
                </View>
              </>
            ) : (
              <>
                <Text style={styles.modalSubtitle}>
                  Confirm order for {pinConfirmList?.customer_name || pinConfirmList?.customer_phone}?
                  {"\n\n"}
                  Note: No stall security PIN is configured yet. You can confirm directly now, or set a PIN in Business Settings to protect transactions.
                </Text>

                {confirmError ? (
                  <View style={{ marginBottom: 12 }}>
                    <Text style={styles.modalInlineError}>{confirmError}</Text>
                    <Pressable
                      style={[styles.zeroPriceBypassBtn, { marginTop: 8 }]}
                      onPress={handlePriceRemainingLinesZeroAndConfirm}
                      disabled={savingConfirm}
                    >
                      <Text style={styles.zeroPriceBypassText}>
                        Price Remaining Items as NGN 0 & Confirm
                      </Text>
                    </Pressable>
                  </View>
                ) : null}

                <View style={[styles.modalButtons, { flexDirection: "column", gap: 8 }]}>
                  <Pressable
                    style={[styles.modalSaveBtn, { width: "100%", height: 46 }]}
                    onPress={() => handleExecutePinConfirm()}
                    disabled={savingConfirm}
                  >
                    {savingConfirm ? (
                      <ActivityIndicator color="#ffffff" size="small" />
                    ) : (
                      <Text style={styles.modalSaveText}>Confirm Order (Without PIN)</Text>
                    )}
                  </Pressable>

                  <Pressable
                    style={[styles.modalSecondaryBtn, { width: "100%", height: 46 }]}
                    onPress={() => {
                      setPinConfirmList(null);
                      setConfirmError(null);
                      setSecurityTab("pin");
                      setShowPasswordModal(true);
                    }}
                    disabled={savingConfirm}
                  >
                    <LockIcon size={16} color="#084a2f" />
                    <Text style={styles.modalSecondaryText}>Set Security PIN Now</Text>
                  </Pressable>

                  <Pressable
                    style={[styles.modalCancelBtn, { width: "100%" }]}
                    onPress={() => {
                      setPinConfirmList(null);
                      setConfirmError(null);
                    }}
                    disabled={savingConfirm}
                  >
                    <Text style={styles.modalCancelText}>Cancel</Text>
                  </Pressable>
                </View>
              </>
            )}
          </View>
        </View>
      </Modal>

      {/* Official Invoice Modal */}
      <Modal statusBarTranslucent visible={invoiceModalList !== null} transparent animationType="slide">
        <View style={styles.modalBackdrop}>
          <View style={[styles.modalCard, { maxHeight: "90%", padding: 16 }]}>
            <View style={styles.invoiceModalHeader}>
              <View>
                <Text style={styles.modalTitle}>{activeBusiness?.name || "Official Invoice"}</Text>
                <Text style={styles.modalSubtitle}>
                  Order #{invoiceModalList ? invoiceModalList.id.slice(0, 8) : ""}
                </Text>
              </View>
              <Pressable
                style={styles.closeCircleBtn}
                onPress={() => setInvoiceModalList(null)}
              >
                <CloseIcon size={18} color="#64748b" />
              </Pressable>
            </View>

            {invoiceModalList && (
              <ScrollView style={{ marginTop: 10 }} showsVerticalScrollIndicator={false}>
                {/* Customer Meta */}
                <View style={styles.invoiceClientBox}>
                  <View>
                    <Text style={styles.invoiceClientLabel}>BILLED TO</Text>
                    <Text style={styles.invoiceClientName}>
                      {invoiceModalList.customer_name || invoiceModalList.customer_phone || "Customer"}
                    </Text>
                    <Text style={styles.invoiceClientPhone}>
                      Phone: {invoiceModalList.customer_phone || "N/A"}
                    </Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={styles.invoiceClientLabel}>STATUS</Text>
                    <View
                      style={[
                        styles.statusPill,
                        invoiceModalList.status === "confirmed"
                          ? styles.statusPillConfirmed
                          : styles.statusPillDraft,
                        { marginTop: 4 },
                      ]}
                    >
                      <Text
                        style={[
                          styles.statusPillText,
                          invoiceModalList.status === "confirmed"
                            ? styles.statusPillTextConfirmed
                            : styles.statusPillTextDraft,
                        ]}
                      >
                        {invoiceModalList.status}
                      </Text>
                    </View>
                  </View>
                </View>

                {/* Itemized Table */}
                <View style={styles.invoiceTable}>
                  <View style={styles.invoiceTableHeader}>
                    <Text style={[styles.invoiceTh, { flex: 2 }]}>ITEM</Text>
                    <Text style={[styles.invoiceTh, { width: 40, textAlign: "center" }]}>QTY</Text>
                    <Text style={[styles.invoiceTh, { width: 85, textAlign: "right" }]}>UNIT</Text>
                    <Text style={[styles.invoiceTh, { width: 95, textAlign: "right" }]}>TOTAL</Text>
                  </View>

                  {invoiceModalList.lines.map((line, idx) => {
                    const name = line.product_name || line.free_text || "Item";
                    const qty = Number(line.quantity) || 1;
                    const unitPrice = Number(line.shop_price ?? "0");
                    const hasPrice = Boolean(line.shop_price && Number.isFinite(unitPrice));
                    const lineTotal = hasPrice ? unitPrice * qty : 0;

                    return (
                      <View key={line.id || idx} style={styles.invoiceTableRow}>
                        <View style={{ flex: 2 }}>
                          <Text style={styles.invoiceItemName}>{name}</Text>
                          {line.note && line.note !== "heading" ? (
                            <Text style={styles.invoiceItemNote}>{line.note}</Text>
                          ) : null}
                        </View>
                        <Text style={[styles.invoiceItemQty, { width: 40, textAlign: "center" }]}>
                          {line.quantity}
                        </Text>
                        <Text style={[styles.invoiceItemPrice, { width: 85, textAlign: "right" }]}>
                          {hasPrice ? formatMoney(line.shop_price) : "Pending"}
                        </Text>
                        <Text style={[styles.invoiceItemTotal, { width: 95, textAlign: "right" }]}>
                          {hasPrice ? formatMoney(lineTotal.toString()) : "-"}
                        </Text>
                      </View>
                    );
                  })}
                </View>

                {/* Summary / Totals */}
                {(() => {
                  const subtotal = invoiceModalList.lines.reduce((acc, l) => {
                    const p = Number(l.shop_price ?? "0");
                    const q = Number(l.quantity) || 1;
                    return acc + (l.shop_price && Number.isFinite(p) ? p * q : 0);
                  }, 0);
                  const dispatchFee = Number(invoiceModalList.dispatch_cost ?? "0");
                  const grandTotal = invoiceModalList.priced_total
                    ? formatMoney(invoiceModalList.priced_total)
                    : formatMoney((subtotal + dispatchFee).toString());

                  return (
                    <View style={styles.invoiceSummaryBox}>
                      <View style={styles.invoiceSummaryRow}>
                        <Text style={styles.invoiceSummaryLabel}>Subtotal</Text>
                        <Text style={styles.invoiceSummaryValue}>{formatMoney(subtotal.toString())}</Text>
                      </View>
                      {invoiceModalList.dispatch_cost ? (
                        <View style={styles.invoiceSummaryRow}>
                          <Text style={styles.invoiceSummaryLabel}>Waybill / Dispatch</Text>
                          <Text style={styles.invoiceSummaryValue}>
                            {formatMoney(invoiceModalList.dispatch_cost)}
                          </Text>
                        </View>
                      ) : null}
                      <View style={[styles.invoiceSummaryRow, styles.invoiceGrandTotalRow]}>
                        <Text style={styles.invoiceGrandTotalLabel}>Total Due</Text>
                        <Text style={styles.invoiceGrandTotalValue}>{grandTotal}</Text>
                      </View>
                    </View>
                  );
                })()}

                {/* Waybill tracking details if dispatched */}
                {invoiceModalList.waybill_number && (
                  <View style={styles.invoiceWaybillBox}>
                    <Text style={styles.invoiceWaybillTitle}>WAYBILL & DISPATCH TRACKING</Text>
                    <Text style={styles.invoiceWaybillText}>
                      Transporter: {invoiceModalList.transporter_name || "Courier"}
                    </Text>
                    <Text style={styles.invoiceWaybillText}>
                      Waybill #: {invoiceModalList.waybill_number}
                    </Text>
                    {invoiceModalList.transporter_phone && (
                      <Text style={styles.invoiceWaybillText}>
                        Phone: {invoiceModalList.transporter_phone}
                      </Text>
                    )}
                  </View>
                )}

                {/* Action Buttons */}
                <View style={styles.invoiceModalActions}>
                  <Pressable
                    style={styles.invoiceExportPdfBtn}
                    onPress={() => handleExportPdfInvoice(invoiceModalList)}
                    disabled={exportingPdf}
                  >
                    {exportingPdf ? (
                      <ActivityIndicator color="#ffffff" size="small" />
                    ) : (
                      <>
                        <ShareIcon size={16} color="#ffffff" />
                        <Text style={styles.invoiceExportPdfText}>Share Invoice (PDF)</Text>
                      </>
                    )}
                  </Pressable>

                  <Pressable
                    style={styles.invoiceShareWaBtn}
                    onPress={() => handlePrintPdfInvoice(invoiceModalList)}
                  >
                    <ReceiptIcon size={16} color="#ffffff" />
                    <Text style={styles.invoiceShareWaText}>Print / Save PDF</Text>
                  </Pressable>
                </View>
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>

      {/* Record Order Payment / Advance Deposit Modal */}
      <Modal statusBarTranslucent visible={paymentModalList !== null} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Record Order Payment</Text>
            <Text style={styles.modalSubtitle}>
              Customer: {paymentModalList?.customer_name || paymentModalList?.customer_phone}
            </Text>

            <TextInput
              style={styles.modalInput}
              placeholder="Amount (NGN)"
              placeholderTextColor="#8a928e"
              keyboardType="numeric"
              value={paymentAmount}
              onChangeText={setPaymentAmount}
            />

            {/* Quick chips */}
            {paymentModalList && (() => {
              const curTotalPaid = (paymentModalList.payments ?? []).reduce(
                (acc, p) => acc + (Number(p.amount) || 0),
                Number(paymentModalList.amount_paid ?? paymentModalList.advance_payment ?? 0)
              );
              const curGrand = (Number(paymentModalList.priced_total) || 0) + (Number(paymentModalList.dispatch_cost) || 0);
              const curRem = Math.max(0, curGrand - curTotalPaid);
              return curRem > 0 ? (
                <View style={{ flexDirection: "row", gap: 8, marginBottom: 12 }}>
                  <Pressable
                    style={styles.quickChip}
                    onPress={() => setPaymentAmount(curRem.toString())}
                  >
                    <Text style={styles.quickChipText}>Full Balance ({formatMoney(curRem.toString())})</Text>
                  </Pressable>
                  <Pressable
                    style={styles.quickChip}
                    onPress={() => setPaymentAmount(Math.round(curRem / 2).toString())}
                  >
                    <Text style={styles.quickChipText}>50% Part</Text>
                  </Pressable>
                </View>
              ) : null;
            })()}

            {/* Payment Method Selector */}
            <View style={{ flexDirection: "row", gap: 8, marginBottom: 12 }}>
              {["transfer", "cash", "pos"].map((m) => (
                <Pressable
                  key={m}
                  style={[
                    styles.methodChip,
                    paymentMethod === m && styles.methodChipActive,
                  ]}
                  onPress={() => setPaymentMethod(m)}
                >
                  <Text
                    style={[
                      styles.methodChipText,
                      paymentMethod === m && styles.methodChipTextActive,
                    ]}
                  >
                    {m.toUpperCase()}
                  </Text>
                </Pressable>
              ))}
            </View>

            <TextInput
              style={styles.modalInput}
              placeholder="Note (e.g. Advance deposit before dispatch, Part payment)"
              placeholderTextColor="#8a928e"
              value={paymentNote}
              onChangeText={setPaymentNote}
            />

            <View style={styles.modalButtons}>
              <Pressable
                style={styles.modalCancelBtn}
                onPress={() => setPaymentModalList(null)}
                disabled={savingPayment}
              >
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.modalSaveBtn}
                onPress={handleRecordPayment}
                disabled={savingPayment}
              >
                {savingPayment ? (
                  <ActivityIndicator color="#ffffff" size="small" />
                ) : (
                  <Text style={styles.modalSaveText}>Save Payment</Text>
                )}
              </Pressable>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Quick-Paste Order Modal */}
      <Modal statusBarTranslucent visible={showQuickPasteModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Record Custom Sale Modal */}
      <Modal statusBarTranslucent visible={showRecordSaleModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
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
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>

      {/* Log Expense Modal */}
      <Modal statusBarTranslucent visible={showExpenseModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
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
                {expenseCategories.map((c) => {
                  const key = c.value || c.id || "OTHER";
                  const label = c.label || c.name || "Expense";
                  const isSelected = expenseCategoryId === key;
                  return (
                    <Pressable
                      key={key}
                      style={[
                        styles.rolePill,
                        isSelected && styles.rolePillActive,
                      ]}
                      onPress={() => {
                        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                        setExpenseCategoryId(key);
                        setExpenseError(null);
                      }}
                    >
                      <Text
                        style={[
                          styles.rolePillText,
                          isSelected && styles.rolePillTextActive,
                        ]}
                      >
                        {label}
                      </Text>
                    </Pressable>
                  );
                })}
              </ScrollView>

              {expenseError ? (
                <Text style={styles.modalInlineError}>{expenseError}</Text>
              ) : null}

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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Invite Staff Modal */}
      <Modal statusBarTranslucent visible={showInviteModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
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
              <Text style={styles.modalFieldLabel}>Select Staff Role</Text>
              <View style={styles.rolePickerRow}>
                {(["SALES", "MANAGER", "INVENTORY"] as MemberRole[]).map((r) => (
                  <Pressable
                    key={r}
                    style={[styles.rolePill, inviteRole === r && styles.rolePillActive]}
                    onPress={() => setInviteRole(r)}
                  >
                    <Text style={[styles.rolePillText, inviteRole === r && styles.rolePillTextActive]}>
                      {r === "SALES" ? "Sales Staff" : r === "MANAGER" ? "Manager" : "Inventory"}
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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Product Image Gallery Modal */}
      <Modal statusBarTranslucent visible={galleryProduct !== null} transparent animationType="slide">
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

            {/* Add Photo URL / Phone Picker Section */}
            <View style={{ marginBottom: 16, borderTopWidth: 1, borderTopColor: "#30363d", paddingTop: 12 }}>
              <Text style={styles.modalFieldLabel}>+ Attach Photo to Gallery</Text>
              <Pressable
                style={[styles.imagePickerButton, { marginBottom: 8 }]}
                onPress={() => handlePickDeviceImage((uri) => setNewPhotoUrl(uri))}
              >
                <CameraIcon size={18} color="#4ade80" />
                <Text style={styles.imagePickerButtonText}>Choose Photo from Phone</Text>
              </Pressable>
              <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                <TextInput
                  style={[styles.modalInput, { flex: 1, marginBottom: 0 }]}
                  placeholder="Or paste photo / image link (https://...)"
                  placeholderTextColor="#8a928e"
                  value={newPhotoUrl}
                  onChangeText={setNewPhotoUrl}
                  autoCapitalize="none"
                />
                <Pressable
                  style={[styles.modalSaveBtn, (!newPhotoUrl.trim() || attachingPhoto) && { opacity: 0.6 }]}
                  onPress={handleAttachPhoto}
                  disabled={!newPhotoUrl.trim() || attachingPhoto}
                >
                  {attachingPhoto ? (
                    <ActivityIndicator color="#ffffff" size="small" />
                  ) : (
                    <Text style={styles.modalSaveText}>+ Attach</Text>
                  )}
                </Pressable>
              </View>
            </View>

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
      <Modal statusBarTranslucent visible={showStorefrontModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
            <View style={styles.modalCard}>
              <Text style={styles.modalTitle}>Customize Storefront</Text>
              <Text style={styles.modalSubtitle}>
                Control how buyers experience your stall on WhatsApp and the web.
              </Text>

              <View style={{ maxHeight: 380 }}>
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
            </View>

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
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>

      {/* Edit Business Profile Modal */}
      <Modal statusBarTranslucent visible={showBusinessModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            automaticallyAdjustKeyboardInsets={true}
            contentContainerStyle={styles.modalScrollContent}
          >
            <View style={styles.modalCard}>
              <Text style={styles.modalTitle}>Edit Business / Stall</Text>
              <Text style={styles.modalFieldLabel}>Shop Name</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Shop Name"
                placeholderTextColor="#8a928e"
                value={editBizName}
                onChangeText={setEditBizName}
              />
              <Text style={styles.modalFieldLabel}>Stall Logo / Cover Photo</Text>
              {editBizLogo ? (
                <View style={styles.imagePickerPreviewBox}>
                  <Image source={{ uri: editBizLogo }} style={styles.imagePickerThumb} />
                  <View style={{ flex: 1, gap: 4 }}>
                    <Text style={styles.imagePickerSelectedText} numberOfLines={1}>
                      {editBizLogo.startsWith("file://") ? "Selected from Device" : editBizLogo}
                    </Text>
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      <Pressable
                        style={styles.imagePickerActionBtn}
                        onPress={() => handlePickDeviceImage((uri) => setEditBizLogo(uri))}
                      >
                        <Text style={styles.imagePickerActionBtnText}>Change</Text>
                      </Pressable>
                      <Pressable
                        style={[styles.imagePickerActionBtn, styles.imagePickerRemoveBtn]}
                        onPress={() => setEditBizLogo("")}
                      >
                        <Text style={[styles.imagePickerActionBtnText, { color: "#f87171" }]}>Remove</Text>
                      </Pressable>
                    </View>
                  </View>
                </View>
              ) : (
                <Pressable
                  style={styles.imagePickerButton}
                  onPress={() => handlePickDeviceImage((uri) => setEditBizLogo(uri))}
                >
                  <CameraIcon size={20} color="#4ade80" />
                  <Text style={styles.imagePickerButtonText}>Choose Stall Logo from Phone</Text>
                </Pressable>
              )}
              <Text style={styles.modalFieldLabel}>Market Stall / Address</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Market Stall / Address"
                placeholderTextColor="#8a928e"
                value={editBizAddress}
                onChangeText={setEditBizAddress}
              />
              <Text style={styles.modalFieldLabel}>Official Phone Number</Text>
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
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Security Credentials Modal (Password & Stall PIN) */}
      <Modal statusBarTranslucent visible={showPasswordModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalScrollContent}
          >
            <View style={styles.modalCard}>
              <Text style={styles.modalTitle}>Security & Stall Protection</Text>

              {/* Sub-tabs: Account Password vs Stall Security PIN */}
              <View style={styles.securityTabRow}>
                <Pressable
                  style={[
                    styles.securityTabBtn,
                    securityTab === "password" && styles.securityTabBtnActive,
                  ]}
                  onPress={() => setSecurityTab("password")}
                >
                  <Text
                    style={[
                      styles.securityTabText,
                      securityTab === "password" && styles.securityTabTextActive,
                    ]}
                  >
                    Account Password
                  </Text>
                </Pressable>
                {isOwner && (
                  <Pressable
                    style={[
                      styles.securityTabBtn,
                      securityTab === "pin" && styles.securityTabBtnActive,
                    ]}
                    onPress={() => setSecurityTab("pin")}
                  >
                    <Text
                      style={[
                        styles.securityTabText,
                        securityTab === "pin" && styles.securityTabTextActive,
                      ]}
                    >
                      Stall PIN (Owner)
                    </Text>
                  </Pressable>
                )}
              </View>

              {securityTab === "password" ? (
                /* Personal Account Password Section */
                <View>
                  <Text style={styles.modalSubtitle}>
                    Update your personal account password used to sign into AHIA.
                  </Text>
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
                    <Pressable
                      style={styles.modalCancelBtn}
                      onPress={() => setShowPasswordModal(false)}
                    >
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
              ) : (
                /* Stall Security PIN Section (Owner Only) */
                <View>
                  <Text style={styles.modalSubtitle}>
                    The Business Security PIN is linked directly to this stall. Only the Business Owner can set or change it. It protects sensitive owner actions (price changes, deleting items, and staff removal).
                  </Text>
                  <View style={styles.pinStatusBox}>
                    <LockIcon size={16} color={hasPin ? "#4ade80" : "#f59e0b"} />
                    <Text style={[styles.pinStatusText, { color: hasPin ? "#4ade80" : "#f59e0b" }]}>
                      {hasPin ? "Stall Security PIN is Active" : "No PIN Set for this Stall"}
                    </Text>
                  </View>
                  {pinSetupStep === 1 ? (
                    <View style={{ alignItems: "center", marginTop: 8 }}>
                      <Text style={styles.pinStepTitle}>Choose a 4-digit Stall Security PIN</Text>
                      <PinPad
                        length={4}
                        error={pinSetupError}
                        loading={savingPin}
                        onComplete={(pin) => {
                          setPinSetupFirst(pin);
                          setPinSetupStep(2);
                          setPinSetupError(null);
                        }}
                      />
                    </View>
                  ) : (
                    <View style={{ alignItems: "center", marginTop: 8 }}>
                      <Text style={styles.pinStepTitle}>Re-enter your 4-digit PIN to confirm</Text>
                      <PinPad
                        length={4}
                        error={pinSetupError}
                        loading={savingPin}
                        loadingMessage="Saving Security PIN..."
                        onComplete={async (confirmedPin) => {
                          if (!activeBusiness) {
                            setPinSetupError("No active business selected.");
                            return;
                          }
                          if (confirmedPin !== pinSetupFirst) {
                            setPinSetupError("PINs do not match. Please try again.");
                            void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
                            setPinSetupStep(1);
                            setPinSetupFirst("");
                            return;
                          }
                          setSavingPin(true);
                          setPinSetupError(null);
                          try {
                            await setBusinessPin(activeBusiness.id, confirmedPin);
                            setHasPin(true);
                            setPinSetupStep(1);
                            setPinSetupFirst("");
                            showToast("Stall Security PIN set successfully!");
                            setShowPasswordModal(false);
                          } catch {
                            setPinSetupError("Could not save Security PIN.");
                          } finally {
                            setSavingPin(false);
                          }
                        }}
                      />
                      <Pressable
                        style={{ marginTop: 8, padding: 6 }}
                        onPress={() => {
                          setPinSetupStep(1);
                          setPinSetupFirst("");
                          setPinSetupError(null);
                        }}
                      >
                        <Text style={{ color: "#38bdf8", fontSize: 13, fontWeight: "600" }}>Start over</Text>
                      </Pressable>
                    </View>
                  )}

                  <View style={[styles.modalButtons, { marginTop: 12 }]}>
                    <Pressable
                      style={[styles.modalCancelBtn, { width: "100%" }]}
                      onPress={() => {
                        setShowPasswordModal(false);
                        setPinSetupStep(1);
                        setPinSetupFirst("");
                        setPinSetupError(null);
                      }}
                    >
                      <Text style={styles.modalCancelText}>Cancel</Text>
                    </Pressable>
                  </View>
                </View>
              )}
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Edit User Profile Modal */}
      <Modal statusBarTranslucent visible={showProfileModal} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBackdrop}
        >
          <ScrollView
            style={{ width: "100%" }}
            keyboardShouldPersistTaps="handled"
            automaticallyAdjustKeyboardInsets={true}
            contentContainerStyle={styles.modalScrollContent}
          >
            <View style={styles.modalCard}>
              <Text style={styles.modalTitle}>Edit Your Profile</Text>
              <Text style={styles.modalSubtitle}>Update your personal account details</Text>

              <Text style={styles.modalFieldLabel}>Profile Avatar / Photo</Text>
              {editAvatarUrl ? (
                <View style={styles.imagePickerPreviewBox}>
                  <Image source={{ uri: editAvatarUrl }} style={styles.imagePickerThumb} />
                  <View style={{ flex: 1, gap: 4 }}>
                    <Text style={styles.imagePickerSelectedText} numberOfLines={1}>
                      {editAvatarUrl.startsWith("file://") ? "Selected from Device" : editAvatarUrl}
                    </Text>
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      <Pressable
                        style={styles.imagePickerActionBtn}
                        onPress={() => handlePickDeviceImage((uri) => setEditAvatarUrl(uri))}
                      >
                        <Text style={styles.imagePickerActionBtnText}>Change</Text>
                      </Pressable>
                      <Pressable
                        style={[styles.imagePickerActionBtn, styles.imagePickerRemoveBtn]}
                        onPress={() => setEditAvatarUrl("")}
                      >
                        <Text style={[styles.imagePickerActionBtnText, { color: "#f87171" }]}>Remove</Text>
                      </Pressable>
                    </View>
                  </View>
                </View>
              ) : (
                <Pressable
                  style={styles.imagePickerButton}
                  onPress={() => handlePickDeviceImage((uri) => setEditAvatarUrl(uri))}
                >
                  <CameraIcon size={20} color="#4ade80" />
                  <Text style={styles.imagePickerButtonText}>Choose Profile Photo from Phone</Text>
                </Pressable>
              )}

              <Text style={styles.modalFieldLabel}>First Name</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="First Name"
                placeholderTextColor="#8a928e"
                value={editFirstName}
                onChangeText={setEditFirstName}
              />
              <Text style={styles.modalFieldLabel}>Last Name</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Last Name"
                placeholderTextColor="#8a928e"
                value={editLastName}
                onChangeText={setEditLastName}
              />
              <Text style={styles.modalFieldLabel}>Phone Number</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Phone Number"
                placeholderTextColor="#8a928e"
                value={editPhone}
                onChangeText={setEditPhone}
                keyboardType="phone-pad"
              />
              <Text style={styles.modalFieldLabel}>Email Address</Text>
              <TextInput
                style={styles.modalInput}
                placeholder="Email Address"
                placeholderTextColor="#8a928e"
                value={editEmail}
                onChangeText={setEditEmail}
                keyboardType="email-address"
                autoCapitalize="none"
              />

              <View style={styles.modalButtons}>
                <Pressable
                  style={styles.modalCancelBtn}
                  onPress={() => setShowProfileModal(false)}
                >
                  <Text style={styles.modalCancelText}>Cancel</Text>
                </Pressable>
                <Pressable
                  style={styles.modalSaveBtn}
                  onPress={handleUpdateProfile}
                  disabled={savingProfile || !editFirstName.trim()}
                >
                  {savingProfile ? (
                    <ActivityIndicator color="#ffffff" size="small" />
                  ) : (
                    <Text style={styles.modalSaveText}>Save Profile</Text>
                  )}
                </Pressable>
              </View>
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </Modal>

      {/* Switch Business Modal */}
      <Modal statusBarTranslucent visible={showShopModal} transparent animationType="slide">
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
                  setAppSetting("last_active_tenant_id", b.id);
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

      {/* Custom Styled Sign Out Modal */}
      <Modal statusBarTranslucent visible={showSignOutModal}
        transparent
        animationType="fade"
        onRequestClose={() => setShowSignOutModal(false)}
      >
        <View style={styles.centeredModalBackdrop}>
          <View style={styles.signOutModalCard}>
            <View style={styles.signOutIconWrap}>
              <LockIcon size={28} color="#dc2626" />
            </View>
            <Text style={styles.signOutModalTitle}>Sign Out of AHIA?</Text>
            <Text style={styles.signOutModalDesc}>
              You can sign back in at any time with your phone number and password.
            </Text>
            <View style={styles.signOutModalButtons}>
              <Pressable
                style={styles.signOutCancelBtn}
                onPress={() => setShowSignOutModal(false)}
              >
                <Text style={styles.signOutCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={styles.signOutConfirmBtn}
                onPress={async () => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                  setShowSignOutModal(false);
                  clearLocalDatabase();
                  await forgetSession();
                  router.replace("/sign-in");
                }}
              >
                <Text style={styles.signOutConfirmText}>Sign Out</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const createStyles = (theme: ThemePalette) => StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: theme.bg,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.borderLight,
    backgroundColor: theme.card,
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
    color: theme.text,
    fontWeight: "700",
    fontSize: 15,
  },
  businessSub: {
    color: theme.textSecondary,
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
    backgroundColor: theme.card,
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.border,
  },
  kpiCardHighlight: {
    borderColor: "#084a2f",
  },
  kpiLabel: {
    color: theme.textSecondary,
    fontSize: 12,
    fontWeight: "600",
    marginBottom: 6,
  },
  kpiValue: {
    color: theme.text,
    fontSize: 20,
    fontWeight: "800",
    marginBottom: 4,
  },
  kpiMeta: {
    color: "#4ade80",
    fontSize: 11,
  },
  sectionHeading: {
    color: theme.text,
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
    backgroundColor: theme.card,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.border,
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
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
  },
  actionTileDesc: {
    color: theme.textSecondary,
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
    backgroundColor: theme.card,
    borderRadius: 12,
    padding: 24,
    alignItems: "center",
    borderWidth: 1,
    borderColor: theme.borderLight,
    marginVertical: 12,
  },
  emptyTitle: {
    color: theme.text,
    fontSize: 15,
    fontWeight: "700",
    marginTop: 8,
    marginBottom: 4,
  },
  emptySubtitle: {
    color: theme.textSecondary,
    fontSize: 12,
    textAlign: "center",
  },
  saleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: theme.card,
    padding: 14,
    borderRadius: 10,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: theme.borderLight,
  },
  saleReceipt: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "600",
  },
  saleDate: {
    color: theme.textSecondary,
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
    backgroundColor: theme.card,
    borderBottomWidth: 1,
    borderBottomColor: theme.borderLight,
    gap: 10,
  },
  searchBoxWrap: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: theme.bg,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.border,
    gap: 8,
    height: 42,
  },
  searchInputClean: {
    flex: 1,
    color: theme.text,
    fontSize: 13,
  },
  modeToggleBtn: {
    width: 42,
    height: 42,
    borderRadius: 8,
    backgroundColor: theme.cardHover,
    alignItems: "center",
    justifyContent: "center",
  },
  modeToggleBtnActive: {
    backgroundColor: "#084a2f",
  },
  breadcrumbBar: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: theme.card,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.borderLight,
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
    color: theme.textSecondary,
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
    backgroundColor: theme.cardHover,
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
    backgroundColor: theme.bg,
    borderBottomWidth: 1,
    borderBottomColor: theme.borderLight,
  },
  folderActionBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: theme.card,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: theme.border,
  },
  folderActionText: {
    fontSize: 12,
    fontWeight: "600",
  },
  subHeading: {
    color: theme.text,
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
    backgroundColor: theme.card,
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: theme.border,
  },
  folderIconRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  folderName: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
    marginBottom: 2,
  },
  folderMeta: {
    color: theme.textSecondary,
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
    backgroundColor: theme.card,
    padding: 14,
    borderRadius: 12,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: theme.border,
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
    color: theme.text,
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
    backgroundColor: theme.cardHover,
    borderRadius: 6,
    alignItems: "center",
  },
  stockBtnText: {
    color: theme.textSecondary,
    fontWeight: "600",
    fontSize: 12,
  },
  editBtn: {
    paddingHorizontal: 10,
    paddingVertical: 8,
    backgroundColor: theme.cardHover,
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
    backgroundColor: theme.card,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: theme.border,
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
    color: theme.text,
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 12,
  },
  treeRootNode: {
    marginBottom: 12,
    backgroundColor: theme.card,
    borderRadius: 8,
    padding: 10,
    borderWidth: 1,
    borderColor: theme.border,
  },
  treeNodeHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  treeNodeName: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
  },
  treeNodeMeta: {
    color: theme.textSecondary,
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
    color: theme.textMuted,
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
    borderBottomColor: theme.borderLight,
  },
  targetFolderName: {
    color: theme.text,
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
    color: theme.text,
    fontSize: 16,
    fontWeight: "700",
  },
  listsHeaderSubtitle: {
    color: theme.textSecondary,
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
    backgroundColor: theme.card,
    borderRadius: 12,
    padding: 14,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: theme.border,
  },
  listCardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  listCustomerName: {
    color: theme.text,
    fontSize: 16,
    fontWeight: "700",
  },
  listDate: {
    color: theme.textSecondary,
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
  badgeSmall: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  badgeSmallText: {
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  badgeWaybill: {
    backgroundColor: "rgba(245, 158, 11, 0.15)",
  },
  badgePickup: {
    backgroundColor: "rgba(56, 189, 248, 0.15)",
  },
  badgePaid: {
    backgroundColor: "rgba(74, 222, 128, 0.15)",
  },
  badgePartPaid: {
    backgroundColor: "rgba(251, 146, 60, 0.15)",
  },
  badgeUnpaid: {
    backgroundColor: "rgba(148, 163, 184, 0.15)",
  },
  fulfillmentRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 12,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  fulfillmentLabel: {
    color: theme.textSecondary,
    fontSize: 12,
    fontWeight: "600",
  },
  fulfillmentToggleBox: {
    flexDirection: "row",
    backgroundColor: theme.bg,
    borderRadius: 8,
    padding: 2,
    borderWidth: 1,
    borderColor: theme.border,
  },
  fulfillmentOption: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 6,
  },
  fulfillmentOptionActive: {
    backgroundColor: "#084a2f",
  },
  fulfillmentOptionText: {
    fontSize: 11,
    fontWeight: "600",
    color: theme.textSecondary,
  },
  fulfillmentOptionTextActive: {
    color: "#ffffff",
    fontWeight: "700",
  },
  paymentSummaryCard: {
    backgroundColor: theme.bg,
    borderRadius: 8,
    padding: 10,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: theme.border,
  },
  paymentSummaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  paymentLabel: {
    color: theme.textSecondary,
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
    marginBottom: 2,
  },
  paymentVal: {
    color: theme.text,
    fontSize: 13,
    fontWeight: "800",
  },
  recordPaymentBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#4ade80",
    paddingVertical: 8,
    borderRadius: 6,
  },
  recordPaymentBtnText: {
    color: "#084a2f",
    fontSize: 12,
    fontWeight: "700",
  },
  quickChip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: "#1e293b",
    borderWidth: 1,
    borderColor: "#334155",
  },
  quickChipText: {
    color: "#4ade80",
    fontSize: 11,
    fontWeight: "600",
  },
  methodChip: {
    flex: 1,
    alignItems: "center",
    paddingVertical: 8,
    borderRadius: 6,
    backgroundColor: "#1e293b",
    borderWidth: 1,
    borderColor: "#334155",
  },
  methodChipActive: {
    backgroundColor: "#084a2f",
    borderColor: "#4ade80",
  },
  methodChipText: {
    color: "#94a3b8",
    fontSize: 12,
    fontWeight: "700",
  },
  methodChipTextActive: {
    color: "#ffffff",
  },
  pinStepTitle: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "600",
    marginBottom: 8,
    textAlign: "center",
  },
  sectionBox: {
    backgroundColor: theme.bg,
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
    color: theme.textSecondary,
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
    borderBottomColor: theme.borderLight,
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
    color: theme.text,
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
    backgroundColor: theme.cardHover,
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
    color: theme.textSecondary,
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
    backgroundColor: theme.cardHover,
  },
  linePriceBtn: {
    width: 32,
    height: 32,
    borderRadius: 6,
    backgroundColor: theme.cardHover,
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
    borderTopWidth: 1,
    borderTopColor: theme.borderLight,
    paddingTop: 10,
    marginTop: 6,
  },
  listFooterTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  totalLabel: {
    color: theme.textSecondary,
    fontSize: 10,
    fontWeight: "600",
    textTransform: "uppercase",
  },
  totalAmount: {
    color: "#4ade80",
    fontSize: 15,
    fontWeight: "700",
  },
  statusPill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  statusPillConfirmed: {
    backgroundColor: "#dcfce7",
  },
  statusPillDraft: {
    backgroundColor: "#fef9c3",
  },
  statusPillText: {
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  statusPillTextConfirmed: {
    color: "#15803d",
  },
  statusPillTextDraft: {
    color: "#a16207",
  },
  footerActions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    alignItems: "center",
    justifyContent: "flex-end",
  },
  autoPriceBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#dcfce7",
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: "#86efac",
  },
  autoPriceBtnText: {
    color: "#084a2f",
    fontSize: 11,
    fontWeight: "700",
  },
  categoryPricePill: {
    backgroundColor: theme.card,
    borderWidth: 1,
    borderColor: theme.border,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    marginRight: 8,
  },
  categoryPricePillName: {
    color: theme.text,
    fontSize: 12,
    fontWeight: "700",
  },
  categoryPricePillPrices: {
    color: "#4ade80",
    fontSize: 10,
    fontWeight: "600",
    marginTop: 2,
  },
  applyAllCheckboxRow: {
    flexDirection: "row",
    alignItems: "center",
    marginVertical: 10,
    gap: 8,
  },
  checkboxBox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: theme.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.card,
  },
  checkboxBoxChecked: {
    backgroundColor: "#084a2f",
    borderColor: "#084a2f",
  },
  applyAllCheckboxLabel: {
    color: theme.text,
    fontSize: 12,
    flex: 1,
  },
  zeroPriceBypassBtn: {
    backgroundColor: "#fef3c7",
    borderWidth: 1,
    borderColor: "#f59e0b",
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 6,
    alignItems: "center",
  },
  zeroPriceBypassText: {
    color: "#b45309",
    fontSize: 12,
    fontWeight: "700",
  },
  modalSecondaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#f0fdf4",
    borderWidth: 1,
    borderColor: "#86efac",
    paddingVertical: 10,
    borderRadius: 8,
  },
  modalSecondaryText: {
    color: "#084a2f",
    fontSize: 13,
    fontWeight: "700",
  },
  invoiceModalHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  closeCircleBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: theme.bg,
    alignItems: "center",
    justifyContent: "center",
  },
  invoiceClientBox: {
    flexDirection: "row",
    justifyContent: "space-between",
    backgroundColor: theme.card,
    padding: 12,
    borderRadius: 8,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: theme.borderLight,
  },
  invoiceClientLabel: {
    fontSize: 10,
    fontWeight: "700",
    color: theme.textSecondary,
    letterSpacing: 0.5,
  },
  invoiceClientName: {
    fontSize: 15,
    fontWeight: "700",
    color: theme.text,
    marginTop: 2,
  },
  invoiceClientPhone: {
    fontSize: 12,
    color: theme.textSecondary,
    marginTop: 2,
  },
  invoiceTable: {
    borderWidth: 1,
    borderColor: theme.borderLight,
    borderRadius: 8,
    overflow: "hidden",
    marginBottom: 12,
  },
  invoiceTableHeader: {
    flexDirection: "row",
    backgroundColor: theme.cardHover,
    paddingVertical: 8,
    paddingHorizontal: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.borderLight,
  },
  invoiceTh: {
    fontSize: 10,
    fontWeight: "700",
    color: theme.textSecondary,
  },
  invoiceTableRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 8,
    paddingHorizontal: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.borderLight,
  },
  invoiceItemName: {
    fontSize: 13,
    fontWeight: "600",
    color: theme.text,
  },
  invoiceItemNote: {
    fontSize: 10,
    color: theme.textSecondary,
    marginTop: 1,
  },
  invoiceItemQty: {
    fontSize: 12,
    fontWeight: "600",
    color: theme.text,
  },
  invoiceItemPrice: {
    fontSize: 12,
    color: theme.text,
  },
  invoiceItemTotal: {
    fontSize: 12,
    fontWeight: "700",
    color: "#4ade80",
  },
  invoiceSummaryBox: {
    backgroundColor: theme.card,
    padding: 12,
    borderRadius: 8,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: theme.borderLight,
  },
  invoiceSummaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 3,
  },
  invoiceSummaryLabel: {
    fontSize: 12,
    color: theme.textSecondary,
  },
  invoiceSummaryValue: {
    fontSize: 12,
    fontWeight: "600",
    color: theme.text,
  },
  invoiceGrandTotalRow: {
    borderTopWidth: 1,
    borderTopColor: theme.borderLight,
    paddingTop: 8,
    marginTop: 6,
  },
  invoiceGrandTotalLabel: {
    fontSize: 14,
    fontWeight: "700",
    color: theme.text,
  },
  invoiceGrandTotalValue: {
    fontSize: 16,
    fontWeight: "800",
    color: "#4ade80",
  },
  invoiceWaybillBox: {
    backgroundColor: theme.card,
    padding: 12,
    borderRadius: 8,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: theme.borderLight,
  },
  invoiceWaybillTitle: {
    fontSize: 10,
    fontWeight: "700",
    color: "#4ade80",
    marginBottom: 4,
  },
  invoiceWaybillText: {
    fontSize: 12,
    color: theme.text,
    lineHeight: 18,
  },
  invoiceModalActions: {
    flexDirection: "row",
    gap: 8,
    marginTop: 6,
    marginBottom: 16,
  },
  invoiceExportPdfBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#084a2f",
    paddingVertical: 12,
    borderRadius: 8,
  },
  invoiceExportPdfText: {
    color: "#ffffff",
    fontSize: 13,
    fontWeight: "700",
  },
  invoiceShareWaBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#25d366",
    paddingVertical: 12,
    borderRadius: 8,
  },
  invoiceShareWaText: {
    color: "#ffffff",
    fontSize: 13,
    fontWeight: "700",
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
    backgroundColor: theme.bg,
    padding: 10,
    borderRadius: 6,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: theme.border,
  },
  marginPreviewLabel: {
    color: theme.textSecondary,
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
    backgroundColor: theme.card,
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#084a2f",
    marginBottom: 20,
  },
  tradingSummaryLabel: {
    color: theme.textSecondary,
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
    color: theme.textSecondary,
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
    backgroundColor: theme.cardHover,
  },
  tradingPillActive: {
    backgroundColor: "#084a2f",
  },
  tradingPillText: {
    color: theme.textSecondary,
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
    color: theme.textMuted,
  },
  voidBtn: {
    backgroundColor: theme.cardHover,
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
    backgroundColor: theme.bg,
    marginBottom: 6,
    borderWidth: 1,
    borderColor: theme.borderLight,
  },
  productPickRowActive: {
    borderColor: "#4ade80",
    backgroundColor: "#0d281e",
  },
  productPickName: {
    color: theme.text,
    fontSize: 13,
    fontWeight: "600",
  },
  productPickNameActive: {
    color: "#4ade80",
  },
  productPickMeta: {
    color: theme.textSecondary,
    fontSize: 11,
  },
  userProfileCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    backgroundColor: theme.card,
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.border,
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
    color: theme.text,
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 2,
  },
  userProfilePhone: {
    color: theme.textSecondary,
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
    backgroundColor: theme.card,
    padding: 14,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: theme.border,
    alignItems: "flex-start",
    gap: 4,
  },
  everythingTileTitle: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
    marginTop: 4,
  },
  everythingTileDesc: {
    color: theme.textSecondary,
    fontSize: 11,
  },
  moreCard: {
    backgroundColor: theme.card,
    borderRadius: 12,
    padding: 14,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: theme.border,
  },
  moreCardTitle: {
    color: theme.text,
    fontSize: 15,
    fontWeight: "700",
  },
  moreCardDesc: {
    color: theme.textSecondary,
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
    borderBottomColor: theme.borderLight,
  },
  memberName: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "600",
  },
  memberRole: {
    color: theme.textSecondary,
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
    color: theme.textSecondary,
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
    backgroundColor: theme.card,
    borderTopWidth: 1,
    borderTopColor: theme.borderLight,
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
    color: theme.textSecondary,
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
  modalScrollContent: {
    flexGrow: 1,
    justifyContent: "center",
    paddingVertical: 24,
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.8)",
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 16,
  },
  modalCard: {
    backgroundColor: theme.card,
    borderRadius: 24,
    padding: 22,
    width: "100%",
    borderWidth: 1,
    borderColor: theme.border,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.3,
    shadowRadius: 20,
    elevation: 10,
  },
  modalTitle: {
    color: theme.text,
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 4,
  },
  modalSubtitle: {
    color: theme.textSecondary,
    fontSize: 12,
    marginBottom: 10,
  },
  modalFieldLabel: {
    color: theme.textSecondary,
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
    backgroundColor: theme.bg,
    color: theme.text,
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
    backgroundColor: theme.cardHover,
    padding: 12,
    borderRadius: 8,
    alignItems: "center",
  },
  modalCancelText: {
    color: theme.textSecondary,
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
  modalInlineError: {
    color: "#f87171",
    fontSize: 13,
    fontWeight: "600",
    marginBottom: 8,
    textAlign: "center",
  },
  rolePickerRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 12,
  },
  rolePill: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: theme.cardHover,
    borderRadius: 6,
    alignItems: "center",
    marginRight: 6,
  },
  rolePillActive: {
    backgroundColor: "#084a2f",
  },
  rolePillText: {
    color: theme.textSecondary,
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
    backgroundColor: theme.cardHover,
  },
  storefrontStatusText: {
    color: "#ffffff",
    fontSize: 9,
    fontWeight: "800",
  },
  publishToggleBtn: {
    backgroundColor: theme.cardHover,
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: theme.border,
  },
  publishToggleBtnText: {
    color: theme.text,
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
    color: theme.textSecondary,
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
    borderBottomColor: theme.borderLight,
  },
  invitationPhone: {
    color: theme.text,
    fontSize: 13,
    fontWeight: "600",
  },
  invitationMeta: {
    color: theme.textSecondary,
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
    backgroundColor: theme.bg,
    padding: 10,
    borderRadius: 8,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: theme.borderLight,
  },
  galleryImageUrl: {
    color: theme.text,
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
    color: theme.textSecondary,
    fontSize: 11,
  },
  makePrimaryBtn: {
    backgroundColor: theme.cardHover,
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
    backgroundColor: theme.cardHover,
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
    backgroundColor: theme.bg,
    padding: 10,
    borderRadius: 8,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: theme.borderLight,
  },
  passwordStrengthRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 6,
  },
  passwordStrengthLabel: {
    color: theme.textSecondary,
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
    backgroundColor: theme.cardHover,
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
    color: theme.textSecondary,
    fontSize: 11,
    marginTop: 2,
  },
  shopOption: {
    padding: 14,
    backgroundColor: theme.bg,
    borderRadius: 8,
    marginBottom: 8,
  },
  shopOptionActive: {
    borderColor: "#084a2f",
    borderWidth: 1,
  },
  shopOptionName: {
    color: theme.text,
    fontSize: 14,
  },
  shopOptionNameActive: {
    color: "#4ade80",
    fontWeight: "700",
  },
  kpiCardWarn: {
    borderColor: "#78350f",
  },
  kpiValueWarn: {
    color: "#f59e0b",
  },
  lowStockSection: {
    backgroundColor: theme.card,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#78350f",
    padding: 14,
    marginBottom: 16,
  },
  lowStockSectionTitle: {
    color: "#f59e0b",
    fontSize: 14,
    fontWeight: "700",
  },
  lowStockBadge: {
    backgroundColor: "#78350f",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
  },
  lowStockBadgeText: {
    color: "#fde047",
    fontSize: 11,
    fontWeight: "700",
  },
  lowStockRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.borderLight,
  },
  lowStockName: {
    color: theme.text,
    fontSize: 13,
    fontWeight: "600",
  },
  lowStockQty: {
    color: theme.textSecondary,
    fontSize: 11,
    marginTop: 2,
  },
  lowStockRestockBtn: {
    backgroundColor: "#064e3b",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
  },
  lowStockRestockBtnText: {
    color: "#4ade80",
    fontSize: 11,
    fontWeight: "700",
  },
  productNameRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  itemPublishBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  itemPublishLive: {
    backgroundColor: "#064e3b",
  },
  itemPublishDraft: {
    backgroundColor: theme.cardHover,
  },
  itemPublishBadgeText: {
    fontSize: 9,
    fontWeight: "700",
  },
  itemPublishBadgeTextLive: {
    color: "#4ade80",
  },
  itemPublishBadgeTextDraft: {
    color: theme.textSecondary,
  },
  shareBtn: {
    padding: 6,
    backgroundColor: "#075985",
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
  },
  userProfileEmail: {
    color: theme.textSecondary,
    fontSize: 12,
    marginTop: 1,
  },
  editProfileBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: theme.cardHover,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: theme.border,
    alignSelf: "flex-start",
  },
  editProfileBtnText: {
    color: theme.text,
    fontSize: 12,
    fontWeight: "600",
  },
  signOutModalCard: {
    backgroundColor: theme.card,
    borderRadius: 16,
    padding: 24,
    alignItems: "center",
    width: "100%",
    maxWidth: 340,
    borderWidth: 1,
    borderColor: theme.border,
  },
  signOutIconWrap: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: "#450a0a",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 16,
  },
  signOutModalTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: theme.text,
    marginBottom: 8,
    textAlign: "center",
  },
  signOutModalDesc: {
    fontSize: 14,
    color: theme.textSecondary,
    textAlign: "center",
    lineHeight: 20,
    marginBottom: 20,
  },
  signOutModalButtons: {
    flexDirection: "row",
    gap: 12,
    width: "100%",
  },
  signOutCancelBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: theme.cardHover,
    alignItems: "center",
    justifyContent: "center",
  },
  signOutCancelText: {
    color: theme.text,
    fontWeight: "600",
    fontSize: 14,
  },
  signOutConfirmBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: "#dc2626",
    alignItems: "center",
    justifyContent: "center",
  },
  signOutConfirmText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 14,
  },
  themeToggleBtn: {
    flex: 1,
    paddingVertical: 10,
    paddingHorizontal: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.cardHover,
    alignItems: "center",
    justifyContent: "center",
  },
  themeToggleBtnActive: {
    borderColor: "#4ade80",
    backgroundColor: "#064e3b",
  },
  themeToggleBtnText: {
    color: theme.textSecondary,
    fontSize: 12,
    fontWeight: "600",
    textAlign: "center",
  },
  themeToggleBtnTextActive: {
    color: "#ffffff",
    fontWeight: "700",
  },
  // Dedicated Team Management Styles
  teamTopBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
    backgroundColor: theme.card,
    marginBottom: 12,
  },
  teamBackBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: theme.cardHover,
    borderWidth: 1,
    borderColor: theme.border,
  },
  teamBackBtnText: {
    color: theme.text,
    fontSize: 13,
    fontWeight: "600",
  },
  teamInviteTopBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#084a2f",
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 8,
  },
  teamInviteTopBtnText: {
    color: "#ffffff",
    fontSize: 13,
    fontWeight: "700",
  },
  teamBannerCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: theme.card,
    marginHorizontal: 16,
    marginBottom: 12,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.border,
  },
  teamBannerIconWrap: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: theme.mode === "light" ? "#e6f4ea" : "#0d281e",
    alignItems: "center",
    justifyContent: "center",
  },
  teamBannerTitle: {
    color: theme.text,
    fontSize: 16,
    fontWeight: "700",
  },
  teamBannerSub: {
    color: theme.textSecondary,
    fontSize: 12,
    marginTop: 2,
    lineHeight: 16,
  },
  teamStatsRow: {
    flexDirection: "row",
    gap: 8,
    marginHorizontal: 16,
    marginBottom: 12,
  },
  teamStatBox: {
    flex: 1,
    backgroundColor: theme.card,
    borderRadius: 10,
    padding: 12,
    alignItems: "center",
    borderWidth: 1,
    borderColor: theme.border,
  },
  teamStatValue: {
    color: theme.mode === "light" ? "#084a2f" : "#4ade80",
    fontSize: 18,
    fontWeight: "800",
  },
  teamStatLabel: {
    color: theme.textSecondary,
    fontSize: 11,
    fontWeight: "600",
    marginTop: 4,
  },
  teamMemberCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.borderLight,
  },
  teamMemberAvatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: theme.mode === "light" ? "#084a2f" : "#21262d",
    alignItems: "center",
    justifyContent: "center",
  },
  teamMemberAvatarText: {
    color: "#ffffff",
    fontWeight: "800",
    fontSize: 15,
  },
  teamMemberName: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
  },
  teamMemberMeta: {
    color: theme.textSecondary,
    fontSize: 12,
    marginTop: 2,
  },
  sentInviteCard: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: theme.cardHover,
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: theme.border,
    marginTop: 10,
  },
  sentInviteTarget: {
    color: theme.text,
    fontSize: 13,
    fontWeight: "700",
  },
  sentInviteRolePill: {
    backgroundColor: theme.mode === "light" ? "#e6f4ea" : "#0d281e",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#4ade80",
  },
  sentInviteRolePillText: {
    color: theme.mode === "light" ? "#084a2f" : "#4ade80",
    fontSize: 11,
    fontWeight: "700",
  },
  sentInviteStatus: {
    color: theme.textSecondary,
    fontSize: 11,
    marginTop: 4,
  },
  inviteShareWhatsAppBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#25d366",
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 8,
    marginLeft: 8,
  },
  inviteShareWhatsAppBtnText: {
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "700",
  },
  emptyInviteBox: {
    paddingVertical: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  emptyInviteBtn: {
    marginTop: 10,
    backgroundColor: "#084a2f",
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 8,
  },
  emptyInviteBtnText: {
    color: "#ffffff",
    fontSize: 13,
    fontWeight: "700",
  },
  roleGuideList: {
    marginTop: 10,
    gap: 8,
  },
  roleGuideItem: {
    backgroundColor: theme.cardHover,
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.border,
  },
  roleGuideName: {
    color: theme.mode === "light" ? "#084a2f" : "#4ade80",
    fontSize: 13,
    fontWeight: "700",
    marginBottom: 2,
  },
  roleGuideDesc: {
    color: theme.textSecondary,
    fontSize: 12,
    lineHeight: 16,
  },
  securityTabRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 16,
    marginTop: 8,
  },
  securityTabBtn: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.cardHover,
    alignItems: "center",
  },
  securityTabBtnActive: {
    borderColor: "#4ade80",
    backgroundColor: theme.mode === "light" ? "#e6f4ea" : "#064e3b",
  },
  securityTabText: {
    color: theme.textSecondary,
    fontSize: 12,
    fontWeight: "600",
  },
  securityTabTextActive: {
    color: theme.mode === "light" ? "#084a2f" : "#ffffff",
    fontWeight: "700",
  },
  pinStatusBox: {
    padding: 12,
    borderRadius: 8,
    backgroundColor: theme.cardHover,
    borderWidth: 1,
    borderColor: theme.border,
    marginBottom: 16,
  },
  pinStatusText: {
    fontSize: 13,
    fontWeight: "600",
  },
  centeredModalBackdrop: {
    flex: 1,
    backgroundColor: theme.modalBackdrop,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 20,
  },
  imagePickerButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 8,
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: "#4ade80",
    backgroundColor: theme.mode === "light" ? "#f0fdf4" : "#062e1e",
    marginBottom: 14,
  },
  imagePickerButtonText: {
    color: "#4ade80",
    fontSize: 14,
    fontWeight: "700",
  },
  imagePickerPreviewBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.cardHover,
    marginBottom: 14,
  },
  imagePickerThumb: {
    width: 60,
    height: 60,
    borderRadius: 6,
    backgroundColor: "#1e293b",
  },
  imagePickerSelectedText: {
    fontSize: 13,
    fontWeight: "600",
    color: theme.text,
  },
  imagePickerActionBtn: {
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: 4,
    backgroundColor: theme.card,
    borderWidth: 1,
    borderColor: theme.border,
  },
  imagePickerRemoveBtn: {
    borderColor: "rgba(248, 113, 113, 0.4)",
  },
  imagePickerActionBtnText: {
    fontSize: 12,
    fontWeight: "600",
    color: theme.text,
  },
});
