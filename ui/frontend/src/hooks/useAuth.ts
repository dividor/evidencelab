import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import API_BASE_URL, { USER_MODULE } from '../config';
import type { AuthContextValue, AuthState, AuthUser, LoginCredentials, RegisterData } from '../types/auth';

/**
 * Auth uses httpOnly cookies (set by the backend) — the browser sends the
 * cookie automatically on every request.  No tokens are stored in
 * localStorage, eliminating XSS token-theft risk.
 *
 * `axios.defaults.withCredentials = true` tells axios to include cookies
 * on cross-origin requests.
 */
axios.defaults.withCredentials = true;

/**
 * CSRF protection — double-submit cookie pattern.
 * The backend sets a non-httpOnly `evidencelab_csrf` cookie.  We read it
 * and echo it back as the `X-CSRF-Token` header on every state-changing
 * request so the backend can verify the two match.
 */
axios.interceptors.request.use((config) => {
  const method = (config.method ?? '').toLowerCase();
  if (method !== 'get' && method !== 'head' && method !== 'options') {
    const match = document.cookie.match(/(?:^|;\s*)evidencelab_csrf=([^;]*)/);
    if (match && config.headers) {
      config.headers['X-CSRF-Token'] = decodeURIComponent(match[1]);
    }
  }
  return config;
});

const initialState: AuthState = {
  user: null,
  token: null,
  isLoading: true,
  isAuthenticated: false,
};

export const AuthContext = createContext<AuthContextValue>({
  ...initialState,
  login: async () => {},
  register: async () => {},
  logout: async () => {},
  refreshUser: async () => {},
  sessionExpired: false,
  verificationMessage: null,
  clearVerificationMessage: () => {},
  resetPasswordToken: null,
  clearResetPasswordToken: () => {},
});

/** Hook to access the auth context. */
export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

/** Inactivity timeout — 1 hour. */
const INACTIVITY_TIMEOUT_MS = 60 * 60 * 1000;

/** Custom hook that provides auth state management. Use inside AuthProvider. */
export function useAuthState(): AuthContextValue {
  const [state, setState] = useState<AuthState>(initialState);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [verificationMessage, setVerificationMessage] = useState<string | null>(null);
  const [resetPasswordToken, setResetPasswordToken] = useState<string | null>(null);

  // Track current auth state for use inside the interceptor closure
  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; }, [state]);

  // Promise-based coordination: when a 401 is caught, pending requests wait
  // on this promise until the user re-authenticates.
  const authPromiseRef = useRef<{
    promise: Promise<boolean>;
    resolve: (success: boolean) => void;
  } | null>(null);

  const getAuthPromise = useCallback((): Promise<boolean> => {
    if (!authPromiseRef.current) {
      let resolve!: (success: boolean) => void;
      const promise = new Promise<boolean>((r) => { resolve = r; });
      authPromiseRef.current = { promise, resolve };
    }
    return authPromiseRef.current.promise;
  }, []);

  // ---- 401 response interceptor ----------------------------------------
  // Catches 401 errors from data endpoints (not /auth/* or /users/me),
  // marks the session as expired, waits for re-authentication, then retries
  // the original request automatically.
  useEffect(() => {
    const interceptorId = axios.interceptors.response.use(
      (response) => response,
      async (error) => {
        const config = error.config;
        if (!config) return Promise.reject(error);

        const url: string = config.url || '';

        if (
          error.response?.status === 401 &&
          !url.includes('/auth/') &&
          !url.includes('/users/me') &&
          !(config as any)._authRetry
        ) {
          // Prevent infinite retry loops
          (config as any)._authRetry = true;

          // Only show "session expired" if user was previously authenticated
          // (not on initial visit before first login)
          if (stateRef.current.isAuthenticated) {
            setSessionExpired(true);
          }
          setState({
            user: null,
            token: null,
            isLoading: false,
            isAuthenticated: false,
          });

          // Wait for the user to re-authenticate via the login modal
          const success = await getAuthPromise();
          if (success) {
            // Cookie is now valid — retry the original request
            return axios(config);
          }
        }

        return Promise.reject(error);
      }
    );

    return () => {
      axios.interceptors.response.eject(interceptorId);
    };
  }, [getAuthPromise]);

  // ---- Inactivity timeout (1 hour) ------------------------------------
  // After 1 hour of no user interaction, expire the session and show the
  // login modal.  The server-side cookie is also cleared (best-effort).
  useEffect(() => {
    if (!USER_MODULE || !state.isAuthenticated) return;

    let timeoutId: ReturnType<typeof setTimeout>;

    const handleTimeout = async () => {
      // Clear the server-side cookie (best-effort — may already be expired)
      try {
        await axios.post(`${API_BASE_URL}/auth/cookie-login/logout`);
      } catch {
        // Ignore — cookie may have already expired or CSRF may be stale
      }
      setSessionExpired(true);
      setState({
        user: null,
        token: null,
        isLoading: false,
        isAuthenticated: false,
      });
    };

    const resetTimer = () => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(handleTimeout, INACTIVITY_TIMEOUT_MS);
    };

    const ACTIVITY_EVENTS = ['mousedown', 'keydown', 'scroll', 'touchstart'] as const;
    for (const evt of ACTIVITY_EVENTS) {
      window.addEventListener(evt, resetTimer, { passive: true });
    }
    resetTimer(); // start the clock

    return () => {
      clearTimeout(timeoutId);
      for (const evt of ACTIVITY_EVENTS) {
        window.removeEventListener(evt, resetTimer);
      }
    };
  }, [state.isAuthenticated]);

  const clearVerificationMessage = useCallback(() => {
    setVerificationMessage(null);
  }, []);

  const clearResetPasswordToken = useCallback(() => {
    setResetPasswordToken(null);
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      const resp = await axios.get<AuthUser>(`${API_BASE_URL}/users/me`);
      setState({ user: resp.data, token: null, isLoading: false, isAuthenticated: true });
    } catch {
      // No valid session cookie — user is not logged in
      setState({ user: null, token: null, isLoading: false, isAuthenticated: false });
    }
  }, []);

  // Check auth status on mount
  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  // Handle ?verify=TOKEN from email verification links
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('verify');
    if (!token) return;

    // Clean the URL immediately so a refresh won't re-verify
    params.delete('verify');
    const clean = params.toString();
    const newUrl = window.location.pathname + (clean ? `?${clean}` : '');
    window.history.replaceState({}, '', newUrl);

    (async () => {
      try {
        await axios.post(`${API_BASE_URL}/auth/verify`, { token });
        setVerificationMessage(
          'Your email has been verified! You can now sign in.'
        );
      } catch (err: any) {
        const detail = err.response?.data?.detail ?? '';
        const detailNorm =
          typeof detail === 'string' ? detail.toLowerCase() : '';
        if (detailNorm.includes('already_verified') ||
            detailNorm.includes('already verified')) {
          setVerificationMessage(
            'Your account has already been verified. You can sign in.'
          );
        } else {
          setVerificationMessage(
            'Email verification failed. The link may have expired.'
          );
        }
      }
    })();
  }, []);

  // Handle ?reset-password=TOKEN from password reset email links
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('reset-password');
    if (!token) return;

    // Clean the URL so a refresh won't re-trigger
    params.delete('reset-password');
    const clean = params.toString();
    const newUrl = window.location.pathname + (clean ? `?${clean}` : '');
    window.history.replaceState({}, '', newUrl);

    setResetPasswordToken(token);
  }, []);

  const login = useCallback(async (credentials: LoginCredentials) => {
    const form = new URLSearchParams();
    form.append('username', credentials.username);
    form.append('password', credentials.password);

    // Cookie-based login — the backend sets an httpOnly cookie in the response
    await axios.post(
      `${API_BASE_URL}/auth/cookie-login/login`,
      form,
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
    );

    // Fetch full user profile (cookie is now set)
    const userResp = await axios.get<AuthUser>(`${API_BASE_URL}/users/me`);
    setState({ user: userResp.data, token: null, isLoading: false, isAuthenticated: true });

    // Clear session expired state
    setSessionExpired(false);

    // Resolve any pending 401 retries so intercepted requests are replayed
    if (authPromiseRef.current) {
      authPromiseRef.current.resolve(true);
      authPromiseRef.current = null;
    }
  }, []);

  const register = useCallback(async (data: RegisterData) => {
    await axios.post(`${API_BASE_URL}/auth/register`, data);
  }, []);

  const logout = useCallback(async () => {
    try {
      // Ask the backend to clear the auth cookie
      await axios.post(`${API_BASE_URL}/auth/cookie-login/logout`);
    } catch {
      // Logout endpoint might fail if already expired — that's fine
    }
    setState({ user: null, token: null, isLoading: false, isAuthenticated: false });
    setSessionExpired(false);

    // Reject any pending 401 retries — user chose to log out
    if (authPromiseRef.current) {
      authPromiseRef.current.resolve(false);
      authPromiseRef.current = null;
    }
  }, []);

  return {
    ...state,
    login,
    register,
    logout,
    refreshUser,
    sessionExpired,
    verificationMessage,
    clearVerificationMessage,
    resetPasswordToken,
    clearResetPasswordToken,
  };
}

export default useAuth;
