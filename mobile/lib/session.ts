import * as SecureStore from "expo-secure-store";

/**
 * The session, kept where a phone keeps secrets.
 *
 * The web client keeps its credential in an HttpOnly cookie the browser attaches for it, and it never sees the
 * value. A native app has no such thing: whatever it holds, it holds in its own process, and the difference
 * between the keychain and a JSON file in the app's documents folder is the difference between a stolen phone
 * being a phone somebody stole and being an account somebody has.
 *
 * So the **refresh token lives in SecureStore** - the iOS keychain, the Android keystore - and the **access
 * token lives in memory only**. The access token is short-lived and replaced constantly; writing it to disk
 * would buy nothing and leave a second credential lying around.
 *
 * This is not a defence against somebody in the app's process - an app can always read its own keychain. It is
 * a defence against a backup, a shared device, and the file someone copies off a laptop. The server deciding
 * what a person may do, on every call, is still the only thing that protects the business.
 */

const REFRESH_KEY = "ahia.refresh_token";

let accessToken: string | null = null;

export function currentAccessToken(): string | null {
  return accessToken;
}

export function rememberAccessToken(token: string): void {
  accessToken = token;
}

export async function rememberSession(session: {
  access_token: string;
  refresh_token: string;
}): Promise<void> {
  accessToken = session.access_token;
  // Requires the device to be unlocked on both platforms, which is the moment a trader is at his shop.
  await SecureStore.setItemAsync(REFRESH_KEY, session.refresh_token, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
}

export async function readRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_KEY);
}

/** Forget everything, for a phone being handed on or a person signing out. */
export async function forgetSession(): Promise<void> {
  accessToken = null;
  await SecureStore.deleteItemAsync(REFRESH_KEY);
}
