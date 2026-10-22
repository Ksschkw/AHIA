import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const FALLBACK_DOWNLOAD_URL =
  "https://github.com/Ksschkw/AHIA/releases/download/v0.4.6/AHIA-v0.4.6-android.apk";

export async function GET() {
  try {
    const res = await fetch(
      "https://api.github.com/repos/Ksschkw/AHIA/releases/latest",
      {
        headers: {
          Accept: "application/vnd.github.v3+json",
          "User-Agent": "AHIA-Web",
        },
        next: { revalidate: 60 },
      },
    );

    if (res.ok) {
      const release = (await res.json()) as {
        assets?: Array<{ name?: string; browser_download_url?: string }>;
      };

      const apkAsset = release.assets?.find(
        (asset) =>
          typeof asset.name === "string" && asset.name.endsWith(".apk"),
      );

      if (apkAsset?.browser_download_url) {
        return NextResponse.redirect(apkAsset.browser_download_url, 302);
      }
    }
  } catch {
    // Fall back to known release asset if GitHub API is unreachable
  }

  return NextResponse.redirect(FALLBACK_DOWNLOAD_URL, 302);
}
