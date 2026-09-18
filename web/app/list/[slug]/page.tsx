import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ListBuilder, type ListShop } from "@/components/list-builder";
import { fetchPublicShop } from "@/lib/server-api";

/**
 * Building a list for one shop.
 *
 * Rendered on the server for the first paint - a customer following a link should see the shop's own
 * catalogue immediately, and the page carries the shop's name in its title so a shared list link says
 * where it is going - and then it is interactive, because counts, quantities and phone numbers are.
 */

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const shop = await fetchPublicShop(slug);
  if (!shop) {
    return { title: "Shop not found" };
  }
  return {
    title: `Send a list to ${shop.business_name}`,
    description: `Put your list together and send it to ${shop.business_name} - they pack it and tell you what it costs.`,
    alternates: { canonical: `/list/${shop.tenant_slug}` },
  };
}

export const revalidate = 60;

export default async function ListPage({ params }: Params) {
  const { slug } = await params;
  const shop = await fetchPublicShop(slug);
  if (!shop) {
    notFound();
  }

  const builderShop: ListShop = {
    tenant_slug: shop.tenant_slug,
    business_name: shop.business_name,
    headline: shop.headline,
    contact_phone: shop.contact_phone,
    products: shop.products.map((product) => ({
      product_slug: product.product_slug,
      name: product.name,
      selling_price: product.selling_price,
    })),
  };

  return <ListBuilder shop={builderShop} />;
}
