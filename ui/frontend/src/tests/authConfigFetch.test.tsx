/**
 * Tests for the auth-aware config fetch pattern used in App.tsx.
 *
 * When USER_MODULE is enabled, config endpoints (/config/datasources,
 * /config/model-combos) are protected by ActiveAuthMiddleware.  The fetch
 * useEffects must wait until the user is authenticated before firing,
 * otherwise the requests are rejected with 401.
 *
 * This test uses a lightweight harness that mirrors the exact guard used
 * in App.tsx (`if (USER_MODULE && !authState.isAuthenticated) return;`)
 * instead of rendering the full App tree.
 */
import React, { useEffect, useState } from 'react';
import { render, screen, act } from '@testing-library/react';
import axios from 'axios';

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/*  Test harness                                                       */
/* ------------------------------------------------------------------ */

/**
 * Mirrors the auth-guarded fetch pattern from App.tsx:
 *
 *   useEffect(() => {
 *     if (userModuleOn && !isAuthenticated) return;
 *     fetchConfig();
 *   }, [isAuthenticated]);
 */
interface HarnessProps {
  userModuleOn: boolean;
  isAuthenticated: boolean;
}

const ConfigFetchHarness: React.FC<HarnessProps> = ({
  userModuleOn,
  isAuthenticated,
}) => {
  const [fetched, setFetched] = useState(false);

  useEffect(() => {
    if (userModuleOn && !isAuthenticated) return;
    axios.get('/api/config/datasources').then(() => setFetched(true));
  }, [isAuthenticated, userModuleOn]);

  return <div data-testid="fetched">{String(fetched)}</div>;
};

const flushPromises = () => act(async () => {});

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('Auth-guarded config fetch pattern', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (axios.get as jest.Mock).mockResolvedValue({ data: { testDs: {} } });
  });

  it('does NOT fetch config when USER_MODULE is on and user is unauthenticated', async () => {
    render(<ConfigFetchHarness userModuleOn={true} isAuthenticated={false} />);
    await flushPromises();

    expect(axios.get).not.toHaveBeenCalled();
    expect(screen.getByTestId('fetched').textContent).toBe('false');
  });

  it('fetches config when USER_MODULE is on and user IS authenticated', async () => {
    render(<ConfigFetchHarness userModuleOn={true} isAuthenticated={true} />);
    await flushPromises();

    expect(axios.get).toHaveBeenCalledWith('/api/config/datasources');
    expect(screen.getByTestId('fetched').textContent).toBe('true');
  });

  it('fetches config immediately when USER_MODULE is off (no auth needed)', async () => {
    render(<ConfigFetchHarness userModuleOn={false} isAuthenticated={false} />);
    await flushPromises();

    expect(axios.get).toHaveBeenCalledWith('/api/config/datasources');
    expect(screen.getByTestId('fetched').textContent).toBe('true');
  });

  it('fetches config after authentication state changes from false to true', async () => {
    const { rerender } = render(
      <ConfigFetchHarness userModuleOn={true} isAuthenticated={false} />
    );
    await flushPromises();

    // Not yet authenticated — no fetch
    expect(axios.get).not.toHaveBeenCalled();

    // User logs in — isAuthenticated becomes true
    rerender(<ConfigFetchHarness userModuleOn={true} isAuthenticated={true} />);
    await flushPromises();

    expect(axios.get).toHaveBeenCalledWith('/api/config/datasources');
    expect(screen.getByTestId('fetched').textContent).toBe('true');
  });

  it('does NOT re-fetch when isAuthenticated stays true across re-renders', async () => {
    const { rerender } = render(
      <ConfigFetchHarness userModuleOn={true} isAuthenticated={true} />
    );
    await flushPromises();

    expect(axios.get).toHaveBeenCalledTimes(1);

    // Re-render with same props — should not trigger a second fetch
    rerender(<ConfigFetchHarness userModuleOn={true} isAuthenticated={true} />);
    await flushPromises();

    expect(axios.get).toHaveBeenCalledTimes(1);
  });
});
