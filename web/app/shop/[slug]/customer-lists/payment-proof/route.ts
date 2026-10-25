import { NextResponse } from "next/server";
import { resolveApiBaseUrl, DEPLOYED_API } from "@/lib/server-api";

export const dynamic = "force-dynamic";

/**
 * Public endpoint to submit payment proof for an order.
 */
export async function POST(
  request: Request,
  context: { params: Promise<{ slug: string }> },
) {
  const { slug } = await context.params;
  const baseUrl = resolveApiBaseUrl();
  const body = await request.json().catch(() => null);

  if (!body || !body.requestId || !body.phone || !body.amount) {
    return NextResponse.json(
      { error: "Missing required fields (requestId, phone, amount)" },
      { status: 400 },
    );
  }

  const payload = {
    customer_phone: body.phone,
    amount: String(body.amount),
    reference_note: body.note || null,
  };

  const targetPath = `/shop/${encodeURIComponent(slug)}/requests/${encodeURIComponent(body.requestId)}/payment-proof`;

  let upstream: Response | null = null;
  try {
    upstream = await fetch(`${baseUrl}${targetPath}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch {
    if (baseUrl !== DEPLOYED_API) {
      try {
        upstream = await fetch(`${DEPLOYED_API}${targetPath}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify(payload),
        });
      } catch {
        // Fallback failed
      }
    }
  }

  if (!upstream) {
    return NextResponse.json(
      { error: "Could not reach store server." },
      { status: 502 },
    );
  }

  const resData = await upstream.json().catch(() => ({}));
  return NextResponse.json(resData, { status: upstream.status });
}
