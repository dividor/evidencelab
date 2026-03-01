import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';
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
    if (match) {
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
  logout: () => {},
  refreshUser: async () => {},
});

/** Hook to access the auth context. */
export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

/** Custom hook that provides auth state management. Use inside AuthProvider. */
export function useAuthState(): AuthContextValue {
  const [state, setState] = useState<AuthState>(initialState);

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

  const login = useCallback(async (credentials: LoginCredentials) => {
    const form = new URLSearchParams();
    form.append('username', credentials.username);
    form.append('password', credentials.password);

    // Cookie-based login — the backend sets an httpOnly cookie in the response
    await axios.post(
      `${API_BASE_URL}/auth/cookie-login`,
      form,
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
    );

    // Fetch full user profile (cookie is now set)
    const userResp = await axios.get<AuthUser>(`${API_BASE_URL}/users/me`);
    setState({ user: userResp.data, token: null, isLoading: false, isAuthenticated: true });
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
  }, []);

  return { ...state, login, register, logout, refreshUser };
}

export default useAuth;
