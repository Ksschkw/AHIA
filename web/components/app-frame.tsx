"use client";

/**
 * The frame's data: who is signed in, which businesses they have, and which one they are working in.
 *
 * Kept apart from the shell itself so that the shell is a pure drawing of what it is given - easy to
 * read, and possible to render in a test without a network. The business choice is remembered under
 * the same key the pages already use, so switching here switches everywhere.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import {
  currentUser,
  listBusinesses,
  prefetchAllAppData,
  signOut,
  type TenantSummary,
  type UserProfile,
} from "@/lib/api";
import { isPushSupported, subscribeToWebPush } from "@/lib/notifications";

export const ACTIVE_BUSINESS_KEY = "ahia.business";

export function AppFrame({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [businesses, setBusinesses] = useState<TenantSummary[]>([]);
  const [activeBusinessId, setActiveBusinessId] = useState<string | null>(null);
  const [promptType, setPromptType] = useState<"ask" | "blocked" | "ios_tip" | null>(null);
  const [pushEnabling, setPushEnabling] = useState(false);

  // Auto-prompt check on load: If push is supported and not yet prompted/enabled
  useEffect(() => {
    if (typeof window === "undefined") return;

    if (!isPushSupported()) {
      const isIOS =
        /iPad|iPhone|iPod/.test(navigator.userAgent) &&
        !(window as unknown as { MSStream?: unknown }).MSStream;
      const isStandalone =
        window.matchMedia("(display-mode: standalone)").matches ||
        Boolean((navigator as unknown as { standalone?: boolean }).standalone);
      if (isIOS && !isStandalone && !window.sessionStorage.getItem("ahia.ios_push_dismissed")) {
        setPromptType("ios_tip");
      }
      return;
    }

    if (Notification.permission === "default") {
      setPromptType("ask");
    } else if (
      Notification.permission === "denied" &&
      !window.sessionStorage.getItem("ahia.push_blocked_dismissed")
    ) {
      setPromptType("blocked");
    }
  }, []);

  const loadBusinesses = useCallback(async () => {
    const found = await listBusinesses();
    setBusinesses(found);
    let targetId: string | null = null;
    if (typeof window !== "undefined") {
      const urlParams = new URLSearchParams(window.location.search);
      const urlBiz = urlParams.get("business");
      if (urlBiz && found.some((candidate) => candidate.id === urlBiz)) {
        targetId = urlBiz;
        window.localStorage.setItem(ACTIVE_BUSINESS_KEY, urlBiz);
      } else {
        targetId = window.localStorage.getItem(ACTIVE_BUSINESS_KEY);
      }
    }
    const chosen = found.find((candidate) => candidate.id === targetId) ?? found[0] ?? null;
    setActiveBusinessId(chosen ? chosen.id : null);
    if (chosen) {
      void prefetchAllAppData(chosen.id);
    }
    return chosen;
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const u = await currentUser();
        setUser(u);
        await loadBusinesses();
      } catch {
        // No session: the pages below send the person to sign in, and this frame stays out of the way
        // rather than showing a navigation that leads nowhere.
        router.replace("/start");
      }
    })();
  }, [loadBusinesses, router]);

  useEffect(() => {
    if (activeBusinessId) {
      void prefetchAllAppData(activeBusinessId);
    }
    // Subscribe all businesses the user has access to for multi-stall notifications
    if (
      typeof window !== "undefined" &&
      "Notification" in window &&
      Notification.permission === "granted" &&
      businesses.length > 0
    ) {
      for (const biz of businesses) {
        void subscribeToWebPush(biz.id).catch(() => {});
      }
    }
  }, [activeBusinessId, businesses]);

  const switchBusiness = useCallback(
    (businessId: string) => {
      if (typeof window !== "undefined") {
        window.localStorage.setItem(ACTIVE_BUSINESS_KEY, businessId);
      }
      setActiveBusinessId(businessId);
      // A full navigation rather than a state change: every page reads the business when it loads, and
      // a client-side transition would leave the previous shop's numbers on screen while it did.
      router.refresh();
      window.location.reload();
    },
    [router],
  );

  const handleSignOut = useCallback(async () => {
    try {
      await signOut();
    } catch {
      // Continue cleanup on failure
    }
    if (typeof window !== "undefined") {
      window.localStorage.removeItem("ahia.session");
      window.localStorage.removeItem(ACTIVE_BUSINESS_KEY);
    }
    router.replace("/start");
  }, [router]);

  const handleEnablePush = useCallback(async () => {
    setPushEnabling(true);
    try {
      const activeBiz = activeBusinessId || businesses[0]?.id;
      if (activeBiz) {
        const res = await subscribeToWebPush(activeBiz);
        if (res.success) {
          for (const b of businesses) {
            if (b.id !== activeBiz) {
              void subscribeToWebPush(b.id).catch(() => {});
            }
          }
          setPromptType(null);
        } else if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "denied") {
          setPromptType("blocked");
        } else {
          setPromptType(null);
        }
      }
    } finally {
      setPushEnabling(false);
    }
  }, [activeBusinessId, businesses]);

  const handleDismissPush = useCallback(() => {
    if (promptType === "ask") {
      if (typeof window !== "undefined") {
        window.sessionStorage.setItem("ahia.push_prompt_dismissed", "1");
      }
    } else if (promptType === "blocked") {
      if (typeof window !== "undefined") {
        window.sessionStorage.setItem("ahia.push_blocked_dismissed", "1");
      }
    } else if (promptType === "ios_tip") {
      if (typeof window !== "undefined") {
        window.sessionStorage.setItem("ahia.ios_push_dismissed", "1");
      }
    }
    setPromptType(null);
  }, [promptType]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const legacy = window.localStorage.getItem("ahia.user_avatar");
    if (legacy && !legacy.startsWith("http")) {
      window.localStorage.removeItem("ahia.user_avatar");
    }
  }, []);

  const rawAvatarUrl =
    user?.avatar_url ||
    (typeof window !== "undefined"
      ? (user?.id ? window.localStorage.getItem(`ahia.user_avatar.${user.id}`) : null) ||
        window.localStorage.getItem("ahia.user_avatar")
      : null);
  const avatarUrl =
    rawAvatarUrl && (rawAvatarUrl.startsWith("http://") || rawAvatarUrl.startsWith("https://"))
      ? rawAvatarUrl
      : null;

  return (
    <AppShell
      businesses={businesses.map((business) => ({
        id: business.id,
        name: business.name,
        role_name: business.role_name,
      }))}
      activeBusinessId={activeBusinessId}
      personName={user ? `${user.first_name} ${user.last_name || ""}`.trim() : ""}
      avatarUrl={avatarUrl}
      onSwitchBusiness={switchBusiness}
      onSignOut={handleSignOut}
    >
      {promptType === "ask" && (
        <aside
          role="region"
          aria-label="Push notifications prompt"
          style={{
            position: "sticky",
            top: 0,
            zIndex: 90,
            background: "linear-gradient(135deg, #0b5d3b 0%, #064028 100%)",
            color: "#ffffff",
            padding: "12px 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "12px",
            flexWrap: "wrap",
            boxShadow: "0 4px 12px rgba(0, 0, 0, 0.25)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.15)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: "1 1 280px" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: "32px",
                height: "32px",
                borderRadius: "50%",
                background: "rgba(255,255,255,0.18)",
                flexShrink: 0,
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              </svg>
            </span>
            <div>
              <div style={{ fontWeight: 700, fontSize: "14px", lineHeight: "1.2" }}>
                Enable Instant Shop Alerts
              </div>
              <div style={{ fontSize: "12px", opacity: 0.9, marginTop: "2px", lineHeight: "1.3" }}>
                Get notified on this device when customers submit orders, upload payment receipts, or stock finishes.
              </div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              type="button"
              onClick={handleEnablePush}
              disabled={pushEnabling}
              style={{
                backgroundColor: "#ffffff",
                color: "#064028",
                border: "none",
                fontWeight: 700,
                fontSize: "13px",
                padding: "8px 14px",
                borderRadius: "8px",
                cursor: "pointer",
              }}
            >
              {pushEnabling ? "Enabling..." : "Turn On Alerts"}
            </button>
            <button
              type="button"
              onClick={handleDismissPush}
              style={{
                backgroundColor: "transparent",
                color: "rgba(255, 255, 255, 0.85)",
                border: "1px solid rgba(255, 255, 255, 0.35)",
                fontWeight: 500,
                fontSize: "13px",
                padding: "7px 12px",
                borderRadius: "8px",
                cursor: "pointer",
              }}
            >
              Later
            </button>
          </div>
        </aside>
      )}

      {promptType === "blocked" && (
        <aside
          role="region"
          aria-label="Notifications blocked notice"
          style={{
            position: "sticky",
            top: 0,
            zIndex: 90,
            background: "#7c2d12",
            color: "#ffffff",
            padding: "12px 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "12px",
            flexWrap: "wrap",
            boxShadow: "0 4px 12px rgba(0, 0, 0, 0.25)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.15)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: "1 1 280px" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: "32px",
                height: "32px",
                borderRadius: "50%",
                background: "rgba(255,255,255,0.18)",
                flexShrink: 0,
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </span>
            <div>
              <div style={{ fontWeight: 700, fontSize: "14px", lineHeight: "1.2" }}>
                Notifications Are Blocked in Your Browser
              </div>
              <div style={{ fontSize: "12px", opacity: 0.9, marginTop: "2px", lineHeight: "1.3" }}>
                Click the lock/settings icon in your browser URL bar, set Notifications to "Allow", and reload to get shop alerts.
              </div>
            </div>
          </div>
          <div>
            <button
              type="button"
              onClick={handleDismissPush}
              style={{
                backgroundColor: "#ffffff",
                color: "#7c2d12",
                border: "none",
                fontWeight: 700,
                fontSize: "13px",
                padding: "8px 14px",
                borderRadius: "8px",
                cursor: "pointer",
              }}
            >
              Got It
            </button>
          </div>
        </aside>
      )}

      {promptType === "ios_tip" && (
        <aside
          role="region"
          aria-label="iOS notification tip"
          style={{
            position: "sticky",
            top: 0,
            zIndex: 90,
            background: "#1e293b",
            color: "#ffffff",
            padding: "12px 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "12px",
            flexWrap: "wrap",
            boxShadow: "0 4px 12px rgba(0, 0, 0, 0.25)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.15)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: "1 1 280px" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: "32px",
                height: "32px",
                borderRadius: "50%",
                background: "rgba(255,255,255,0.18)",
                flexShrink: 0,
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
                <polyline points="16 6 12 2 8 6" />
                <line x1="12" y1="2" x2="12" y2="15" />
              </svg>
            </span>
            <div>
              <div style={{ fontWeight: 700, fontSize: "14px", lineHeight: "1.2" }}>
                Get Instant Shop Alerts on iPhone
              </div>
              <div style={{ fontSize: "12px", opacity: 0.9, marginTop: "2px", lineHeight: "1.3" }}>
                Apple requires adding AHIA to your Home Screen: Tap the Share button in Safari, then tap "Add to Home Screen".
              </div>
            </div>
          </div>
          <div>
            <button
              type="button"
              onClick={handleDismissPush}
              style={{
                backgroundColor: "#ffffff",
                color: "#1e293b",
                border: "none",
                fontWeight: 700,
                fontSize: "13px",
                padding: "8px 14px",
                borderRadius: "8px",
                cursor: "pointer",
              }}
            >
              Got It
            </button>
          </div>
        </aside>
      )}
      {children}
    </AppShell>
  );
}
