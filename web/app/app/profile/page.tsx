"use client";

/**
 * The person's own account, and the business they are working in.
 *
 * Two things live here because they are the same question from a trader's point of view: "who am I in
 * this system, and what does my shop say about itself". Your name and how you sign in; your password;
 * the shop's name, phone and address; and the businesses you belong to with the role you hold in each.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { ArrowLeftIcon } from "@/components/icons";
import { Button, Card, Field, Pill, PasswordField, Toast } from "@/components/ui";
import {
  cachedRead,
  changePassword,
  currentUser,
  firstPaint,
  getBusiness,
  getStorefront,
  listBusinesses,
  rememberedBusinessId,
  signOut,
  updateBusiness,
  updateProfile,
  updateStorefront,
  type Tenant,
  type TenantSummary,
  type UserProfile,
} from "@/lib/api";
import { explainFailure, type Explained } from "@/lib/errors";
import { formatMoney } from "@/lib/format";
import {
  PASSWORD_MINIMUM_LENGTH,
  passwordChecks,
  passwordStrength,
} from "@/lib/passwords";
import { CheckList, StrengthMeter } from "@/components/ui";
import styles from "./profile.module.css";

type Notice = { message: string; tone: "good" | "bad"; hint?: string };

function isDarkColor(hex: string): boolean {
  const clean = hex.replace("#", "");
  if (clean.length === 3) {
    const r = parseInt(clean[0] + clean[0], 16);
    const g = parseInt(clean[1] + clean[1], 16);
    const b = parseInt(clean[2] + clean[2], 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5;
  }
  if (clean.length === 6) {
    const r = parseInt(clean.slice(0, 2), 16);
    const g = parseInt(clean.slice(2, 4), 16);
    const b = parseInt(clean.slice(4, 6), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5;
  }
  return false;
}

export default function Profile() {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(() => cachedRead<UserProfile>("/api/v1/users/me"));
  const [businesses, setBusinesses] = useState<TenantSummary[]>(() => cachedRead<TenantSummary[]>("/api/v1/tenants") ?? []);
  const [business, setBusiness] = useState<Tenant | null>(() =>
    firstPaint<Tenant>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}`),
  );
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  // Edit toggles: forms are not left open permanently
  const [editingProfile, setEditingProfile] = useState(false);
  const [editingBusiness, setEditingBusiness] = useState(false);

  // Your details
  const [firstName, setFirstName] = useState(() => cachedRead<UserProfile>("/api/v1/users/me")?.first_name ?? "");
  const [lastName, setLastName] = useState(() => cachedRead<UserProfile>("/api/v1/users/me")?.last_name ?? "");
  const [phone, setPhone] = useState(() => cachedRead<UserProfile>("/api/v1/users/me")?.phone ?? "");
  const [email, setEmail] = useState(() => cachedRead<UserProfile>("/api/v1/users/me")?.email ?? "");

  // The business's details
  const [businessName, setBusinessName] = useState(() => firstPaint<Tenant>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}`)?.name ?? "");
  const [businessPhone, setBusinessPhone] = useState(() => firstPaint<Tenant>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}`)?.phone ?? "");
  const [businessAddress, setBusinessAddress] = useState(() => firstPaint<Tenant>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}`)?.address ?? "");
  const [businessCity, setBusinessCity] = useState(() => firstPaint<Tenant>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}`)?.city ?? "");
  const [businessState, setBusinessState] = useState(() => firstPaint<Tenant>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}`)?.state ?? "");

  // Shop Customization
  const [storefrontHeadline, setStorefrontHeadline] = useState("");
  const [storefrontDescription, setStorefrontDescription] = useState("");
  const [storefrontPhone, setStorefrontPhone] = useState("");
  const [themeColor, setThemeColor] = useState("#084a2f");
  const [themeBg, setThemeBg] = useState("#fbf7f0");
  const [themeBgImage, setThemeBgImage] = useState("");
  const [previewMode, setPreviewMode] = useState<"desktop" | "mobile">("desktop");
  const [isAppearanceExpanded, setIsAppearanceExpanded] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Baseline appearance for dirty check
  const [initialAppearance, setInitialAppearance] = useState({
    headline: "",
    description: "",
    phone: "",
    color: "#084a2f",
    bg: "#fbf7f0",
    bgImage: "",
  });

  // Password
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const report = useCallback((error: unknown) => {
    const explained: Explained = explainFailure(error);
    setNotice({ message: explained.message, hint: explained.hint, tone: "bad" });
  }, []);

  const run = useCallback(
    async (key: string, action: () => Promise<void>) => {
      setBusyAction(key);
      setNotice(null);
      try {
        await action();
      } catch (error) {
        report(error);
      } finally {
        setBusyAction(null);
      }
    },
    [report],
  );

  useEffect(() => {
    void (async () => {
      try {
        const [profile, found] = await Promise.all([currentUser(), listBusinesses()]);
        setUser(profile);
        setFirstName(profile.first_name);
        setLastName(profile.last_name ?? "");
        setPhone(profile.phone ?? "");
        setEmail(profile.email ?? "");
        setBusinesses(found);
        const remembered =
          typeof window === "undefined" ? null : window.localStorage.getItem("ahia.business");
        const chosen = found.find((candidate) => candidate.id === remembered) ?? found[0];
        if (chosen) {
          const detail = await getBusiness(chosen.id);
          setBusiness(detail);
          setBusinessName(detail.name);
          setBusinessPhone(detail.phone ?? "");
          setBusinessAddress(detail.address ?? "");
          setBusinessCity(detail.city ?? "");
          setBusinessState(detail.state ?? "");

          let loadedHeadline = "";
          let loadedDesc = "";
          let loadedPhone = "";
          let themeColorFromDesc: string | null = null;
          let themeBgFromDesc: string | null = null;
          let themeBgImageFromDesc: string | null = null;
          try {
            const sf = await getStorefront(chosen.id);
            loadedHeadline = sf.headline ?? "";
            const rawDesc = sf.description ?? "";
            loadedPhone = sf.contact_phone ?? "";

            // Parse embedded theme if present
            const themeMatch = rawDesc.match(/<!--\s*ahia-theme:({[\s\S]*?})\s*-->/);
            if (themeMatch) {
              try {
                const parsed = JSON.parse(themeMatch[1]);
                if (parsed.color) themeColorFromDesc = parsed.color;
                if (parsed.bg) themeBgFromDesc = parsed.bg;
                if (parsed.bgImage) themeBgImageFromDesc = parsed.bgImage;
              } catch {
                // ignore parse failure
              }
              loadedDesc = rawDesc.replace(/<!--\s*ahia-theme:[\s\S]*?-->/g, "").trim();
            } else {
              loadedDesc = rawDesc;
            }

            setStorefrontHeadline(loadedHeadline);
            setStorefrontDescription(loadedDesc);
            setStorefrontPhone(loadedPhone);
          } catch {
            // storefront might not be created or published yet
          }

          let loadedColor = themeColorFromDesc || "#084a2f";
          let loadedBg = themeBgFromDesc || "#fbf7f0";
          let loadedBgImage = themeBgImageFromDesc || "";
          if (typeof window !== "undefined") {
            try {
              const savedTheme = window.localStorage.getItem(`ahia.theme.${chosen.id}`);
              if (savedTheme) {
                const parsed = JSON.parse(savedTheme);
                if (parsed.color) {
                  loadedColor = parsed.color;
                }
                if (parsed.bg) {
                  loadedBg = parsed.bg;
                }
                if (parsed.bgImage) {
                  loadedBgImage = parsed.bgImage;
                }
              }
            } catch {
              // ignore parse errors
            }
          }
          setThemeColor(loadedColor);
          setThemeBg(loadedBg);
          setThemeBgImage(loadedBgImage);

          setInitialAppearance({
            headline: loadedHeadline,
            description: loadedDesc,
            phone: loadedPhone,
            color: loadedColor,
            bg: loadedBg,
            bgImage: loadedBgImage,
          });
        }
      } catch {
        router.replace("/start");
      }
    })();
  }, [router]);

  // Dirty checking
  const isProfileDirty = useMemo(() => {
    if (!user) return false;
    return (
      firstName.trim() !== (user.first_name || "") ||
      lastName.trim() !== (user.last_name || "") ||
      phone.trim() !== (user.phone || "") ||
      email.trim() !== (user.email || "")
    );
  }, [user, firstName, lastName, phone, email]);

  const isBusinessDirty = useMemo(() => {
    if (!business) return false;
    return (
      businessName.trim() !== (business.name || "") ||
      businessPhone.trim() !== (business.phone || "") ||
      businessAddress.trim() !== (business.address || "") ||
      businessCity.trim() !== (business.city || "") ||
      businessState.trim() !== (business.state || "")
    );
  }, [business, businessName, businessPhone, businessAddress, businessCity, businessState]);

  const isAppearanceDirty = useMemo(() => {
    return (
      storefrontHeadline.trim() !== initialAppearance.headline ||
      storefrontDescription.trim() !== initialAppearance.description ||
      storefrontPhone.trim() !== initialAppearance.phone ||
      themeColor !== initialAppearance.color ||
      themeBg !== initialAppearance.bg ||
      themeBgImage.trim() !== initialAppearance.bgImage
    );
  }, [storefrontHeadline, storefrontDescription, storefrontPhone, themeColor, themeBg, themeBgImage, initialAppearance]);

  const handleImageFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const dataUrl = event.target?.result;
      if (typeof dataUrl === "string") {
        setThemeBgImage(dataUrl);
      }
    };
    reader.readAsDataURL(file);
  };

  const handleLogout = async () => {
    try {
      await signOut();
    } catch {
      // Continue cleanup on failure
    }
    if (typeof window !== "undefined") {
      window.localStorage.removeItem("ahia.business");
    }
    router.replace("/start");
  };

  const strength = passwordStrength(newPassword);
  const checks = passwordChecks(newPassword);
  const passwordsMatch = confirmation.length > 0 && confirmation === newPassword;

  if (!user) {
    return <main className={styles.page} />;
  }

  return (
    <main className={styles.page}>
      <div className={styles.content}>
        <Link className={styles.backLink} href="/app">
          <ArrowLeftIcon size={16} />
          <span>Back to shop</span>
        </Link>

        <div className={styles.identity}>
          <span className={styles.avatar} aria-hidden>
            {(user.first_name[0] ?? "").toUpperCase()}
            {(user.last_name ?? "").slice(0, 1).toUpperCase()}
          </span>
          <div>
            <h1 className={styles.name}>
              {user.first_name} {user.last_name}
            </h1>
            <p className={styles.identityMeta}>
              {businesses.length === 1
                ? "One business"
                : `${businesses.length} businesses`}{" "}
              on this account
            </p>
          </div>
        </div>

        {/* Your details */}
        <Card
          title="Your details"
          action={
            !editingProfile ? (
              <button
                type="button"
                className={styles.secondaryAction}
                onClick={() => setEditingProfile(true)}
              >
                Edit details
              </button>
            ) : null
          }
        >
          {!editingProfile ? (
            <div className={styles.detailsList}>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Full Name</span>
                <span className={styles.detailValue}>
                  {user.first_name} {user.last_name || ""}
                </span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Phone Number</span>
                <span className={styles.detailValue}>{user.phone || "Not provided"}</span>
              </div>
              <div className={styles.detailRow}>
                <span className={styles.detailLabel}>Email Address</span>
                <span className={styles.detailValue}>{user.email || "Not provided"}</span>
              </div>
            </div>
          ) : (
            <div>
              <div className={styles.grid}>
                <Field
                  label="First name"
                  id="first_name"
                  value={firstName}
                  onChange={setFirstName}
                  autoComplete="given-name"
                />
                <Field
                  label="Surname"
                  id="last_name"
                  value={lastName}
                  onChange={setLastName}
                  autoComplete="family-name"
                />
                <Field
                  label="Phone number"
                  id="phone"
                  value={phone}
                  onChange={setPhone}
                  inputMode="tel"
                  autoComplete="tel"
                  hint="This is how you sign in, and how customers reach you."
                />
                <Field
                  label="Email address"
                  id="email"
                  value={email}
                  onChange={setEmail}
                  inputMode="email"
                  autoComplete="email"
                  optional
                  hint="Receipts and reports are sent here."
                />
              </div>
              <div className={styles.formActions}>
                <button
                  type="button"
                  className={styles.secondaryAction}
                  onClick={() => {
                    setFirstName(user.first_name);
                    setLastName(user.last_name ?? "");
                    setPhone(user.phone ?? "");
                    setEmail(user.email ?? "");
                    setEditingProfile(false);
                  }}
                >
                  Cancel
                </button>
                <Button
                  busy={busyAction === "profile"}
                  disabled={!isProfileDirty || busyAction === "profile"}
                  onClick={() =>
                    run("profile", async () => {
                      const saved = await updateProfile({
                        first_name: firstName.trim(),
                        last_name: lastName.trim(),
                        phone: phone.trim() || undefined,
                        email: email.trim() || undefined,
                      });
                      setUser(saved);
                      setEditingProfile(false);
                      setNotice({ message: "Your details are saved.", tone: "good" });
                    })
                  }
                >
                  Save my details
                </Button>
              </div>
            </div>
          )}
        </Card>

        {/* Business details */}
        {business ? (
          <Card
            title={`About ${business.name}`}
            action={
              !editingBusiness ? (
                <button
                  type="button"
                  className={styles.secondaryAction}
                  onClick={() => setEditingBusiness(true)}
                >
                  Edit business
                </button>
              ) : null
            }
          >
            {!editingBusiness ? (
              <div className={styles.detailsList}>
                <div className={styles.detailRow}>
                  <span className={styles.detailLabel}>Business Name</span>
                  <span className={styles.detailValue}>{business.name}</span>
                </div>
                <div className={styles.detailRow}>
                  <span className={styles.detailLabel}>Business Phone</span>
                  <span className={styles.detailValue}>{business.phone || "Not provided"}</span>
                </div>
                <div className={styles.detailRow}>
                  <span className={styles.detailLabel}>Location / Address</span>
                  <span className={styles.detailValue}>
                    {[business.address, business.city, business.state].filter(Boolean).join(", ") ||
                      "Not provided"}
                  </span>
                </div>
                <p className={styles.note}>
                  Money is recorded in {business.currency}, and the public shop address is{" "}
                  <strong>/shop/{business.public_path}</strong>.
                </p>
              </div>
            ) : (
              <div>
                <div className={styles.grid}>
                  <Field
                    label="Business name"
                    id="business_name"
                    value={businessName}
                    onChange={setBusinessName}
                  />
                  <Field
                    label="Business phone"
                    id="business_phone"
                    value={businessPhone}
                    onChange={setBusinessPhone}
                    inputMode="tel"
                    hint="Shown to customers on the shop page."
                  />
                  <Field
                    label="Street address"
                    id="business_address"
                    value={businessAddress}
                    onChange={setBusinessAddress}
                  />
                  <Field
                    label="City"
                    id="business_city"
                    value={businessCity}
                    onChange={setBusinessCity}
                  />
                  <Field
                    label="State"
                    id="business_state"
                    value={businessState}
                    onChange={setBusinessState}
                  />
                </div>
                <p className={styles.note}>
                  Money is recorded in {business.currency}, and the public address is{" "}
                  <strong>/shop/{business.public_path}</strong>.
                </p>
                <div className={styles.formActions}>
                  <button
                    type="button"
                    className={styles.secondaryAction}
                    onClick={() => {
                      setBusinessName(business.name);
                      setBusinessPhone(business.phone ?? "");
                      setBusinessAddress(business.address ?? "");
                      setBusinessCity(business.city ?? "");
                      setBusinessState(business.state ?? "");
                      setEditingBusiness(false);
                    }}
                  >
                    Cancel
                  </button>
                  <Button
                    busy={busyAction === "business"}
                    disabled={!isBusinessDirty || busyAction === "business"}
                    onClick={() =>
                      run("business", async () => {
                        const saved = await updateBusiness(business.id, {
                          name: businessName.trim(),
                          phone: businessPhone.trim() || undefined,
                          address: businessAddress.trim() || undefined,
                          city: businessCity.trim() || undefined,
                          state: businessState.trim() || undefined,
                        });
                        setBusiness(saved);
                        setEditingBusiness(false);
                        setNotice({ message: "The business details are saved.", tone: "good" });
                      })
                    }
                  >
                    Save the business details
                  </Button>
                </div>
              </div>
            )}
          </Card>
        ) : null}

        {/* Shop Appearance & Live Customization */}
        {/* Shop Appearance & Live Customization */}
        {business ? (
          <Card title="Shop Appearance & Storefront Branding">
            {!isAppearanceExpanded ? (
              <div className={styles.appearanceCollapsed}>
                <div className={styles.appearanceSummaryRow}>
                  <div className={styles.themeChipsGroup}>
                    <div className={styles.chipWrap}>
                      <span className={styles.chipLabel}>Accent</span>
                      <span className={styles.chipSwatch} style={{ background: themeColor }} />
                    </div>
                    <div className={styles.chipWrap}>
                      <span className={styles.chipLabel}>Surface</span>
                      <span
                        className={styles.chipSwatch}
                        style={{ background: themeBg, border: "1px solid var(--line-strong)" }}
                      />
                    </div>
                  </div>
                  <div className={styles.appearanceTextSummary}>
                    <span className={styles.summaryHeadline}>
                      {storefrontHeadline || "Wholesale & Retail Market Catalog"}
                    </span>
                    <span className={styles.summaryPath}>
                      Public storefront: /shop/{business.public_path}
                    </span>
                  </div>
                </div>

                <div style={{ marginTop: "14px", display: "flex", gap: "10px", flexWrap: "wrap" }}>
                  <Button onClick={() => setIsAppearanceExpanded(true)}>
                    Customize Colors & Storefront
                  </Button>
                  <a
                    className={styles.secondaryAction}
                    href={business.public_path}
                    target="_blank"
                    rel="noreferrer noopener"
                    style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}
                  >
                    View Live Public Shop
                  </a>
                </div>
              </div>
            ) : (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                  <p className={styles.note} style={{ margin: 0 }}>
                    Customize the colors, banner and text your customers see when they open your link.
                  </p>
                  <button
                    type="button"
                    className={styles.secondaryAction}
                    onClick={() => setIsAppearanceExpanded(false)}
                  >
                    Collapse Studio
                  </button>
                </div>

                {/* 1. Quick Market Presets */}
                <div style={{ marginBottom: "20px" }}>
                  <span style={{ fontSize: "13px", fontWeight: 700 }}>
                    Market Presets (1-tap theme for both accent & background)
                  </span>
                  <div className={styles.presetThemesGrid}>
                    {[
                      { name: "Classic Forest Green", color: "#084a2f", bg: "#fbf7f0" },
                      { name: "Deep Navy Blue", color: "#1e3a8a", bg: "#f8fafc" },
                      { name: "Burgundy Wine", color: "#831843", bg: "#fff1f2" },
                      { name: "Warm Amber Gold", color: "#b45309", bg: "#fefce8" },
                      { name: "Steel Cyan", color: "#0e7490", bg: "#f0fdfa" },
                      { name: "Royal Purple", color: "#581c87", bg: "#faf5ff" },
                      { name: "Charcoal Slate", color: "#1e293b", bg: "#f1f5f9" },
                      { name: "Dark Onyx", color: "#0f172a", bg: "#18181b" },
                    ].map((preset) => {
                      const isSelected = themeColor === preset.color && themeBg === preset.bg;
                      return (
                        <button
                          key={preset.name}
                          type="button"
                          className={`${styles.presetThemeBtn} ${isSelected ? styles.presetThemeBtnSelected : ""}`}
                          onClick={() => {
                            setThemeColor(preset.color);
                            setThemeBg(preset.bg);
                          }}
                        >
                          <span className={styles.presetDualDot}>
                            <span className={styles.presetDotHalf} style={{ background: preset.color }} />
                            <span className={styles.presetDotHalf} style={{ background: preset.bg }} />
                          </span>
                          <span className={styles.presetThemeName}>{preset.name}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* 2. Living Palette of Shades */}
                <div style={{ marginBottom: "20px" }}>
                  <span style={{ fontSize: "13px", fontWeight: 700 }}>
                    Living Shade Spectrum (Tap any color)
                  </span>
                  {[
                    {
                      family: "Forest & Leaf Greens",
                      shades: ["#10b981", "#16a34a", "#084a2f", "#064e3b"],
                    },
                    {
                      family: "Royal & Ocean Blues",
                      shades: ["#0284c7", "#2563eb", "#1e3a8a", "#172554"],
                    },
                    {
                      family: "Amber & Terracotta",
                      shades: ["#ea580c", "#d97706", "#b45309", "#7c2d12"],
                    },
                    {
                      family: "Crimson & Wine",
                      shades: ["#e11d48", "#dc2626", "#b91c1c", "#831843"],
                    },
                    {
                      family: "Purples & Indigo",
                      shades: ["#a855f7", "#7c3aed", "#4f46e5", "#4c1d95"],
                    },
                    {
                      family: "Slate & Charcoal",
                      shades: ["#64748b", "#334155", "#1e293b", "#0a0a0a"],
                    },
                  ].map((group) => (
                    <div key={group.family} className={styles.shadesFamilyRow}>
                      <span style={{ fontSize: "11px", color: "var(--ink-3)", fontWeight: 600 }}>
                        {group.family}
                      </span>
                      <div className={styles.shadesRow}>
                        {group.shades.map((shade) => (
                          <button
                            key={shade}
                            type="button"
                            className={`${styles.swatch} ${themeColor === shade ? styles.swatchSelected : ""}`}
                            style={{ background: shade }}
                            title={shade}
                            onClick={() => setThemeColor(shade)}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                  <div className={styles.colorPickerRow}>
                    <input
                      type="color"
                      value={themeColor}
                      onChange={(e) => setThemeColor(e.target.value)}
                      className={styles.colorInput}
                      title="Pick any custom shade visually"
                    />
                    <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--ink)" }}>
                      Visual Color Eyedropper (tap box to pick any exact shade)
                    </span>
                  </div>
                </div>

                {/* 3. Background Palette */}
                <div style={{ marginBottom: "20px" }}>
                  <span style={{ fontSize: "13px", fontWeight: 700 }}>Shop Background Surface</span>
                  <div className={styles.shadesRow} style={{ marginTop: "8px" }}>
                    {[
                      { name: "Warm Sand (Default)", color: "#fbf7f0" },
                      { name: "Pure White", color: "#ffffff" },
                      { name: "Soft Ivory", color: "#fefce8" },
                      { name: "Cool Ice", color: "#f8fafc" },
                      { name: "Pale Mint", color: "#f0fdf4" },
                      { name: "Dark Charcoal", color: "#18181b" },
                    ].map((item) => (
                      <button
                        key={item.color}
                        type="button"
                        title={item.name}
                        className={`${styles.swatch} ${themeBg === item.color ? styles.swatchSelected : ""}`}
                        style={{ background: item.color, border: "1px solid var(--line-strong)" }}
                        onClick={() => setThemeBg(item.color)}
                      />
                    ))}
                  </div>
                  <div className={styles.colorPickerRow}>
                    <input
                      type="color"
                      value={themeBg}
                      onChange={(e) => setThemeBg(e.target.value)}
                      className={styles.colorInput}
                      title="Pick any background shade visually"
                    />
                    <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--ink)" }}>
                      Custom Background Eyedropper
                    </span>
                  </div>
                </div>

                {/* 4. Text & Header Info */}
                <div className={styles.grid}>
                  <Field
                    label="Shop headline"
                    id="shop_headline"
                    value={storefrontHeadline}
                    onChange={setStorefrontHeadline}
                    placeholder="e.g. Direct wholesale & retail market distributor"
                    hint="Appears prominently at the top of your public shop."
                  />
                  <Field
                    label="Shop WhatsApp / Order phone"
                    id="shop_phone"
                    value={storefrontPhone}
                    onChange={setStorefrontPhone}
                    inputMode="tel"
                    placeholder="e.g. 08012345678"
                    hint="Where customers send completed lists and inquiries."
                  />
                  <Field
                    label="Shop description"
                    id="shop_description"
                    value={storefrontDescription}
                    onChange={setStorefrontDescription}
                    placeholder="e.g. Direct wholesale and retail distribution. Tell us what you need and we will source and pack it."
                    optional
                  />
                  <div>
                    <Field
                      label="Background Image URL"
                      id="shop_bg_image"
                      value={themeBgImage.startsWith("data:") ? "(Uploaded image ready)" : themeBgImage}
                      onChange={(val) => setThemeBgImage(val)}
                      placeholder="https://... (direct image link)"
                      optional
                      hint="Enter a link or choose a photo below."
                    />
                    <div className={styles.uploadRow}>
                      <label className={styles.fileInputLabel}>
                        <span>Upload photo</span>
                        <input
                          ref={fileInputRef}
                          type="file"
                          accept="image/*"
                          className={styles.hiddenFileInput}
                          onChange={handleImageFileChange}
                        />
                      </label>
                      {themeBgImage ? (
                        <button
                          type="button"
                          className={styles.secondaryAction}
                          onClick={() => {
                            setThemeBgImage("");
                            if (fileInputRef.current) fileInputRef.current.value = "";
                          }}
                        >
                          Clear photo
                        </button>
                      ) : null}
                    </div>
                  </div>
                </div>

                {/* 5. Live Responsive Preview Card */}
                <div className={styles.previewCard}>
                  <div className={styles.previewHeader}>
                    <span className={styles.previewTitle}>Live Shop Preview</span>
                    <div className={styles.previewToggleGroup}>
                      <button
                        type="button"
                        className={`${styles.previewToggleBtn} ${previewMode === "desktop" ? styles.previewToggleBtnActive : ""}`}
                        onClick={() => setPreviewMode("desktop")}
                      >
                        Desktop view
                      </button>
                      <button
                        type="button"
                        className={`${styles.previewToggleBtn} ${previewMode === "mobile" ? styles.previewToggleBtnActive : ""}`}
                        onClick={() => setPreviewMode("mobile")}
                      >
                        Mobile phone view
                      </button>
                    </div>
                  </div>

                  <div className={styles.previewWrapper}>
                    <div
                      className={
                        previewMode === "mobile"
                          ? styles.previewFrameMobile
                          : styles.previewFrameDesktop
                      }
                    >
                      {previewMode === "desktop" ? (
                        <div className={styles.browserChrome}>
                          <div className={styles.browserDots}>
                            <span className={styles.browserDotRed} />
                            <span className={styles.browserDotYellow} />
                            <span className={styles.browserDotGreen} />
                          </div>
                          <div className={styles.browserUrlBar}>
                            ahia.ng/shop/{business.public_path}
                          </div>
                        </div>
                      ) : (
                        <div className={styles.phoneNotchBar}>
                          <div className={styles.phoneSpeaker} />
                        </div>
                      )}

                      {/* Storefront Header */}
                      <div className={styles.mockupHeader}>
                        <div className={styles.mockupBrandGroup}>
                          <span
                            className={styles.mockupAvatar}
                            style={{ background: themeColor }}
                          >
                            {business.name.slice(0, 2).toUpperCase()}
                          </span>
                          <span className={styles.mockupShopNameTop}>{business.name}</span>
                        </div>
                        <span className={styles.mockupListBtn}>Build your list</span>
                      </div>

                      {/* Storefront Hero Banner */}
                      <div
                        className={styles.mockupBanner}
                        style={{
                          backgroundColor: themeBg,
                          backgroundImage: themeBgImage ? `url(${themeBgImage})` : undefined,
                          color: isDarkColor(themeBg) ? "#f0ede6" : "var(--ink)",
                        }}
                      >
                        <span
                          className={styles.mockupBadge}
                          style={{ background: themeColor }}
                        >
                          Official Storefront
                        </span>
                        <span className={styles.mockupTitle}>{business.name}</span>
                        <span className={styles.mockupHeadline}>
                          {storefrontHeadline || "Wholesale & Retail Market Catalog"}
                        </span>
                        {storefrontDescription ? (
                          <p className={styles.mockupDesc}>{storefrontDescription}</p>
                        ) : null}
                        <div className={styles.mockupActionsRow}>
                          <span
                            className={styles.mockupPrimaryBtn}
                            style={{ background: themeColor }}
                          >
                            Build your list
                          </span>
                          <span className={styles.mockupWhatsAppBtn}>WhatsApp</span>
                        </div>
                      </div>

                      {/* Storefront Content Grid */}
                      <div className={styles.mockupContent}>
                        <div className={styles.mockupPillsRow}>
                          <span
                            style={{
                              fontSize: "11px",
                              fontWeight: 700,
                              padding: "4px 10px",
                              borderRadius: "999px",
                              background: themeColor,
                              color: "#fff",
                            }}
                          >
                            All Items (12)
                          </span>
                          <span
                            style={{
                              fontSize: "11px",
                              fontWeight: 600,
                              padding: "4px 10px",
                              borderRadius: "999px",
                              background: "#e2e8f0",
                              color: "#334155",
                            }}
                          >
                            Wholesale Packs (8)
                          </span>
                          <span
                            style={{
                              fontSize: "11px",
                              fontWeight: 600,
                              padding: "4px 10px",
                              borderRadius: "999px",
                              background: "#e2e8f0",
                              color: "#334155",
                            }}
                          >
                            Featured Stock (4)
                          </span>
                        </div>

                        <div className={styles.mockupProductGrid}>
                          <div className={styles.mockupProductCard}>
                            <div className={styles.mockupProductThumb}>
                              Wholesale Pack
                            </div>
                            <div className={styles.mockupProductDetails}>
                              <span className={styles.mockupProductTag}>Wholesale</span>
                              <span className={styles.mockupProductName}>Standard Master Pack</span>
                              <span
                                className={styles.mockupProductPrice}
                                style={{ color: themeColor }}
                              >
                                {formatMoney(3500)} / carton
                              </span>
                            </div>
                            <div className={styles.mockupCardAdd} style={{ color: themeColor }}>
                              Add to list +
                            </div>
                          </div>
                          <div className={styles.mockupProductCard}>
                            <div className={styles.mockupProductThumb}>
                              Premium Unit
                            </div>
                            <div className={styles.mockupProductDetails}>
                              <span className={styles.mockupProductTag}>Retail Unit</span>
                              <span className={styles.mockupProductName}>Universal Unit - Model X</span>
                              <span
                                className={styles.mockupProductPrice}
                                style={{ color: themeColor }}
                              >
                                {formatMoney(1200)}
                              </span>
                            </div>
                            <div className={styles.mockupCardAdd} style={{ color: themeColor }}>
                              Add to list +
                            </div>
                          </div>
                        </div>
                      </div>

                      {previewMode === "mobile" ? (
                        <div className={styles.mockupMobileFloatingBar}>
                          <span
                            className={styles.mockupPrimaryBtn}
                            style={{ background: themeColor, flex: 1, textAlign: "center" }}
                          >
                            Build your list
                          </span>
                          <span
                            className={styles.mockupWhatsAppBtn}
                            style={{ flex: 1, textAlign: "center" }}
                          >
                            WhatsApp
                          </span>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>

                <div className={styles.formActions}>
                  <button
                    type="button"
                    className={styles.secondaryAction}
                    onClick={() => {
                      setStorefrontHeadline(initialAppearance.headline);
                      setStorefrontDescription(initialAppearance.description);
                      setStorefrontPhone(initialAppearance.phone);
                      setThemeColor(initialAppearance.color);
                      setThemeBg(initialAppearance.bg);
                      setThemeBgImage(initialAppearance.bgImage);
                      setIsAppearanceExpanded(false);
                    }}
                  >
                    Cancel
                  </button>
                  <Button
                    busy={busyAction === "storefront"}
                    disabled={!isAppearanceDirty || busyAction === "storefront"}
                    onClick={() =>
                      run("storefront", async () => {
                        const themeTrailer = `\n\n<!-- ahia-theme:${JSON.stringify({
                          color: themeColor,
                          bg: themeBg,
                          bgImage: themeBgImage.startsWith("http") ? themeBgImage.trim() : "",
                        })} -->`;
                        const cleanDesc = storefrontDescription.replace(/<!--\s*ahia-theme:[\s\S]*?-->/g, "").trim();
                        const safeDesc = cleanDesc.slice(0, 800);
                        const fullDescription = `${safeDesc}${themeTrailer}`;

                        await updateStorefront(business.id, {
                          headline: storefrontHeadline.trim() || null,
                          description: fullDescription,
                          contact_phone: storefrontPhone.trim() || null,
                        });
                        if (typeof window !== "undefined") {
                          const themeData = JSON.stringify({
                            color: themeColor,
                            bg: themeBg,
                            bgImage: themeBgImage.trim() || null,
                          });
                          window.localStorage.setItem(`ahia.theme.${business.id}`, themeData);
                          window.localStorage.setItem(`ahia.theme.${business.public_path}`, themeData);
                        }
                        setInitialAppearance({
                          headline: storefrontHeadline.trim(),
                          description: storefrontDescription.trim(),
                          phone: storefrontPhone.trim(),
                          color: themeColor,
                          bg: themeBg,
                          bgImage: themeBgImage.trim(),
                        });
                        setNotice({
                          message: "Shop appearance and branding saved.",
                          hint: "Changes are live immediately on your public shop.",
                          tone: "good",
                        });
                        setIsAppearanceExpanded(false);
                      })
                    }
                  >
                    Save shop appearance
                  </Button>
                </div>
              </div>
            )}
          </Card>
        ) : null}

        {/* Your businesses */}
        <Card title="Your businesses">
          <ul className={styles.businessList}>
            {businesses.map((candidate) => (
              <li key={candidate.id} className={styles.businessRow}>
                <div>
                  <span className={styles.businessName}>{candidate.name}</span>
                  <span className={styles.businessSlug}>/shop/{candidate.public_path}</span>
                </div>
                <Pill tone={candidate.is_active ? "good" : "bad"}>
                  {candidate.role_name || "member"}
                </Pill>
              </li>
            ))}
          </ul>
          <p className={styles.note}>
            Everyone in a business signs in with their own account, and their role decides what they can
            do.
          </p>
        </Card>

        {/* Password */}
        <Card title="Password">
          <div className={styles.grid}>
            <PasswordField
              label="Current password"
              id="current_password"
              value={currentPassword}
              onChange={setCurrentPassword}
              autoComplete="current-password"
            />
            <PasswordField
              label="New password"
              id="new_password"
              value={newPassword}
              onChange={setNewPassword}
              autoComplete="new-password"
            />
            <PasswordField
              label="New password again"
              id="confirm_new_password"
              value={confirmation}
              onChange={setConfirmation}
              autoComplete="new-password"
            />
          </div>
          {newPassword.length > 0 ? (
            <>
              <StrengthMeter score={strength.score} label={strength.label} />
              <CheckList checks={checks} />
            </>
          ) : null}
          {confirmation.length > 0 && !passwordsMatch ? (
            <p className={styles.mismatch}>The two new passwords are not the same.</p>
          ) : null}
          <div className={styles.formActions}>
            <Button
              busy={busyAction === "password"}
              disabled={
                currentPassword.length === 0 ||
                newPassword.length < PASSWORD_MINIMUM_LENGTH ||
                !passwordsMatch
              }
              onClick={() =>
                run("password", async () => {
                  await changePassword({
                    current_password: currentPassword,
                    new_password: newPassword,
                  });
                  setCurrentPassword("");
                  setNewPassword("");
                  setConfirmation("");
                  setNotice({
                    message: "Your password is changed.",
                    hint: "Other devices stay signed in until their session ends.",
                    tone: "good",
                  });
                })
              }
            >
              Change my password
            </Button>
          </div>
        </Card>

        {/* Sign Out Card */}
        <div className={styles.signOutCard}>
          <div className={styles.signOutInfo}>
            <span className={styles.signOutTitle}>Sign out of AHIA</span>
            <span className={styles.signOutHint}>
              You will need your phone number and password to sign back in.
            </span>
          </div>
          <button
            type="button"
            className={styles.signOutBtn}
            onClick={handleLogout}
          >
            Sign out
          </button>
        </div>
      </div>

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
