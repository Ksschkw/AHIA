/**
 * What a person sees between tapping a destination and the next screen being ready.
 *
 * Nearly every screen here is drawn from data that arrives over the network, so without this a tap
 * looks like nothing happened for as long as the request takes. A bar that moves immediately is the
 * difference between "this is working" and "did my tap register?" - and it costs one file, because
 * Next.js renders it the instant a route change begins.
 */
export default function Loading() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "20px 4px",
        color: "var(--ink-3)",
        fontSize: "13px",
        fontWeight: 600,
      }}
    >
      <span
        style={{
          width: "14px",
          height: "14px",
          borderRadius: "50%",
          border: "2px solid var(--line-strong)",
          borderTopColor: "var(--leaf)",
          animation: "ahia-spin 0.7s linear infinite",
        }}
      />
      Getting it ready...
    </div>
  );
}
