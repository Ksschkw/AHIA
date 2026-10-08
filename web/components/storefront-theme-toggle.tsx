"use client";

import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "@/components/icons";
import styles from "./storefront-theme-toggle.module.css";

const STORAGE_KEY = "ahia.visitor_theme";

export function StorefrontThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "dark" || stored === "light") {
        setTheme(stored);
        document.documentElement.setAttribute("data-theme", stored);
      } else {
        const rootTheme = document.documentElement.getAttribute("data-theme");
        if (rootTheme === "dark" || rootTheme === "light") {
          setTheme(rootTheme);
        } else if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
          setTheme("dark");
          document.documentElement.setAttribute("data-theme", "dark");
        }
      }
    } catch {
      // Non-fatal
    }
    setMounted(true);
  }, []);

  const toggleTheme = () => {
    const nextTheme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    try {
      window.localStorage.setItem(STORAGE_KEY, nextTheme);
      document.documentElement.setAttribute("data-theme", nextTheme);
      window.dispatchEvent(new CustomEvent("ahia-theme-change", { detail: nextTheme }));
    } catch {
      // Non-fatal
    }
  };

  // Provide stable SSR placeholder to avoid layout shift
  if (!mounted) {
    return (
      <button
        type="button"
        className={styles.toggleBtn}
        aria-label="Toggle light or dark theme"
        disabled
      >
        <span className={styles.iconWrapper}>
          <SunIcon size={16} />
        </span>
        <span className={styles.toggleLabel}>Theme</span>
      </button>
    );
  }

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      className={styles.toggleBtn}
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      <span className={styles.iconWrapper}>
        {isDark ? <SunIcon size={16} /> : <MoonIcon size={16} />}
      </span>
      <span className={styles.toggleLabel}>{isDark ? "Light" : "Dark"}</span>
    </button>
  );
}
