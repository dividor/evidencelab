/** TypeScript types for user authentication and permissions. */

export interface AuthUser {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  /** Computed by backend (first_name + last_name). Read-only. */
  display_name: string | null;
  is_active: boolean;
  is_verified: boolean;
  is_superuser: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface SearchSettings {
  denseWeight?: number;
  rerank?: boolean;
  recencyBoost?: boolean;
  recencyWeight?: number;
  recencyScaleDays?: number;
  sectionTypes?: string[];
  keywordBoostShortQueries?: boolean;
  minChunkSize?: number;
  semanticHighlighting?: boolean;
  autoMinScore?: boolean;
  deduplicate?: boolean;
  fieldBoost?: boolean;
  fieldBoostFields?: Record<string, number>;
  greetingMessage?: string;
}

export interface UserGroup {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
  created_at: string;
  datasource_keys: string[];
  member_count: number;
  search_settings?: SearchSettings | null;
  summary_prompt?: string | null;
}

export interface GroupMember {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
}

export interface LoginCredentials {
  username: string; // fastapi-users uses 'username' for email
  password: string;
}

export interface RegisterData {
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
}

export interface AuthState {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

export interface AuthContextValue extends AuthState {
  login: (credentials: LoginCredentials) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  /** True when a previously authenticated session has expired (401 or inactivity). */
  sessionExpired: boolean;
  /** Set after a successful email verification via ?verify= URL param. */
  verificationMessage: string | null;
  clearVerificationMessage: () => void;
  /** Token from ?reset-password= URL param; opens modal in reset mode. */
  resetPasswordToken: string | null;
  clearResetPasswordToken: () => void;
}
