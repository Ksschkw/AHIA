import { NextResponse } from "next/server";
import { resolveApiBaseUrl } from "@/lib/server-api";

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

  try {
    const upstream = await fetch(
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

    const data = await upstream.json().catch(() => null);
    return NextResponse.json(
      data ?? { error: { message: "Invalid response from shop service" } },
      { status: upstream.status },
    );
  } catch (error) {
    return NextResponse.json(
      { error: { message: "We could not reach the shop service. Try again." } },
      { status: 502 },
    );
  }
}
