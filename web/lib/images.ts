/**
 * Turning whatever the camera produced into what we actually want to store.
 *
 * A phone does not hand over a tidy JPEG. It hands over HEIC, or a 12-megabyte portrait, or a PNG
 * screenshot of a chat, and the trader choosing a photo has no idea which - nor should he have to.
 * Waiting for him to convert it is waiting for him not to bother. So the browser decodes whatever it
 * can, scales it to something a product card shows well, and re-encodes it as WebP; if this browser
 * cannot produce WebP it produces a JPEG instead.
 *
 * What that buys, in order of how much it matters:
 *
 * - **An iPhone photo uploads.** HEIC decodes here and never reaches the API, so the allowlist stops
 *   being a wall the trader walks into.
 * - **Uploads are small enough to work on a market connection.** A 4000px photograph becomes 1600px,
 *   which is a tenth of the bytes and still more than any screen shows.
 * - **One format in storage**, so the delivery pipeline has one thing to do rather than five.
 *
 * **This is not a security control and is not treated as one.** Everything here happens in a browser,
 * which the client controls, so the API keeps its own allowlist and decodes the bytes to check that
 * the type claimed is the type sent. The rule this project holds to - client-side validation is not
 * security - is why both halves exist rather than only this one.
 */

/** The longest edge kept. Wider than any product card, and a tenth of a phone photograph's weight. */
const MAXIMUM_EDGE_PIXELS = 1600;

/** Good enough for a product photograph and small enough to send over a patchy connection. */
const WEBP_QUALITY = 0.82;
const JPEG_QUALITY = 0.85;

export interface NormalisedImage {
  file: File;
  /** A sentence worth showing a person about what happened, when something surprising did. */
  note: string | null;
}

export class ImageNotReadableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ImageNotReadableError";
  }
}

/** True when the browser can encode WebP, which every browser this app supports can. */
async function canEncodeWebp(): Promise<boolean> {
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  return canvas.toDataURL("image/webp").startsWith("data:image/webp");
}

function scaledSize(width: number, height: number): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= MAXIMUM_EDGE_PIXELS) {
    return { width, height };
  }
  const ratio = MAXIMUM_EDGE_PIXELS / longest;
  return {
    width: Math.max(1, Math.round(width * ratio)),
    height: Math.max(1, Math.round(height * ratio)),
  };
}

/**
 * Decode, scale and re-encode one chosen file.
 *
 * The original file is returned unchanged when the browser cannot decode it at all - a format this
 * browser has never heard of has a decent chance of being a format the API has, and refusing here
 * would be this layer deciding something it cannot see. The API remains the judge.
 */
export async function normaliseImage(file: File): Promise<NormalisedImage> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return {
      file,
      note:
        "This browser could not read that picture, so it is being sent as it is. " +
        "If it is refused, try taking the photo again.",
    };
  }

  try {
    const { width, height } = scaledSize(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (context === null) {
      return { file, note: null };
    }
    context.drawImage(bitmap, 0, 0, width, height);

    const webp = await canEncodeWebp();
    const type = webp ? "image/webp" : "image/jpeg";
    const quality = webp ? WEBP_QUALITY : JPEG_QUALITY;

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, type, quality),
    );
    if (blob === null) {
      return { file, note: null };
    }

    // A conversion that made the file bigger is a conversion that helped nobody.
    if (blob.size >= file.size && width === bitmap.width && height === bitmap.height) {
      return { file, note: null };
    }

    const extension = webp ? "webp" : "jpg";
    const name = file.name.replace(/\.[^.]+$/, "") || "photo";
    return {
      file: new File([blob], `${name}.${extension}`, { type, lastModified: Date.now() }),
      note: null,
    };
  } finally {
    bitmap.close();
  }
}

/** A short, true sentence about a picture, for the confirmation a trader sees. */
export function describeImageSize(file: File): string {
  const kilobytes = Math.max(1, Math.round(file.size / 1024));
  return kilobytes >= 1024
    ? `${(kilobytes / 1024).toFixed(1)} MB`
    : `${kilobytes} KB`;
}
