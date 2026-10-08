import { NextResponse } from "next/server";
import { resolveApiBaseUrl, DEPLOYED_API } from "@/lib/server-api";

export const dynamic = "force-dynamic";

/**
 * Public endpoint to submit a customer list.
 *
 * Proxies the submission server-side directly to the backend API.
 * This completely avoids browser mixed-content blocks (HTTPS -> HTTP 307 redirects)
 * when deployed behind reverse proxies or CDNs like Vercel.
 */
export async function POST(
  request: Request,
  context: { params: Promise<{ slug: string }> },
) {
  const { slug } = await context.params;
  const baseUrl = resolveApiBaseUrl();
  const bodyText = await request.text();

  let upstream: Response | null = null;

  try {
    upstream = await fetch(
      `${baseUrl}/shop/${encodeURIComponent(slug)}/requests`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: bodyText,
      },
    );
  } catch {
    // If local/proxy base failed and it wasn't already DEPLOYED_API, attempt fallback
    if (baseUrl !== DEPLOYED_API) {
      try {
        upstream = await fetch(
          `${DEPLOYED_API}/shop/${encodeURIComponent(slug)}/requests`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "application/json",
            },
            body: bodyText,
          },
        );
      } catch {
        // Fallback also failed
      }
    }
  }

  if (!upstream) {
    return NextResponse.json(
      { error: { message: "We could not reach the shop service. Try again." } },
      { status: 502 },
    );
  }

  const data = await upstream.json().catch(() => null);
  return NextResponse.json(
    data ?? { error: { message: "Invalid response from shop service" } },
    { status: upstream.status },
  );
}
