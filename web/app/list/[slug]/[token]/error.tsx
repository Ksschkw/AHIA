"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Brand } from "@/components/brand";

export default function OrderTrackerErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const params = useParams();
  const slug = typeof params?.slug === "string" ? params.slug : "";

  useEffect(() => {
    console.error("Order tracker error boundary caught error:", error);
  }, [error]);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        background: "var(--sand, #fbf7f0)",
        textAlign: "center",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <div
        style={{
          maxWidth: "460px",
          width: "100%",
          background: "var(--card, #ffffff)",
          border: "1px solid var(--line, #e2dcd2)",
          borderRadius: "24px",
          padding: "36px 24px",
          boxShadow: "0 10px 30px rgba(0, 0, 0, 0.08)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "16px",
        }}
      >
        <Brand size={32} />

        <div>
          <span
            style={{
              fontSize: "12px",
              fontWeight: 800,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              color: "#084a2f",
              background: "rgba(8, 74, 47, 0.1)",
              padding: "4px 12px",
              borderRadius: "999px",
            }}
          >
            Order Tracking Notice
          </span>
          <h1
            style={{
              fontSize: "22px",
              fontWeight: 800,
              color: "var(--ink, #0f172a)",
              margin: "12px 0 6px",
            }}
          >
            Unable to Load Order Tracker
          </h1>
          <p
            style={{
              fontSize: "14px",
              color: "var(--ink-2, #334155)",
              lineHeight: 1.5,
              margin: 0,
            }}
          >
            Your order was submitted safely to the merchant. We could not refresh the live view right now. You can retry or head back to the shop catalog.
          </p>
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "10px",
            width: "100%",
            marginTop: "12px",
          }}
        >
          <button
            type="button"
            onClick={() => reset()}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: "46px",
              padding: "0 20px",
              borderRadius: "999px",
              background: "var(--leaf, #084a2f)",
              color: "#ffffff",
              fontWeight: 700,
              fontSize: "14px",
              border: "none",
              cursor: "pointer",
            }}
          >
            Retry Loading Order
          </button>

          {slug ? (
            <Link
              href={`/shop/${slug}`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                minHeight: "46px",
                padding: "0 20px",
                borderRadius: "999px",
                background: "var(--sand-2, #f1ede4)",
                border: "1px solid var(--line-strong, #cbbfaf)",
                color: "var(--ink, #0f172a)",
                fontWeight: 700,
                fontSize: "14px",
                textDecoration: "none",
              }}
            >
              Back to Shop Catalog
            </Link>
          ) : null}

          <Link
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: "36px",
              padding: "0 20px",
              color: "var(--ink-3, #64748b)",
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
