/**
 * What a customer sees while a product is being fetched.
 *
 * The picture frame and the two lines of text appear in the places they will occupy, so the page does
 * not jump when the photograph lands - and somebody waiting sees a product arriving rather than a blank
 * screen.
 */
export default function LoadingProduct() {
  const block = {
    borderRadius: "12px",
    background: "var(--sand-2)",
  } as const;

  return (
    <div
      aria-busy="true"
      aria-live="polite"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr",
        gap: "20px",
        padding: "20px 16px",
        maxWidth: "900px",
        margin: "0 auto",
      }}
    >
      <span style={{ ...block, aspectRatio: "1 / 1", width: "100%" }} />
      <span style={{ ...block, height: "28px", width: "70%" }} />
      <span style={{ ...block, height: "34px", width: "40%" }} />
      <span style={{ ...block, height: "54px", width: "100%" }} />
    </div>
  );
}
