"use client";

/**
 * The frame every screen in the application sits inside.
 *
 * Provides identical navigation across desktop and phone views, matching the mobile app:
 * - On a phone: 5 persistent bottom tabs (Shop, Catalog, Lists, Trading, More).
 * - On a desk: A clean side rail with all destinations, business switcher, and user profile.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Icon } from "@/components/icons";
import { Wordmark } from "@/components/brand";
import { cachedRead, listCustomerLists, type CustomerList } from "@/lib/api";
import styles from "./app-shell.module.css";

export interface ShellBusiness {
  id: string;
  name: string;
  role_name?: string;
}

export interface AppShellProps {
  children: ReactNode;
  businesses: ShellBusiness[];
  activeBusinessId: string | null;
  personName: string;
  avatarUrl?: string | null;
  onSwitchBusiness: (businessId: string) => void;
  onSignOut?: () => void;
}

export interface Destination {
  href: string;
  label: string;
  short: string;
  icon: Parameters<typeof Icon>[0]["name"];
}

export const DESTINATIONS: Destination[] = [
  { href: "/app", label: "The shop", short: "Shop", icon: "store" },
  { href: "/app/items", label: "Catalog", short: "Catalog", icon: "box" },
  { href: "/app/lists", label: "Lists", short: "Lists", icon: "list" },
  { href: "/app/sales", label: "Trading", short: "Trading", icon: "receipt" },
  { href: "/app/more", label: "More", short: "More", icon: "more" },
];

/** True when the destination is the current screen. */
function isCurrent(pathname: string, href: string): boolean {
  if (href === "/app") {
    return pathname === "/app";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({
  children,
  businesses,
  activeBusinessId,
  personName,
  avatarUrl,
  onSwitchBusiness,
  onSignOut,
}: AppShellProps) {
  const pathname = usePathname() ?? "/app";
  const active = businesses.find((business) => business.id === activeBusinessId) ?? businesses[0];
  const [inFlight, setInFlight] = useState(0);
  const [pendingListsCount, setPendingListsCount] = useState<number>(0);

  // Read cached customer lists to show badge on Lists tab
  useEffect(() => {
    if (!active?.id) return;
    const cached = cachedRead<CustomerList[]>(`/api/v1/tenants/${active.id}/requests`);
    if (cached) {
      setPendingListsCount(cached.filter((l) => l.status !== "confirmed").length);
    }
    void listCustomerLists(active.id)
      .then((lists) => {
        setPendingListsCount(lists.filter((l) => l.status !== "confirmed").length);
      })
      .catch(() => {});
  }, [active?.id]);

  useEffect(() => {
    const listener = (event: Event) => {
      setInFlight(Number((event as CustomEvent<number>).detail ?? 0));
    };
    window.addEventListener("ahia:inflight", listener);
    setInFlight(Number(window.__ahiaInFlight ?? 0));
    return () => window.removeEventListener("ahia:inflight", listener);
  }, []);

  const [theme, setTheme] = useState<"light" | "dark">("dark");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem("ahia.theme");
    if (saved === "light") {
      setTheme("light");
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      setTheme("dark");
      document.documentElement.setAttribute("data-theme", "dark");
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      if (typeof window !== "undefined") {
        window.localStorage.setItem("ahia.theme", next);
        if (next === "dark") {
          document.documentElement.setAttribute("data-theme", "dark");
        } else {
          document.documentElement.setAttribute("data-theme", "light");
        }
      }
      return next;
    });
  }, []);

  return (
    <div className={styles.shell}>
      {/* Progress indicator */}
      <div
        className={inFlight > 0 ? styles.progressActive : styles.progress}
        role="progressbar"
        aria-label="Working"
        aria-hidden={inFlight === 0}
      />

      <a className={styles.skip} href="#main">
        Skip to the content
      </a>

      {/* Desktop Rail Navigation */}
      <nav className={styles.rail} aria-label="Sections">
        <Link className={styles.railBrand} href="/app">
          <Wordmark />
        </Link>

        {businesses.length > 0 ? (
          <label className={styles.switcher}>
            <span className={styles.switcherLabel}>You are working in</span>
            <select
              className={styles.switcherSelect}
              value={active?.id ?? ""}
              onChange={(event) => onSwitchBusiness(event.target.value)}
            >
              {businesses.map((business) => (
                <option key={business.id} value={business.id}>
                  {business.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <ul className={styles.railList}>
          {DESTINATIONS.map((destination) => {
            const hasBadge = destination.href === "/app/lists" && pendingListsCount > 0;
            return (
              <li key={destination.href}>
                <Link
                  className={
                    isCurrent(pathname, destination.href)
                      ? `${styles.railLink} ${styles.railLinkCurrent}`
                      : styles.railLink
                  }
                  href={destination.href}
                  aria-current={isCurrent(pathname, destination.href) ? "page" : undefined}
                >
                  <Icon name={destination.icon} />
                  <span>{destination.label}</span>
                  {hasBadge ? (
                    <span
                      style={{
                        marginLeft: "auto",
                        background: "var(--leaf, #238636)",
                        color: "#fff",
                        fontSize: "11px",
                        fontWeight: 700,
                        padding: "1px 6px",
                        borderRadius: "999px",
                      }}
                    >
                      {pendingListsCount}
                    </span>
                  ) : null}
                </Link>
              </li>
            );
          })}
        </ul>

        <button
          type="button"
          className={styles.themeToggle}
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        >
          <span>Theme</span>
          <span>{theme === "dark" ? "Dark Mode" : "Light Mode"}</span>
        </button>

        <div className={styles.railFootWrap}>
          <Link href="/app/profile" className={styles.railUserRow} title="Manage Profile">
            {avatarUrl ? (
              <img src={avatarUrl} alt={personName} className={styles.railAvatar} />
            ) : (
              <span className={styles.railAvatarInitials}>
                {(personName[0] ?? "U").toUpperCase()}
              </span>
            )}
            <p className={styles.railFoot}>
              Signed in as
              <br />
              <strong>{personName}</strong>
            </p>
          </Link>
          {onSignOut ? (
            <button
              type="button"
              className={styles.railSignOutBtn}
              onClick={onSignOut}
              aria-label="Sign out of your account"
            >
              Sign out
            </button>
          ) : null}
        </div>
      </nav>

      <div className={styles.body}>
        {/* Mobile Top Bar */}
        <header className={styles.topbar}>
          <Link className={styles.topbarBrand} href="/app">
            <Wordmark />
          </Link>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Link href="/app/profile" title="View Profile" style={{ display: "flex", alignItems: "center" }}>
              {avatarUrl ? (
                <img src={avatarUrl} alt={personName} className={styles.topbarAvatar} />
              ) : (
                <span className={styles.topbarAvatarInitials}>
                  {(personName[0] ?? "U").toUpperCase()}
                </span>
              )}
            </Link>
            <button
              type="button"
              className={styles.themeToggleTopbar}
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              <span>{theme === "dark" ? "Dark" : "Light"}</span>
            </button>
            {businesses.length > 1 ? (
              <select
                className={styles.topbarSelect}
                value={active?.id ?? ""}
                onChange={(event) => onSwitchBusiness(event.target.value)}
                aria-label="Which business"
              >
                {businesses.map((business) => (
                  <option key={business.id} value={business.id}>
                    {business.name}
                  </option>
                ))}
              </select>
            ) : (
              <span className={styles.topbarName}>{active?.name ?? ""}</span>
            )}
          </div>
        </header>

        <main className={styles.main} id="main">
          {children}
        </main>
      </div>

      {/* Persistent 5-Tab Bottom Navigation Bar matching Mobile App identically */}
      <nav className={styles.bottombar} aria-label="Sections">
        {DESTINATIONS.map((destination) => {
          const hasBadge = destination.href === "/app/lists" && pendingListsCount > 0;
          return (
            <Link
              className={
                isCurrent(pathname, destination.href)
                  ? `${styles.bottombarLink} ${styles.bottombarLinkCurrent}`
                  : styles.bottombarLink
              }
              href={destination.href}
              key={destination.href}
              aria-current={isCurrent(pathname, destination.href) ? "page" : undefined}
            >
              <span className={styles.bottombarIconWrap}>
                <Icon name={destination.icon} />
                {hasBadge ? (
                  <span className={styles.bottombarBadge}>{pendingListsCount}</span>
                ) : null}
              </span>
              <span>{destination.short}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
