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

// The request that clears the sign-in cookie, while one is under way.
let signOutRequest: Promise<void> = Promise.resolve();

/**
 * Make trips to a provider wait for REQUEST, the one that clears the sign-in
 * cookie. Leaving the page first would cancel it, and the old session would
 * outlive the sign-out. A failed request does not hold them up.
 */
export function holdSignInUntilSignedOut(request: Promise<unknown>): void {
  signOutRequest = request.then(
    () => undefined,
    () => undefined,
  );
}

export interface SignInOptions {
  /**
   * Ask the provider to show its account picker rather than sign in, without
   * asking, an account it already knows.
   */
  pickAccount?: boolean;
}

/**
 * Send the browser to PROVIDER's sign-in page. The current path and query go
 * through the signed state token so the callback brings the user back here.
 * Throws when the backend gives no sign-in address, or one that is not the
 * provider's (see checkedSignInAddress).
 */
export async function startOAuthSignIn(
  provider: OAuthProvider,
  { pickAccount = false }: SignInOptions = {},
): Promise<void> {
  await signOutRequest;
  const returnTo = window.location.pathname + window.location.search;
  const prompt = pickAccount ? '&prompt=select_account' : '';
  const authorizeUrl =
    `${API_BASE_URL}/auth/${provider}/authorize?return_to=${encodeURIComponent(returnTo)}${prompt}`;
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

/*
 * How the sign-in screen of this browser tab goes to the only provider by
 * itself (only on sites whose one way to sign in is Microsoft or Google; see
 * onlyOAuthProvider). Nothing stored: it goes. "pick-account": it goes, and
 * asks the provider for its account picker. "paused": it shows the button.
 */
const AUTO_SIGN_IN_KEY = 'evidencelab_auto_sign_in';
const PAUSED = 'paused';
const PICK_ACCOUNT = 'pick-account';

/**
 * Stop the sign-in screen going to the provider by itself in this browser tab
 * until someone signs in. Set before each automatic trip, so a trip that comes
 * back still signed out shows the button instead of going round again.
 */
export function pauseAutoSignIn(): void {
  window.sessionStorage.setItem(AUTO_SIGN_IN_KEY, PAUSED);
}

/**
 * Make the next automatic trip from this browser tab ask the provider for its
 * account picker. Set when someone signs out or their session times out: the
 * provider usually still knows them and would otherwise sign them straight
 * back in, so signing out would undo itself and an unattended tab would sign
 * itself back in.
 */
export function pickAccountNextTime(): void {
  window.sessionStorage.setItem(AUTO_SIGN_IN_KEY, PICK_ACCOUNT);
}

/** Let the sign-in screen go to the provider by itself again, without asking. */
export function resumeAutoSignIn(): void {
  window.sessionStorage.removeItem(AUTO_SIGN_IN_KEY);
}

export function autoSignInPaused(): boolean {
  return window.sessionStorage.getItem(AUTO_SIGN_IN_KEY) === PAUSED;
}

export function accountPickRequested(): boolean {
  return window.sessionStorage.getItem(AUTO_SIGN_IN_KEY) === PICK_ACCOUNT;
}
