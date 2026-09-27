import type { Metadata, Viewport } from "next";
import { DOTTED_CAPITAL_I } from "@/components/brand";
import "./globals.css";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: "#084a2f",
};

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
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("ahia.theme");if(t==="dark"){document.documentElement.setAttribute("data-theme","dark")}else{document.documentElement.setAttribute("data-theme","light")}}catch(e){}})()`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
