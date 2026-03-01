import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';
import type { AuthContextValue, AuthState, AuthUser, LoginCredentials, RegisterData } from '../types/auth';

const TOKEN_KEY = 'evidencelab_token';

const initialState: AuthState = {
  user: null,
  token: localStorage.getItem(TOKEN_KEY),
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

/** Set up axios interceptor for JWT bearer token. */
function setAxiosToken(token: string | null): void {
  if (token) {
    axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
  } else {
    delete axios.defaults.headers.common['Authorization'];
  }
}

/** Custom hook that provides auth state management. Use inside AuthProvider. */
export function useAuthState(): AuthContextValue {
  const [state, setState] = useState<AuthState>(initialState);

  // Set up axios interceptor on mount and token change
  useEffect(() => {
    setAxiosToken(state.token);
  }, [state.token]);

  const refreshUser = useCallback(async () => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setState({ user: null, token: null, isLoading: false, isAuthenticated: false });
      return;
    }
    try {
      setAxiosToken(token);
      const resp = await axios.get<AuthUser>(`${API_BASE_URL}/users/me`);
      setState({ user: resp.data, token, isLoading: false, isAuthenticated: true });
    } catch {
      // Token expired or invalid
      localStorage.removeItem(TOKEN_KEY);
      setAxiosToken(null);
      setState({ user: null, token: null, isLoading: false, isAuthenticated: false });
    }
  }, []);

  // Fetch user on mount if token exists
  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const login = useCallback(async (credentials: LoginCredentials) => {
    const form = new URLSearchParams();
    form.append('username', credentials.username);
    form.append('password', credentials.password);
    const resp = await axios.post<{ access_token: string }>(
      `${API_BASE_URL}/auth/login`,
      form,
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
    );
    const token = resp.data.access_token;
    localStorage.setItem(TOKEN_KEY, token);
    setAxiosToken(token);
    // Fetch full user profile
    const userResp = await axios.get<AuthUser>(`${API_BASE_URL}/users/me`);
    setState({ user: userResp.data, token, isLoading: false, isAuthenticated: true });
  }, []);

  const register = useCallback(async (data: RegisterData) => {
    await axios.post(`${API_BASE_URL}/auth/register`, data);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setAxiosToken(null);
    setState({ user: null, token: null, isLoading: false, isAuthenticated: false });
  }, []);

  return { ...state, login, register, logout, refreshUser };
}

export default useAuth;
