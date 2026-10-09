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

/** Empty sales: register receipt and coin awaiting first transaction. */
export function EmptySalesIllustration({ size = 120, ...rest }: IllustrationProps) {
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
      {/* Receipt paper with zig-zag bottom */}
      <path d="M38 18h44v58l-5.5-4-5.5 4-5.5-4-5.5 4-5.5-4-5.5 4-5.5-4-5.5 4V18Z" />
      {/* Receipt header line */}
      <line x1="48" y1="28" x2="72" y2="28" strokeWidth="2.2" />
      {/* Receipt item lines */}
      <line x1="46" y1="38" x2="60" y2="38" opacity="0.6" />
      <line x1="68" y1="38" x2="74" y2="38" opacity="0.6" />
      <line x1="46" y1="46" x2="58" y2="46" opacity="0.6" />
      <line x1="68" y1="46" x2="74" y2="46" opacity="0.6" />
      {/* Divider */}
      <line x1="44" y1="54" x2="76" y2="54" strokeDasharray="2 2" opacity="0.8" />
      {/* Total line */}
      <line x1="46" y1="62" x2="74" y2="62" strokeWidth="2" />
      {/* Coin badge on bottom right */}
      <circle cx="82" cy="70" r="14" fill="var(--card, #fff)" />
      <circle cx="82" cy="70" r="10" strokeDasharray="1.5 1.5" />
      <path d="M82 65v10M79 67h6M79 73h6" />
    </svg>
  );
}

/** Empty team: placeholder badge awaiting staff invitations. */
export function EmptyTeamIllustration({ size = 120, ...rest }: IllustrationProps) {
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
      {/* Center user avatar */}
      <circle cx="60" cy="38" r="14" />
      <path d="M40 76c0-11 9-20 20-20s20 9 20 20" />

      {/* Left dotted avatar */}
      <circle cx="28" cy="42" r="10" strokeDasharray="2 2" opacity="0.5" />
      <path d="M14 74c0-8 6-15 14-15" strokeDasharray="2 2" opacity="0.5" />

      {/* Right dotted avatar with plus */}
      <circle cx="92" cy="42" r="10" strokeDasharray="2 2" opacity="0.5" />
      <path d="M92 59c8 0 14 7 14 15" strokeDasharray="2 2" opacity="0.5" />
      <circle cx="92" cy="42" r="14" strokeDasharray="none" opacity="0.8" />
      <line x1="92" y1="36" x2="92" y2="48" />
      <line x1="86" y1="42" x2="98" y2="42" />

      {/* Base baseline */}
      <line x1="10" y1="84" x2="110" y2="84" strokeWidth="1.2" opacity="0.4" />
    </svg>
  );
}

/** Empty orders / tracking: package with radar pulse awaiting customer order history. */
export function EmptyOrdersIllustration({ size = 120, ...rest }: IllustrationProps) {
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
      {/* Central box / order package */}
      <polygon points="60 22 92 38 60 54 28 38" />
      <polygon points="28 38 60 54 60 84 28 68" />
      <polygon points="92 38 60 54 60 84 92 68" />
      {/* Box tape mark */}
      <line x1="60" y1="22" x2="60" y2="38" />
      <line x1="44" y1="46" x2="76" y2="46" />
      {/* Radar waves signaling tracking */}
      <path d="M20 28A46 46 0 0 1 100 28" strokeDasharray="3 3" opacity="0.4" />
      <path d="M12 20A58 58 0 0 1 108 20" strokeDasharray="3 3" opacity="0.25" />
      {/* Ground shadow line */}
      <ellipse cx="60" cy="88" rx="36" ry="6" opacity="0.15" />
    </svg>
  );
}

/** Directional pointer arrow down: guides first-time shoppers toward catalogue / search. */
export function DirectionPointerDownIllustration({ size = 48, ...rest }: IllustrationProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...rest}
    >
      <circle cx="24" cy="24" r="20" opacity="0.1" fill="currentColor" />
      <line x1="24" y1="12" x2="24" y2="34" />
      <polyline points="16 26 24 34 32 26" />
    </svg>
  );
}
