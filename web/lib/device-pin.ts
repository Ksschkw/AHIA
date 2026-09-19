/**
 * The PIN that stands in front of what matters.
 *
 * **What this is.** A trader's phone is picked up by a shop assistant, a customer, a nephew. This is the
 * difference between "the app is open" and "the person holding it is the owner" - for changing a price,
 * taking somebody off the team, or confirming a payout.
 *
 * **What this is not.** It is not a security boundary, and it must never be described as one. It is stored
 * on the device, it can be bypassed by anybody who can read the browser's storage or the source, and it
 * does not replace the server deciding what a signed-in person is allowed to do - the server does that
 * already, on every call, and this adds nothing to it. A device PIN defends against the person standing
 * next to you, and against nobody else. Saying so in the file is the point: a later reader who mistakes
 * this for access control would make a decision that costs money.
 *
 * The PIN itself is never stored - only a salted digest - so a glance at the storage does not give it away.
 * That still does not make it a secret worth reusing, and the screen says so when it is set.
 */

const PIN_DIGEST_KEY = "ahia.pin.digest";
const PIN_SALT_KEY = "ahia.pin.salt";
export const SHORTEST_PIN = 4;

async function digest(pin: string, salt: string): Promise<string> {
  const bytes = new TextEncoder().encode(`${salt}:${pin}`);
  const hashed = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hashed)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    // A browser with storage turned off leaves the gate unset rather than crashing a screen.
    return null;
  }
}

/** Whether this device has a PIN. */
export function hasDevicePin(): boolean {
  const store = storage();
  return Boolean(store?.getItem(PIN_DIGEST_KEY) && store?.getItem(PIN_SALT_KEY));
}

/** Set, or replace, the PIN on this device. */
export async function setDevicePin(pin: string): Promise<void> {
  const store = storage();
  if (!store) return;
  const salt = crypto.randomUUID();
  store.setItem(PIN_SALT_KEY, salt);
  store.setItem(PIN_DIGEST_KEY, await digest(pin, salt));
}

/** Forget it, for a device being handed on. */
export function clearDevicePin(): void {
  const store = storage();
  store?.removeItem(PIN_DIGEST_KEY);
  store?.removeItem(PIN_SALT_KEY);
}

/** Whether what was typed is the PIN this device knows. */
export async function verifyDevicePin(pin: string): Promise<boolean> {
  const store = storage();
  const salt = store?.getItem(PIN_SALT_KEY);
  const known = store?.getItem(PIN_DIGEST_KEY);
  if (!salt || !known) return false;
  return (await digest(pin, salt)) === known;
}
