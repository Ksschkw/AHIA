import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

/**
 * The session, kept where a device keeps secrets.
 *
 * Persists both access_token and refresh_token in SecureStore on mobile and localStorage
 * on web so that app closes, background kills, browser reloads, and device restarts do
 * not lose authentication or kick the trader back to the login screen.
 */

const REFRESH_KEY = "ahia.refresh_token";
const ACCESS_KEY = "ahia.access_token";

let accessToken: string | null = null;

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

export function currentAccessToken(): string | null {
  return accessToken;
}

export function rememberAccessToken(token: string): void {
  accessToken = token;
  storageSet(ACCESS_KEY, token).catch(() => {});
}

export async function readStoredAccessToken(): Promise<string | null> {
  try {
    const token = await storageGet(ACCESS_KEY);
    if (token) {
      accessToken = token;
    }
    return token;
  } catch {
    return null;
  }
}

export async function rememberSession(session: {
  access_token: string;
  refresh_token: string;
}): Promise<void> {
  accessToken = session.access_token;
  try {
    await Promise.all([
      storageSet(ACCESS_KEY, session.access_token),
      storageSet(REFRESH_KEY, session.refresh_token),
    ]);
  } catch {
    // Non-fatal if storage write delays
  }
}

export async function readRefreshToken(): Promise<string | null> {
  try {
    return await storageGet(REFRESH_KEY);
  } catch {
    return null;
  }
}

/** Forget everything, for a phone being handed on or a person signing out. */
export async function forgetSession(): Promise<void> {
  accessToken = null;
  try {
    await Promise.all([
      storageDelete(ACCESS_KEY),
      storageDelete(REFRESH_KEY),
    ]);
  } catch {
    // Ignore deletion errors during signout
  }
}
