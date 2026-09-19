import { currentAccessToken, forgetSession, readRefreshToken, rememberSession } from "./session";

/**
 * The same API the web app calls, from a phone.
 *
 * **Nothing about the backend changes for mobile.** It already accepts an `Authorization` header before it
 * looks for a session cookie - its own docstring says so, and names a mobile client as the reason - and its
 * sign-in and refresh endpoints already return both tokens in the body. What follows is the client side of
 * that: hold the access token in memory, keep the refresh token in the keychain, and refresh in exactly one
 * place when a call comes back 401.
 *
 * The base address comes from the environment so a build points at whichever API it was built for, rather than
 * carrying a hostname that happens to be right today.
 */

const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "https://p01--ahia-api--qw5xhkblp8hy.code.run";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function refreshOnce(): Promise<boolean> {
  const refreshToken = await readRefreshToken();
  if (!refreshToken) return false;
  const response = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) {
    // The refresh token is gone, expired or revoked: there is no session left to rescue, and pretending
    // otherwise would leave a screen that looks signed in and cannot do anything.
    await forgetSession();
    return false;
  }
  await rememberSession(await response.json());
  return true;
}

/**
 * Call the API, refreshing once if the access token has expired.
 *
 * One retry, never a loop: an endpoint that answers 401 twice in a row is not a stale token, it is a refusal,
 * and retrying would turn a clear answer into a delay.
 */
export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const send = async (): Promise<Response> => {
    const token = currentAccessToken();
    return fetch(`${BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
    });
  };

  let response = await send();
  if (response.status === 401 && (await refreshOnce())) {
    response = await send();
  }
  const payload = (await response.json().catch(() => null)) as
    | { error?: { message?: string } }
    | null;
  if (!response.ok) {
    throw new ApiError(response.status, payload?.error?.message ?? "That did not work. Try again.");
  }
  return payload as T;
}

/**
 * Sign in and keep the session where a phone keeps secrets.
 *
 * The field is **`identifier`**, not `phone`: one field for whichever a trader remembers, phone or email, and
 * the service decides which it is. The schema forbids extra fields, so sending `phone` is refused with
 * `INVALID_REQUEST` before anything is looked up - which is exactly what happened the first time this app was
 * opened on a phone.
 */
export async function signIn(identifier: string, password: string): Promise<void> {
  const session = await request<{ access_token: string; refresh_token: string }>("/api/v1/auth/login", {
    method: "POST",
    body: { identifier, password },
  });
  await rememberSession(session);
}

/** Create an account, and be signed in with it. */
export async function registerAccount(details: {
  firstName: string;
  lastName: string;
  phone: string;
  password: string;
}): Promise<void> {
  const session = await request<{ access_token: string; refresh_token: string }>("/api/v1/auth/register", {
    method: "POST",
    body: {
      first_name: details.firstName,
      ...(details.lastName.trim() ? { last_name: details.lastName } : {}),
      phone: details.phone,
      password: details.password,
    },
  });
  await rememberSession(session);
}
