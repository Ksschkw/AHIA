import type { MetadataRoute } from "next";

/**
 * The shop as something installable.
 *
 * A trader who uses AHIA every day should not be opening a browser and typing an address: the app belongs on
 * his home screen with an icon, opening without browser chrome, and working when the network is poor. That is
 * what a manifest is for, and it is the same page - no separate build, no store, no download.
 *
 * Deliberately no offline caching rules here: what the service worker keeps is a decision about a trader's
 * data, and it belongs where it can be read alongside the sync rules rather than in a metadata file.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "AHIA - your shop, your list, your waybill",
    short_name: "AHIA",
    description:
      "For traders: what is on the shelf, what a list comes to, and what you made on it.",
    // The shelf is where a trader starts his day, and it is the screen that opens.
    start_url: "/app",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#f7f3ec",
    theme_color: "#0b5d3b",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
