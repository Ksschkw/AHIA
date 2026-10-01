import * as SecureStore from "expo-secure-store";

/**
 * The session, kept where a phone keeps secrets.
 *
 * Persists both access_token and refresh_token in SecureStore so that app closes,
 * background kills, and device restarts do not lose authentication or kick the
 * trader back to the login screen.
 */

const REFRESH_KEY = "ahia.refresh_token";
const ACCESS_KEY = "ahia.access_token";

let accessToken: string | null = null;

export function currentAccessToken(): string | null {
  return accessToken;
}

export function rememberAccessToken(token: string): void {
  accessToken = token;
  SecureStore.setItemAsync(ACCESS_KEY, token, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  }).catch(() => {});
}

export async function readStoredAccessToken(): Promise<string | null> {
  try {
    const token = await SecureStore.getItemAsync(ACCESS_KEY);
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
      SecureStore.setItemAsync(ACCESS_KEY, session.access_token, {
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      }),
      SecureStore.setItemAsync(REFRESH_KEY, session.refresh_token, {
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      }),
    ]);
  } catch {
    // Non-fatal if keychain write delays
  }
}

export async function readRefreshToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(REFRESH_KEY);
  } catch {
    return null;
  }
}

/** Forget everything, for a phone being handed on or a person signing out. */
export async function forgetSession(): Promise<void> {
  accessToken = null;
  try {
    await Promise.all([
      SecureStore.deleteItemAsync(ACCESS_KEY).catch(() => {}),
      SecureStore.deleteItemAsync(REFRESH_KEY).catch(() => {}),
    ]);
  } catch {
    // Ignore deletion errors during signout
  }
}
