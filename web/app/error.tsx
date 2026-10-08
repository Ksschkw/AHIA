"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "@/components/brand";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const pathname = usePathname();

  useEffect(() => {
    // Log error cleanly for debugging
    console.error("Application error boundary triggered:", error);
  }, [error]);

  const isCustomerStorefront = pathname?.startsWith("/shop") || pathname?.startsWith("/list");
  const isTraderApp = pathname?.startsWith("/app");

  // Derive target shop slug if available from pathname
  const shopSlug = pathname?.split("/")[2] || null;

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
          maxWidth: "480px",
          width: "100%",
          background: "var(--card, #ffffff)",
          border: "1px solid var(--line, #e2dcd2)",
          borderRadius: "20px",
          padding: "36px 24px",
          boxShadow: "0 10px 30px rgba(0, 0, 0, 0.08)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "16px",
        }}
      >
        <Brand size={32} />

        <div style={{ marginTop: "8px" }}>
          <span
            style={{
              fontSize: "12px",
              fontWeight: 800,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              color: isCustomerStorefront ? "#084a2f" : "var(--clay, #c2571f)",
              background: isCustomerStorefront ? "rgba(8, 74, 47, 0.1)" : "var(--clay-soft, #fbe9dd)",
              padding: "4px 12px",
              borderRadius: "999px",
            }}
          >
            {isCustomerStorefront ? "Storefront Connection Notice" : "Temporary Connection Glitch"}
          </span>
          <h1
            style={{
              fontSize: "24px",
              fontWeight: 800,
              color: "var(--ink, #0f172a)",
              margin: "14px 0 8px",
            }}
          >
            {isCustomerStorefront ? "Unable to Complete Action" : "Something went wrong"}
          </h1>
          <p
            style={{
              fontSize: "14px",
              color: "var(--ink-2, #334155)",
              lineHeight: 1.5,
              margin: 0,
            }}
          >
            {isCustomerStorefront
              ? "We could not reach the shop service at this moment. Your order list items are preserved safely on your phone. Please tap retry or return to the shop."
              : "We could not complete this action. Your records are safe. Please tap retry to try again."}
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
              boxShadow: "0 4px 12px rgba(8, 74, 47, 0.25)",
            }}
          >
            Try Again / Retry
          </button>

          {isCustomerStorefront ? (
            <>
              <button
                type="button"
                onClick={() => {
                  if (typeof window !== "undefined" && window.history.length > 1) {
                    window.history.back();
                  } else if (shopSlug) {
                    window.location.href = `/shop/${shopSlug}`;
                  } else {
                    window.location.href = "/";
                  }
                }}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  minHeight: "46px",
                  padding: "0 20px",
                  borderRadius: "999px",
                  background: "var(--card, #ffffff)",
                  border: "1.5px solid var(--line-strong, #cbbfaf)",
                  color: "var(--ink, #0f172a)",
                  fontWeight: 700,
                  fontSize: "14px",
                  cursor: "pointer",
                }}
              >
                Back to Order List
              </button>

              {shopSlug ? (
                <Link
                  href={`/shop/${shopSlug}`}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    minHeight: "40px",
                    padding: "0 20px",
                    color: "var(--leaf, #084a2f)",
                    fontWeight: 700,
                    fontSize: "13px",
                    textDecoration: "none",
                  }}
                >
                  Return to Stall Catalog
                </Link>
              ) : null}
            </>
          ) : isTraderApp ? (
            <Link
              href="/app"
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
              Go to Trader Dashboard
            </Link>
          ) : (
            <Link
              href="/"
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
              Return Home
            </Link>
          )}

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
              fontSize: "12px",
              textDecoration: "none",
            }}
          >
            AHIA Market System
          </Link>
        </div>
      </div>
    </main>
  );
}
