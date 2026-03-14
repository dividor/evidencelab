/**
 * Tests for auth session management:
 * - 401 response interceptor (retry queue, session expired state)
 * - Inactivity timeout
 * - login/logout session state transitions
 */
import React from 'react';
import { render, screen, act } from '@testing-library/react';
import axios from 'axios';

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// Capture interceptor handlers so we can invoke them in tests.
let responseSuccessHandler: (r: any) => any;
let responseErrorHandler: (e: any) => any;

jest.mock('axios', () => {
  const actualAxios = jest.requireActual('axios');
  const mockAxios: any = jest.fn((config: any) => Promise.resolve({ data: {} }));
  mockAxios.get = jest.fn(() => Promise.resolve({ data: {} }));
  mockAxios.post = jest.fn(() => Promise.resolve({ data: {} }));
  mockAxios.defaults = { withCredentials: false };
  mockAxios.interceptors = {
    request: { use: jest.fn() },
    response: {
      use: jest.fn(),
      eject: jest.fn(),
    },
  };
  mockAxios.isCancel = actualAxios.isCancel;
  mockAxios.CancelToken = actualAxios.CancelToken;
  return {
    __esModule: true,
    default: mockAxios,
  };
});

// Enable the user module so inactivity-timeout logic is reachable.
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  USER_MODULE: true,
  USER_MODULE_MODE: 'on_active',
  APP_BASE_PATH: '',
  PDF_SEMANTIC_HIGHLIGHTS: false,
  SEARCH_SEMANTIC_HIGHLIGHTS: false,
  SEMANTIC_HIGHLIGHT_THRESHOLD: 0.4,
  AI_SUMMARY_ON: false,
  SEARCH_RESULTS_PAGE_SIZE: '50',
  HEATMAP_CELL_LIMIT: '1000',
  USER_FEEDBACK: false,
  GA_MEASUREMENT_ID: undefined,
}));

// Must import AFTER mocking axios
import { useAuthState, AuthContext } from '../hooks/useAuth';
import type { AuthContextValue } from '../types/auth';

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

let latestAuth: AuthContextValue;

const AuthTestHarness: React.FC = () => {
  const auth = useAuthState();
  latestAuth = auth;
  return (
    <AuthContext.Provider value={auth}>
      <div data-testid="authenticated">{String(auth.isAuthenticated)}</div>
      <div data-testid="session-expired">{String(auth.sessionExpired)}</div>
      <div data-testid="loading">{String(auth.isLoading)}</div>
    </AuthContext.Provider>
  );
};

const mockUser = {
  id: '1', email: 'a@b.com', first_name: null, last_name: null, display_name: null,
  is_active: true, is_verified: true, is_superuser: false,
  created_at: null, updated_at: null,
};

/** Flush all pending promises and state updates. */
const flushPromises = () => act(async () => {});

/**
 * Re-apply the mock implementation for axios.interceptors.response.use
 * so it captures the handlers registered by useAuthState's useEffect.
 * Must be called in every beforeEach because jest.clearAllMocks()
 * removes implementations set inside jest.mock() factories.
 */
function setupInterceptorMock() {
  (axios.interceptors.response.use as jest.Mock).mockImplementation(
    (success: any, error: any) => {
      responseSuccessHandler = success;
      responseErrorHandler = error;
      return 42; // interceptor id
    }
  );
}

/* ------------------------------------------------------------------ */
/*  Tests — 401 interceptor                                            */
/* ------------------------------------------------------------------ */

describe('useAuthState — 401 interceptor', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupInterceptorMock();
    // Restore default mock implementations cleared by clearAllMocks
    (axios.get as jest.Mock).mockResolvedValue({ data: {} });
    (axios.post as jest.Mock).mockResolvedValue({ data: {} });
  });

  it('registers a response interceptor on mount', async () => {
    render(<AuthTestHarness />);
    await flushPromises();
    expect(axios.interceptors.response.use).toHaveBeenCalledWith(
      expect.any(Function),
      expect.any(Function),
    );
  });

  it('ejects the interceptor on unmount', async () => {
    const { unmount } = render(<AuthTestHarness />);
    await flushPromises();
    unmount();
    expect(axios.interceptors.response.eject).toHaveBeenCalledWith(42);
  });

  it('passes through successful responses', async () => {
    render(<AuthTestHarness />);
    await flushPromises();
    const mockResponse = { data: { ok: true }, status: 200 };
    expect(responseSuccessHandler(mockResponse)).toBe(mockResponse);
  });

  it('rejects non-401 errors normally', async () => {
    render(<AuthTestHarness />);
    await flushPromises();
    const error = {
      config: { url: '/api/search' },
      response: { status: 500 },
    };
    await expect(responseErrorHandler(error)).rejects.toBe(error);
  });

  it('rejects 401 from /auth/ endpoints without intercepting', async () => {
    render(<AuthTestHarness />);
    await flushPromises();
    const error = {
      config: { url: '/api/auth/cookie-login/login' },
      response: { status: 401 },
    };
    await expect(responseErrorHandler(error)).rejects.toBe(error);
  });

  it('rejects 401 from /users/me without intercepting', async () => {
    render(<AuthTestHarness />);
    await flushPromises();
    const error = {
      config: { url: '/api/users/me' },
      response: { status: 401 },
    };
    await expect(responseErrorHandler(error)).rejects.toBe(error);
  });

  it('does not set sessionExpired for unauthenticated users (first visit)', async () => {
    // Start unauthenticated — refreshUser call on mount should fail
    (axios.get as jest.Mock).mockRejectedValueOnce(new Error('Not authenticated'));

    render(<AuthTestHarness />);
    await flushPromises();

    // Simulate a 401 on a data endpoint while user has not yet logged in
    const error = {
      config: { url: '/api/config/datasources' },
      response: { status: 401 },
    };
    const interceptPromise = responseErrorHandler(error);

    // Allow login to succeed (re-mock axios.get for the /users/me call inside login)
    (axios.get as jest.Mock).mockResolvedValue({ data: mockUser });

    // Resolve the auth promise via login
    await act(async () => {
      await latestAuth.login({ username: 'test@test.com', password: 'pass1234' }); // pragma: allowlist secret
    });
    try { await interceptPromise; } catch { /* retry may fail in test env */ }

    // sessionExpired should remain false — user wasn't previously authenticated
    expect(screen.getByTestId('session-expired').textContent).toBe('false');
  });

  it('sets _authRetry flag to prevent infinite retry loops', async () => {
    render(<AuthTestHarness />);
    await flushPromises();

    const config = { url: '/api/config/datasources' };
    const error = { config, response: { status: 401 } };
    const interceptPromise = responseErrorHandler(error);

    expect((config as any)._authRetry).toBe(true);

    // Clean up: resolve auth promise
    await act(async () => {
      await latestAuth.login({ username: 'test@test.com', password: 'pass1234' }); // pragma: allowlist secret
    });
    try { await interceptPromise; } catch { /* ok */ }
  });

  it('does not retry if _authRetry is already set', async () => {
    render(<AuthTestHarness />);
    await flushPromises();

    const error = {
      config: { url: '/api/search', _authRetry: true },
      response: { status: 401 },
    };

    // Should reject immediately without waiting for auth
    await expect(responseErrorHandler(error)).rejects.toBe(error);
  });

  it('rejects errors with no config', async () => {
    render(<AuthTestHarness />);
    await flushPromises();
    const error = { response: { status: 401 } };
    await expect(responseErrorHandler(error)).rejects.toBe(error);
  });
});

/* ------------------------------------------------------------------ */
/*  Tests — Inactivity timeout                                         */
/* ------------------------------------------------------------------ */

describe('useAuthState — inactivity timeout', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupInterceptorMock();
    (axios.get as jest.Mock).mockResolvedValue({ data: mockUser });
    (axios.post as jest.Mock).mockResolvedValue({ data: {} });
  });

  it('does not expire session before 1 hour', async () => {
    jest.useFakeTimers();
    render(<AuthTestHarness />);
    await flushPromises();

    expect(screen.getByTestId('authenticated').textContent).toBe('true');

    // Advance 59 minutes
    act(() => { jest.advanceTimersByTime(59 * 60 * 1000); });

    expect(screen.getByTestId('authenticated').textContent).toBe('true');
    expect(screen.getByTestId('session-expired').textContent).toBe('false');
    jest.useRealTimers();
  });

  it('expires session after 1 hour of inactivity', async () => {
    jest.useFakeTimers();
    render(<AuthTestHarness />);
    await flushPromises();

    expect(screen.getByTestId('authenticated').textContent).toBe('true');

    // Advance past the 1-hour mark
    await act(async () => { jest.advanceTimersByTime(60 * 60 * 1000 + 100); });

    expect(screen.getByTestId('authenticated').textContent).toBe('false');
    expect(screen.getByTestId('session-expired').textContent).toBe('true');
    jest.useRealTimers();
  });

  it('resets the inactivity timer on user activity', async () => {
    jest.useFakeTimers();
    render(<AuthTestHarness />);
    await flushPromises();

    expect(screen.getByTestId('authenticated').textContent).toBe('true');

    // Advance 50 minutes
    act(() => { jest.advanceTimersByTime(50 * 60 * 1000); });

    // Simulate user activity — resets the timer
    act(() => { window.dispatchEvent(new MouseEvent('mousedown')); });

    // Advance another 50 minutes (100 min total, but 50 since last activity)
    act(() => { jest.advanceTimersByTime(50 * 60 * 1000); });

    // Should STILL be authenticated — timer was reset
    expect(screen.getByTestId('authenticated').textContent).toBe('true');
    expect(screen.getByTestId('session-expired').textContent).toBe('false');
    jest.useRealTimers();
  });

  it('calls logout endpoint on timeout', async () => {
    jest.useFakeTimers();
    render(<AuthTestHarness />);
    await flushPromises();

    expect(screen.getByTestId('authenticated').textContent).toBe('true');

    (axios.post as jest.Mock).mockClear();

    await act(async () => { jest.advanceTimersByTime(60 * 60 * 1000 + 100); });

    expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining('/auth/cookie-login/logout'),
    );
    jest.useRealTimers();
  });
});

/* ------------------------------------------------------------------ */
/*  Tests — login/logout session state                                 */
/* ------------------------------------------------------------------ */

describe('useAuthState — login/logout session state', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupInterceptorMock();
    (axios.get as jest.Mock).mockResolvedValue({ data: mockUser });
    (axios.post as jest.Mock).mockResolvedValue({ data: {} });
  });

  it('clears sessionExpired on login', async () => {
    render(<AuthTestHarness />);
    await flushPromises();

    await act(async () => {
      await latestAuth.login({ username: 'test@test.com', password: 'pass1234' }); // pragma: allowlist secret
    });

    expect(screen.getByTestId('session-expired').textContent).toBe('false');
    expect(screen.getByTestId('authenticated').textContent).toBe('true');
  });

  it('clears sessionExpired on logout', async () => {
    render(<AuthTestHarness />);
    await flushPromises();

    await act(async () => {
      await latestAuth.login({ username: 'test@test.com', password: 'pass1234' }); // pragma: allowlist secret
    });
    await act(async () => {
      await latestAuth.logout();
    });

    expect(screen.getByTestId('session-expired').textContent).toBe('false');
    expect(screen.getByTestId('authenticated').textContent).toBe('false');
  });
});
