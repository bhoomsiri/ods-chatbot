/**
 * Cloudflare Access auth helpers.
 *
 * The demo is gated by Cloudflare Access at the edge (Google login), so these
 * `/cdn-cgi/access/*` endpoints are served by Cloudflare — not our backend —
 * and only exist when the app is reached through the protected domain. On
 * localhost they 404, which we treat as "no gateway / dev mode" so the app
 * still works without auth.
 */

export interface Identity {
  email: string;
  name?: string;
}

const IDENTITY_URL = "/cdn-cgi/access/get-identity";

/**
 * sessionStorage key marking that the user passed the in-app login screen this
 * tab session. sessionStorage survives a refresh but is cleared when the tab /
 * browser closes — so a refresh keeps you in, reopening shows login again.
 */
export const ENTERED_KEY = "ods-entered";

/** Cloudflare clears the Access session, then shows its logout page. */
export const LOGOUT_URL =
  process.env.NEXT_PUBLIC_LOGOUT_URL ?? "/cdn-cgi/access/logout";

/**
 * Visiting any protected path while logged out makes Cloudflare Access show the
 * Google login. "/" is the simplest such path; override per-deploy if needed.
 */
export const LOGIN_URL = process.env.NEXT_PUBLIC_LOGIN_URL ?? "/";

/** Who is logged in (via Cloudflare), or null if not behind Access / not signed in. */
export async function fetchIdentity(): Promise<Identity | null> {
  try {
    const res = await fetch(IDENTITY_URL, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { email?: string; name?: string };
    return data.email ? { email: data.email, name: data.name } : null;
  } catch {
    return null;
  }
}

export function login(): void {
  window.location.assign(LOGIN_URL);
}

export function logout(): void {
  // Drop the in-app entry flag so returning lands on the login screen.
  try {
    window.sessionStorage.removeItem(ENTERED_KEY);
  } catch {
    /* sessionStorage unavailable — ignore */
  }
  window.location.assign(LOGOUT_URL);
}
