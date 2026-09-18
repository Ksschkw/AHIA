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
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Icon } from "@/components/icons";
import { Wordmark } from "@/components/brand";
import { Sheet } from "@/components/ui";
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

/** Where the pinned destinations are remembered, so a person's own bar survives a reload. */
export const PINNED_DESTINATIONS_KEY = "ahia.pinned";

/**
 * How many fit in a phone's bottom bar before it stops being readable.
 *
 * Three, plus More and You, is five slots across 390 pixels - which is as many as a thumb can hit
 * without looking. Four made six, and six is a row of small targets rather than a navigation bar.
 */
export const MAXIMUM_PINNED = 3;

/**
 * The destinations in the bar on a phone.
 *
 * Three fit comfortably, plus "More" and "You" - and which three is the person's choice, because the
 * one who sells all day and the one who counts stock do not reach for the same screen. The default is
 * the order above, which is the order most shops would pick.
 */
function pinnedDestinations(pinnedHrefs: string[]): Destination[] {
  const chosen = DESTINATIONS.filter((destination) => pinnedHrefs.includes(destination.href));
  const fallback = DESTINATIONS.filter((destination) => destination.primary);
  const merged = [...chosen, ...fallback.filter((one) => !chosen.includes(one))];
  return merged.slice(0, MAXIMUM_PINNED);
}

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
  const [pinned, setPinned] = useState<string[]>([]);
  const [moreOpen, setMoreOpen] = useState(false);
  //: Non-zero while any request is in flight, from the one counter in the API client.
  const [inFlight, setInFlight] = useState(0);

  useEffect(() => {
    const remembered =
      typeof window === "undefined" ? null : window.localStorage.getItem(PINNED_DESTINATIONS_KEY);
    if (remembered) {
      try {
        const parsed = JSON.parse(remembered) as unknown;
        if (Array.isArray(parsed)) {
          setPinned(parsed.filter((entry): entry is string => typeof entry === "string"));
        }
      } catch {
        // A remembered value that cannot be read is not worth a broken navigation: the defaults stand.
      }
    }
  }, []);

  useEffect(() => {
    const listener = (event: Event) => {
      setInFlight(Number((event as CustomEvent<number>).detail ?? 0));
    };
    window.addEventListener("ahia:inflight", listener);
    setInFlight(Number(window.__ahiaInFlight ?? 0));
    return () => window.removeEventListener("ahia:inflight", listener);
  }, []);

  const togglePinned = useCallback((href: string) => {
    setPinned((current) => {
      const next = current.includes(href)
        ? current.filter((entry) => entry !== href)
        : [...current, href].slice(-MAXIMUM_PINNED);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(PINNED_DESTINATIONS_KEY, JSON.stringify(next));
      }
      return next;
    });
  }, []);

  const phoneDestinations = pinnedDestinations(pinned);

  return (
    <div className={styles.shell}>
      {/* One thin line, present the instant anything starts and gone the instant it finishes, so
          "is it doing anything?" is answered by a glance rather than by a guess. */}
      <div
        className={inFlight > 0 ? styles.progressActive : styles.progress}
        role="progressbar"
        aria-label="Working"
        aria-hidden={inFlight === 0}
      />

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
        <button
          className={styles.bottombarLink}
          onClick={() => setMoreOpen(true)}
          aria-expanded={moreOpen}
        >
          <Icon name="more" />
          <span>More</span>
        </button>
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

      {/* Everything, reachable from anywhere, and the place where the bar itself is chosen. A trader
          who never opens the prices should not have Prices taking a slot from the thing he does all
          day - and the pinning is remembered, so he only decides once. */}
      <Sheet open={moreOpen} title="Everything" onClose={() => setMoreOpen(false)}>
        <ul className={styles.moreList}>
          {DESTINATIONS.map((destination) => {
            const isPinned = phoneDestinations.some((one) => one.href === destination.href);
            return (
              <li className={styles.moreRow} key={destination.href}>
                <Link
                  className={styles.moreLink}
                  href={destination.href}
                  onClick={() => setMoreOpen(false)}
                >
                  <Icon name={destination.icon} />
                  <span>{destination.label}</span>
                </Link>
                <button
                  className={isPinned ? styles.pinOn : styles.pinOff}
                  onClick={() => togglePinned(destination.href)}
                  aria-label={
                    isPinned
                      ? `${destination.label} is in the bottom bar; tap to take it out`
                      : `${destination.label} is not in the bottom bar; tap to put it in`
                  }
                  aria-pressed={isPinned}
                >
                  {isPinned ? "In the bar" : "Add to the bar"}
                </button>
              </li>
            );
          })}
        </ul>
        <p className={styles.moreHint}>
          Three stay in the bar at the bottom of your screen, plus More and You. Choose the ones you
          use most - everything is always in here either way.
        </p>
      </Sheet>
    </div>
  );
}
