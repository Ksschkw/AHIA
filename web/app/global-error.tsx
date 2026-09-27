"use client";

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          padding: "24px",
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#f7f3ec",
          fontFamily: "system-ui, sans-serif",
          color: "#1e1b16",
        }}
      >
        <div
          style={{
            maxWidth: "460px",
            width: "100%",
            background: "#ffffff",
            padding: "32px 24px",
            borderRadius: "14px",
            border: "1px solid #e7dfd2",
            textAlign: "center",
          }}
        >
          <h1 style={{ fontSize: "22px", fontWeight: 800, margin: "0 0 10px" }}>
            Application Error
          </h1>
          <p style={{ fontSize: "14px", color: "#5c5549", lineHeight: 1.5, margin: "0 0 20px" }}>
            The app encountered an unexpected error. Please retry or refresh the page.
          </p>
          <button
            type="button"
            onClick={() => reset()}
            style={{
              padding: "12px 24px",
              borderRadius: "8px",
              background: "#084a2f",
              color: "#ffffff",
              fontWeight: 700,
              fontSize: "14px",
              border: "none",
              cursor: "pointer",
            }}
          >
            Retry / Reload
          </button>
        </div>
      </body>
    </html>
  );
}
