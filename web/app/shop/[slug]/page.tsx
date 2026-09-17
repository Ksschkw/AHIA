import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BrandMark, Wordmark } from "@/components/brand";
import { fetchPublicShop, whatsAppLink } from "@/lib/server-api";
import { formatMoney } from "@/lib/format";
import styles from "./shop.module.css";

/**
 * A business's public shop.
 *
 * The one page in this product that has no session, no permissions and no idea who is looking at it.
 * It is rendered on the server so that a link shared on WhatsApp unfurls with the shop's name and what
 * it sells, which is the whole reason a trader shares it - and because a customer on a slow connection
 * deserves HTML rather than a spinner.
 */

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const shop = await fetchPublicShop(slug);
  if (!shop) {
    return { title: "Shop not found" };
  }
  const description =
    shop.description ??
    shop.headline ??
    `${shop.business_name} - what is on the shelf, and what it costs.`;
  return {
    title: shop.business_name,
    description,
    openGraph: {
      title: shop.business_name,
      description,
      type: "website",
    },
  };
}

export default async function ShopPage({ params }: Params) {
  const { slug } = await params;
  const shop = await fetchPublicShop(slug);
  if (!shop) {
    notFound();
  }

  const message = `Hello ${shop.business_name}, I saw your shop on AHIA.`;
  const whatsapp = whatsAppLink(shop.contact_phone, message);
  const available = shop.products.filter((product) => product.is_available);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <span className={styles.brand}>
            <BrandMark size={30} />
            <Wordmark />
          </span>
          {whatsapp ? (
            <a className={styles.whatsapp} href={whatsapp} rel="noreferrer noopener" target="_blank">
              Message us
            </a>
          ) : null}
        </div>
      </header>

      <section className={styles.hero}>
        <h1 className={styles.shopName}>{shop.business_name}</h1>
        {shop.headline ? <p className={styles.headline}>{shop.headline}</p> : null}
        {shop.description ? <p className={styles.description}>{shop.description}</p> : null}
        {shop.contact_phone ? (
          <p className={styles.contact}>Call or message {shop.contact_phone}</p>
        ) : null}
      </section>

      <section className={styles.catalogue}>
        {shop.products.length === 0 ? (
          <p className={styles.empty}>Nothing on the shelf just yet.</p>
        ) : (
          <ul className={styles.grid}>
            {shop.products.map((product) => (
              <li key={product.product_slug} className={styles.card}>
                <Link className={styles.cardLink} href={`/shop/${shop.tenant_slug}/product/${product.product_slug}`}>
                  <span className={styles.imageWrap}>
                    {product.primary_image_url ? (
                      /* eslint-disable-next-line @next/next/no-img-element */
                      <img className={styles.image} src={product.primary_image_url} alt="" />
                    ) : (
                      <span className={styles.imagePlaceholder} aria-hidden />
                    )}
                    {!product.is_available ? <span className={styles.soldOut}>Out of stock</span> : null}
                  </span>
                  <span className={styles.productName}>{product.name}</span>
                  <span className={styles.price}>{formatMoney(product.selling_price)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className={styles.footer}>
        <span>
          {available.length} of {shop.products.length} available now
        </span>
        <span className={styles.footerBrand}>
          <BrandMark size={18} /> Powered by AHIA
        </span>
      </footer>
    </main>
  );
}
