import { NextResponse } from "next/server";
import { resolveApiBaseUrl, DEPLOYED_API } from "@/lib/server-api";

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

  let upstream: Response | null = null;

  try {
    upstream = await fetch(
      `${baseUrl}/shop/${encodeURIComponent(slug)}/customer-lists?phone=${encodeURIComponent(phone)}`,
      {
        headers: {
          Accept: "application/json",
        },
      },
    );
  } catch {
    if (baseUrl !== DEPLOYED_API) {
      try {
        upstream = await fetch(
          `${DEPLOYED_API}/shop/${encodeURIComponent(slug)}/customer-lists?phone=${encodeURIComponent(phone)}`,
          {
            headers: {
              Accept: "application/json",
            },
          },
        );
      } catch {
        // Fallback also failed
      }
    }
  }

  if (!upstream) {
    return NextResponse.json([], { status: 502 });
  }

  const data = await upstream.json().catch(() => null);
  return NextResponse.json(data ?? [], { status: upstream.status });
}
