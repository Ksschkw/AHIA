import Link from "next/link";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui";

export default function NotFound() {
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
              background: "var(--sand-2)",
              padding: "3px 10px",
              borderRadius: "999px",
            }}
          >
            404 - Page Not Found
          </span>
          <h1
            style={{
              fontSize: "24px",
              fontWeight: 800,
              color: "var(--ink)",
              margin: "12px 0 6px",
            }}
          >
            This page does not exist
          </h1>
          <p
            style={{
              fontSize: "14px",
              color: "var(--ink-2)",
              lineHeight: 1.5,
              margin: 0,
            }}
          >
            The link you opened might be broken, outdated, or the shop address may have changed.
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
          <Link
            href="/app"
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
            Go to Trader Dashboard
          </Link>
          <Link
            href="/"
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
            Return to AHIA Home
          </Link>
        </div>
      </div>
    </main>
  );
}
