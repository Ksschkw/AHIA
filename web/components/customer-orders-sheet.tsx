"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { EmptyOrdersIllustration } from "@/components/illustrations";
import { formatMoneyOrOnRequest } from "@/lib/format";
import type { CustomerListSummary } from "@/lib/api";
import styles from "./customer-orders-sheet.module.css";

interface CustomerOrdersSheetProps {
  isOpen: boolean;
  onClose: () => void;
  tenantSlug: string;
  businessName: string;
  initialPhone?: string;
  onReorderLines?: (
    lines: Array<{
      text: string;
      quantity: string;
      unit: string;
      product_slug?: string;
      group?: string | null;
      shop_price?: string | null;
    }>,
  ) => void;
}

export function CustomerOrdersSheet({
  isOpen,
  onClose,
  tenantSlug,
  businessName,
  initialPhone = "",
  onReorderLines,
}: CustomerOrdersSheetProps) {
  const [phone, setPhone] = useState(initialPhone);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [orders, setOrders] = useState<CustomerListSummary[]>([]);
  const [knownTokens, setKnownTokens] = useState<Record<string, string>>({});

  // Restore remembered phone number and cached list paths on mount or open
  useEffect(() => {
    if (!isOpen || typeof window === "undefined") return;

    let remembered = initialPhone;
    if (!remembered) {
      remembered =
        window.localStorage.getItem("ahia.customer_phone") ||
        window.localStorage.getItem("ahia.last_phone") ||
        "";
    }
    if (remembered) {
      setPhone(remembered);
    }

    // Load known list paths from local order history
    try {
      const historyKey = `ahia.history.${tenantSlug}`;
      const raw = window.localStorage.getItem(historyKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          const map: Record<string, string> = {};
          for (const item of parsed) {
            if (item.listPath) {
              // Extract token from listPath: /list/[slug]/[token]
              const parts = item.listPath.split("/");
              const token = parts[parts.length - 1];
              if (token) {
                map[item.id || token] = item.listPath;
              }
            }
          }
          setKnownTokens(map);
        }
      }
    } catch {
      // ignore parse error
    }
  }, [isOpen, initialPhone, tenantSlug]);

  const fetchOrders = useCallback(
    async (targetPhone: string) => {
      const cleanPhone = targetPhone.trim();
      if (!cleanPhone || cleanPhone.length < 5) return;

      setLoading(true);
      setSearched(true);
      try {
        if (typeof window !== "undefined") {
          window.localStorage.setItem("ahia.customer_phone", cleanPhone);
        }
        const res = await fetch(
          `/shop/${encodeURIComponent(tenantSlug)}/customer-lists?phone=${encodeURIComponent(cleanPhone)}`,
        );
        if (res.ok) {
          const data = (await res.json()) as CustomerListSummary[];
          setOrders(Array.isArray(data) ? data : []);
        } else {
          setOrders([]);
        }
      } catch {
        setOrders([]);
      } finally {
        setLoading(false);
      }
    },
    [tenantSlug],
  );

  // Auto-fetch if phone is already set when modal opens
  useEffect(() => {
    if (isOpen && phone.trim().length >= 7 && !searched) {
      void fetchOrders(phone);
    }
  }, [isOpen, phone, searched, fetchOrders]);

  if (!isOpen) return null;

  function formatStatusBadge(status: string) {
    switch (status) {
      case "submitted":
        return { label: "Sent / Pending Quote", cls: styles.statusSubmitted };
      case "quoted":
        return { label: "Priced by Merchant", cls: styles.statusQuoted };
      case "confirmed":
        return { label: "Confirmed Order", cls: styles.statusConfirmed };
      case "fulfilled":
        return { label: "Completed", cls: styles.statusFulfilled };
      case "cancelled":
        return { label: "Cancelled", cls: styles.statusCancelled };
      default:
        return { label: status, cls: styles.statusSubmitted };
    }
  }

  function formatDate(iso: string) {
    try {
      const d = new Date(iso);
      return d.toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  return (
    <div
      className={styles.backdrop}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Track past orders"
    >
      <div className={styles.sheet}>
        <div className={styles.header}>
          <div className={styles.titleGroup}>
            <span className={styles.badge}>Order Tracking</span>
            <h2 className={styles.title}>My Orders at {businessName}</h2>
          </div>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Close orders sheet"
          >
            &times;
          </button>
        </div>

        <div className={styles.body}>
          <form
            className={styles.phoneForm}
            onSubmit={(e) => {
              e.preventDefault();
              void fetchOrders(phone);
            }}
          >
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="Your phone number (e.g. 08012345678)"
              className={styles.phoneInput}
              autoFocus={!phone}
            />
            <button type="submit" disabled={loading} className={styles.lookupBtn}>
              {loading ? "Checking..." : "Look Up"}
            </button>
          </form>

          {loading ? (
            <div className={styles.emptyBox}>
              <p className={styles.emptyText}>Fetching orders from {businessName}...</p>
            </div>
          ) : searched && orders.length === 0 ? (
            <div className={styles.emptyBox}>
              <EmptyOrdersIllustration size={100} />
              <p className={styles.emptyText}>
                No orders found for <strong>{phone}</strong> yet. Any list you send to {businessName} will appear here automatically.
              </p>
            </div>
          ) : orders.length > 0 ? (
            <ul className={styles.orderList}>
              {orders.map((order) => {
                const badge = formatStatusBadge(order.status);
                const trackerPath = knownTokens[order.id];

                return (
                  <li key={order.id} className={styles.orderCard}>
                    <div className={styles.orderCardHeader}>
                      <div className={styles.orderMeta}>
                        <span className={styles.orderDate}>{formatDate(order.created_at)}</span>
                        <span className={styles.orderCount}>
                          {order.line_count} {order.line_count === 1 ? "item" : "items"}
                        </span>
                      </div>
                      <span className={`${styles.statusPill} ${badge.cls}`}>{badge.label}</span>
                    </div>

                    {order.priced_total ? (
                      <div className={styles.orderPriceRow}>
                        <span className={styles.orderPriceLabel}>Total Quote</span>
                        <span className={styles.orderPriceValue}>
                          {formatMoneyOrOnRequest(order.priced_total)}
                        </span>
                      </div>
                    ) : null}

                    {order.lines_preview && order.lines_preview.length > 0 ? (
                      <div className={styles.chipsWrap}>
                        {order.lines_preview.map((preview, idx) => (
                          <span key={idx} className={styles.chip}>
                            {preview}
                          </span>
                        ))}
                      </div>
                    ) : null}

                    <div className={styles.orderActions}>
                      {onReorderLines ? (
                        <button
                          type="button"
                          className={styles.reorderBtn}
                          onClick={() => {
                            const linesToLoad = order.lines.map((l) => ({
                              text: l.text,
                              quantity: l.quantity,
                              unit: l.unit,
                              group: l.group,
                              shop_price: l.shop_price,
                            }));
                            onReorderLines(linesToLoad);
                            onClose();
                          }}
                        >
                          Reorder into List
                        </button>
                      ) : (
                        <Link
                          href={`/list/${tenantSlug}`}
                          className={styles.reorderBtn}
                          onClick={onClose}
                        >
                          Open List Builder
                        </Link>
                      )}

                      {trackerPath ? (
                        <Link href={trackerPath} className={styles.trackerLink} onClick={onClose}>
                          Live Status
                        </Link>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className={styles.emptyBox}>
              <EmptyOrdersIllustration size={100} />
              <p className={styles.emptyText}>
                Enter the phone number you used when sending your list to follow quote progress or reorder goods.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
