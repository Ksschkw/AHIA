"use client";

import { useEffect } from "react";
import Link from "next/link";
import { Brand } from "@/components/brand";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log error cleanly for debugging
    console.error("Application error boundary triggered:", error);
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
        background: "var(--sand)",
        textAlign: "center",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <div
        style={{
          maxWidth: "480px",
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
              color: "var(--clay)",
              background: "var(--clay-soft, #fbe9dd)",
              padding: "3px 10px",
              borderRadius: "999px",
            }}
          >
            Connection / Temporary Glitch
          </span>
          <h1
            style={{
              fontSize: "24px",
              fontWeight: 800,
              color: "var(--ink)",
              margin: "12px 0 6px",
            }}
          >
            Something went wrong
          </h1>
          <p
            style={{
              fontSize: "14px",
              color: "var(--ink-2)",
              lineHeight: 1.5,
              margin: 0,
            }}
          >
            We could not complete this action. Your data is safe. Please tap retry to try again.
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
              minHeight: "44px",
              padding: "0 20px",
              borderRadius: "var(--radius-sm)",
              background: "var(--leaf)",
              color: "#ffffff",
              fontWeight: 700,
              fontSize: "14px",
              border: "none",
              cursor: "pointer",
            }}
          >
            Try Again / Retry
          </button>
          <Link
            href="/app"
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
            Go to Trader Dashboard
          </Link>
          <Link
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: "40px",
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
