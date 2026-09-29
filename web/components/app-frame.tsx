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
  signOut,
  type TenantSummary,
  type UserProfile,
} from "@/lib/api";

export const ACTIVE_BUSINESS_KEY = "ahia.business";

export function AppFrame({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [businesses, setBusinesses] = useState<TenantSummary[]>([]);
  const [activeBusinessId, setActiveBusinessId] = useState<string | null>(null);

  const loadBusinesses = useCallback(async () => {
    const found = await listBusinesses();
    setBusinesses(found);
    const remembered =
      typeof window === "undefined" ? null : window.localStorage.getItem(ACTIVE_BUSINESS_KEY);
    const chosen = found.find((candidate) => candidate.id === remembered) ?? found[0] ?? null;
    setActiveBusinessId(chosen ? chosen.id : null);
    return chosen;
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        setUser(await currentUser());
        await loadBusinesses();
      } catch {
        // No session: the pages below send the person to sign in, and this frame stays out of the way
        // rather than showing a navigation that leads nowhere.
        router.replace("/start");
      }
    })();
  }, [loadBusinesses, router]);

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

  return (
    <AppShell
      businesses={businesses.map((business) => ({
        id: business.id,
        name: business.name,
        role_name: business.role_name,
      }))}
      activeBusinessId={activeBusinessId}
      personName={user ? `${user.first_name} ${user.last_name}` : ""}
      onSwitchBusiness={switchBusiness}
      onSignOut={handleSignOut}
    >
      {children}
    </AppShell>
  );
}
