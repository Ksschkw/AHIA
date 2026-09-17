import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BrandMark, Wordmark } from "@/components/brand";
import { fetchPublicProduct, whatsAppLink } from "@/lib/server-api";
import { formatMoneyOrOnRequest, formatMoney } from "@/lib/format";
import styles from "../../shop.module.css";
import detail from "./product.module.css";

/**
 * One product, as a customer sees it.
 *
 * Separate from the catalogue because this is the page a trader sends to a customer on WhatsApp: it
 * has to stand on its own, unfurl with the product's name and picture, and give one obvious way to ask
 * about it. The picture is the whole point - a customer buying electronics wants to see the thing.
 */

type Params = { params: Promise<{ slug: string; productSlug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug, productSlug } = await params;
  const page = await fetchPublicProduct(slug, productSlug);
  if (!page) {
    return { title: "Product not found" };
  }
  const { product, business_name: businessName } = page;
  return {
    title: `${product.name} - ${businessName}`,
    description: product.description ?? `${product.name} at ${businessName}.`,
    openGraph: {
      title: product.name,
      description: product.description ?? `${product.name} at ${businessName}.`,
      images: product.primary_image_url ? [product.primary_image_url] : undefined,
      type: "website",
    },
  };
}

export default async function ProductPage({ params }: Params) {
  const { slug, productSlug } = await params;
  const page = await fetchPublicProduct(slug, productSlug);
  if (!page) {
    notFound();
  }
  const { product, business_name: businessName, contact_phone: contactPhone } = page;

  const message = `Hello ${businessName}, I am asking about ${product.name} (${formatMoneyOrOnRequest(product.selling_price)}).`;
  const whatsapp = whatsAppLink(contactPhone, message);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link className={styles.brand} href={`/shop/${page.tenant_slug}`}>
            <BrandMark size={30} />
            <Wordmark />
          </Link>
          {whatsapp ? (
            <a className={styles.whatsapp} href={whatsapp} rel="noreferrer noopener" target="_blank">
              Ask about this
            </a>
          ) : null}
        </div>
      </header>

      <article className={detail.article}>
        <div className={detail.photo}>
          {product.primary_image_url ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img src={product.primary_image_url} alt={product.name} />
          ) : (
            <span className={detail.photoPlaceholder} aria-hidden />
          )}
        </div>

        <div className={detail.info}>
          <Link className={detail.back} href={`/shop/${page.tenant_slug}`}>
            {businessName}
          </Link>
          <h1 className={detail.name}>{product.name}</h1>
          <p className={detail.price}>{formatMoneyOrOnRequest(product.selling_price)}</p>
          {/* Availability is not a customer's business: an Igbo trader is never truly out of
              stock - he goes and finds it. What a customer reads here is what the shop does. */}
          <p className={detail.available}>This can be sourced for you</p>
          {product.description ? <p className={detail.description}>{product.description}</p> : null}

          <div className={detail.actions}>
            {whatsapp ? (
              <a className={detail.primary} href={whatsapp} rel="noreferrer noopener" target="_blank">
                Ask on WhatsApp
              </a>
            ) : (
              <span className={detail.noContact}>
                This shop has no number to message yet.
              </span>
            )}
          </div>
        </div>
      </article>
    </main>
  );
}
