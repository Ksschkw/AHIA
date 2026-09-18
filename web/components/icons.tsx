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

/* ---------------------------------------------------------------------------
 * The navigation set.
 *
 * One glyph per destination, drawn on the same 24-unit grid and at the same stroke weight as the
 * action icons above, so the rail and the buttons look like the same hand drew them. A name rather
 * than a component in the shell, because a navigation list is data - it is mapped over, filtered and
 * ordered - and data cannot hold JSX without making the list harder to read than the icons are worth.
 * ------------------------------------------------------------------------- */

/** The shop: an awning over a counter. */
function ShopGlyph() {
  return (
    <>
      <path d="M3 9.5 5 4h14l2 5.5" />
      <path d="M4 9.5h16V20H4z" />
      <path d="M9 20v-5h6v5" />
    </>
  );
}

/** A sale: a receipt with a torn edge. */
function ReceiptGlyph() {
  return (
    <>
      <path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" />
      <path d="M9.5 8h5M9.5 12h5" />
    </>
  );
}

/** An item on the shelf: a carton seen at an angle. */
function BoxGlyph() {
  return (
    <>
      <path d="M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5z" />
      <path d="M3.5 7.5 12 12l8.5-4.5M12 12v9" />
    </>
  );
}

/** A customer's list: lines with ticks. */
function ListGlyph() {
  return (
    <>
      <path d="M4 6.5h2M4 12h2M4 17.5h2" />
      <path d="M9 6.5h11M9 12h11M9 17.5h11" />
    </>
  );
}

/** People: the team. */
function PeopleGlyph() {
  return (
    <>
      <circle cx="9" cy="9" r="3" />
      <path d="M3.5 20c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
      <path d="M16 7.5a3 3 0 0 1 0 5.5M17.5 15c2 .6 3 2.3 3 5" />
    </>
  );
}

/** A price tag: the price book. */
function TagGlyph() {
  return (
    <>
      <path d="M11.5 3H21v9.5L11 22.5 2.5 14z" />
      <circle cx="17" cy="7" r="1.4" />
    </>
  );
}

/** One person: the profile. */
function PersonGlyph() {
  return (
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 20c0-3.5 3-6 7-6s7 2.5 7 6" />
    </>
  );
}

const NAVIGATION_GLYPHS = {
  store: ShopGlyph,
  receipt: ReceiptGlyph,
  box: BoxGlyph,
  list: ListGlyph,
  people: PeopleGlyph,
  tag: TagGlyph,
  person: PersonGlyph,
} as const;

export type NavigationIconName = keyof typeof NAVIGATION_GLYPHS;

/** One navigation icon, chosen by name. */
export function Icon({ name, ...rest }: IconProps & { name: NavigationIconName }) {
  const Glyph = NAVIGATION_GLYPHS[name];
  return (
    <Frame {...rest}>
      <Glyph />
    </Frame>
  );
}

/** Every navigation name, so a test can assert the shell only ever asks for glyphs that exist. */
export const NAVIGATION_ICON_NAMES = Object.keys(
  NAVIGATION_GLYPHS,
) as NavigationIconName[];
