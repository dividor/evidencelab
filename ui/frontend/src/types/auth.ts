/** TypeScript types for user authentication and permissions. */

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  is_verified: boolean;
  is_superuser: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface UserGroup {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
  created_at: string;
  datasource_keys: string[];
  member_count: number;
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
  display_name?: string;
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
  logout: () => void;
  refreshUser: () => Promise<void>;
}
