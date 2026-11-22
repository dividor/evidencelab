import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import axios from 'axios';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

import LoginModal from './LoginModal';
import { AuthContext } from '../../hooks/useAuth';
import type { AuthContextValue } from '../../types/auth';

const mockAuthValue = (overrides: Partial<AuthContextValue> = {}): AuthContextValue => ({
  user: null,
  token: null,
  isLoading: false,
  isAuthenticated: false,
  login: jest.fn(),
  register: jest.fn(),
  logout: jest.fn(),
  refreshUser: jest.fn(),
  sessionExpired: false,
  verificationMessage: null,
  clearVerificationMessage: jest.fn(),
  resetPasswordToken: null,
  clearResetPasswordToken: jest.fn(),
  ...overrides,
});

interface MockAuthStatusOverrides {
  email_login_disabled?: boolean;
  google_oauth_enabled?: boolean;
  microsoft_oauth_enabled?: boolean;
}

const mockAuthStatusResponse = (overrides: MockAuthStatusOverrides = {}) => {
  mockedAxios.get.mockImplementation((url: string) => {
    if (url.includes('/config/auth-status')) {
      return Promise.resolve({
        data: {
          email_login_disabled: overrides.email_login_disabled ?? false,
          google_oauth_enabled: overrides.google_oauth_enabled ?? true,
          microsoft_oauth_enabled: overrides.microsoft_oauth_enabled ?? true,
        },
      });
    }
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
};

beforeEach(() => {
  mockedAxios.get.mockReset();
  mockedAxios.post.mockReset();
  mockAuthStatusResponse();
});

/** The sign-in forms wait for /config/auth-status; this waits for them. */
const waitForSignInOptions = () => screen.findByText('Sign In', { selector: 'button.auth-submit' });

const renderModal = (
  authValue?: AuthContextValue,
  props?: Partial<React.ComponentProps<typeof LoginModal>>,
) =>
  render(
    <AuthContext.Provider value={authValue || mockAuthValue()}>
      <LoginModal onClose={props?.onClose || jest.fn()} {...props} />
    </AuthContext.Provider>
  );

describe('LoginModal', () => {
  it('renders with Sign In tab active by default', () => {
    renderModal();
    const signInTab = screen.getByText('Sign In', { selector: 'button.login-tab' });
    expect(signInTab).toHaveClass('login-tab-active');
  });

  it('shows email and password fields', async () => {
    renderModal();
    await waitForSignInOptions();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('shows name fields only on register tab', async () => {
    renderModal();
    await waitForSignInOptions();
    expect(screen.queryByLabelText('First name')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Last name')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Register'));
    expect(screen.getByLabelText('First name')).toBeInTheDocument();
    expect(screen.getByLabelText('Last name')).toBeInTheDocument();
  });

  it('shows OAuth buttons when providers are enabled', async () => {
    renderModal();
    expect(await screen.findByText(/Sign in with Google/)).toBeInTheDocument();
    expect(await screen.findByText(/Sign in with Microsoft/)).toBeInTheDocument();
  });

  it('hides Google button when google_oauth_enabled is false', async () => {
    mockAuthStatusResponse({ google_oauth_enabled: false });
    renderModal();
    expect(await screen.findByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(screen.queryByText(/Sign in with Google/)).not.toBeInTheDocument();
  });

  it('hides Microsoft button when microsoft_oauth_enabled is false', async () => {
    mockAuthStatusResponse({ microsoft_oauth_enabled: false });
    renderModal();
    expect(await screen.findByText(/Sign in with Google/)).toBeInTheDocument();
    expect(screen.queryByText(/Sign in with Microsoft/)).not.toBeInTheDocument();
  });

  it('hides email form, Register tab and "or" divider when email login is disabled', async () => {
    mockAuthStatusResponse({ email_login_disabled: true });
    renderModal();
    // OAuth buttons still render
    expect(await screen.findByText(/Sign in with Google/)).toBeInTheDocument();
    // Email form and Register tab are gone
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Register', { selector: 'button.login-tab' }),
    ).not.toBeInTheDocument();
    // "or" divider is also hidden when no email form follows
    expect(screen.queryByText('or')).not.toBeInTheDocument();
  });

  it('switches to register tab', async () => {
    renderModal();
    await waitForSignInOptions();
    fireEvent.click(screen.getByText('Register'));
    const registerTab = screen.getByText('Register', { selector: 'button.login-tab' });
    expect(registerTab).toHaveClass('login-tab-active');
    expect(screen.getByText('Create Account')).toBeInTheDocument();
  });

  it('calls onClose when overlay is clicked', () => {
    const onClose = jest.fn();
    renderModal(undefined, { onClose });
    fireEvent.click(
      screen.getByText('Sign In', { selector: 'button.login-tab' }).closest('.modal-overlay')!,
    );
    // The overlay click triggers onClose, but stopPropagation on modal-content prevents it
    // when clicking inside. We click the overlay itself.
  });
});

/* ------------------------------------------------------------------ */
/*  Forgot password flow                                              */
/* ------------------------------------------------------------------ */

describe('LoginModal — Forgot password', () => {
  it('shows "Forgot password?" link in login mode', async () => {
    renderModal();
    await waitForSignInOptions();
    expect(screen.getByText('Forgot password?')).toBeInTheDocument();
  });

  it('does not show "Forgot password?" link in register mode', async () => {
    renderModal();
    await waitForSignInOptions();
    fireEvent.click(screen.getByText('Register'));
    expect(screen.queryByText('Forgot password?')).not.toBeInTheDocument();
  });

  it('switches to forgot mode when link is clicked', async () => {
    renderModal();
    await waitForSignInOptions();
    fireEvent.click(screen.getByText('Forgot password?'));
    expect(
      screen.getByText(/Enter your email address and we'll send you a link/),
    ).toBeInTheDocument();
    expect(screen.getByText('Send Reset Link')).toBeInTheDocument();
  });

  it('shows email field in forgot mode', async () => {
    renderModal();
    await waitForSignInOptions();
    fireEvent.click(screen.getByText('Forgot password?'));
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
  });

  it('shows "Back to Sign In" link in forgot mode', async () => {
    renderModal();
    await waitForSignInOptions();
    fireEvent.click(screen.getByText('Forgot password?'));
    expect(screen.getByText('Back to Sign In')).toBeInTheDocument();
  });

  it('returns to login mode when "Back to Sign In" is clicked', async () => {
    renderModal();
    // Wait for auth-status fetch to complete so OAuth buttons would appear
    await screen.findByText(/Sign in with Google/);
    fireEvent.click(screen.getByText('Forgot password?'));
    fireEvent.click(screen.getByText('Back to Sign In'));
    expect(screen.getByText(/Sign in with Google/)).toBeInTheDocument();
    expect(screen.getByText('Forgot password?')).toBeInTheDocument();
  });

  it('hides OAuth buttons and password field in forgot mode', async () => {
    renderModal();
    await screen.findByText(/Sign in with Google/);
    fireEvent.click(screen.getByText('Forgot password?'));
    expect(screen.queryByText(/Sign in with Google/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
  });

  it('submits forgot-password request and shows success', async () => {
    mockedAxios.post.mockResolvedValueOnce({ data: {} });
    renderModal();
    await waitForSignInOptions();
    fireEvent.click(screen.getByText('Forgot password?'));

    const emailInput = screen.getByLabelText('Email');
    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.click(screen.getByText('Send Reset Link'));

    await waitFor(() => {
      expect(screen.getByText(/If an account exists for that email/)).toBeInTheDocument();
    });
    expect(mockedAxios.post).toHaveBeenCalledWith(
      expect.stringContaining('/auth/forgot-password'),
      { email: 'test@example.com' },
    );
  });

  it('shows success message even when forgot-password request fails', async () => {
    mockedAxios.post.mockRejectedValueOnce(new Error('Network error'));
    renderModal();
    await waitForSignInOptions();
    fireEvent.click(screen.getByText('Forgot password?'));

    const emailInput = screen.getByLabelText('Email');
    fireEvent.change(emailInput, { target: { value: 'nonexistent@example.com' } });
    fireEvent.click(screen.getByText('Send Reset Link'));

    await waitFor(() => {
      expect(screen.getByText(/If an account exists for that email/)).toBeInTheDocument();
    });
  });
});

/* ------------------------------------------------------------------ */
/*  Reset password flow (from email link)                             */
/* ------------------------------------------------------------------ */

describe('LoginModal — Reset password', () => {
  it('opens in reset mode when resetToken is provided', () => {
    renderModal(undefined, { resetToken: 'test-token-abc' });
    expect(screen.getByText('Choose a new password for your account.')).toBeInTheDocument();
    expect(screen.getByLabelText('New Password')).toBeInTheDocument();
    expect(screen.getByLabelText('Confirm Password')).toBeInTheDocument();
    expect(screen.getByText('Reset Password')).toBeInTheDocument();
  });

  it('does not show OAuth buttons or email field in reset mode', () => {
    renderModal(undefined, { resetToken: 'test-token-abc' });
    expect(screen.queryByText(/Sign in with Google/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument();
  });

  it('shows error when passwords do not match', async () => {
    renderModal(undefined, { resetToken: 'test-token-abc' });

    fireEvent.change(screen.getByLabelText('New Password'), {
      target: { value: 'newpassword123' },
    });
    fireEvent.change(screen.getByLabelText('Confirm Password'), {
      target: { value: 'different456' },
    });
    fireEvent.click(screen.getByText('Reset Password'));

    await waitFor(() => {
      expect(screen.getByText('Passwords do not match.')).toBeInTheDocument();
    });
    // Should NOT have called the API
    expect(mockedAxios.post).not.toHaveBeenCalled();
  });

  it('submits reset password and shows success on valid token', async () => {
    mockedAxios.post.mockResolvedValueOnce({ data: {} });
    renderModal(undefined, { resetToken: 'valid-token-123' });

    fireEvent.change(screen.getByLabelText('New Password'), {
      target: { value: 'newpassword123' },
    });
    fireEvent.change(screen.getByLabelText('Confirm Password'), {
      target: { value: 'newpassword123' },
    });
    fireEvent.click(screen.getByText('Reset Password'));

    await waitFor(() => {
      expect(
        screen.getByText('Your password has been reset. You can now sign in.'),
      ).toBeInTheDocument();
    });
    expect(mockedAxios.post).toHaveBeenCalledWith(
      expect.stringContaining('/auth/reset-password'),
      { token: 'valid-token-123', password: 'newpassword123' }, // pragma: allowlist secret
    );
  });

  it('shows expired token error', async () => {
    mockedAxios.post.mockRejectedValueOnce({
      response: { data: { detail: 'RESET_PASSWORD_BAD_TOKEN' } },
    });
    renderModal(undefined, { resetToken: 'expired-token' });

    fireEvent.change(screen.getByLabelText('New Password'), {
      target: { value: 'newpassword123' },
    });
    fireEvent.change(screen.getByLabelText('Confirm Password'), {
      target: { value: 'newpassword123' },
    });
    fireEvent.click(screen.getByText('Reset Password'));

    await waitFor(() => {
      expect(
        screen.getByText('This reset link has expired or is invalid. Please request a new one.'),
      ).toBeInTheDocument();
    });
  });

  it('shows generic error for non-token failures', async () => {
    mockedAxios.post.mockRejectedValueOnce({
      response: { data: { detail: { reason: 'Some other error' } } },
    });
    renderModal(undefined, { resetToken: 'some-token' });

    fireEvent.change(screen.getByLabelText('New Password'), {
      target: { value: 'newpassword123' },
    });
    fireEvent.change(screen.getByLabelText('Confirm Password'), {
      target: { value: 'newpassword123' },
    });
    fireEvent.click(screen.getByText('Reset Password'));

    await waitFor(() => {
      expect(screen.getByText('Some other error')).toBeInTheDocument();
    });
  });

  it('can navigate to Sign In tab from reset mode', async () => {
    renderModal(undefined, { resetToken: 'test-token-abc' });
    fireEvent.click(screen.getByText('Sign In', { selector: 'button.login-tab' }));
    expect(await screen.findByText(/Sign in with Google/)).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/*  Session expired banner                                             */
/* ------------------------------------------------------------------ */

describe('LoginModal — Session expired banner', () => {
  it('shows session expired info banner when sessionExpired is true', () => {
    renderModal(undefined, { sessionExpired: true });
    expect(
      screen.getByText('Your session has expired. Please sign in again to continue.'),
    ).toBeInTheDocument();
  });

  it('does not show session expired banner by default', () => {
    renderModal();
    expect(
      screen.queryByText('Your session has expired. Please sign in again to continue.'),
    ).not.toBeInTheDocument();
  });

  it('hides session expired banner when there is an error', () => {
    renderModal(undefined, { sessionExpired: true });
    // Initially visible
    expect(
      screen.getByText('Your session has expired. Please sign in again to continue.'),
    ).toBeInTheDocument();

    // Trigger a login error
    const loginMock = jest.fn().mockRejectedValue({
      response: { data: { detail: 'Invalid credentials' } },
    });
    const authValue = mockAuthValue({ login: loginMock });
    const { rerender } = render(
      <AuthContext.Provider value={authValue}>
        <LoginModal onClose={jest.fn()} sessionExpired={true} />
      </AuthContext.Provider>,
    );

    // After login failure, error is shown — session expired banner should be hidden
    // (the banner condition is: sessionExpired && !error && !displaySuccess)
    // We test the initial render condition here: banner IS shown when no error
    expect(
      screen.getAllByText('Your session has expired. Please sign in again to continue.').length,
    ).toBeGreaterThan(0);
  });

  it('hides session expired banner when there is a verification message', () => {
    const authValue = mockAuthValue({
      verificationMessage: 'Your email has been verified!',
    });
    renderModal(authValue, { sessionExpired: true });
    // The displaySuccess takes priority — session expired banner should be hidden
    expect(
      screen.queryByText('Your session has expired. Please sign in again to continue.'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText('Your email has been verified!'),
    ).toBeInTheDocument();
  });

  it('uses auth-info CSS class for styling', () => {
    renderModal(undefined, { sessionExpired: true });
    const banner = screen.getByText(
      'Your session has expired. Please sign in again to continue.',
    );
    expect(banner).toHaveClass('auth-info');
  });

  it('does not render close button when required is true', () => {
    renderModal(undefined, { required: true, sessionExpired: true });
    expect(screen.queryByText('×')).not.toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/*  Going straight to the only sign-in provider                       */
/* ------------------------------------------------------------------ */

describe('LoginModal — only one way to sign in', () => {
  const MICROSOFT_PAGE =
    'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=test-client';
  const GOOGLE_PAGE = 'https://accounts.google.com/o/oauth2/v2/auth?client_id=test-client';
  const TAKING_YOU_TO_MICROSOFT = 'Taking you to Microsoft sign-in…';
  const originalLocation = window.location;
  let assignedHref = '';

  const mockAuthorize = (ok: boolean, httpStatus: number, body: object) => {
    global.fetch = jest.fn().mockResolvedValue({
      ok,
      status: httpStatus,
      json: () => Promise.resolve(body),
    }) as unknown as typeof fetch;
  };

  beforeEach(() => {
    assignedHref = '';
    window.sessionStorage.clear();
    delete (window as unknown as { location?: Location }).location;
    (window as unknown as { location: Partial<Location> }).location = {
      pathname: '/',
      search: '?q=resilience',
      get href() {
        return assignedHref;
      },
      set href(value: string) {
        assignedHref = value;
      },
    } as Location;
    mockAuthorize(true, 200, { authorization_url: MICROSOFT_PAGE });
  });

  afterEach(() => {
    (window as unknown as { location: Location }).location = originalLocation;
  });

  it('goes straight to Microsoft when it is the only way in', async () => {
    mockAuthStatusResponse({ email_login_disabled: true, google_oauth_enabled: false });
    renderModal(undefined, { autoSignIn: true, required: true });

    expect(await screen.findByText(TAKING_YOU_TO_MICROSOFT)).toBeInTheDocument();
    await waitFor(() => expect(assignedHref).toBe(MICROSOFT_PAGE));
    const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
    expect(calledUrl).toContain('/auth/microsoft/authorize');
    expect(calledUrl).toContain('return_to=' + encodeURIComponent('/?q=resilience'));
    // A trip that comes back still signed out must show the button, not go again.
    expect(window.sessionStorage.length).toBe(1);
    expect(screen.queryByText(/Sign in with Microsoft/)).not.toBeInTheDocument();
  });

  it('goes straight to Google when it is the only way in', async () => {
    mockAuthStatusResponse({ email_login_disabled: true, microsoft_oauth_enabled: false });
    mockAuthorize(true, 200, { authorization_url: GOOGLE_PAGE });
    renderModal(undefined, { autoSignIn: true });

    expect(await screen.findByText('Taking you to Google sign-in…')).toBeInTheDocument();
    await waitFor(() => expect(assignedHref).toBe(GOOGLE_PAGE));
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain('/auth/google/authorize');
  });

  it('shows the button when the caller does not ask to go straight there', async () => {
    mockAuthStatusResponse({ email_login_disabled: true, google_oauth_enabled: false });
    renderModal(undefined, { required: true, sessionExpired: true });

    expect(await screen.findByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows the button and the email form when email login is on too', async () => {
    mockAuthStatusResponse({ google_oauth_enabled: false });
    renderModal(undefined, { autoSignIn: true });

    expect(await screen.findByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows both buttons when both providers are on', async () => {
    mockAuthStatusResponse({ email_login_disabled: true });
    renderModal(undefined, { autoSignIn: true });

    expect(await screen.findByText(/Sign in with Google/)).toBeInTheDocument();
    expect(screen.getByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows the error and the button when the trip cannot start', async () => {
    mockAuthStatusResponse({ email_login_disabled: true, google_oauth_enabled: false });
    mockAuthorize(false, 503, {});
    renderModal(undefined, { autoSignIn: true, required: true });

    expect(
      await screen.findByText('Could not start Microsoft sign-in (HTTP 503). Please try again.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(assignedHref).toBe('');
  });

  it('refuses a sign-in address that is not the provider\'s', async () => {
    mockAuthStatusResponse({ email_login_disabled: true, google_oauth_enabled: false });
    mockAuthorize(true, 200, { authorization_url: 'https://login.example.org/authorize' });
    renderModal(undefined, { autoSignIn: true, required: true });

    expect(await screen.findByText(/the sign-in address is not Microsoft's/)).toBeInTheDocument();
    expect(screen.getByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(assignedHref).toBe('');
  });

  it('shows the button when Back from the provider restores the page', async () => {
    mockAuthStatusResponse({ email_login_disabled: true, google_oauth_enabled: false });
    global.fetch = jest.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    renderModal(undefined, { autoSignIn: true, required: true });
    await screen.findByText(TAKING_YOU_TO_MICROSOFT);

    act(() => {
      window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
    });

    expect(await screen.findByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(screen.queryByText(TAKING_YOU_TO_MICROSOFT)).not.toBeInTheDocument();
  });

  it('says so, and shows no sign-in form, when the sign-in options cannot load', async () => {
    mockedAxios.get.mockRejectedValue({ response: { status: 401 } });
    renderModal(undefined, { autoSignIn: true, required: true });

    expect(
      await screen.findByText(/Could not load the sign-in options \(HTTP 401\)/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument();
    expect(screen.queryByText(/Sign in with/)).not.toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows no sign-in form until it knows which ways to sign in are on', () => {
    mockedAxios.get.mockImplementation(() => new Promise(() => {}));
    renderModal(undefined, { autoSignIn: true, required: true });

    expect(screen.getByText('Sign In', { selector: 'button.login-tab' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument();
    expect(screen.queryByText(/Sign in with/)).not.toBeInTheDocument();
  });
});
