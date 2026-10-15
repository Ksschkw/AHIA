import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.redirect(
    "https://github.com/Ksschkw/AHIA/releases/latest/download/AHIA-latest.apk",
    302,
  );
}
