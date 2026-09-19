import type { Metadata } from "next";
import { DOTTED_CAPITAL_I } from "@/components/brand";
import "./globals.css";

export const metadata: Metadata = {
  // Installable: the manifest is what puts the shop on a home screen, and these are what make it open without
  // browser chrome on iOS, which reads neither the manifest's display field nor anything else reliably.
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "AHIA",
    statusBarStyle: "default",
  },
  icons: {
    icon: "/icon-192.png",
    apple: "/icon-192.png",
  },
  formatDetection: { telephone: false },
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
