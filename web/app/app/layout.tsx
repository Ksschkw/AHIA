import type { ReactNode } from "react";

import { AppFrame } from "@/components/app-frame";

/**
 * Every screen inside the application shares this frame.
 *
 * A layout rather than a component each page imports: a page cannot forget it, and a new page gets the
 * navigation for free. That is the difference between "we have a design system" and a design system
 * that is actually applied.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppFrame>{children}</AppFrame>;
}
