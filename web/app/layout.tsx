import type { Metadata } from "next";
import { DOTTED_CAPITAL_I } from "@/components/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: `AH${DOTTED_CAPITAL_I}A`,
  description: "Record a sale, watch the stock move, see the money.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
