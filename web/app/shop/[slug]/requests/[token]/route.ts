import { NextResponse } from "next/server";
import { resolveApiBaseUrl, DEPLOYED_API } from "@/lib/server-api";

export const dynamic = "force-dynamic";

/**
 * Public endpoint to poll a customer list by token.
 *
 * Reads live list state server-to-server and passes it directly to the customer.
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ slug: string; token: string }> },
) {
  const { slug, token } = await context.params;
  const baseUrl = resolveApiBaseUrl();

  let upstream: Response | null = null;

  try {
    upstream = await fetch(
      `${baseUrl}/shop/${encodeURIComponent(slug)}/requests/${encodeURIComponent(token)}`,
      {
        headers: { Accept: "application/json" },
        cache: "no-store",
      },
    );
  } catch {
    if (baseUrl !== DEPLOYED_API) {
      try {
        upstream = await fetch(
          `${DEPLOYED_API}/shop/${encodeURIComponent(slug)}/requests/${encodeURIComponent(token)}`,
          {
            headers: { Accept: "application/json" },
            cache: "no-store",
          },
        );
      } catch {
        // Fallback also failed
      }
    }
  }

  if (!upstream) {
    return NextResponse.json(
      { error: { message: "We could not reach the shop service." } },
      { status: 502 },
    );
  }

  const data = await upstream.json().catch(() => null);
  return NextResponse.json(
    data ?? { error: { message: "List not found" } },
    { status: upstream.status },
  );
}
