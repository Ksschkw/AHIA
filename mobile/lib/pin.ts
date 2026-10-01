import * as SecureStore from "expo-secure-store";

/**
 * Business Security PIN for AHIA Mobile.
 *
 * Distinct from personal account passwords:
 * - Account Password: Used by a user (owner, manager, apprentice) to sign into AHIA.
 * - Business Security PIN: A 4 to 6-digit numeric PIN linked to a specific stall/business.
 *   Only the business OWNER is authorized to configure, change, or reset this PIN.
 *   It is used in-app to authorize high-stakes operations such as price overrides,
 *   staff removal, ledger resets, and bulk item deletions.
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
  try {
    const stored = await SecureStore.getItemAsync(pinKey(tenantId));
    return Boolean(stored);
  } catch {
    return false;
  }
}

export async function setBusinessPin(tenantId: string, pin: string): Promise<void> {
  const salt = `salt_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
  const digest = await simpleHash(pin, salt);
  await SecureStore.setItemAsync(saltKey(tenantId), salt);
  await SecureStore.setItemAsync(pinKey(tenantId), digest);
}

export async function verifyBusinessPin(tenantId: string, pin: string): Promise<boolean> {
  try {
    const salt = await SecureStore.getItemAsync(saltKey(tenantId));
    const known = await SecureStore.getItemAsync(pinKey(tenantId));
    if (!salt || !known) return false;
    const computed = await simpleHash(pin, salt);
    return computed === known;
  } catch {
    return false;
  }
}

export async function clearBusinessPin(tenantId: string): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(saltKey(tenantId));
    await SecureStore.deleteItemAsync(pinKey(tenantId));
  } catch {
    // Non-fatal
  }
}
