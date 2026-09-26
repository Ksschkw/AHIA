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
import {
  PASSWORD_MINIMUM_LENGTH,
  passwordChecks,
  passwordStrength,
} from "@/lib/passwords";
import { CheckList, StrengthMeter } from "@/components/ui";
import styles from "./profile.module.css";

type Notice = { message: string; tone: "good" | "bad"; hint?: string };

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
          try {
            const sf = await getStorefront(chosen.id);
            loadedHeadline = sf.headline ?? "";
            loadedDesc = sf.description ?? "";
            loadedPhone = sf.contact_phone ?? "";
            setStorefrontHeadline(loadedHeadline);
            setStorefrontDescription(loadedDesc);
            setStorefrontPhone(loadedPhone);
          } catch {
            // storefront might not be created or published yet
          }

          let loadedColor = "#084a2f";
          let loadedBg = "#fbf7f0";
          let loadedBgImage = "";
          if (typeof window !== "undefined") {
            try {
              const savedTheme = window.localStorage.getItem(`ahia.theme.${chosen.id}`);
              if (savedTheme) {
                const parsed = JSON.parse(savedTheme);
                if (parsed.color) {
                  loadedColor = parsed.color;
                  setThemeColor(parsed.color);
                }
                if (parsed.bg) {
                  loadedBg = parsed.bg;
                  setThemeBg(parsed.bg);
                }
                if (parsed.bgImage) {
                  loadedBgImage = parsed.bgImage;
                  setThemeBgImage(parsed.bgImage);
                }
              }
            } catch {
              // ignore parse errors
            }
          }

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
        {business ? (
          <Card title="Shop Appearance & Customization">
            <div className={styles.grid}>
              <Field
                label="Shop headline"
                id="shop_headline"
                value={storefrontHeadline}
                onChange={setStorefrontHeadline}
                placeholder="e.g. Phone accessories, wholesale & retail"
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
                placeholder="e.g. We stock 21D screenguards, pouches, fast chargers and accessories in Alaba."
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
                    <span>Upload image</span>
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
                      Clear image
                    </button>
                  ) : null}
                </div>
              </div>
            </div>

            {/* Accent Color picker */}
            <div style={{ marginTop: "16px" }}>
              <span style={{ fontSize: "13px", fontWeight: 700 }}>Shop Accent Color</span>
              <div className={styles.colorSwatches}>
                {[
                  { name: "Forest Green", color: "#084a2f" },
                  { name: "Royal Blue", color: "#1e40af" },
                  { name: "Indigo", color: "#3730a3" },
                  { name: "Maroon", color: "#831843" },
                  { name: "Amber", color: "#b45309" },
                  { name: "Slate", color: "#1e293b" },
                ].map((item) => (
                  <button
                    key={item.color}
                    type="button"
                    title={item.name}
                    className={`${styles.swatch} ${themeColor === item.color ? styles.swatchSelected : ""}`}
                    style={{ background: item.color }}
                    onClick={() => setThemeColor(item.color)}
                  />
                ))}
              </div>
              <div className={styles.colorPickerRow}>
                <input
                  type="color"
                  value={themeColor}
                  onChange={(e) => setThemeColor(e.target.value)}
                  className={styles.colorInput}
                  title="Pick any custom color"
                />
                <input
                  type="text"
                  value={themeColor}
                  onChange={(e) => setThemeColor(e.target.value)}
                  className={styles.hexInput}
                  placeholder="#084a2f"
                  maxLength={7}
                />
                <span style={{ fontSize: "12px", color: "var(--ink-3)" }}>
                  Pick or enter any custom hex code
                </span>
              </div>
            </div>

            {/* Background Style picker */}
            <div style={{ marginTop: "16px" }}>
              <span style={{ fontSize: "13px", fontWeight: 700 }}>Shop Background Color</span>
              <div className={styles.colorSwatches}>
                {[
                  { name: "Warm Sand", color: "#fbf7f0" },
                  { name: "Clean White", color: "#ffffff" },
                  { name: "Soft Cream", color: "#fefce8" },
                  { name: "Cool Slate", color: "#f1f5f9" },
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
                  title="Pick any background color"
                />
                <input
                  type="text"
                  value={themeBg}
                  onChange={(e) => setThemeBg(e.target.value)}
                  className={styles.hexInput}
                  placeholder="#fbf7f0"
                  maxLength={7}
                />
                <span style={{ fontSize: "12px", color: "var(--ink-3)" }}>
                  Enter any custom background hex
                </span>
              </div>
            </div>

            {/* Live Responsive Preview Card */}
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
                    Mobile view
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
                  <div
                    className={styles.mockupBanner}
                    style={{
                      backgroundColor: themeBg,
                      backgroundImage: themeBgImage ? `url(${themeBgImage})` : undefined,
                      color: "#1e1b16",
                    }}
                  >
                    <span className={styles.mockupTitle}>{business.name}</span>
                    <span className={styles.mockupHeadline}>
                      {storefrontHeadline || "Wholesale & Retail Market Catalog"}
                    </span>
                    {storefrontDescription ? (
                      <p className={styles.mockupDesc}>{storefrontDescription}</p>
                    ) : null}
                    <span
                      className={styles.mockupPhoneBadge}
                      style={{ background: themeColor }}
                    >
                      Order on WhatsApp: {storefrontPhone || business.phone || "08012345678"}
                    </span>
                  </div>

                  <div className={styles.mockupContent}>
                    <div style={{ display: "flex", gap: "8px", overflowX: "hidden" }}>
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
                        All Items
                      </span>
                      <span
                        style={{
                          fontSize: "11px",
                          fontWeight: 600,
                          padding: "4px 10px",
                          borderRadius: "999px",
                          background: "#e7dfd2",
                          color: "#1e1b16",
                        }}
                      >
                        Screenguards
                      </span>
                      <span
                        style={{
                          fontSize: "11px",
                          fontWeight: 600,
                          padding: "4px 10px",
                          borderRadius: "999px",
                          background: "#e7dfd2",
                          color: "#1e1b16",
                        }}
                      >
                        Accessories
                      </span>
                    </div>

                    <div className={styles.mockupProductGrid}>
                      <div className={styles.mockupProductCard}>
                        <span className={styles.mockupProductName}>21D Hot 8 / Hot 9</span>
                        <span
                          className={styles.mockupProductPrice}
                          style={{ color: themeColor }}
                        >
                          NGN 350 / pack
                        </span>
                      </div>
                      <div className={styles.mockupProductCard}>
                        <span className={styles.mockupProductName}>Fast Type-C Cable</span>
                        <span
                          className={styles.mockupProductPrice}
                          style={{ color: themeColor }}
                        >
                          NGN 1,200
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className={styles.formActions}>
              <Button
                busy={busyAction === "storefront"}
                disabled={!isAppearanceDirty || busyAction === "storefront"}
                onClick={() =>
                  run("storefront", async () => {
                    await updateStorefront(business.id, {
                      headline: storefrontHeadline.trim() || null,
                      description: storefrontDescription.trim() || null,
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
                    setNotice({ message: "Shop appearance and branding saved.", tone: "good" });
                  })
                }
              >
                Save shop appearance
              </Button>
            </div>
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
