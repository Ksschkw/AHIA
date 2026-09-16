import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AHIA",
  description: "Record a sale, watch the stock move, see the money.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
