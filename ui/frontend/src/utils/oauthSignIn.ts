import API_BASE_URL from '../config';

export type OAuthProvider = 'google' | 'microsoft';

/** The provider's name as people know it. */
export function providerName(provider: OAuthProvider): string {
  return provider === 'google' ? 'Google' : 'Microsoft';
}

/** The ways to sign in that the backend offers (GET /config/auth-status). */
export interface AuthStatus {
  email_login_disabled: boolean;
  google_oauth_enabled: boolean;
  microsoft_oauth_enabled: boolean;
}

/**
 * The only way to sign in, when email login is off and exactly one OAuth
 * provider is set up; otherwise null.
 */
export function onlyOAuthProvider(status: AuthStatus): OAuthProvider | null {
  if (!status.email_login_disabled) return null;
  const enabled: OAuthProvider[] = [];
  if (status.google_oauth_enabled) enabled.push('google');
  if (status.microsoft_oauth_enabled) enabled.push('microsoft');
  return enabled.length === 1 ? enabled[0] : null;
}

/**
 * Where each provider's sign-in page lives: the authorize endpoints of
 * httpx-oauth, which builds the address the backend returns.
 */
function signInHost(provider: OAuthProvider): string {
  return provider === 'google' ? 'accounts.google.com' : 'login.microsoftonline.com';
}

/**
 * ADDRESS, once it is PROVIDER's own sign-in page over HTTPS. The browser is
 * sent there with no click, so nothing else (another site, a javascript: or
 * data: address) is ever followed, whatever the response says.
 */
export function checkedSignInAddress(provider: OAuthProvider, address: unknown): string {
  const refused = new Error(
    `Could not start ${providerName(provider)} sign-in: the sign-in address is not ` +
      `${providerName(provider)}'s. Please contact the site's administrator.`,
  );
  if (typeof address !== 'string') throw refused;
  let url: URL;
  try {
    url = new URL(address);
  } catch {
    throw refused;
  }
  if (url.protocol !== 'https:' || url.host !== signInHost(provider)) throw refused;
  return url.href;
}

/**
 * Send the browser to PROVIDER's sign-in page. The current path and query go
 * through the signed state token so the callback brings the user back here.
 * Throws when the backend gives no sign-in address, or one that is not the
 * provider's (see checkedSignInAddress).
 */
export async function startOAuthSignIn(provider: OAuthProvider): Promise<void> {
  const returnTo = window.location.pathname + window.location.search;
  const authorizeUrl =
    `${API_BASE_URL}/auth/${provider}/authorize?return_to=${encodeURIComponent(returnTo)}`;
  const res = await fetch(authorizeUrl, {
    method: 'GET',
    headers: { Accept: 'application/json' },
  });
  const data = res.ok ? await res.json() : {};
  if (!data.authorization_url) {
    throw new Error(
      `Could not start ${providerName(provider)} sign-in (HTTP ${res.status}). Please try again.`,
    );
  }
  window.location.href = checkedSignInAddress(provider, data.authorization_url);
}

const AUTO_SIGN_IN_PAUSED_KEY = 'evidencelab_auto_sign_in_paused';

/**
 * Stop the sign-in screen going to the provider by itself in this browser tab
 * until someone signs in. Set when someone signs out, so the provider does not
 * sign them straight back in, and before each automatic trip, so a trip that
 * comes back still signed out shows the button instead of going round again.
 */
export function pauseAutoSignIn(): void {
  window.sessionStorage.setItem(AUTO_SIGN_IN_PAUSED_KEY, '1');
}

/** Let the sign-in screen go to the provider by itself again. */
export function resumeAutoSignIn(): void {
  window.sessionStorage.removeItem(AUTO_SIGN_IN_PAUSED_KEY);
}

export function autoSignInPaused(): boolean {
  return window.sessionStorage.getItem(AUTO_SIGN_IN_PAUSED_KEY) !== null;
}
