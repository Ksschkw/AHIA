import { NextResponse } from "next/server";
import { resolveApiBaseUrl } from "@/lib/server-api";

export const dynamic = "force-dynamic";

/**
 * Public endpoint to list a customer's previous requests for a shop.
 *
 * Proxies the request server-side directly to the backend API to avoid
 * CORS or mixed-content issues on CDN edge deployments.
 */
export async function GET(
  request: Request,
  context: { params: Promise<{ slug: string }> },
) {
  const { slug } = await context.params;
  const baseUrl = resolveApiBaseUrl();
  const url = new URL(request.url);
  const phone = url.searchParams.get("phone") ?? "";

  try {
    const upstream = await fetch(
      `${baseUrl}/shop/${encodeURIComponent(slug)}/customer-lists?phone=${encodeURIComponent(phone)}`,
      {
        headers: {
          Accept: "application/json",
        },
      },
    );

    const data = await upstream.json().catch(() => null);
    return NextResponse.json(data ?? [], { status: upstream.status });
  } catch {
    return NextResponse.json([], { status: 502 });
  }
}
