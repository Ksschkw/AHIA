/**
 * What a customer sees while the shop is being fetched.
 *
 * The shape of the page rather than a spinner in the middle of nothing: a heading where the heading will
 * be and cards where the cards will be. Somebody waiting sees the shop arriving instead of a blank
 * screen, and the layout does not jump when it does.
 */
export default function LoadingShop() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        gap: "20px",
        padding: "20px 16px",
        maxWidth: "900px",
        margin: "0 auto",
      }}
    >
      <span style={{ color: "var(--ink-3)", fontSize: "13px", fontWeight: 600 }}>
        Opening the shop...
      </span>
      <span
        style={{
          display: "block",
          height: "38px",
          width: "60%",
          borderRadius: "10px",
          background: "var(--sand-2)",
        }}
      />
      <span
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: "12px",
        }}
      >
        {[0, 1, 2, 3].map((index) => (
          <span
            key={index}
            style={{
              display: "block",
              aspectRatio: "1 / 1",
              borderRadius: "10px",
              background: "var(--sand-2)",
            }}
          />
        ))}
      </span>
    </div>
  );
}
