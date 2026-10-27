import type { Metadata } from "next";

import { ListNotFound } from "@/components/list-not-found";
import { LiveList } from "@/components/live-list";
import { extractStorefrontTheme } from "@/lib/api";
import { fetchPublicList, fetchPublicShop } from "@/lib/server-api";

/**
 * One customer's list, at its own address.
 *
 * This is the link the customer keeps and the trader opens: the same list, two views, and whichever of
 * them changes it the other sees it. It is rendered on the server for the first paint - a customer
 * opening a link in a market should not watch a blank screen - and then kept current in the browser,
 * because a list is a thing two people are working on together.
 */

type Params = { params: Promise<{ slug: string; token: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  try {
    const { slug, token } = await params;
    const list = await fetchPublicList(slug, token);
    if (!list) {
      return { title: "Order List Not Found" };
    }
    return {
      title: `Your list for ${list.business_name}`,
      description: `${list.lines.length} items, sent to ${list.business_name}.`,
      robots: { index: false, follow: false },
    };
  } catch {
    return { title: "Your Order List" };
  }
}

export const revalidate = 10;

export default async function ListPage({ params }: Params) {
  try {
    const { slug, token } = await params;
    const [list, shop] = await Promise.all([
      fetchPublicList(slug, token),
      fetchPublicShop(slug).catch(() => null),
    ]);
    if (!list) {
      return <ListNotFound slug={slug} businessName={shop?.business_name} />;
    }
    const sfTheme = extractStorefrontTheme(shop?.description);
    return <LiveList initial={list} slug={slug} token={token} logoUrl={sfTheme.logoUrl} />;
  } catch {
    return <ListNotFound slug="" businessName="AHIA Shop" />;
  }
}
