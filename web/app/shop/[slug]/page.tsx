import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BrandMark, Wordmark } from "@/components/brand";
import { ShopCatalog } from "@/components/shop-catalog";
import { fetchPublicShop, whatsAppLink } from "@/lib/server-api";
import { formatMoneyOrOnRequest } from "@/lib/format";
import styles from "./shop.module.css";

/**
 * A business's public shop.
 *
 * The one page in this product with no session, no permissions and no idea who is looking at it - and
 * the only page that has to sell itself without anybody explaining it. It is rendered on the server so
 * that a link shared on WhatsApp unfurls with the shop's name **and a photograph of what it sells**,
 * because a preview with a picture is a preview people tap.
 *
 * Two things it deliberately does not do. It never mentions stock: an Igbo trader is never truly out of
 * stock, he goes and finds it, and a customer reading "unavailable" takes his list somewhere else. And
 * it never uses a word of the software's own vocabulary - a customer reads what the shop does for them.
 */

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const shop = await fetchPublicShop(slug);
  if (!shop) {
    return { title: "Shop not found" };
  }

  const description =
    shop.headline ??
    shop.description ??
    `${shop.business_name} - what is on the shelf, and what it costs. Send a list of what you want.`;
  // The first photograph in the catalogue stands in for the shop, because a link with a picture is a
  // link somebody taps, and a shop with no photograph yet still gets a clean card.
  const preview = shop.products.find((product) => product.primary_image_url)?.primary_image_url;

  return {
    title: `${shop.business_name} - send a list, we will get it`,
    description,
    alternates: { canonical: `/shop/${shop.tenant_slug}` },
    openGraph: {
      title: shop.business_name,
      description,
      type: "website",
      url: `/shop/${shop.tenant_slug}`,
      images: preview ? [{ url: preview, alt: shop.business_name }] : undefined,
    },
  };
}

export const dynamic = "force-dynamic";
export const revalidate = 0;

function extractStorefrontTheme(description: string | null | undefined): {
  cleanDescription: string;
  themeColor: string;
  themeBg: string;
  themeBgImage: string;
} {
  const defaultTheme = {
    cleanDescription: description ?? "",
    themeColor: "#084a2f",
    themeBg: "#fbf7f0",
    themeBgImage: "",
  };
  if (!description) return defaultTheme;

  const match = description.match(/<!--\s*ahia-theme:({[\s\S]*?})\s*-->/);
  if (!match) return defaultTheme;

  try {
    const parsed = JSON.parse(match[1]);
    const clean = description.replace(/<!--\s*ahia-theme:[\s\S]*?-->/, "").trim();
    return {
      cleanDescription: clean,
      themeColor: parsed.color || defaultTheme.themeColor,
      themeBg: parsed.bg || defaultTheme.themeBg,
      themeBgImage: parsed.bgImage || "",
    };
  } catch {
    return defaultTheme;
  }
}

function isDarkColor(hex: string): boolean {
  const clean = hex.replace("#", "");
  if (clean.length === 3) {
    const r = parseInt(clean[0] + clean[0], 16);
    const g = parseInt(clean[1] + clean[1], 16);
    const b = parseInt(clean[2] + clean[2], 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5;
  }
  if (clean.length === 6) {
    const r = parseInt(clean.slice(0, 2), 16);
    const g = parseInt(clean.slice(2, 4), 16);
    const b = parseInt(clean.slice(4, 6), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5;
  }
  return false;
}

export default async function ShopPage({ params }: Params) {
  const { slug } = await params;
  const shop = await fetchPublicShop(slug);
  if (!shop) {
    notFound();
  }

  const { cleanDescription, themeColor, themeBg, themeBgImage } = extractStorefrontTheme(
    shop.description,
  );
  const isBgDark = isDarkColor(themeBg);

  // The message arrives already written, because a customer with an empty text box often sends nothing.
  const message = `Hello ${shop.business_name}, I want to order:\n\n- \n\n(My name and delivery address:)`;
  const whatsapp = whatsAppLink(shop.contact_phone, message);
  const call = shop.contact_phone ? `tel:${shop.contact_phone.replace(/\s/g, "")}` : null;

  return (
    <main
      id="shop_root"
      className={styles.page}
      style={
        {
          "--shop-theme-color": themeColor,
          "--shop-theme-bg": themeBg,
          "--shop-theme-bg-image": themeBgImage ? `url(${themeBgImage})` : "none",
          "--shop-brand-text": isBgDark ? "#f0ede6" : "var(--ink)",
        } as React.CSSProperties
      }
    >
      <script
        dangerouslySetInnerHTML={{
          __html: `(function(){try{var s=window.localStorage.getItem('ahia.theme.${shop.tenant_slug}');if(s){var d=JSON.parse(s);var el=document.getElementById('shop_root');if(el){if(d.color)el.style.setProperty('--shop-theme-color',d.color);if(d.bg)el.style.setProperty('--shop-theme-bg',d.bg);if(d.bgImage)el.style.setProperty('--shop-theme-bg-image','url('+d.bgImage+')');}}}catch(e){}})();`,
        }}
      />
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <div className={styles.shopBrandHeader}>
            <span className={styles.businessAvatar}>
              {shop.business_name.slice(0, 2).toUpperCase()}
            </span>
            <div className={styles.businessTitleGroup}>
              <span className={styles.businessNameTop}>{shop.business_name}</span>
              <span className={styles.verifiedStoreBadge}>Direct Market Storefront</span>
            </div>
          </div>
          <div className={styles.headerRight}>
            <Link className={styles.listShortcutBtn} href={`/list/${shop.tenant_slug}`}>
              Build your list
            </Link>
            {whatsapp ? (
              <a className={styles.headerCta} href={whatsapp} rel="noreferrer noopener" target="_blank">
                WhatsApp Order
              </a>
            ) : null}
          </div>
        </div>
      </header>

      <section className={styles.hero}>
        <div className={styles.heroBadgeRow}>
          <span className={styles.verifiedPill}>Official Market Storefront</span>
          <span className={styles.kicker}>Direct Wholesale & Retail</span>
        </div>
        <h1 className={styles.shopName}>{shop.business_name}</h1>
        {shop.headline ? <p className={styles.headline}>{shop.headline}</p> : null}
        {cleanDescription ? <p className={styles.description}>{cleanDescription}</p> : null}

        <div className={styles.heroActions}>
          <Link className={styles.primary} href={`/list/${shop.tenant_slug}`}>
            Build your list
          </Link>
          {whatsapp ? (
            <a className={styles.secondary} href={whatsapp} rel="noreferrer noopener" target="_blank">
              Order on WhatsApp
            </a>
          ) : null}
          {call ? (
            <a className={styles.tertiaryBtn} href={call}>
              Call {shop.contact_phone}
            </a>
          ) : null}
        </div>

        <p className={styles.promise}>
          Not everything is on this page - if you do not see it, ask for it in your list and we will get it directly from the market.
        </p>
      </section>

      <ShopCatalog
        products={shop.products}
        groups={shop.groups ?? []}
        tenantSlug={shop.tenant_slug}
        businessName={shop.business_name}
      />

      <section className={styles.closing}>
        <h2 className={styles.closingTitle}>Want something not listed here?</h2>
        <p className={styles.closingText}>
          Send us a list - a photograph of a written one works too - and we will find it, pack it and
          send it to you. Wholesale prices are available for bulk orders.
        </p>
        <div className={styles.heroActions}>
          <Link className={styles.primary} href={`/list/${shop.tenant_slug}`}>
            Build your list
          </Link>
          {whatsapp ? (
            <a className={styles.secondary} href={whatsapp} rel="noreferrer noopener" target="_blank">
              Or send it on WhatsApp
            </a>
          ) : null}
        </div>
      </section>

      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div className={styles.footerBrand}>
            <span className={styles.businessAvatarSmall}>
              {shop.business_name.slice(0, 2).toUpperCase()}
            </span>
            <span className={styles.footerBusinessName}>{shop.business_name}</span>
          </div>
          <span className={styles.footerNote}>Verified Merchant - Powered by AHIA</span>
        </div>
      </footer>

      <div className={styles.mobileFloatingBar}>
        <Link className={styles.mobileFloatingPrimary} href={`/list/${shop.tenant_slug}`}>
          Build your list
        </Link>
        {whatsapp ? (
          <a
            className={styles.mobileFloatingWhatsApp}
            href={whatsapp}
            rel="noreferrer noopener"
            target="_blank"
          >
            WhatsApp
          </a>
        ) : null}
      </div>
    </main>
  );
}
