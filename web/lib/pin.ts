/**
 * Business Security PIN for AHIA Web.
 *
 * Distinct from personal account passwords:
 * - Account Password: Used by a user (owner, manager, apprentice) to sign into AHIA.
 * - Business Security PIN: A 4-digit numeric PIN linked to a specific stall/business.
 *   Only the business OWNER is authorized to configure, change, or reset this PIN.
 *   It is used in-app to authorize high-stakes operations such as confirming orders,
 *   voiding sales, changing member roles, and security overrides.
 */

export const SHORTEST_PIN = 4;

function pinKey(tenantId: string): string {
  return `ahia.biz_pin.${tenantId}`;
}

function saltKey(tenantId: string): string {
  return `ahia.biz_pin_salt.${tenantId}`;
}

async function simpleHash(pin: string, salt: string): Promise<string> {
  const input = `${salt}:${pin}`;
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    const char = input.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash |= 0;
  }
  return `h_${Math.abs(hash).toString(16)}_${input.length}`;
}

export async function hasBusinessPin(tenantId: string): Promise<boolean> {
  if (typeof window === "undefined") return false;
  try {
    const stored = window.localStorage.getItem(pinKey(tenantId));
    return Boolean(stored);
  } catch {
    return false;
  }
}

export async function setBusinessPin(tenantId: string, pin: string): Promise<void> {
  if (typeof window === "undefined") return;
  const salt = `salt_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
  const digest = await simpleHash(pin, salt);
  window.localStorage.setItem(saltKey(tenantId), salt);
  window.localStorage.setItem(pinKey(tenantId), digest);
}

export async function verifyBusinessPin(tenantId: string, pin: string): Promise<boolean> {
  if (typeof window === "undefined") return false;
  try {
    const salt = window.localStorage.getItem(saltKey(tenantId));
    const known = window.localStorage.getItem(pinKey(tenantId));
    if (!salt || !known) return false;
    const computed = await simpleHash(pin, salt);
    return computed === known;
  } catch {
    return false;
  }
}

export async function clearBusinessPin(tenantId: string): Promise<void> {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(saltKey(tenantId));
    window.localStorage.removeItem(pinKey(tenantId));
  } catch {
    // Non-fatal
  }
}
