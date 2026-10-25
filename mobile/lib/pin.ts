import { Platform } from "react-native";
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

const isWeb = Platform.OS === "web";

async function storageSet(key: string, value: string): Promise<void> {
  if (isWeb && typeof window !== "undefined" && window.localStorage) {
    window.localStorage.setItem(key, value);
    return;
  }
  try {
    await SecureStore.setItemAsync(key, value, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
  } catch {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem(key, value);
    }
  }
}

async function storageGet(key: string): Promise<string | null> {
  if (isWeb && typeof window !== "undefined" && window.localStorage) {
    return window.localStorage.getItem(key);
  }
  try {
    const val = await SecureStore.getItemAsync(key);
    if (val) return val;
  } catch {
    // Fallback
  }
  if (typeof window !== "undefined" && window.localStorage) {
    return window.localStorage.getItem(key);
  }
  return null;
}

async function storageDelete(key: string): Promise<void> {
  if (isWeb && typeof window !== "undefined" && window.localStorage) {
    window.localStorage.removeItem(key);
    return;
  }
  try {
    await SecureStore.deleteItemAsync(key).catch(() => {});
  } catch {
    // Fallback
  }
  if (typeof window !== "undefined" && window.localStorage) {
    window.localStorage.removeItem(key);
  }
}

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
    const stored = await storageGet(pinKey(tenantId));
    return Boolean(stored);
  } catch {
    return false;
  }
}

export async function setBusinessPin(tenantId: string, pin: string): Promise<void> {
  const salt = `salt_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
  const digest = await simpleHash(pin, salt);
  await storageSet(saltKey(tenantId), salt);
  await storageSet(pinKey(tenantId), digest);
}

export async function verifyBusinessPin(tenantId: string, pin: string): Promise<boolean> {
  try {
    const salt = await storageGet(saltKey(tenantId));
    const known = await storageGet(pinKey(tenantId));
    if (!salt || !known) return false;
    const computed = await simpleHash(pin, salt);
    return computed === known;
  } catch {
    return false;
  }
}

export async function clearBusinessPin(tenantId: string): Promise<void> {
  try {
    await storageDelete(saltKey(tenantId));
    await storageDelete(pinKey(tenantId));
  } catch {
    // Non-fatal
  }
}
