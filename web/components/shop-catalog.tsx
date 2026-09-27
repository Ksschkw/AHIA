"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { BrandMark } from "@/components/brand";
import { SearchIcon } from "@/components/icons";
import { formatMoneyOrOnRequest } from "@/lib/format";
import type { PublicGroup, PublicProduct } from "@/lib/server-api";
import styles from "./shop-catalog.module.css";

interface ShopCatalogProps {
  products: PublicProduct[];
  groups: PublicGroup[];
  tenantSlug: string;
  businessName: string;
}

export function ShopCatalog({ products, groups, tenantSlug, businessName }: ShopCatalogProps) {
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Extract unique category names and counts from products
  const categoryStats = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const prod of products) {
      const group = prod.group_name || "General";
      counts[group] = (counts[group] || 0) + 1;
    }
    const categories = Object.keys(counts).sort((a, b) => {
      if (a === "General") return 1;
      if (b === "General") return -1;
      return a.localeCompare(b);
    });
    return { counts, categories };
  }, [products]);

  // Filter products based on search and selected category
  const filteredProducts = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return products.filter((prod) => {
      const matchesCategory =
        selectedCategory === "all" ||
        (prod.group_name || "General").toLowerCase() === selectedCategory.toLowerCase();
      if (!matchesCategory) return false;

      if (!query) return true;
      const matchesName = prod.name.toLowerCase().includes(query);
      const matchesGroup = (prod.group_name || "").toLowerCase().includes(query);
      const matchesDesc = (prod.description || "").toLowerCase().includes(query);
      return matchesName || matchesGroup || matchesDesc;
    });
  }, [products, selectedCategory, searchQuery]);

  // When "all" is selected without search, group items by category for structured sections
  const groupedSections = useMemo(() => {
    if (selectedCategory !== "all" || searchQuery.trim().length > 0) {
      return null;
    }
    const sections: { category: string; items: PublicProduct[] }[] = [];
    const map = new Map<string, PublicProduct[]>();

    for (const prod of products) {
      const cat = prod.group_name || "General";
      if (!map.has(cat)) {
        map.set(cat, []);
      }
      map.get(cat)!.push(prod);
    }

    for (const cat of categoryStats.categories) {
      const items = map.get(cat);
      if (items && items.length > 0) {
        sections.push({ category: cat, items });
      }
    }
    return sections;
  }, [products, selectedCategory, searchQuery, categoryStats.categories]);

  return (
    <section className={styles.catalogSection} aria-label="Shop catalog">
      <div className={styles.filterBar}>
        <div className={styles.searchWrap}>
          <SearchIcon size={18} className={styles.searchIcon} />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={`Search ${businessName}'s catalog...`}
            className={styles.searchInput}
            aria-label="Search items"
          />
          {searchQuery ? (
            <button
              type="button"
              className={styles.clearSearchBtn}
              onClick={() => setSearchQuery("")}
              aria-label="Clear search"
            >
              Clear
            </button>
          ) : null}
        </div>

        {categoryStats.categories.length > 1 ? (
          <div className={styles.categoryPills} role="tablist" aria-label="Category filters">
            <button
              type="button"
              role="tab"
              aria-selected={selectedCategory === "all"}
              className={`${styles.pill} ${selectedCategory === "all" ? styles.pillActive : ""}`}
              onClick={() => setSelectedCategory("all")}
            >
              <span>All Items</span>
              <span className={styles.pillBadge}>{products.length}</span>
            </button>
            {categoryStats.categories.map((cat) => {
              const count = categoryStats.counts[cat] ?? 0;
              const isSelected = selectedCategory.toLowerCase() === cat.toLowerCase();
              return (
                <button
                  key={cat}
                  type="button"
                  role="tab"
                  aria-selected={isSelected}
                  className={`${styles.pill} ${isSelected ? styles.pillActive : ""}`}
                  onClick={() => setSelectedCategory(cat)}
                >
                  <span>{cat}</span>
                  <span className={styles.pillBadge}>{count}</span>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>

      {groupedSections ? (
        // Structured category sections
        groupedSections.map((sec) => (
          <div key={sec.category} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionHeading}>{sec.category}</h2>
              <span className={styles.sectionCount}>
                {sec.items.length} {sec.items.length === 1 ? "item" : "items"}
              </span>
            </div>
            <ul className={styles.grid}>
              {sec.items.map((product) => (
                <ProductCard key={product.product_slug} product={product} tenantSlug={tenantSlug} />
              ))}
            </ul>
          </div>
        ))
      ) : filteredProducts.length > 0 ? (
        // Flat filtered grid (filtered by search or single category)
        <div>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionHeading}>
              {searchQuery
                ? `Results for "${searchQuery}"`
                : selectedCategory === "all"
                  ? "All Items"
                  : selectedCategory}
            </h2>
            <span className={styles.sectionCount}>
              {filteredProducts.length} {filteredProducts.length === 1 ? "item" : "items"}
            </span>
          </div>
          <ul className={styles.grid} style={{ marginTop: "14px" }}>
            {filteredProducts.map((product) => (
              <ProductCard key={product.product_slug} product={product} tenantSlug={tenantSlug} />
            ))}
          </ul>
        </div>
      ) : (
        <div className={styles.emptyState}>
          <span className={styles.emptyTitle}>No matching items found</span>
          <p style={{ fontSize: "14px", margin: 0 }}>
            {searchQuery
              ? `Nothing in ${businessName}'s shelf matches "${searchQuery}".`
              : "No items listed under this category yet."}
          </p>
          {(searchQuery || selectedCategory !== "all") ? (
            <button
              type="button"
              className={styles.pill}
              style={{ marginTop: "8px" }}
              onClick={() => {
                setSearchQuery("");
                setSelectedCategory("all");
              }}
            >
              Show all items
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}

function ProductCard({
  product,
  tenantSlug,
}: {
  product: PublicProduct;
  tenantSlug: string;
}) {
  return (
    <li className={styles.card}>
      <Link
        className={styles.cardLink}
        href={`/shop/${tenantSlug}/product/${product.product_slug}`}
        prefetch
      >
        <span className={styles.imageWrap}>
          {product.primary_image_url ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              className={styles.image}
              src={product.primary_image_url}
              alt={product.name}
              loading="lazy"
              decoding="async"
            />
          ) : (
            <span className={styles.imagePlaceholder} aria-hidden>
              <BrandMark size={24} />
            </span>
          )}
          {product.is_special ? <span className={styles.specialBadge}>Special</span> : null}
        </span>
        {product.group_name ? (
          <span className={styles.categoryTag}>{product.group_name}</span>
        ) : null}
        <span className={styles.productName}>{product.name}</span>
        <span className={styles.price}>{formatMoneyOrOnRequest(product.selling_price)}</span>
      </Link>
    </li>
  );
}
