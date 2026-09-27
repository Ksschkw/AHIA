"use client";

import { useState } from "react";
import Link from "next/link";
import { Brand } from "@/components/brand";
import { PhoneIcon } from "@/components/icons";
import { getCustomerPastLists, type CustomerListSummary } from "@/lib/api";

export function ListNotFound({
  slug,
  businessName,
}: {
  slug: string;
  businessName?: string | null;
}) {
  const [phone, setPhone] = useState("");
  const [pastLists, setPastLists] = useState<CustomerListSummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shopLabel = businessName || "this shop";

  async function handleFindLists() {
    const cleanPhone = phone.trim();
    if (cleanPhone.length < 7) {
      setError("Please enter a valid phone number.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const found = await getCustomerPastLists(slug, cleanPhone);
      setPastLists(found);
      setSearched(true);
    } catch {
      setError("Could not retrieve past lists. Please check your connection.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        background: "var(--sand)",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <div
        style={{
          maxWidth: "520px",
          width: "100%",
          background: "var(--card)",
          border: "1px solid var(--line)",
          borderRadius: "var(--radius)",
          padding: "36px 24px",
          boxShadow: "var(--shadow-sm)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "16px",
          textAlign: "center",
        }}
      >
        <Brand size={30} />

        <div>
          <span
            style={{
              fontSize: "11px",
              fontWeight: 800,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              color: "var(--clay)",
              background: "var(--clay-soft, #fbe9dd)",
              padding: "3px 10px",
              borderRadius: "999px",
            }}
          >
            Order List Not Found
          </span>
          <h1
            style={{
              fontSize: "22px",
              fontWeight: 800,
              color: "var(--ink)",
              margin: "12px 0 6px",
            }}
          >
            This list is no longer available
          </h1>
          <p
            style={{
              fontSize: "14px",
              color: "var(--ink-2)",
              lineHeight: 1.5,
              margin: 0,
            }}
          >
            This list reference link may have expired, or was already completed or deleted by{" "}
            <strong>{shopLabel}</strong>.
          </p>
        </div>

        {/* Find previous orders by phone */}
        <div
          style={{
            width: "100%",
            background: "var(--sand)",
            padding: "16px",
            borderRadius: "var(--radius-sm)",
            textAlign: "left",
            border: "1px solid var(--line)",
            marginTop: "8px",
          }}
        >
          <label
            htmlFor="recovery_phone"
            style={{
              display: "block",
              fontSize: "13px",
              fontWeight: 700,
              color: "var(--ink)",
              marginBottom: "6px",
            }}
          >
            Look up previous orders with {shopLabel}:
          </label>
          <div style={{ display: "flex", gap: "8px" }}>
            <input
              id="recovery_phone"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="Your phone number"
              style={{
                flex: 1,
                padding: "10px 12px",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--line-strong)",
                fontSize: "14px",
                background: "var(--card)",
                color: "var(--ink)",
              }}
            />
            <button
              type="button"
              disabled={loading || phone.trim().length < 7}
              onClick={() => void handleFindLists()}
              style={{
                padding: "0 16px",
                borderRadius: "var(--radius-sm)",
                background: "var(--leaf)",
                color: "#ffffff",
                fontWeight: 700,
                fontSize: "13px",
                border: "none",
                cursor: "pointer",
                whiteSpace: "nowrap",
                opacity: loading || phone.trim().length < 7 ? 0.6 : 1,
              }}
            >
              {loading ? "Finding..." : "Find"}
            </button>
          </div>
          {error ? (
            <p style={{ color: "var(--clay)", fontSize: "12px", margin: "6px 0 0" }}>{error}</p>
          ) : null}

          {searched && pastLists && pastLists.length > 0 ? (
            <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
              <span style={{ fontSize: "12px", fontWeight: 700, color: "var(--ink-2)" }}>
                Found {pastLists.length} past {pastLists.length === 1 ? "list" : "lists"}:
              </span>
              {pastLists.map((past) => (
                <div
                  key={past.id}
                  style={{
                    background: "var(--card)",
                    border: "1px solid var(--line)",
                    borderRadius: "8px",
                    padding: "10px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <span style={{ fontSize: "12px", fontWeight: 700, color: "var(--ink)" }}>
                      {new Date(past.created_at).toLocaleDateString("en-GB", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </span>
                    <span style={{ fontSize: "12px", color: "var(--ink-3)", display: "block" }}>
                      {past.lines.length} items - {past.status}
                    </span>
                  </div>
                  <Link
                    href={`/list/${slug}`}
                    style={{
                      padding: "6px 12px",
                      borderRadius: "6px",
                      background: "var(--leaf-soft)",
                      color: "var(--leaf-dark)",
                      fontSize: "12px",
                      fontWeight: 700,
                      textDecoration: "none",
                    }}
                  >
                    Build from this
                  </Link>
                </div>
              ))}
            </div>
          ) : searched && pastLists && pastLists.length === 0 ? (
            <p style={{ fontSize: "12px", color: "var(--ink-3)", margin: "8px 0 0" }}>
              No previous orders found for this number at this shop.
            </p>
          ) : null}
        </div>

        {/* Primary action buttons */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "10px",
            width: "100%",
            marginTop: "8px",
          }}
        >
          <Link
            href={`/list/${slug}`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: "44px",
              padding: "0 20px",
              borderRadius: "var(--radius-sm)",
              background: "var(--leaf)",
              color: "#ffffff",
              fontWeight: 700,
              fontSize: "14px",
              textDecoration: "none",
            }}
          >
            Create a New List for {shopLabel}
          </Link>
          <Link
            href={`/shop/${slug}`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: "44px",
              padding: "0 20px",
              borderRadius: "var(--radius-sm)",
              background: "var(--sand-2)",
              border: "1px solid var(--line-strong)",
              color: "var(--ink)",
              fontWeight: 700,
              fontSize: "14px",
              textDecoration: "none",
            }}
          >
            Browse {shopLabel}&apos;s Catalog
          </Link>
          <Link
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: "36px",
              padding: "0 20px",
              color: "var(--ink-3)",
              fontWeight: 600,
              fontSize: "13px",
              textDecoration: "none",
            }}
          >
            Return to AHIA Home
          </Link>
        </div>
      </div>
    </main>
  );
}
