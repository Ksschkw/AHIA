"use client";

/**
 * The unified More & Settings hub for AHIA.
 *
 * Matches the mobile app's More tab identically:
 * - User Profile with Avatar & Account Settings
 * - Everything in AHIA navigation grid with actual SVG icons
 * - Storefront Studio (publish/draft, live preview link, copy/share)
 * - Team & Staff management (invitations, roles, permissions)
 * - Business profile & logo management
 * - Stall Security PIN & Password reset
 * - Theme selector (Light Ivory / Dark Theme)
 * - Sign out
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  BoxIcon,
  BuildingIcon,
  GlobeIcon,
  KeyIcon,
  ListIcon,
  LockIcon,
  ReceiptIcon,
  ShopIcon,
} from "@/components/icons";
import { Field, Loading, Pill, Select, Sheet, Toast } from "@/components/ui";
import {
  acceptInvitation,
  changeMemberRole,
  changeMemberStatus,
  changePassword,
  currentUser,
  getBusiness,
  getStorefront,
  inviteMember,
  listBusinesses,
  listIssuedInvitations,
  listMembers,
  listMyInvitations,
  publishStorefront,
  removeMember,
  signIn,
  signOut,
  unpublishStorefront,
  updateBusiness,
  updateProfile,
  updateStorefront,
  type Member,
  type MemberRole,
  type MembershipInvitation,
  type PendingInvitation,
  type Storefront,
  type Tenant,
  type UserProfile,
} from "@/lib/api";
import {
  hasBusinessPin,
  setBusinessPin,
  clearBusinessPin,
} from "@/lib/pin";
import styles from "./more.module.css";

function parseStorefrontTheme(description: string | null | undefined) {
  let cleanDesc = description || "";
  let themeColor = "#084a2f";
  let themeBg = "#fbf7f0";
  let closing = "";
  let logoUrl = "";

  if (description) {
    const match = description.match(/<!--\s*ahia-theme:(\{[\s\S]*?\})\s*-->/);
    if (match) {
      cleanDesc = description.replace(match[0], "").trim();
      try {
        const parsed = JSON.parse(match[1]);
        if (parsed.color) themeColor = parsed.color;
        if (parsed.bg) themeBg = parsed.bg;
        if (parsed.closing) closing = parsed.closing;
        if (parsed.logoUrl) logoUrl = parsed.logoUrl;
      } catch {
        // ignore parse error
      }
    }
  }
  return { cleanDesc, themeColor, themeBg, closing, logoUrl };
}

function packStorefrontDescription(
  desc: string,
  options: {
    color?: string;
    bg?: string;
    closing?: string;
    logoUrl?: string;
  },
) {
  const themePayload: Record<string, unknown> = {};
  if (options.color) themePayload.color = options.color;
  if (options.bg) themePayload.bg = options.bg;
  if (options.closing) themePayload.closing = options.closing;
  if (options.logoUrl) themePayload.logoUrl = options.logoUrl;

  const base = desc.trim();
  const metaTag =
    Object.keys(themePayload).length > 0
      ? `\n<!-- ahia-theme:${JSON.stringify(themePayload)} -->`
      : "";
  return `${base}${metaTag}`.trim() || null;
}

export default function MorePage() {
  const router = useRouter();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [avatarUrl, setAvatarUrl] = useState<string>("");
  const [business, setBusiness] = useState<Tenant | null>(null);
  const [userRole, setUserRole] = useState("OWNER");
  const [businessLogo, setBusinessLogo] = useState("");
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<MembershipInvitation[]>([]);
  const [myInvitations, setMyInvitations] = useState<PendingInvitation[]>([]);
  const [storefront, setStorefront] = useState<Storefront | null>(null);
  const [hasPin, setHasPin] = useState(false);
  const [themeMode, setThemeMode] = useState<"light" | "dark">("dark");
  const [state, setState] = useState<"loading" | "ready">("loading");
  const [notice, setNotice] = useState<{ message: string; tone: "good" | "bad" } | null>(null);

  // Modals
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [editFirstName, setEditFirstName] = useState("");
  const [editLastName, setEditLastName] = useState("");
  const [editPhone, setEditPhone] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editAvatarUrl, setEditAvatarUrl] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);

  const [showBusinessModal, setShowBusinessModal] = useState(false);
  const [editBizName, setEditBizName] = useState("");
  const [editBizAddress, setEditBizAddress] = useState("");
  const [editBizPhone, setEditBizPhone] = useState("");
  const [editBizLogo, setEditBizLogo] = useState("");
  const [savingBusiness, setSavingBusiness] = useState(false);

  const [showStorefrontModal, setShowStorefrontModal] = useState(false);
  const [storefrontHeadline, setStorefrontHeadline] = useState("");
  const [storefrontDesc, setStorefrontDesc] = useState("");
  const [storefrontPhone, setStorefrontPhone] = useState("");
  const [storefrontThemeColor, setStorefrontThemeColor] = useState("#084a2f");
  const [storefrontThemeBg, setStorefrontThemeBg] = useState("#fbf7f0");
  const [storefrontClosing, setStorefrontClosing] = useState("");
  const [savingStorefront, setSavingStorefront] = useState(false);

  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteIdentifier, setInviteIdentifier] = useState("");
  const [inviteRole, setInviteRole] = useState<MemberRole>("SALES");
  const [savingInvite, setSavingInvite] = useState(false);

  const [showPinModal, setShowPinModal] = useState(false);
  const [pinStep, setPinStep] = useState<1 | 2>(1);
  const [firstPin, setFirstPin] = useState("");
  const [secondPin, setSecondPin] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  const [savingPin, setSavingPin] = useState(false);

  const [showPinResetFlow, setShowPinResetFlow] = useState(false);
  const [pinResetPassword, setPinResetPassword] = useState("");
  const [pinResetError, setPinResetError] = useState<string | null>(null);
  const [pinResetVerifying, setPinResetVerifying] = useState(false);

  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);

  const [showSignOutModal, setShowSignOutModal] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const user = await currentUser();
      const storedAvatar =
        typeof window !== "undefined"
          ? window.localStorage.getItem(`ahia.user_avatar.${user.id}`) ||
            window.localStorage.getItem("ahia.user_avatar") ||
            ""
          : "";
      const effectiveAvatar = user.avatar_url || storedAvatar;
      setAvatarUrl(effectiveAvatar);
      setProfile({ ...user, avatar_url: effectiveAvatar || null });

      const businesses = await listBusinesses();
      const remembered =
        typeof window === "undefined" ? null : window.localStorage.getItem("ahia.business");
      const chosen = businesses.find((b) => b.id === remembered) ?? businesses[0];

      if (chosen) {
        setUserRole(chosen.role_name || "OWNER");
        const storedLogo =
          typeof window !== "undefined"
            ? window.localStorage.getItem(`ahia.business_logo.${chosen.id}`) || ""
            : "";
        const [bizDetail, mems, invites, myInvs, sf, pinExists] = await Promise.all([
          getBusiness(chosen.id).catch(() => null),
          listMembers(chosen.id).catch(() => []),
          listIssuedInvitations(chosen.id).catch(() => []),
          listMyInvitations().catch(() => []),
          getStorefront(chosen.id).catch(() => null),
          hasBusinessPin(chosen.id),
        ]);
        setBusiness(bizDetail);
        setMembers(mems);
        setInvitations(invites);
        setMyInvitations(myInvs);
        setStorefront(sf);
        setHasPin(pinExists);

        const parsed = parseStorefrontTheme(sf?.description);
        setBusinessLogo(storedLogo || parsed.logoUrl || "");
      }
      setState("ready");
    } catch {
      setState("ready");
    }
  }, []);

  useEffect(() => {
    void loadData();
    if (typeof window !== "undefined") {
      const savedTheme = window.localStorage.getItem("ahia.theme");
      if (savedTheme === "light") {
        setThemeMode("light");
      } else {
        setThemeMode("dark");
      }
    }
  }, [loadData]);

  const toggleTheme = (mode: "light" | "dark") => {
    setThemeMode(mode);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("ahia.theme", mode);
      document.documentElement.setAttribute("data-theme", mode);
    }
  };

  const isOwnerOrManager =
    !userRole ||
    userRole.toUpperCase() === "OWNER" ||
    userRole.toUpperCase() === "MANAGER";

  // Handlers
  const handleSaveProfile = async () => {
    if (!profile) return;
    setSavingProfile(true);
    try {
      const updated = await updateProfile({
        first_name: editFirstName.trim(),
        last_name: editLastName.trim() || undefined,
        phone: editPhone.trim() || undefined,
        email: editEmail.trim() || undefined,
      });

      const trimmedAvatar = editAvatarUrl.trim();
      if (typeof window !== "undefined") {
        if (trimmedAvatar) {
          window.localStorage.setItem(`ahia.user_avatar.${updated.id}`, trimmedAvatar);
          window.localStorage.setItem("ahia.user_avatar", trimmedAvatar);
        } else {
          window.localStorage.removeItem(`ahia.user_avatar.${updated.id}`);
          window.localStorage.removeItem("ahia.user_avatar");
        }
      }
      setAvatarUrl(trimmedAvatar);
      setProfile({ ...updated, avatar_url: trimmedAvatar || null });
      setShowProfileModal(false);
      setNotice({ message: "Profile updated successfully!", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not update profile.", tone: "bad" });
    } finally {
      setSavingProfile(false);
    }
  };

  const handleSaveBusiness = async () => {
    if (!business) return;
    setSavingBusiness(true);
    try {
      const updated = await updateBusiness(business.id, {
        name: editBizName.trim(),
        address: editBizAddress.trim() || undefined,
        phone: editBizPhone.trim() || undefined,
      });
      setBusiness(updated);

      const trimmedLogo = editBizLogo.trim();
      if (trimmedLogo) {
        if (typeof window !== "undefined") {
          window.localStorage.setItem(`ahia.business_logo.${business.id}`, trimmedLogo);
        }
        setBusinessLogo(trimmedLogo);
      } else {
        if (typeof window !== "undefined") {
          window.localStorage.removeItem(`ahia.business_logo.${business.id}`);
        }
        setBusinessLogo("");
      }

      setShowBusinessModal(false);
      setNotice({ message: "Stall profile updated!", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not update business.", tone: "bad" });
    } finally {
      setSavingBusiness(false);
    }
  };

  const handleToggleStorefrontPublish = async () => {
    if (!business || !storefront) return;
    try {
      const nextPublished = !storefront.is_published;
      let updated: Storefront;
      if (nextPublished) {
        updated = await publishStorefront(business.id, {
          headline: storefront.headline,
          description: storefront.description,
          contact_phone: storefront.contact_phone,
        });
      } else {
        updated = await unpublishStorefront(business.id);
      }
      setStorefront(updated);
      setNotice({
        message: nextPublished ? "Your storefront is now live!" : "Storefront unpublished to draft.",
        tone: "good",
      });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not toggle storefront.", tone: "bad" });
    }
  };

  const handleSaveStorefront = async () => {
    if (!business) return;
    setSavingStorefront(true);
    try {
      const combinedDesc = packStorefrontDescription(storefrontDesc, {
        color: storefrontThemeColor.trim() || undefined,
        bg: storefrontThemeBg.trim() || undefined,
        closing: storefrontClosing.trim() || undefined,
        logoUrl: businessLogo || undefined,
      });
      const updated = await updateStorefront(business.id, {
        headline: storefrontHeadline.trim() || null,
        description: combinedDesc,
        contact_phone: storefrontPhone.trim() || null,
      });
      setStorefront(updated);
      setShowStorefrontModal(false);
      setNotice({ message: "Storefront settings saved!", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not save storefront.", tone: "bad" });
    } finally {
      setSavingStorefront(false);
    }
  };

  const handleInviteStaff = async () => {
    if (!business || !inviteIdentifier.trim()) return;
    setSavingInvite(true);
    try {
      const isEmail = inviteIdentifier.includes("@");
      const created = await inviteMember(business.id, {
        role_name: inviteRole,
        email: isEmail ? inviteIdentifier.trim() : undefined,
        phone: !isEmail ? inviteIdentifier.trim() : undefined,
      });
      setInvitations((prev) => [created, ...prev]);
      setShowInviteModal(false);
      setInviteIdentifier("");
      setNotice({ message: "Invitation sent successfully!", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not send invite.", tone: "bad" });
    } finally {
      setSavingInvite(false);
    }
  };

  const handleRemoveStaff = async (member: Member) => {
    if (!business || !window.confirm(`Remove ${member.full_name || "staff member"} from stall?`)) return;
    try {
      await removeMember(business.id, member.id);
      setMembers((prev) => prev.filter((m) => m.id !== member.id));
      setNotice({ message: "Member removed from stall.", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not remove member.", tone: "bad" });
    }
  };

  const handleToggleMemberRole = async (member: Member) => {
    if (!business) return;
    const roles: MemberRole[] = ["SALES", "INVENTORY", "MANAGER", "OWNER"];
    const currentIdx = roles.indexOf(member.role_name as MemberRole);
    const nextRole = roles[(currentIdx + 1) % roles.length];
    try {
      const updated = await changeMemberRole(business.id, member.id, nextRole);
      setMembers((prev) => prev.map((m) => (m.id === member.id ? updated : m)));
      setNotice({ message: `Role changed to ${nextRole}`, tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not update role.", tone: "bad" });
    }
  };

  const handleToggleMemberStatus = async (member: Member) => {
    if (!business) return;
    const nextStatus = member.status === "active" ? "suspended" : "active";
    try {
      const updated = await changeMemberStatus(business.id, member.id, nextStatus);
      setMembers((prev) => prev.map((m) => (m.id === member.id ? updated : m)));
      setNotice({ message: `Member marked ${nextStatus}`, tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not update status.", tone: "bad" });
    }
  };

  const handleAcceptMyInvitation = async (inv: PendingInvitation) => {
    try {
      await acceptInvitation(inv.id);
      setMyInvitations((prev) => prev.filter((one) => one.id !== inv.id));
      setNotice({ message: `Accepted invitation to ${inv.tenant_name}!`, tone: "good" });
      void loadData();
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not accept invite.", tone: "bad" });
    }
  };

  const handleSavePin = async () => {
    if (!business) return;
    if (pinStep === 1) {
      if (firstPin.length !== 4 || !/^\d{4}$/.test(firstPin)) {
        setPinError("PIN must be exactly 4 numeric digits.");
        return;
      }
      setPinError(null);
      setPinStep(2);
      return;
    }
    if (secondPin !== firstPin) {
      setPinError("PINs do not match. Please try again.");
      setPinStep(1);
      setFirstPin("");
      setSecondPin("");
      return;
    }
    setSavingPin(true);
    try {
      await setBusinessPin(business.id, secondPin);
      setHasPin(true);
      setShowPinModal(false);
      setPinStep(1);
      setFirstPin("");
      setSecondPin("");
      setNotice({ message: "Stall Security PIN set successfully!", tone: "good" });
    } catch {
      setPinError("Could not save Security PIN.");
    } finally {
      setSavingPin(false);
    }
  };

  const handleVerifyPasswordForPinReset = async () => {
    if (!business || !profile) return;
    const identifier = profile.phone || profile.email;
    if (!identifier) {
      setPinResetError("No phone or email found on account.");
      return;
    }
    setPinResetVerifying(true);
    setPinResetError(null);
    try {
      await signIn({ identifier, password: pinResetPassword });
      setShowPinResetFlow(false);
      setPinResetPassword("");
      setPinStep(1);
      setFirstPin("");
      setSecondPin("");
      setPinError(null);
      setShowPinModal(true);
      setNotice({ message: "Password verified! Please enter your new 4-digit PIN.", tone: "good" });
    } catch {
      setPinResetError("Incorrect account password. Please try again.");
    } finally {
      setPinResetVerifying(false);
    }
  };

  const handleChangeAccountPassword = async () => {
    setSavingPassword(true);
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword });
      setShowPasswordModal(false);
      setCurrentPassword("");
      setNewPassword("");
      setNotice({ message: "Account password changed successfully!", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not change password.", tone: "bad" });
    } finally {
      setSavingPassword(false);
    }
  };

  const handleSignOutConfirm = async () => {
    try {
      await signOut();
    } catch {
      // ignore
    }
    if (typeof window !== "undefined") {
      window.localStorage.removeItem("ahia.session");
      window.localStorage.removeItem("ahia.business");
    }
    router.replace("/start");
  };

  const publicShopUrl = business?.slug
    ? `https://useahia-hazel.vercel.app/shop/${business.slug}`
    : "https://useahia-hazel.vercel.app";

  return (
    <main className={styles.page}>
      {state === "loading" ? <Loading label="Loading stall settings..." /> : null}

      {/* User Profile Card */}
      <div className={styles.profileCard}>
        <div className={styles.avatar}>
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt={profile?.first_name || "Profile"}
              className={styles.avatarImg}
            />
          ) : profile?.first_name ? (
            profile.first_name.slice(0, 1).toUpperCase()
          ) : (
            "U"
          )}
        </div>
        <div className={styles.profileInfo}>
          <h2 className={styles.profileName}>
            {profile?.first_name} {profile?.last_name ?? ""}
          </h2>
          <p className={styles.profilePhone}>{profile?.phone ?? profile?.email ?? "No phone set"}</p>
          <span className={styles.roleBadge}>
            {business?.name ?? "Stall"} &bull; {userRole}
          </span>
        </div>
        <button
          type="button"
          className={styles.editBtn}
          onClick={() => {
            setEditFirstName(profile?.first_name ?? "");
            setEditLastName(profile?.last_name ?? "");
            setEditPhone(profile?.phone ?? "");
            setEditEmail(profile?.email ?? "");
            setEditAvatarUrl(avatarUrl);
            setShowProfileModal(true);
          }}
        >
          Edit Profile
        </button>
      </div>

      {/* Everything in AHIA Grid */}
      <h3 className={styles.sectionTitle}>Everything in AHIA</h3>
      <div className={styles.grid}>
        <Link href="/app" className={styles.tile}>
          <span className={styles.tileIcon}>
            <ShopIcon size={24} style={{ color: "#22c55e" }} />
          </span>
          <span className={styles.tileTitle}>The Shop</span>
          <span className={styles.tileDesc}>Daily counter</span>
        </Link>
        <Link href="/app/items" className={styles.tile}>
          <span className={styles.tileIcon}>
            <BoxIcon size={24} style={{ color: "#3b82f6" }} />
          </span>
          <span className={styles.tileTitle}>Catalog</span>
          <span className={styles.tileDesc}>Folders & Items</span>
        </Link>
        <Link href="/app/lists" className={styles.tile}>
          <span className={styles.tileIcon}>
            <ListIcon size={24} style={{ color: "#f59e0b" }} />
          </span>
          <span className={styles.tileTitle}>Lists</span>
          <span className={styles.tileDesc}>Customer orders</span>
        </Link>
        <Link href="/app/sales" className={styles.tile}>
          <span className={styles.tileIcon}>
            <ReceiptIcon size={24} style={{ color: "#8b5cf6" }} />
          </span>
          <span className={styles.tileTitle}>Trading</span>
          <span className={styles.tileDesc}>Daily ledger</span>
        </Link>
        <a
          href={publicShopUrl}
          target="_blank"
          rel="noopener noreferrer"
          className={styles.tile}
        >
          <span className={styles.tileIcon}>
            <GlobeIcon size={24} style={{ color: "#10b981" }} />
          </span>
          <span className={styles.tileTitle}>Storefront</span>
          <span className={styles.tileDesc}>Public link</span>
        </a>
        <button
          type="button"
          className={styles.tile}
          onClick={() => {
            setEditBizName(business?.name ?? "");
            setEditBizAddress(business?.address ?? "");
            setEditBizPhone(business?.phone ?? "");
            setEditBizLogo(businessLogo);
            setShowBusinessModal(true);
          }}
        >
          <span className={styles.tileIcon}>
            <BuildingIcon size={24} style={{ color: "#eab308" }} />
          </span>
          <span className={styles.tileTitle}>Stall Profile</span>
          <span className={styles.tileDesc}>Address & name</span>
        </button>
        <button
          type="button"
          className={styles.tile}
          onClick={() => {
            setFirstPin("");
            setSecondPin("");
            setPinError(null);
            setPinStep(1);
            setShowPinModal(true);
          }}
        >
          <span className={styles.tileIcon}>
            <LockIcon size={24} style={{ color: "#ef4444" }} />
          </span>
          <span className={styles.tileTitle}>Security PIN</span>
          <span className={styles.tileDesc}>{hasPin ? "PIN Protected" : "Set PIN"}</span>
        </button>
        <button
          type="button"
          className={styles.tile}
          onClick={() => setShowPasswordModal(true)}
        >
          <span className={styles.tileIcon}>
            <KeyIcon size={24} style={{ color: "#ec4899" }} />
          </span>
          <span className={styles.tileTitle}>Password</span>
          <span className={styles.tileDesc}>Account login</span>
        </button>
      </div>

      {/* Storefront Studio Card */}
      {isOwnerOrManager && (
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <h3 className={styles.cardTitle}>Storefront Studio</h3>
              <Pill tone={storefront?.is_published ? "good" : "warn"}>
                {storefront?.is_published ? "PUBLISHED" : "DRAFT"}
              </Pill>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={handleToggleStorefrontPublish}
              >
                {storefront?.is_published ? "Unpublish" : "Go Live"}
              </button>
              <button
                type="button"
                className={styles.editBtn}
                onClick={() => {
                  const parsed = parseStorefrontTheme(storefront?.description);
                  setStorefrontHeadline(storefront?.headline ?? "");
                  setStorefrontDesc(parsed.cleanDesc);
                  setStorefrontPhone(storefront?.contact_phone ?? "");
                  setStorefrontThemeColor(parsed.themeColor);
                  setStorefrontThemeBg(parsed.themeBg);
                  setStorefrontClosing(parsed.closing);
                  setShowStorefrontModal(true);
                }}
              >
                Edit
              </button>
            </div>
          </div>
          <p className={styles.cardDesc}>
            {storefront?.headline || "Your public shop catalog is live on AHIA."}
          </p>
          <div className={styles.urlBox}>
            <span>{publicShopUrl}</span>
            <button
              type="button"
              className={styles.editBtn}
              onClick={() => {
                void navigator.clipboard.writeText(publicShopUrl);
                setNotice({ message: "Storefront link copied to clipboard!", tone: "good" });
              }}
            >
              Copy Link
            </button>
          </div>
          <div className={styles.actionRow}>
            <a
              href={`https://wa.me/?text=${encodeURIComponent(`Check out our shop on AHIA: ${publicShopUrl}`)}`}
              target="_blank"
              rel="noopener noreferrer"
              className={styles.primaryBtn}
              style={{ textDecoration: "none" }}
            >
              Share Storefront Link on WhatsApp
            </a>
          </div>
        </div>
      )}

      {/* Team & Staff Management */}
      {isOwnerOrManager && (
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <h3 className={styles.cardTitle}>Team & Staff ({members.length})</h3>
            <button
              type="button"
              className={styles.primaryBtn}
              onClick={() => setShowInviteModal(true)}
            >
              + Invite Staff
            </button>
          </div>
          <p className={styles.cardDesc}>
            Manage apprentices and managers. Tap a role or status badge to change privileges.
          </p>

          <div className={styles.memberList}>
            {members.map((m) => (
              <div key={m.id} className={styles.memberRow}>
                <div>
                  <div className={styles.memberName}>
                    {m.full_name || "Staff Member"}
                  </div>
                  <div className={styles.memberMeta}>
                    {m.phone || m.email || "Staff Member"} &bull;{" "}
                    <button
                      type="button"
                      onClick={() => handleToggleMemberRole(m)}
                      style={{
                        background: "none",
                        border: "none",
                        color: "var(--leaf, #238636)",
                        fontWeight: 700,
                        cursor: "pointer",
                      }}
                    >
                      {m.role_name} &bull; Tap to change
                    </button>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <button
                    type="button"
                    onClick={() => handleToggleMemberStatus(m)}
                    style={{
                      padding: "2px 8px",
                      borderRadius: "6px",
                      fontSize: "11px",
                      fontWeight: 700,
                      border: "none",
                      cursor: "pointer",
                      background: m.status === "active" ? "#dcfce7" : "#fee2e2",
                      color: m.status === "active" ? "#15803d" : "#b91c1c",
                    }}
                  >
                    {m.status.toUpperCase()}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRemoveStaff(m)}
                    className={styles.editBtn}
                    style={{ color: "#cf222e" }}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Sent Invitations */}
          {invitations.length > 0 && (
            <div style={{ marginTop: "16px", paddingTop: "12px", borderTop: "1px solid var(--line, #e5e7eb)" }}>
              <h4 style={{ fontSize: "12px", fontWeight: 700, color: "var(--ink-secondary, #6b7280)", margin: "0 0 8px" }}>
                SENT INVITATIONS ({invitations.length})
              </h4>
              {invitations.map((inv) => (
                <div key={inv.id} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", fontSize: "12px" }}>
                  <span>{inv.phone || inv.email}</span>
                  <span style={{ fontWeight: 600 }}>Role: {inv.role_name}</span>
                </div>
              ))}
            </div>
          )}

          {/* Invitations Waiting For You */}
          {myInvitations.length > 0 && (
            <div style={{ marginTop: "16px", paddingTop: "12px", borderTop: "1px solid var(--line, #e5e7eb)" }}>
              <h4 style={{ fontSize: "12px", fontWeight: 700, color: "var(--leaf, #238636)", margin: "0 0 8px" }}>
                INVITATIONS WAITING FOR YOU ({myInvitations.length})
              </h4>
              {myInvitations.map((inv) => (
                <div key={inv.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0" }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: "13px" }}>{inv.tenant_name}</div>
                    <div style={{ fontSize: "11px", color: "var(--ink-secondary, #6b7280)" }}>Role: {inv.role_name}</div>
                  </div>
                  <button
                    type="button"
                    className={styles.primaryBtn}
                    onClick={() => handleAcceptMyInvitation(inv)}
                  >
                    Accept
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Business Profile Card */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <h3 className={styles.cardTitle}>Business Profile</h3>
          {isOwnerOrManager && (
            <button
              type="button"
              className={styles.editBtn}
              onClick={() => {
                setEditBizName(business?.name ?? "");
                setEditBizAddress(business?.address ?? "");
                setEditBizPhone(business?.phone ?? "");
                setEditBizLogo(businessLogo);
                setShowBusinessModal(true);
              }}
            >
              Edit
            </button>
          )}
        </div>
        <div style={{ display: "flex", gap: "16px", alignItems: "center" }}>
          {businessLogo ? (
            <img
              src={businessLogo}
              alt={business?.name || "Business Logo"}
              style={{ width: "56px", height: "56px", borderRadius: "10px", objectFit: "cover", border: "1px solid var(--line)" }}
            />
          ) : null}
          <div>
            <div style={{ fontSize: "15px", fontWeight: 700, color: "var(--ink, #111)" }}>{business?.name}</div>
            <div style={{ fontSize: "13px", color: "var(--ink-secondary, #6b7280)", marginTop: "2px" }}>
              Address: {business?.address || "Alaba International Market"}
            </div>
            <div style={{ fontSize: "13px", color: "var(--ink-secondary, #6b7280)", marginTop: "2px" }}>
              Phone: {business?.phone || "Not set"}
            </div>
          </div>
        </div>
      </div>

      {/* Stall Security & PIN Management */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <h3 className={styles.cardTitle}>Stall Security & PIN</h3>
            <Pill tone={hasPin ? "good" : "warn"}>
              {hasPin ? "ACTIVE & PROTECTED" : "NO PIN SET"}
            </Pill>
          </div>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={() => {
              setFirstPin("");
              setSecondPin("");
              setPinError(null);
              setPinStep(1);
              setShowPinModal(true);
            }}
          >
            {hasPin ? "Change 4-Digit PIN" : "Set Security PIN"}
          </button>
        </div>
        <p className={styles.cardDesc}>
          Protects order confirmations, stock voids, and financial numbers from apprentices on the floor.
        </p>
        {hasPin && (
          <div style={{ display: "flex", gap: "10px" }}>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => {
                setShowPinResetFlow(true);
                setPinResetPassword("");
                setPinResetError(null);
              }}
            >
              Forgot PIN? Reset with Account Password
            </button>
            <button
              type="button"
              className={styles.secondaryBtn}
              style={{ color: "#cf222e" }}
              onClick={async () => {
                if (!business || !window.confirm("Remove stall PIN protection?")) return;
                await clearBusinessPin(business.id);
                setHasPin(false);
                setNotice({ message: "Stall PIN removed.", tone: "good" });
              }}
            >
              Remove PIN
            </button>
          </div>
        )}
      </div>

      {/* App Appearance / Theme */}
      <div className={styles.card}>
        <h3 className={styles.cardTitle}>App Appearance</h3>
        <p className={styles.cardDesc}>
          Choose your preferred visual theme for the market floor.
        </p>
        <div className={styles.themeWrap}>
          <button
            type="button"
            className={`${styles.themeBtn} ${themeMode === "light" ? styles.themeBtnActive : ""}`}
            onClick={() => toggleTheme("light")}
          >
            Light Ivory (Default)
          </button>
          <button
            type="button"
            className={`${styles.themeBtn} ${themeMode === "dark" ? styles.themeBtnActive : ""}`}
            onClick={() => toggleTheme("dark")}
          >
            Dark Theme
          </button>
        </div>
      </div>

      {/* Sign Out Button */}
      <button
        type="button"
        className={styles.signOutBtn}
        onClick={() => setShowSignOutModal(true)}
      >
        Sign Out of AHIA
      </button>

      {/* ---------------- MODALS / SHEETS ---------------- */}

      {/* Edit Profile Sheet */}
      <Sheet open={showProfileModal} title="Edit User Profile" onClose={() => setShowProfileModal(false)}>
        <Field label="First Name" id="edit-first-name" value={editFirstName} onChange={setEditFirstName} />
        <Field label="Last Name" id="edit-last-name" value={editLastName} onChange={setEditLastName} optional />
        <Field label="Phone Number" id="edit-phone" value={editPhone} onChange={setEditPhone} optional />
        <Field label="Email Address" id="edit-email" value={editEmail} onChange={setEditEmail} optional />
        <Field
          label="Profile Avatar / Photo URL"
          id="edit-avatar"
          value={editAvatarUrl}
          onChange={setEditAvatarUrl}
          hint="Direct web link to your avatar photo"
          optional
        />
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button type="button" className={styles.secondaryBtn} onClick={() => setShowProfileModal(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={handleSaveProfile}
            disabled={savingProfile || !editFirstName.trim()}
          >
            {savingProfile ? "Saving..." : "Save Profile"}
          </button>
        </div>
      </Sheet>

      {/* Edit Business Profile Sheet */}
      <Sheet open={showBusinessModal} title="Stall Business Profile" onClose={() => setShowBusinessModal(false)}>
        <Field label="Stall Name" id="edit-biz-name" value={editBizName} onChange={setEditBizName} />
        <Field label="Physical Address" id="edit-biz-address" value={editBizAddress} onChange={setEditBizAddress} optional />
        <Field label="Contact Phone" id="edit-biz-phone" value={editBizPhone} onChange={setEditBizPhone} optional />
        <Field label="Logo URL" id="edit-biz-logo" value={editBizLogo} onChange={setEditBizLogo} hint="URL to your business logo image" optional />
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button type="button" className={styles.secondaryBtn} onClick={() => setShowBusinessModal(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={handleSaveBusiness}
            disabled={savingBusiness || !editBizName.trim()}
          >
            {savingBusiness ? "Saving..." : "Save Stall Profile"}
          </button>
        </div>
      </Sheet>

      {/* Storefront Studio Sheet */}
      <Sheet open={showStorefrontModal} title="Storefront Studio Settings" onClose={() => setShowStorefrontModal(false)}>
        <Field label="Shop Headline" id="sf-headline" value={storefrontHeadline} onChange={setStorefrontHeadline} optional />
        <Field label="Description" id="sf-desc" value={storefrontDesc} onChange={setStorefrontDesc} optional />
        <Field label="Contact Phone" id="sf-phone" value={storefrontPhone} onChange={setStorefrontPhone} optional />
        <Field label="Theme Color" id="sf-color" value={storefrontThemeColor} onChange={setStorefrontThemeColor} optional />
        <Field label="Closing Statement" id="sf-closing" value={storefrontClosing} onChange={setStorefrontClosing} optional />
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button type="button" className={styles.secondaryBtn} onClick={() => setShowStorefrontModal(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={handleSaveStorefront}
            disabled={savingStorefront}
          >
            {savingStorefront ? "Saving..." : "Save Storefront"}
          </button>
        </div>
      </Sheet>

      {/* Invite Staff Sheet */}
      <Sheet open={showInviteModal} title="Invite Stall Member" onClose={() => setShowInviteModal(false)}>
        <Field
          label="Phone or Email"
          id="invite-id"
          value={inviteIdentifier}
          onChange={setInviteIdentifier}
          placeholder="08012345678 or staff@example.com"
        />
        <Select
          label="Stall Role"
          id="invite-role"
          value={inviteRole}
          onChange={(val) => setInviteRole(val as MemberRole)}
          options={[
            { value: "SALES", label: "Sales / Cashier" },
            { value: "INVENTORY", label: "Inventory Staff" },
            { value: "MANAGER", label: "Manager" },
            { value: "OWNER", label: "Co-Owner" },
          ]}
        />
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button type="button" className={styles.secondaryBtn} onClick={() => setShowInviteModal(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={handleInviteStaff}
            disabled={savingInvite || !inviteIdentifier.trim()}
          >
            {savingInvite ? "Sending..." : "Send Invitation"}
          </button>
        </div>
      </Sheet>

      {/* Security PIN Sheet */}
      <Sheet open={showPinModal} title="Stall Security PIN" onClose={() => setShowPinModal(false)}>
        {pinStep === 1 ? (
          <div>
            <p style={{ fontSize: "13px", color: "var(--ink-secondary)", marginBottom: "12px" }}>
              Enter a 4-digit numeric PIN for authorizing transactions:
            </p>
            <Field
              label="Choose 4-Digit PIN"
              id="first-pin"
              type="password"
              value={firstPin}
              onChange={setFirstPin}
              placeholder="****"
            />
          </div>
        ) : (
          <div>
            <p style={{ fontSize: "13px", color: "var(--ink-secondary)", marginBottom: "12px" }}>
              Re-enter your 4-digit PIN to confirm:
            </p>
            <Field
              label="Confirm 4-Digit PIN"
              id="second-pin"
              type="password"
              value={secondPin}
              onChange={setSecondPin}
              placeholder="****"
            />
          </div>
        )}
        {pinError ? <p style={{ color: "#cf222e", fontSize: "13px", margin: "8px 0" }}>{pinError}</p> : null}
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button type="button" className={styles.secondaryBtn} onClick={() => setShowPinModal(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={handleSavePin}
            disabled={savingPin}
          >
            {savingPin ? "Saving..." : pinStep === 1 ? "Next" : "Save Security PIN"}
          </button>
        </div>
      </Sheet>

      {/* Forgot PIN / Reset via Password Sheet */}
      <Sheet open={showPinResetFlow} title="Reset PIN with Account Password" onClose={() => setShowPinResetFlow(false)}>
        <p style={{ fontSize: "13px", color: "var(--ink-secondary)", marginBottom: "12px" }}>
          Verify your AHIA account password to unlock PIN reset:
        </p>
        <Field
          label="Account Password"
          id="pin-reset-pass"
          type="password"
          value={pinResetPassword}
          onChange={setPinResetPassword}
        />
        {pinResetError ? <p style={{ color: "#cf222e", fontSize: "13px", margin: "8px 0" }}>{pinResetError}</p> : null}
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button type="button" className={styles.secondaryBtn} onClick={() => setShowPinResetFlow(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={handleVerifyPasswordForPinReset}
            disabled={pinResetVerifying || !pinResetPassword.trim()}
          >
            {pinResetVerifying ? "Verifying..." : "Verify & Reset PIN"}
          </button>
        </div>
      </Sheet>

      {/* Account Password Change Sheet */}
      <Sheet open={showPasswordModal} title="Change Account Password" onClose={() => setShowPasswordModal(false)}>
        <Field
          label="Current Password"
          id="cur-pass"
          type="password"
          value={currentPassword}
          onChange={setCurrentPassword}
        />
        <Field
          label="New Password"
          id="new-pass"
          type="password"
          value={newPassword}
          onChange={setNewPassword}
        />
        <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
          <button type="button" className={styles.secondaryBtn} onClick={() => setShowPasswordModal(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={handleChangeAccountPassword}
            disabled={savingPassword || !currentPassword.trim() || !newPassword.trim()}
          >
            {savingPassword ? "Updating..." : "Update Password"}
          </button>
        </div>
      </Sheet>

      {/* Sign Out Confirmation Sheet */}
      <Sheet open={showSignOutModal} title="Sign Out of AHIA" onClose={() => setShowSignOutModal(false)}>
        <p style={{ fontSize: "14px", color: "var(--ink-secondary)", marginBottom: "16px" }}>
          Are you sure you want to sign out of your stall on this browser?
        </p>
        <div style={{ display: "flex", gap: "10px" }}>
          <button type="button" className={styles.secondaryBtn} onClick={() => setShowSignOutModal(false)}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            style={{ background: "#cf222e" }}
            onClick={handleSignOutConfirm}
          >
            Confirm Sign Out
          </button>
        </div>
      </Sheet>

      {notice ? <Toast message={notice.message} tone={notice.tone} onDismiss={() => setNotice(null)} /> : null}
    </main>
  );
}
