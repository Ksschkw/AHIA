/**
 * Visual SVG illustrations for empty states and beginner onboarding.
 *
 * Designed with pure ASCII characters and standard SVG geometry to comply with ADR-0006.
 * Line weights match the 1.8px-2px stroke system of the application icons.
 */

import type { SVGProps } from "react";

type IllustrationProps = SVGProps<SVGSVGElement> & { size?: number };

/** Empty shelf: store rack waiting for categories and goods. */
export function EmptyShelfIllustration({ size = 120, ...rest }: IllustrationProps) {
  return (
    <svg
      width={size}
      height={Math.round((size * 5) / 6)}
      viewBox="0 0 120 100"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...rest}
    >
      {/* Upright shelf pillars */}
      <line x1="20" y1="15" x2="20" y2="85" />
      <line x1="100" y1="15" x2="100" y2="85" />

      {/* Top shelf tier */}
      <line x1="14" y1="38" x2="106" y2="38" />
      {/* Bottom shelf tier */}
      <line x1="14" y1="72" x2="106" y2="72" />

      {/* Product carton on top shelf */}
      <rect x="30" y="20" width="22" height="18" rx="2" strokeDasharray="none" />
      <line x1="30" y1="26" x2="52" y2="26" />
      <circle cx="41" cy="32" r="1.5" />

      {/* Tag dangling from top tier */}
      <path d="M72 38v8l6 4 6-4v-8H72Z" />
      <circle cx="78" cy="42" r="1" />

      {/* Ghost/dotted box on bottom shelf encouraging addition */}
      <rect x="42" y="52" width="36" height="20" rx="3" strokeDasharray="3 3" opacity="0.6" />
      <line x1="60" y1="58" x2="60" y2="66" strokeDasharray="none" opacity="0.8" />
      <line x1="56" y1="62" x2="64" y2="62" strokeDasharray="none" opacity="0.8" />

      {/* Floor baseline */}
      <line x1="10" y1="85" x2="110" y2="85" strokeWidth="1.2" opacity="0.4" />
    </svg>
  );
}

/** Empty requests: clipboard awaiting customer lists. */
export function EmptyRequestsIllustration({ size = 120, ...rest }: IllustrationProps) {
  return (
    <svg
      width={size}
      height={Math.round((size * 5) / 6)}
      viewBox="0 0 120 100"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...rest}
    >
      {/* Clipboard board */}
      <rect x="32" y="16" width="56" height="72" rx="4" />

      {/* Clipboard top clip */}
      <path d="M48 16V12a2 2 0 0 1 2-2h20a2 2 0 0 1 2 2v4" />
      <rect x="52" y="10" width="16" height="8" rx="1.5" />

      {/* Checklist rows */}
      <line x1="42" y1="34" x2="48" y2="34" />
      <line x1="54" y1="34" x2="78" y2="34" />

      <line x1="42" y1="46" x2="48" y2="46" />
      <line x1="54" y1="46" x2="74" y2="46" />

      <line x1="42" y1="58" x2="48" y2="58" />
      <line x1="54" y1="58" x2="70" y2="58" />

      {/* Dotted target line */}
      <rect x="42" y="68" width="36" height="12" rx="2" strokeDasharray="2 2" opacity="0.5" />

      {/* Check tick floating */}
      <polyline points="78 68 84 74 94 62" strokeWidth="2.2" />
    </svg>
  );
}

/** Empty basket: shopper's bag awaiting items. */
export function EmptyBasketIllustration({ size = 120, ...rest }: IllustrationProps) {
  return (
    <svg
      width={size}
      height={Math.round((size * 5) / 6)}
      viewBox="0 0 120 100"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...rest}
    >
      {/* Basket handles */}
      <path d="M42 42c0-14 7-22 18-22s18 8 18 22" />

      {/* Basket container */}
      <path d="M26 42h68l-8 42H34L26 42Z" />

      {/* Grid weave patterns */}
      <line x1="38" y1="42" x2="43" y2="84" strokeWidth="1.2" opacity="0.6" />
      <line x1="60" y1="42" x2="60" y2="84" strokeWidth="1.2" opacity="0.6" />
      <line x1="82" y1="42" x2="77" y2="84" strokeWidth="1.2" opacity="0.6" />
      <line x1="29" y1="56" x2="91" y2="56" strokeWidth="1.2" opacity="0.6" />
      <line x1="32" y1="70" x2="88" y2="70" strokeWidth="1.2" opacity="0.6" />

      {/* Plus badge inside */}
      <circle cx="86" cy="30" r="10" />
      <line x1="86" y1="25" x2="86" y2="35" />
      <line x1="81" y1="30" x2="91" y2="30" />
    </svg>
  );
}
