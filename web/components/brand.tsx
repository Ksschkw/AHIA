/**
 * The brand: the wordmark and the mark.
 *
 * **The dotted I is the point.** The product is AHIA, and in Igbo orthography that is written with a
 * dotted I - AHIA with an I that carries a dot. Rendering it as a plain "I" loses the language the
 * name comes from, and rendering it as a *character in the source* would break the repository's
 * ASCII-only rule for engineering artifacts (ADR-0006). So it is written as an escape sequence: the
 * source stays ASCII, and the screen shows the correct letter. That is the one place in this
 * codebase where those two facts meet, and this comment is why.
 *
 * The mark is deliberately small and geometric: a market grid - four stalls, one of them lit - inside
 * a rounded square. It reads at 16 pixels in a browser tab, which is the only size that matters for
 * an icon, and it says trade without drawing a market scene.
 */

import type { ReactNode } from "react";

import styles from "./brand.module.css";

/** The dotted capital I of Igbo orthography, expressed so the source file stays ASCII. */
export const DOTTED_CAPITAL_I = "\u1ECA";

export function BrandMark({ size = 40 }: { size?: number }) {
  const cells = [
    { x: 5, y: 5, filled: true },
    { x: 15, y: 5, filled: false },
    { x: 5, y: 15, filled: false },
    { x: 15, y: 15, filled: true },
  ];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role="img"
      aria-label="AHIA"
      className={styles.mark}
    >
      <rect x="1" y="1" width="22" height="22" rx="7" className={styles.markPlate} />
      {cells.map((cell) => (
        <rect
          key={`${cell.x}-${cell.y}`}
          x={cell.x}
          y={cell.y}
          width="4"
          height="4"
          rx="1.2"
          className={cell.filled ? styles.markCellFilled : styles.markCell}
        />
      ))}
    </svg>
  );
}

/**
 * The name, with the dotted I given the accent colour so the letter that carries the language is the
 * letter a reader notices.
 */
export function Wordmark({ size = "regular" }: { size?: "regular" | "large" }) {
  return (
    <span className={`${styles.wordmark} ${size === "large" ? styles.wordmarkLarge : ""}`}>
      <span>AH</span>
      <span className={styles.dotted}>{DOTTED_CAPITAL_I}</span>
      <span>A</span>
    </span>
  );
}

export function Brand({ children, size = 40 }: { children?: ReactNode; size?: number }) {
  return (
    <span className={styles.brand}>
      <BrandMark size={size} />
      {children ?? <Wordmark />}
    </span>
  );
}
