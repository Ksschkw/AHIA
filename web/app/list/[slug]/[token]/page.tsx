import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LiveList } from "@/components/live-list";
import { fetchPublicList } from "@/lib/server-api";

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
  const { slug, token } = await params;
  const list = await fetchPublicList(slug, token);
  if (!list) {
    return { title: "List not found" };
  }
  return {
    title: `Your list for ${list.business_name}`,
    description: `${list.lines.length} items, sent to ${list.business_name}.`,
    // A customer's list is their own business: nothing here belongs in a search engine.
    robots: { index: false, follow: false },
  };
}

export const revalidate = 10;

export default async function ListPage({ params }: Params) {
  const { slug, token } = await params;
  const list = await fetchPublicList(slug, token);
  if (!list) {
    notFound();
  }
  return <LiveList initial={list} slug={slug} token={token} />;
}
