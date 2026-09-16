/**
 * The icons the actions wear.
 *
 * Drawn here rather than pulled from an icon package: there are four of them, they need to match the
 * brand's line weight, and a dependency for four paths would be a dependency to keep updated for no
 * gain. Each is a stroke drawing on a 24 unit grid, so they line up with each other and scale with
 * the text around them.
 */

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Frame({ size = 22, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...rest}
    >
      {children}
    </svg>
  );
}

/** A sale: money changing hands, drawn as a note with a plus. */
export function SaleIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <rect x="2.5" y="6" width="19" height="12" rx="3" />
      <path d="M12 9.5v5M9.5 12h5" />
    </Frame>
  );
}

/** A product: a label on a new line of stock. */
export function ProductIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M3 12.5V5.5A2.5 2.5 0 0 1 5.5 3h7L21 11.5a2 2 0 0 1 0 2.8l-4.7 4.7a2 2 0 0 1-2.8 0L3 12.5Z" />
      <circle cx="8" cy="8" r="1.4" />
    </Frame>
  );
}

/** Stock in: a crate with an arrow arriving into it. */
export function StockIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M3 8.5 12 4l9 4.5v7L12 20l-9-4.5v-7Z" />
      <path d="M3 8.5 12 13l9-4.5M12 13v7" />
    </Frame>
  );
}

/** Spending: a receipt with a minus. */
export function ExpenseIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M5 3h14v18l-2.3-1.6L14.4 21l-2.4-1.6L9.6 21l-2.3-1.6L5 21V3Z" />
      <path d="M9 9h6M9 13h3" />
    </Frame>
  );
}
