"use client";

/**
 * The frame every screen in the application sits inside.
 *
 * Before this existed, each page drew its own header and its own idea of where navigation lives, so
 * the product read as a set of pages rather than one application - and on a phone, most destinations
 * were simply out of reach. There is now exactly one place that decides where navigation is:
 *
 *   * on a phone, a **bottom bar**: the four things a trader does standing up, under the thumb.
 *   * on a desk, a **side rail**: everywhere, with room for the words rather than only the icons.
 *
 * The destinations are ordered by how often they are used, not by how they were built: the shop first,
 * then sales, then the shelf, then what people are asking for. Everything else - the team, the prices,
 * the profile - is one tap away in a rail that is always visible on a desk and one tap away on a phone.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Icon } from "@/components/icons";
import { Wordmark } from "@/components/brand";
import styles from "./app-shell.module.css";

export interface ShellBusiness {
  id: string;
  name: string;
}

export interface AppShellProps {
  children: ReactNode;
  businesses: ShellBusiness[];
  activeBusinessId: string | null;
  personName: string;
  onSwitchBusiness: (businessId: string) => void;
}

interface Destination {
  href: string;
  label: string;
  short: string;
  icon: Parameters<typeof Icon>[0]["name"];
  /** In the bottom bar on a phone: the four things worth a permanent slot. */
  primary: boolean;
}

export const DESTINATIONS: Destination[] = [
  { href: "/app", label: "The shop", short: "Shop", icon: "store", primary: true },
  { href: "/app/sales", label: "Sales", short: "Sales", icon: "receipt", primary: true },
  { href: "/app/items", label: "Items", short: "Items", icon: "box", primary: true },
  { href: "/app/lists", label: "Lists", short: "Lists", icon: "list", primary: true },
  { href: "/app/team", label: "Team", short: "Team", icon: "people", primary: false },
  { href: "/app/prices", label: "Prices", short: "Prices", icon: "tag", primary: false },
  { href: "/app/profile", label: "You", short: "You", icon: "person", primary: false },
];

/** True when the destination is the current screen, without matching "/app" against every path. */
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
  onSwitchBusiness,
}: AppShellProps) {
  const pathname = usePathname() ?? "/app";
  const active = businesses.find((business) => business.id === activeBusinessId) ?? businesses[0];
  const phoneDestinations = DESTINATIONS.filter((destination) => destination.primary);

  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#main">
        Skip to the content
      </a>

      {/* The rail is the desk's navigation. It is not rendered on a phone at all, rather than hidden
          with CSS, so nothing about it can trap a tap or a keyboard tab. */}
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
          {DESTINATIONS.map((destination) => (
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
              </Link>
            </li>
          ))}
        </ul>

        <p className={styles.railFoot}>
          Signed in as
          <br />
          <strong>{personName}</strong>
        </p>
      </nav>

      <div className={styles.body}>
        {/* The phone's bar carries the business and the way to record something, which is the two
            things a person needs while standing at the counter. */}
        <header className={styles.topbar}>
          <Link className={styles.topbarBrand} href="/app">
            <Wordmark />
          </Link>
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
        </header>

        <main className={styles.main} id="main">
          {children}
        </main>
      </div>

      <nav className={styles.bottombar} aria-label="Sections">
        {phoneDestinations.map((destination) => (
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
            <Icon name={destination.icon} />
            <span>{destination.short}</span>
          </Link>
        ))}
        <Link
          className={
            isCurrent(pathname, "/app/profile")
              ? `${styles.bottombarLink} ${styles.bottombarLinkCurrent}`
              : styles.bottombarLink
          }
          href="/app/profile"
          aria-current={isCurrent(pathname, "/app/profile") ? "page" : undefined}
        >
          <Icon name="person" />
          <span>You</span>
        </Link>
      </nav>
    </div>
  );
}
