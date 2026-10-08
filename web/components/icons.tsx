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

/** More: three dots, which is the one sign everybody already reads as "there is more here". */
function MoreGlyph() {
  return (
    <>
      <circle cx="5.5" cy="12" r="1.4" />
      <circle cx="12" cy="12" r="1.4" />
      <circle cx="18.5" cy="12" r="1.4" />
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
  more: MoreGlyph,
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

/* ---------------------------------------------------------------------------
 * Descriptive action & entity icons.
 *
 * Drawn on the same 24-unit grid with matching line weights. Used across the
 * category tree, request workbench, search, and list builder to replace text
 * bloat with intuitive visual iconography.
 * ------------------------------------------------------------------------- */

/** A category folder: tab + body. */
export function FolderIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" />
    </Frame>
  );
}

/** An open category folder. */
export function FolderOpenIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="m6 14 1.5-6.5A2 2 0 0 1 9.4 6H20a2 2 0 0 1 2 2v1" />
      <path d="M3 8V5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v1" />
      <path d="M2.5 21h17.2a2 2 0 0 0 1.95-1.55L23 13.5A2 2 0 0 0 21 11H5.4a2 2 0 0 0-1.95 1.55L1 20a1 1 0 0 0 1.5 1Z" />
    </Frame>
  );
}

/** An item box / product carton. */
export function ItemBoxIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" />
      <path d="m3.3 7 8.7 5 8.7-5" />
      <path d="M12 22V12" />
    </Frame>
  );
}

/** Plus: add action. */
export function PlusIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M12 5v14M5 12h14" />
    </Frame>
  );
}

/** Chevron right: navigation drill-down / breadcrumb. */
export function ChevronRightIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="m9 18 6-6-6-6" />
    </Frame>
  );
}

/** Chevron down: accordion or dropdown expand. */
export function ChevronDownIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="m6 9 6 6 6-6" />
    </Frame>
  );
}

/** Search: magnifying glass. */
export function SearchIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.35-4.35" />
    </Frame>
  );
}

/** Checkmark: completed / saved. */
export function CheckMarkIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <polyline points="20 6 9 17 4 12" />
    </Frame>
  );
}

/** Cannot get: circle with diagonal line. */
export function CannotGetIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <circle cx="12" cy="12" r="10" />
      <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
    </Frame>
  );
}

/** Trash: remove item. */
export function TrashIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
    </Frame>
  );
}

/** Clock: pending / waiting. */
export function ClockIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </Frame>
  );
}

/** Phone / call. */
export function PhoneIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
    </Frame>
  );
}

/** Sparkles / Magic / Quick paste. */
export function SparklesIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3Z" />
    </Frame>
  );
}

/** Arrow Left / Back. */
export function ArrowLeftIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </Frame>
  );
}

/** Edit / pencil. */
export function EditIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
      <path d="m15 5 4 4" />
    </Frame>
  );
}

/** Close / cross: dismiss modal or dialog. */
export function CloseIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </Frame>
  );
}

/** Copy / duplicate pages or items. */
export function CopyIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
      <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
    </Frame>
  );
}

/** Android robot symbol for native app install CTA. */
export function AndroidIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M5 16v4M19 16v4M8 19h8M6 8h12a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2Z" />
      <path d="m8 5-1.5-2M16 5l1.5-2" />
      <circle cx="9" cy="12" r="1" fill="currentColor" />
      <circle cx="15" cy="12" r="1" fill="currentColor" />
    </Frame>
  );
}

/** Sun / Light mode toggle. */
export function SunIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </Frame>
  );
}

/** Moon / Dark mode toggle. */
export function MoonIcon(props: IconProps) {
  return (
    <Frame {...props}>
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </Frame>
  );
}
