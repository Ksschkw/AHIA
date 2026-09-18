import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BrandMark } from "@/components/brand";
import { fetchPublicProduct, whatsAppLink } from "@/lib/server-api";
import { formatMoneyOrOnRequest } from "@/lib/format";
import styles from "../../shop.module.css";

/**
 * One product, as a customer sees it.
 *
 * This is the page a trader sends to a customer on WhatsApp, so it has to do three things in the first
 * screen: show the thing, say what it costs, and offer one way to ask about it. The photograph leads,
 * because somebody buying electronics is buying what they can see - and a page that opens with a
 * paragraph about the shop is a page that gets closed.
 *
 * It unfurls as a card with the product's own picture and price, so the message preview does the selling
 * before anybody taps. And it never mentions stock: the trader goes and finds what he does not have.
 */

type Params = { params: Promise<{ slug: string; productSlug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug, productSlug } = await params;
  const page = await fetchPublicProduct(slug, productSlug);
  if (!page) {
    return { title: "Product not found" };
  }
  const { product, business_name: businessName } = page;
  const price = formatMoneyOrOnRequest(product.selling_price);
  const description =
    product.description ?? `${product.name} at ${businessName}. ${price}. Ask us about it.`;

  return {
    title: `${product.name} - ${price} at ${businessName}`,
    description,
    alternates: { canonical: `/shop/${page.tenant_slug}/product/${product.product_slug}` },
    openGraph: {
      title: `${product.name} - ${price}`,
      description,
      images: product.primary_image_url ? [{ url: product.primary_image_url, alt: product.name }] : undefined,
      type: "website",
    },
  };
}

/**
 * Regenerated in the background at most once a minute, and served from the edge in between. A product
 * changes when the trader edits it and not before, so making a customer wait for a fresh round trip was
 * paying for nothing.
 */
export const revalidate = 60;

export default async function ProductPage({ params }: Params) {
  const { slug, productSlug } = await params;
  const page = await fetchPublicProduct(slug, productSlug);
  if (!page) {
    notFound();
  }
  const { product, business_name: businessName, contact_phone: contactPhone } = page;

  const price = formatMoneyOrOnRequest(product.selling_price);
  // The question arrives written, with the product already named: a customer should have to add only
  // what is particular to them, and the trader should know which item is being asked about.
  const message = `Hello ${businessName}, I want to order:\n\n${product.name} - ${price}\nQuantity: \n\n(My name and delivery address:)`;
  const whatsapp = whatsAppLink(contactPhone, message);
  const call = contactPhone ? `tel:${contactPhone.replace(/\s/g, "")}` : null;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link className={styles.brand} href={`/shop/${page.tenant_slug}`}>
            <BrandMark size={26} />
          </Link>
          <Link className={styles.headerCta} href={`/shop/${page.tenant_slug}`}>
            All of {businessName}
          </Link>
        </div>
      </header>

      <article className={styles.product}>
        {/* The photograph first, and in a fixed frame: a picture that arrives late must not move the
            price down the screen while somebody is reading it. */}
        <div
          className={
            product.primary_image_url ? styles.productPhoto : styles.productPhotoEmpty
          }
        >
          {product.primary_image_url ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={product.primary_image_url}
              alt={product.name}
              decoding="async"
              /* The largest thing on the page, so it is not lazy: waiting for it is the difference
                 between a shop and a blank frame. */
            />
          ) : (
            <span className={styles.productPhotoPlaceholder}>
              <BrandMark size={28} />
              <span className={styles.productPhotoNote}>
                Ask us for a photograph of this one
              </span>
            </span>
          )}
        </div>

        <div className={styles.productInfo}>
          <h1 className={styles.productTitle}>{product.name}</h1>
          <p className={styles.productPrice}>{price}</p>

          {product.description ? (
            <p className={styles.productDescription}>{product.description}</p>
          ) : null}

          <p className={styles.promise}>
            Want a different colour, size or quantity? Ask - we will get it for you, and wholesale
            prices are available for bulk.
          </p>

          <div className={styles.productActions}>
            {whatsapp ? (
              <a
                className={styles.primary}
                href={whatsapp}
                rel="noreferrer noopener"
                target="_blank"
              >
                Ask about this on WhatsApp
              </a>
            ) : null}
            {call ? (
              <a className={styles.secondary} href={call}>
                Call {contactPhone}
              </a>
            ) : null}
          </div>

          <p className={styles.productShop}>
            Sold by{" "}
            <Link className={styles.productShopLink} href={`/shop/${page.tenant_slug}`}>
              {businessName}
            </Link>
          </p>
        </div>
      </article>
    </main>
  );
}
