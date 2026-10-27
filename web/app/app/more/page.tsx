"use client";

/**
 * The unified More & Settings hub for AHIA.
 *
 * Matches the mobile app's More tab 1-for-1 identically:
 * - User Profile with Avatar & Account Settings
 * - Everything in AHIA navigation grid with actual SVG icons
 * - Team & Staff subview (stats, roles, status cycling, WhatsApp invite sharing, permissions guide)
 * - Storefront Studio (publish/draft, live preview link, copy/share)
 * - Stall Business profile & logo management
 * - Stall Security PIN & Password reset in unified Security modal
 * - Push Notifications (VAPID web push configuration)
 * - Theme selector (Light Ivory / Dark Theme)
 * - Sign out confirmation modal
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  ArrowLeftIcon,
  BoxIcon,
  ListIcon,
  LockIcon,
  PeopleIcon,
  PlusIcon,
  ReceiptIcon,
  ShareIcon,
  ShopIcon,
  TagIcon,
} from "@/components/icons";
import { ImageUploadField } from "@/components/image-upload-field";
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
  uploadTenantMedia,
  uploadUserAvatar,
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
import {
  isPushSupported,
  getPushPermission,
  subscribeToWebPush,
  sendTestPush,
} from "@/lib/notifications";
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

  // Subview for Team (matching mobile identically)
  const [activeSubView, setActiveSubView] = useState<"team" | null>(null);

  // Push Notifications State
  const [pushSupported, setPushSupported] = useState(false);
  const [pushSubscribed, setPushSubscribed] = useState(false);
  const [pushEnabling, setPushEnabling] = useState(false);
  const [testingPush, setTestingPush] = useState(false);

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

  // Unified Security Modal (Password + PIN sub-tabs)
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [securityTab, setSecurityTab] = useState<"password" | "pin">("password");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);

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
    if (isPushSupported()) {
      setPushSupported(true);
      if (getPushPermission() === "granted") {
        setPushSubscribed(true);
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

  const isOwner = userRole.toUpperCase() === "OWNER";
  const isOwnerOrManager =
    !userRole ||
    userRole.toUpperCase() === "OWNER" ||
    userRole.toUpperCase() === "MANAGER";

  // Handlers
  const handleSaveProfile = async () => {
    if (!profile) return;
    setSavingProfile(true);
    try {
      const trimmedAvatar = editAvatarUrl.trim();
      const updated = await updateProfile({
        first_name: editFirstName.trim(),
        last_name: editLastName.trim() || undefined,
        phone: editPhone.trim() || undefined,
        email: editEmail.trim() || undefined,
        avatar_url: trimmedAvatar || null,
      });

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

  const handleRemoveMember = async (member: Member) => {
    if (!business) return;
    if (!window.confirm(`Remove ${member.full_name || "staff member"} from stall?`)) return;
    try {
      await removeMember(business.id, member.id);
      setMembers((prev) => prev.filter((m) => m.id !== member.id));
      setNotice({ message: "Member removed from stall.", tone: "good" });
    } catch (err: unknown) {
      setNotice({ message: (err as Error)?.message || "Could not remove member.", tone: "bad" });
    }
  };

  const handleChangeMemberRole = async (member: Member) => {
    if (!business) return;
    const current = (member.role_name || "SALES").toUpperCase();
    const nextRole: MemberRole =
      current === "OWNER"
        ? "MANAGER"
        : current === "MANAGER"
        ? "SALES"
        : current === "SALES"
        ? "INVENTORY"
        : "OWNER";
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

  const handleShareInviteWhatsApp = (inv: MembershipInvitation) => {
    if (!business) return;
    const url = `https://useahia-hazel.vercel.app/join/${inv.token}`;
    const text = `You've been invited to join ${business.name} on AHIA as ${(inv.role_name || "STAFF").toUpperCase()}!\n\nTap to accept: ${url}`;
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank");
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
      setShowPasswordModal(false);
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

      {/* -------------------------------------------------------------
          SUBVIEW: TEAM & STAFF (1:1 identical with Mobile)
          ------------------------------------------------------------- */}
      {activeSubView === "team" ? (
        <div>
          {/* Top Bar with Back & Invite */}
          <div className={styles.teamTopBar}>
            <button
              type="button"
              className={styles.teamBackBtn}
              onClick={() => setActiveSubView(null)}
            >
              <ArrowLeftIcon size={18} />
              <span>Back to More</span>
            </button>
            <button
              type="button"
              className={styles.teamInviteTopBtn}
              onClick={() => setShowInviteModal(true)}
            >
              <PlusIcon size={16} />
              <span>Invite Staff</span>
            </button>
          </div>

          {/* Team Banner */}
          <div className={styles.teamBannerCard}>
            <div className={styles.teamBannerIconWrap}>
              <PeopleIcon size={26} />
            </div>
            <div>
              <h3 className={styles.teamBannerTitle}>Team & Staff Management</h3>
              <p className={styles.teamBannerSub}>
                {business?.name} - Manage staff members, send WhatsApp invitations, and configure role permissions.
              </p>
            </div>
          </div>

          {/* Quick Stats Row (3 boxes) */}
          <div className={styles.teamStatsRow}>
            <div className={styles.teamStatBox}>
              <div className={styles.teamStatValue}>{members.length}</div>
              <div className={styles.teamStatLabel}>Staff Members</div>
            </div>
            <div className={styles.teamStatBox}>
              <div className={styles.teamStatValue}>
                {members.filter((m) => m.status === "active").length}
              </div>
              <div className={styles.teamStatLabel}>Active Staff</div>
            </div>
            <div className={styles.teamStatBox}>
              <div className={styles.teamStatValue}>{invitations.length}</div>
              <div className={styles.teamStatLabel}>Sent Invites</div>
            </div>
          </div>

          {/* Active Members Section */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h3 className={styles.cardTitle}>Staff Members ({members.length})</h3>
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => setShowInviteModal(true)}
              >
                + Invite
              </button>
            </div>
            <p className={styles.cardDesc}>
              Tap any staff member&apos;s role badge to cycle their permission level, or tap status to toggle Active / Suspended.
            </p>

            {members.length === 0 ? (
              <p style={{ color: "var(--ink-secondary)", fontSize: "13px" }}>No staff members added yet.</p>
            ) : (
              members.map((m) => {
                const displayName = m.full_name || m.phone || m.email || "Staff Member";
                const displayRole = (m.role_name || "SALES").toUpperCase();
                const initial = (m.full_name || m.phone || "S").slice(0, 1).toUpperCase();
                return (
                  <div key={m.id} className={styles.teamMemberCard}>
                    <div className={styles.teamMemberAvatar}>{initial}</div>
                    <div style={{ flex: 1 }}>
                      <div className={styles.teamMemberName}>{displayName}</div>
                      <div className={styles.teamMemberMeta}>
                        {m.phone || m.email || "No contact info"}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "6px" }}>
                        <button
                          type="button"
                          className={styles.memberRoleBadge}
                          onClick={() => handleChangeMemberRole(m)}
                          title="Tap to cycle permission role"
                        >
                          {displayRole}
                        </button>
                        <button
                          type="button"
                          className={`${styles.memberStatusBadge} ${
                            m.status === "active" ? styles.memberStatusActive : styles.memberStatusSuspended
                          }`}
                          onClick={() => handleToggleMemberStatus(m)}
                        >
                          {(m.status ?? "ACTIVE").toUpperCase()}
                        </button>
                      </div>
                    </div>
                    {isOwner && displayRole !== "OWNER" && (
                      <button
                        type="button"
                        className={styles.removeStaffBtn}
                        onClick={() => handleRemoveMember(m)}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* Sent Invitations Section */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h3 className={styles.cardTitle}>Sent Invitations ({invitations.length})</h3>
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => setShowInviteModal(true)}
              >
                + Send New
              </button>
            </div>
            <p className={styles.cardDesc}>
              Track invitations sent to staff. Tap Share to send their invite link directly via WhatsApp.
            </p>

            {invitations.length === 0 ? (
              <div className={styles.emptyInviteBox}>
                <p style={{ margin: 0, fontSize: "13px", color: "var(--ink-secondary)" }}>
                  No pending staff invitations.
                </p>
                <button
                  type="button"
                  className={styles.emptyInviteBtn}
                  onClick={() => setShowInviteModal(true)}
                >
                  Invite your first staff member
                </button>
              </div>
            ) : (
              invitations.map((inv) => {
                const roleLabel = (inv.role_name || "STAFF").toUpperCase();
                return (
                  <div key={inv.id} className={styles.sentInviteCard}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span className={styles.sentInviteTarget}>
                          {inv.phone || inv.email || "Invited Staff"}
                        </span>
                        <span className={styles.sentInviteRolePill}>{roleLabel}</span>
                      </div>
                      <div className={styles.sentInviteStatus}>
                        Status: PENDING &bull; Created: {new Date(inv.created_at).toLocaleDateString()}
                      </div>
                    </div>
                    <button
                      type="button"
                      className={styles.inviteShareWhatsAppBtn}
                      onClick={() => handleShareInviteWhatsApp(inv)}
                    >
                      <ShareIcon size={14} />
                      <span>Share</span>
                    </button>
                  </div>
                );
              })
            )}
          </div>

          {/* Invitations Waiting For You */}
          {myInvitations.length > 0 && (
            <div className={styles.card}>
              <h3 className={styles.cardTitle} style={{ color: "var(--leaf)" }}>
                Invitations Waiting for You ({myInvitations.length})
              </h3>
              <p className={styles.cardDesc}>
                Other businesses have invited you to join their team on AHIA:
              </p>
              {myInvitations.map((inv) => (
                <div key={inv.id} className={styles.sentInviteCard}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: "13px" }}>{inv.tenant_name}</div>
                    <div style={{ fontSize: "11px", color: "var(--ink-secondary)" }}>Role: {inv.role_name}</div>
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

          {/* Role Permissions Guide */}
          <div className={styles.card}>
            <h3 className={styles.cardTitle}>Role Permissions Guide</h3>
            <p className={styles.cardDesc}>
              Summary of privileges for each stall role:
            </p>
            <div className={styles.roleGuideList}>
              <div className={styles.roleGuideItem}>
                <div className={styles.roleGuideName}>Owner</div>
                <div className={styles.roleGuideDesc}>
                  Full stall ownership, financial records, team management, business security PIN, and storefront settings.
                </div>
              </div>
              <div className={styles.roleGuideItem}>
                <div className={styles.roleGuideName}>Manager</div>
                <div className={styles.roleGuideDesc}>
                  Sales recording, inventory & shelf categories, order lists, and staff management.
                </div>
              </div>
              <div className={styles.roleGuideItem}>
                <div className={styles.roleGuideName}>Sales / Cashier</div>
                <div className={styles.roleGuideDesc}>
                  Record customer sales, print/send customer WhatsApp receipts, search products and prices.
                </div>
              </div>
              <div className={styles.roleGuideItem}>
                <div className={styles.roleGuideName}>Inventory</div>
                <div className={styles.roleGuideDesc}>
                  Manage categories and products, update stock quantities, view stock alerts.
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* -------------------------------------------------------------
           MAIN MORE VIEW
           ------------------------------------------------------------- */
        <div>
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

          {/* Everything in AHIA Grid (1:1 identical to Mobile) */}
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
              <span className={styles.tileTitle}>Waybills</span>
              <span className={styles.tileDesc}>Customer lists</span>
            </Link>
            <Link href="/app/sales" className={styles.tile}>
              <span className={styles.tileIcon}>
                <ReceiptIcon size={24} style={{ color: "#8b5cf6" }} />
              </span>
              <span className={styles.tileTitle}>Trading</span>
              <span className={styles.tileDesc}>Daily ledger</span>
            </Link>
            {isOwnerOrManager && (
              <button
                type="button"
                className={styles.tile}
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
                <span className={styles.tileIcon}>
                  <ShareIcon size={24} style={{ color: "#10b981" }} />
                </span>
                <span className={styles.tileTitle}>Storefront</span>
                <span className={styles.tileDesc}>WhatsApp link</span>
              </button>
            )}
            {isOwnerOrManager && (
              <button
                type="button"
                className={styles.tile}
                onClick={() => setActiveSubView("team")}
              >
                <span className={styles.tileIcon}>
                  <PeopleIcon size={24} style={{ color: "#38bdf8" }} />
                </span>
                <span className={styles.tileTitle}>Team & Staff</span>
                <span className={styles.tileDesc}>Manage team & invites</span>
              </button>
            )}
            {isOwnerOrManager && (
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
                  <TagIcon size={24} style={{ color: "#fbbf24" }} />
                </span>
                <span className={styles.tileTitle}>Stall Profile</span>
                <span className={styles.tileDesc}>Address & name</span>
              </button>
            )}
            <button
              type="button"
              className={styles.tile}
              onClick={() => {
                setSecurityTab("password");
                setShowPasswordModal(true);
              }}
            >
              <span className={styles.tileIcon}>
                <LockIcon size={24} style={{ color: "#ec4899" }} />
              </span>
              <span className={styles.tileTitle}>Security</span>
              <span className={styles.tileDesc}>PIN & password</span>
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

          {/* Team & Staff Management (Inline Summary) */}
          {isOwnerOrManager && (
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <h3 className={styles.cardTitle}>Team & Staff ({members.length})</h3>
                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    type="button"
                    className={styles.secondaryBtn}
                    onClick={() => setActiveSubView("team")}
                  >
                    Full View
                  </button>
                  <button
                    type="button"
                    className={styles.primaryBtn}
                    onClick={() => setShowInviteModal(true)}
                  >
                    + Invite Staff
                  </button>
                </div>
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
                          onClick={() => handleChangeMemberRole(m)}
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
                        onClick={() => handleRemoveMember(m)}
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
                    <div key={inv.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", fontSize: "12px" }}>
                      <span>{inv.phone || inv.email} (Role: {inv.role_name})</span>
                      <button
                        type="button"
                        className={styles.inviteShareWhatsAppBtn}
                        style={{ padding: "4px 10px", fontSize: "11px" }}
                        onClick={() => handleShareInviteWhatsApp(inv)}
                      >
                        <ShareIcon size={12} />
                        <span>Share</span>
                      </button>
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

          {/* Push Notifications Card */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <h3 className={styles.cardTitle}>Push Notifications</h3>
                <Pill tone={pushSubscribed ? "good" : "warn"}>
                  {pushSubscribed ? "ACTIVE (VAPID)" : "NOT ENABLED"}
                </Pill>
              </div>
              {pushSupported && !pushSubscribed && (
                <button
                  type="button"
                  className={styles.primaryBtn}
                  disabled={pushEnabling}
                  onClick={async () => {
                    if (!business) return;
                    setPushEnabling(true);
                    const res = await subscribeToWebPush(business.id);
                    setPushEnabling(false);
                    if (res.success) {
                      setPushSubscribed(true);
                      setNotice({ message: "Push notifications successfully enabled!", tone: "good" });
                    } else {
                      setNotice({ message: res.message, tone: "bad" });
                    }
                  }}
                >
                  {pushEnabling ? "Enabling..." : "Enable Push Notifications"}
                </button>
              )}
            </div>
            <p className={styles.cardDesc}>
              Receive instant browser and device alerts whenever customers submit orders, dispatch waybills, or stock runs low. Protected with end-to-end VAPID encryption.
            </p>
            {pushSubscribed && (
              <div style={{ marginTop: "12px", display: "flex", flexWrap: "wrap", gap: "8px" }}>
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  disabled={testingPush}
                  onClick={async () => {
                    if (!business) return;
                    setTestingPush(true);
                    const res = await sendTestPush(business.id, "brief");
                    setTestingPush(false);
                    setNotice({ message: res.message, tone: res.success ? "good" : "bad" });
                  }}
                >
                  {testingPush ? "Sending..." : "Test Brief Alert"}
                </button>
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  disabled={testingPush}
                  onClick={async () => {
                    if (!business) return;
                    setTestingPush(true);
                    const res = await sendTestPush(business.id, "detailed");
                    setTestingPush(false);
                    setNotice({ message: res.message, tone: res.success ? "good" : "bad" });
                  }}
                >
                  Test Detailed Alert
                </button>
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  disabled={testingPush}
                  onClick={async () => {
                    if (!business) return;
                    setTestingPush(true);
                    const res = await sendTestPush(business.id, "multimedia");
                    setTestingPush(false);
                    setNotice({ message: res.message, tone: res.success ? "good" : "bad" });
                  }}
                >
                  Test Multi-Media Alert
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
                Light Ivory
              </button>
              <button
                type="button"
                className={`${styles.themeBtn} ${themeMode === "dark" ? styles.themeBtnActive : ""}`}
                onClick={() => toggleTheme("dark")}
              >
                Dark Theme (Default)
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
        </div>
      )}

      {/* ---------------- MODALS / SHEETS (1:1 with Mobile) ---------------- */}

      {/* Edit Profile Sheet */}
      <Sheet open={showProfileModal} title="Edit User Profile" onClose={() => setShowProfileModal(false)}>
        <Field label="First Name" id="edit-first-name" value={editFirstName} onChange={setEditFirstName} />
        <Field label="Last Name" id="edit-last-name" value={editLastName} onChange={setEditLastName} optional />
        <Field label="Phone Number" id="edit-phone" value={editPhone} onChange={setEditPhone} optional />
        <Field label="Email Address" id="edit-email" value={editEmail} onChange={setEditEmail} optional />
        <ImageUploadField
          label="Profile Avatar / Photo"
          value={editAvatarUrl}
          shape="circle"
          onChange={(url) => setEditAvatarUrl(url || "")}
          onUpload={async (file) => {
            const updated = await uploadUserAvatar(file);
            return updated.avatar_url || "";
          }}
          hint="Accepts any photo format; converted and stored securely"
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
        <ImageUploadField
          label="Stall / Business Logo"
          value={editBizLogo}
          shape="square"
          onChange={(url) => setEditBizLogo(url || "")}
          onUpload={async (file) => {
            if (!business) throw new Error("No business selected.");
            const res = await uploadTenantMedia(business.id, file, "logo");
            return res.delivery_url;
          }}
          hint="Accepts any image format; displayed on shop and receipts"
          optional
        />
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

      {/* Unified Security & Stall Protection Modal (1:1 with Mobile) */}
      <Sheet open={showPasswordModal} title="Security & Stall Protection" onClose={() => setShowPasswordModal(false)}>
        {/* Sub-tabs: Account Password vs Stall Security PIN */}
        <div className={styles.securityTabRow}>
          <button
            type="button"
            className={`${styles.securityTabBtn} ${securityTab === "password" ? styles.securityTabBtnActive : ""}`}
            onClick={() => setSecurityTab("password")}
          >
            Account Password
          </button>
          {isOwner && (
            <button
              type="button"
              className={`${styles.securityTabBtn} ${securityTab === "pin" ? styles.securityTabBtnActive : ""}`}
              onClick={() => setSecurityTab("pin")}
            >
              Stall PIN (Owner)
            </button>
          )}
        </div>

        {securityTab === "password" ? (
          <div>
            <p className={styles.cardDesc}>
              Update your personal account password used to sign into AHIA.
            </p>
            <Field
              label="Current Password"
              id="current-password"
              type="password"
              value={currentPassword}
              onChange={setCurrentPassword}
            />
            <Field
              label="New Password"
              id="new-password"
              type="password"
              value={newPassword}
              onChange={setNewPassword}
              hint="Must be at least 8 characters long."
            />
            {newPassword.length > 0 && (
              <div className={styles.passwordMeterBox}>
                <div className={styles.passwordStrengthRow}>
                  <span className={styles.passwordStrengthLabel}>Strength:</span>
                  <span
                    className={
                      newPassword.length >= 8 && /\d/.test(newPassword)
                        ? styles.strengthStrong
                        : newPassword.length >= 8
                        ? styles.strengthMedium
                        : styles.strengthWeak
                    }
                  >
                    {newPassword.length >= 8 && /\d/.test(newPassword)
                      ? "Strong"
                      : newPassword.length >= 8
                      ? "Medium"
                      : "Too Short"}
                  </span>
                </div>
                <div className={styles.strengthBarWrap}>
                  <div
                    className={`${styles.strengthBar} ${
                      newPassword.length >= 8 && /\d/.test(newPassword)
                        ? styles.barStrong
                        : newPassword.length >= 8
                        ? styles.barMedium
                        : styles.barWeak
                    }`}
                  />
                </div>
                <div className={styles.pwdChecklistText}>
                  {newPassword.length >= 8 ? "[OK]" : "[ ]"} Minimum 8 characters
                </div>
                <div className={styles.pwdChecklistText}>
                  {/\d/.test(newPassword) ? "[OK]" : "[ ]"} Contains a number
                </div>
              </div>
            )}
            <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={() => setShowPasswordModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={handleChangeAccountPassword}
                disabled={savingPassword || !currentPassword || newPassword.length < 8}
              >
                {savingPassword ? "Changing..." : "Change Password"}
              </button>
            </div>
          </div>
        ) : (
          <div>
            <p className={styles.cardDesc}>
              The Business Security PIN is linked directly to this stall. Only the Business Owner can set or change it. It protects sensitive owner actions (price changes, deleting items, and staff removal).
            </p>
            <div className={styles.pinStatusBox}>
              <LockIcon size={16} style={{ color: hasPin ? "#15803d" : "#d97706" }} />
              <span className={styles.pinStatusText} style={{ color: hasPin ? "#15803d" : "#d97706" }}>
                {hasPin ? "Stall Security PIN is Active" : "No PIN Set for this Stall"}
              </span>
            </div>

            {hasPin && !showPinResetFlow && (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginBottom: "16px" }}>
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  onClick={() => {
                    setFirstPin("");
                    setSecondPin("");
                    setPinError(null);
                    setPinStep(1);
                    setShowPinModal(true);
                    setShowPasswordModal(false);
                  }}
                >
                  Change 4-Digit PIN
                </button>
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
                    setShowPasswordModal(false);
                  }}
                >
                  Remove PIN
                </button>
              </div>
            )}

            {!hasPin && (
              <div style={{ marginTop: "12px" }}>
                <button
                  type="button"
                  className={styles.primaryBtn}
                  onClick={() => {
                    setFirstPin("");
                    setSecondPin("");
                    setPinError(null);
                    setPinStep(1);
                    setShowPinModal(true);
                    setShowPasswordModal(false);
                  }}
                >
                  Set 4-Digit Security PIN
                </button>
              </div>
            )}

            {showPinResetFlow && (
              <div style={{ marginTop: "16px", padding: "14px", borderRadius: "8px", background: "var(--sand)" }}>
                <h4 style={{ margin: "0 0 8px 0", fontSize: "13px" }}>Reset PIN with Account Password</h4>
                <Field
                  label="Enter your Account Password"
                  id="pin-reset-pass"
                  type="password"
                  value={pinResetPassword}
                  onChange={setPinResetPassword}
                  error={pinResetError || undefined}
                />
                <div style={{ display: "flex", gap: "8px", marginTop: "10px" }}>
                  <button
                    type="button"
                    className={styles.secondaryBtn}
                    onClick={() => setShowPinResetFlow(false)}
                  >
                    Back
                  </button>
                  <button
                    type="button"
                    className={styles.primaryBtn}
                    disabled={pinResetVerifying || !pinResetPassword}
                    onClick={handleVerifyPasswordForPinReset}
                  >
                    {pinResetVerifying ? "Verifying..." : "Verify & Set New PIN"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </Sheet>

      {/* Security PIN Setup Sheet */}
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
