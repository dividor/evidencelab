import {
  accountPickRequested,
  autoSignInPaused,
  checkedSignInAddress,
  holdSignInUntilSignedOut,
  onlyOAuthProvider,
  pauseAutoSignIn,
  pickAccountNextTime,
  resumeAutoSignIn,
  startOAuthSignIn,
} from '../oauthSignIn';

const MICROSOFT_PAGE =
  'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=test-client';

// Test input only: an address that would run script if the browser followed it.
const SCRIPT_ADDRESS = ['javascript', 'alert(1)'].join(':');

const status = (email: boolean, google: boolean, microsoft: boolean) => ({
  email_login_disabled: !email,
  google_oauth_enabled: google,
  microsoft_oauth_enabled: microsoft,
});

describe('onlyOAuthProvider', () => {
  it('returns microsoft when it is the only way to sign in', () => {
    expect(onlyOAuthProvider(status(false, false, true))).toBe('microsoft');
  });

  it('returns google when it is the only way to sign in', () => {
    expect(onlyOAuthProvider(status(false, true, false))).toBe('google');
  });

  it('returns null when email login is on as well', () => {
    expect(onlyOAuthProvider(status(true, false, true))).toBeNull();
  });

  it('returns null when both providers are on', () => {
    expect(onlyOAuthProvider(status(false, true, true))).toBeNull();
  });

  it('returns null when no provider is on', () => {
    expect(onlyOAuthProvider(status(false, false, false))).toBeNull();
  });
});

describe('pauseAutoSignIn / pickAccountNextTime / resumeAutoSignIn', () => {
  beforeEach(() => window.sessionStorage.clear());

  it('goes without asking in a fresh tab', () => {
    expect(autoSignInPaused()).toBe(false);
    expect(accountPickRequested()).toBe(false);
  });

  it('stays paused until resumed', () => {
    pauseAutoSignIn();
    expect(autoSignInPaused()).toBe(true);
    expect(accountPickRequested()).toBe(false);
    resumeAutoSignIn();
    expect(autoSignInPaused()).toBe(false);
  });

  it('asks for the account picker, without pausing, until resumed', () => {
    pickAccountNextTime();
    expect(accountPickRequested()).toBe(true);
    expect(autoSignInPaused()).toBe(false);
    resumeAutoSignIn();
    expect(accountPickRequested()).toBe(false);
  });

  it('pauses instead of asking once a trip has started', () => {
    pickAccountNextTime();
    pauseAutoSignIn();
    expect(autoSignInPaused()).toBe(true);
    expect(accountPickRequested()).toBe(false);
  });
});

describe('startOAuthSignIn', () => {
  const originalLocation = window.location;
  let assignedHref = '';

  beforeEach(() => {
    assignedHref = '';
    delete (window as unknown as { location?: Location }).location;
    (window as unknown as { location: Partial<Location> }).location = {
      pathname: '/search',
      search: '?q=school+meals',
      get href() {
        return assignedHref;
      },
      set href(value: string) {
        assignedHref = value;
      },
    } as Location;
  });

  afterEach(() => {
    (window as unknown as { location: Location }).location = originalLocation;
    jest.restoreAllMocks();
  });

  const mockFetch = (ok: boolean, httpStatus: number, body: object) => {
    global.fetch = jest.fn().mockResolvedValue({
      ok,
      status: httpStatus,
      json: () => Promise.resolve(body),
    }) as unknown as typeof fetch;
  };

  it('goes to the address the backend gives, asking to come back to this page', async () => {
    mockFetch(true, 200, { authorization_url: MICROSOFT_PAGE });

    await startOAuthSignIn('microsoft');

    const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
    expect(calledUrl).toContain('/auth/microsoft/authorize');
    expect(calledUrl).toContain('return_to=' + encodeURIComponent('/search?q=school+meals'));
    expect(calledUrl).not.toContain('prompt=');
    expect(assignedHref).toBe(MICROSOFT_PAGE);
  });

  it('asks the provider for its account picker when told to', async () => {
    mockFetch(true, 200, { authorization_url: MICROSOFT_PAGE });

    await startOAuthSignIn('microsoft', { pickAccount: true });

    const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
    expect(calledUrl).toContain('/auth/microsoft/authorize?return_to=');
    expect(calledUrl).toContain('&prompt=select_account');
    expect(assignedHref).toBe(MICROSOFT_PAGE);
  });

  it('waits for the sign-out request before it leaves the page', async () => {
    mockFetch(true, 200, { authorization_url: MICROSOFT_PAGE });
    let finishSignOut: () => void = () => {};
    holdSignInUntilSignedOut(new Promise<void>((resolve) => { finishSignOut = resolve; }));

    const trip = startOAuthSignIn('microsoft', { pickAccount: true });
    await Promise.resolve();
    await Promise.resolve();
    expect(global.fetch).not.toHaveBeenCalled();
    expect(assignedHref).toBe('');

    finishSignOut();
    await trip;
    expect(assignedHref).toBe(MICROSOFT_PAGE);
  });

  it('still goes when the sign-out request fails', async () => {
    mockFetch(true, 200, { authorization_url: MICROSOFT_PAGE });
    holdSignInUntilSignedOut(Promise.reject(new Error('network down')));

    await startOAuthSignIn('microsoft');

    expect(assignedHref).toBe(MICROSOFT_PAGE);
  });

  it('throws, naming the provider, when the backend refuses', async () => {
    mockFetch(false, 500, { detail: 'boom' });

    await expect(startOAuthSignIn('google')).rejects.toThrow(
      'Could not start Google sign-in (HTTP 500)',
    );
    expect(assignedHref).toBe('');
  });

  it('throws, and goes nowhere, when the address is not the provider\'s', async () => {
    mockFetch(true, 200, { authorization_url: 'https://evil.example/authorize' });

    await expect(startOAuthSignIn('microsoft')).rejects.toThrow(
      "the sign-in address is not Microsoft's",
    );
    expect(assignedHref).toBe('');
  });

  it('throws when the backend gives no sign-in address', async () => {
    mockFetch(true, 200, {});

    await expect(startOAuthSignIn('microsoft')).rejects.toThrow(
      'Could not start Microsoft sign-in (HTTP 200)',
    );
    expect(assignedHref).toBe('');
  });
});

describe('checkedSignInAddress', () => {
  it.each([
    ['microsoft', MICROSOFT_PAGE],
    ['google', 'https://accounts.google.com/o/oauth2/v2/auth?client_id=test-client'],
  ] as const)('accepts %s\'s own sign-in page', (provider, address) => {
    expect(checkedSignInAddress(provider, address)).toBe(address);
  });

  it.each([
    ['another site', 'https://evil.example/authorize'],
    ['plain http', 'http://login.microsoftonline.com/common/oauth2/v2.0/authorize'],
    ['a javascript: address', SCRIPT_ADDRESS],
    ['a data: address', 'data:text/html,<script>alert(1)</script>'],
    ['a look-alike host', 'https://login.microsoftonline.com.evil.example/authorize'],
    ['a user-name trick', 'https://login.microsoftonline.com@evil.example/authorize'],
    ['another port', 'https://login.microsoftonline.com:8443/common/oauth2/v2.0/authorize'],
    ['the other provider', 'https://accounts.google.com/o/oauth2/v2/auth'],
    ['a relative path', '/auth/callback'],
    ['not a string', 42],
    ['nothing', undefined],
  ])('refuses %s', (_label, address) => {
    expect(() => checkedSignInAddress('microsoft', address)).toThrow(
      "the sign-in address is not Microsoft's",
    );
  });
});
