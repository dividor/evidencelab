import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';
import { AuthGate } from './AuthGate';
import { AuthContext } from '../../hooks/useAuth';
import { pauseAutoSignIn } from '../../utils/oauthSignIn';
import type { AuthContextValue } from '../../types/auth';

// babel-jest hoists these above the imports.
jest.mock('axios');
jest.mock('../../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: '',
  USER_MODULE: true,
  USER_MODULE_MODE: 'on_active',
}));

const PROVIDER_PAGE =
  'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=test-client';

const mockedAxios = axios as jest.Mocked<typeof axios>;

const signedOut = (overrides: Partial<AuthContextValue> = {}): AuthContextValue => ({
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

const renderGate = (auth: AuthContextValue) =>
  render(
    <AuthContext.Provider value={auth}>
      <AuthGate>
        <div>the app</div>
      </AuthGate>
    </AuthContext.Provider>,
  );

describe('AuthGate with Microsoft as the only way to sign in', () => {
  const originalLocation = window.location;
  let assignedHref = '';

  const setSearch = (search: string) => {
    (window.location as unknown as { search: string }).search = search;
  };

  beforeEach(() => {
    assignedHref = '';
    window.sessionStorage.clear();
    delete (window as unknown as { location?: Location }).location;
    (window as unknown as { location: Partial<Location> }).location = {
      pathname: '/',
      search: '',
      get href() {
        return assignedHref;
      },
      set href(value: string) {
        assignedHref = value;
      },
    } as Location;
    mockedAxios.get.mockResolvedValue({
      data: {
        email_login_disabled: true,
        google_oauth_enabled: false,
        microsoft_oauth_enabled: true,
      },
    });
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ authorization_url: PROVIDER_PAGE }),
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    (window as unknown as { location: Location }).location = originalLocation;
  });

  it('goes straight to Microsoft for someone who is not signed in', async () => {
    renderGate(signedOut());

    await waitFor(() => expect(assignedHref).toBe(PROVIDER_PAGE));
    expect(screen.queryByText('the app')).not.toBeInTheDocument();
  });

  it('shows nothing, not the app, while it checks whether someone is signed in', () => {
    const { container } = renderGate(signedOut({ isLoading: true }));

    expect(container).toBeEmptyDOMElement();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows the button after a session times out', async () => {
    renderGate(signedOut({ sessionExpired: true }));

    expect(await screen.findByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows the button after someone signed out or a trip came back signed out', async () => {
    pauseAutoSignIn();
    renderGate(signedOut());

    expect(await screen.findByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('goes straight to Microsoft to approve an MCP client', async () => {
    setSearch('?mcp_auth=pending-123');
    renderGate(signedOut());

    await waitFor(() => expect(assignedHref).toBe(PROVIDER_PAGE));
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain(
      'return_to=' + encodeURIComponent('/?mcp_auth=pending-123'),
    );
  });

  it('shows the button to approve an MCP client when paused', async () => {
    setSearch('?mcp_auth=pending-123');
    pauseAutoSignIn();
    renderGate(signedOut());

    expect(await screen.findByText(/Sign in with Microsoft/)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows the app to someone signed in', () => {
    renderGate(signedOut({
      isAuthenticated: true,
      user: {
        id: '1', email: 'a@b.com', first_name: null, last_name: null, display_name: null,
        is_active: true, is_verified: true, is_superuser: false,
        created_at: null, updated_at: null,
      } as unknown as AuthContextValue['user'],
    }));

    expect(screen.getByText('the app')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
