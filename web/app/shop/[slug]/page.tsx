import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CheckMarkIcon, ItemBoxIcon, PhoneIcon, SparklesIcon } from "@/components/icons";
import { ShopCatalog } from "@/components/shop-catalog";
import { StorefrontThemeToggle } from "@/components/storefront-theme-toggle";
import { TrackOrdersTrigger } from "@/components/customer-orders-sheet";
import { BuildListButton } from "@/components/build-list-button";
import { fetchPublicShop, whatsAppLink } from "@/lib/server-api";
import styles from "./shop.module.css";

/**
 * A business's public shop.
 *
 * Rendered on the server so that a link shared on WhatsApp unfurls with the shop's name
 * and photographs of what it sells.
 *
 * Designed with a premium, responsive e-commerce layout across desktop and mobile screens.
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
  const preview = shop.products.find((product) => product.primary_image_url)?.primary_image_url;

  return {
    title: `${shop.business_name} - Wholesale & Retail Market Storefront`,
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
  closingMessage: string;
  logoUrl: string | null;
} {
  const defaultTheme = {
    cleanDescription: description ?? "",
    themeColor: "#084a2f",
    themeBg: "#fbf7f0",
    themeBgImage: "",
    closingMessage: "",
    logoUrl: null,
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
      closingMessage: parsed.closing || "",
      logoUrl: parsed.logoUrl || null,
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

  const { cleanDescription, themeColor, themeBg, themeBgImage, closingMessage, logoUrl } = extractStorefrontTheme(
    shop.description,
  );
  const isBgDark = isDarkColor(themeBg);
  const themeVariables: React.CSSProperties = {
    "--shop-theme-color": themeColor,
    "--shop-theme-bg": themeBg,
    "--shop-theme-bg-image": themeBgImage ? `url(${themeBgImage})` : "none",
    "--shop-brand-text": isBgDark ? "#f8fafc" : "#0f172a",
    "--card": isBgDark ? "#161e19" : "#ffffff",
    "--card-hover": isBgDark ? "#1f2a23" : "#f8fafc",
    "--sand": themeBg,
    "--sand-2": isBgDark ? "#111814" : "#f1ede4",
    "--ink": isBgDark ? "#f8fafc" : "#0f172a",
    "--ink-2": isBgDark ? "#cbd5e1" : "#334155",
    "--ink-3": isBgDark ? "#94a3b8" : "#64748b",
    "--line": isBgDark ? "#26352b" : "#e2dcd2",
    "--line-strong": isBgDark ? "#384d3e" : "#cbbfaf",
    color: isBgDark ? "#f8fafc" : "#0f172a",
  } as React.CSSProperties;

  const message = `Hello ${shop.business_name}, I want to order:\n\n- \n\n(My name and delivery address:)`;
  const whatsapp = whatsAppLink(shop.contact_phone, message);
  const call = shop.contact_phone ? `tel:${shop.contact_phone.replace(/\s/g, "")}` : null;

  return (
    <main
      id="shop_root"
      className={styles.page}
      style={themeVariables}
    >
      <script
        dangerouslySetInnerHTML={{
          __html: `(function(){try{var v=window.localStorage.getItem('ahia.visitor_theme');if(v){document.documentElement.setAttribute('data-theme',v);}var s=window.localStorage.getItem('ahia.theme.${shop.tenant_slug}');if(s){var d=JSON.parse(s);var el=document.getElementById('shop_root');if(el){if(d.color)el.style.setProperty('--shop-theme-color',d.color);if(d.bg)el.style.setProperty('--shop-theme-bg',d.bg);if(d.bgImage)el.style.setProperty('--shop-theme-bg-image','url('+d.bgImage+')');}}}catch(e){}})();`,
        }}
      />
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <div className={styles.shopBrandHeader}>
            {logoUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={logoUrl}
                alt={shop.business_name}
                className={styles.businessAvatar}
                style={{ objectFit: "cover" }}
              />
            ) : (
              <span className={styles.businessAvatar}>
                {shop.business_name.slice(0, 2).toUpperCase()}
              </span>
            )}
            <div className={styles.businessTitleGroup}>
              <span className={styles.businessNameTop}>{shop.business_name}</span>
              <span className={styles.verifiedStoreBadge}>
                <CheckMarkIcon size={12} className={styles.verifiedIcon} />
                Verified Market Storefront
              </span>
            </div>
          </div>
          <div className={styles.headerRight}>
            <TrackOrdersTrigger
              tenantSlug={shop.tenant_slug}
              businessName={shop.business_name}
              className={styles.headerTrackBtn}
            />
            <BuildListButton
              href={`/list/${shop.tenant_slug}`}
              className={styles.listShortcutBtn}
            />
            <StorefrontThemeToggle />
          </div>
        </div>
      </header>

      <section className={styles.heroSection}>
        <div className={styles.heroCard}>
          <div className={styles.heroMain}>
            <div className={styles.heroIdentityRow}>
              {logoUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={logoUrl}
                  alt={shop.business_name}
                  className={styles.heroAvatar}
                  style={{ objectFit: "cover" }}
                />
              ) : (
                <span className={styles.heroAvatar}>
                  {shop.business_name.slice(0, 2).toUpperCase()}
                </span>
              )}
              <div className={styles.heroBadgeColumn}>
                <div className={styles.heroBadgeRow}>
                  <span className={styles.verifiedPill}>
                    <CheckMarkIcon size={12} />
                    Verified Merchant
                  </span>
                  <span className={styles.kicker}>Direct Wholesale & Retail</span>
                </div>
                <h1 className={styles.shopName}>{shop.business_name}</h1>
                {shop.headline ? <p className={styles.headline}>{shop.headline}</p> : null}
              </div>
            </div>

            {cleanDescription ? <p className={styles.description}>{cleanDescription}</p> : null}

            <div className={styles.valuePropsRow}>
              <div className={styles.valuePropChip}>
                <SparklesIcon size={15} className={styles.valuePropIcon} />
                <span>Direct Market Prices</span>
              </div>
              <div className={styles.valuePropChip}>
                <ItemBoxIcon size={15} className={styles.valuePropIcon} />
                <span>Nationwide Waybill Delivery</span>
              </div>
              <div className={styles.valuePropChip}>
                <CheckMarkIcon size={15} className={styles.valuePropIcon} />
                <span>Custom Order Sourcing</span>
              </div>
            </div>

            <div className={styles.heroActions}>
              <BuildListButton
                href={`/list/${shop.tenant_slug}`}
                className={styles.primary}
              />
              <TrackOrdersTrigger
                tenantSlug={shop.tenant_slug}
                businessName={shop.business_name}
                className={styles.heroTrackBtn}
              />
              {whatsapp ? (
                <a className={styles.secondaryWhatsApp} href={whatsapp} rel="noreferrer noopener" target="_blank">
                  <span>Order on WhatsApp</span>
                </a>
              ) : null}
              {call ? (
                <a className={styles.tertiaryBtn} href={call}>
                  <PhoneIcon size={16} />
                  <span>Call {shop.contact_phone}</span>
                </a>
              ) : null}
            </div>

            <div className={styles.promiseBox}>
              <p className={styles.promise}>
                Not seeing what you need? Add any item, model or quantity to your order list. If it exists in the market, we source, pack, and waybill it directly to you.
              </p>
            </div>
          </div>
        </div>
      </section>

      <ShopCatalog
        products={shop.products}
        groups={shop.groups ?? []}
        tenantSlug={shop.tenant_slug}
        businessName={shop.business_name}
      />

      <section className={styles.closingSection}>
        <div className={styles.closingCard}>
          <div className={styles.closingHeader}>
            <span className={styles.closingTag}>Full Market Sourcing</span>
            <h2 className={styles.closingTitle}>Need bulk wholesale or unlisted items?</h2>
          </div>
          <p className={styles.closingText}>
            {closingMessage ||
              "Just build and send your order list. Whether single pieces or carton quantities, we cross-check market stock, pack your goods, and provide verified receipts and waybills."}
          </p>
          <div className={styles.heroActions}>
            <Link className={styles.primary} href={`/list/${shop.tenant_slug}`}>
              <ItemBoxIcon size={18} />
              <span>Build your list</span>
            </Link>
            {whatsapp ? (
              <a className={styles.secondaryWhatsApp} href={whatsapp} rel="noreferrer noopener" target="_blank">
                <span>Send list on WhatsApp</span>
              </a>
            ) : null}
          </div>
        </div>
      </section>

      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div className={styles.footerBrand}>
            {logoUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={logoUrl}
                alt=""
                className={styles.businessAvatarSmall}
                style={{ objectFit: "cover" }}
              />
            ) : (
              <span className={styles.businessAvatarSmall}>
                {shop.business_name.slice(0, 2).toUpperCase()}
              </span>
            )}
            <span className={styles.footerBusinessName}>{shop.business_name}</span>
          </div>
          <span className={styles.footerNote}>Verified Merchant - Powered by AHIA Market OS</span>
        </div>
      </footer>

      <div className={styles.mobileFloatingBar}>
        <Link className={styles.mobileFloatingPrimary} href={`/list/${shop.tenant_slug}`}>
          <ItemBoxIcon size={18} />
          <span>Build your list</span>
        </Link>
        {whatsapp ? (
          <a
            className={styles.mobileFloatingWhatsApp}
            href={whatsapp}
            rel="noreferrer noopener"
            target="_blank"
          >
            <span>WhatsApp</span>
          </a>
        ) : null}
      </div>
    </main>
  );
}
