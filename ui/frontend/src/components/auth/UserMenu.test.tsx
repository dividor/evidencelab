import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import UserMenu from './UserMenu';
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
  ...overrides,
});

const renderWithAuth = (authValue: AuthContextValue, props = {}) =>
  render(
    <AuthContext.Provider value={authValue}>
      <UserMenu {...props} />
    </AuthContext.Provider>
  );

describe('UserMenu', () => {
  it('renders nothing while loading', () => {
    const { container } = renderWithAuth(mockAuthValue({ isLoading: true }));
    expect(container.firstChild).toBeNull();
  });

  it('renders sign-in button when not authenticated', () => {
    renderWithAuth(mockAuthValue());
    const button = screen.getByTitle('Sign in');
    expect(button).toBeInTheDocument();
  });

  it('renders user initials when authenticated', () => {
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        user: {
          id: '1',
          email: 'alice@example.com',
          display_name: 'Alice Baker',
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: null,
          updated_at: null,
        },
      })
    );
    // Should show initials "AB"
    expect(screen.getByText('AB')).toBeInTheDocument();
  });

  it('shows dropdown menu on click', () => {
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        user: {
          id: '1',
          email: 'alice@example.com',
          display_name: 'Alice Baker',
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: null,
          updated_at: null,
        },
      })
    );
    fireEvent.click(screen.getByText('AB'));
    expect(screen.getByText('Profile')).toBeInTheDocument();
    expect(screen.getByText('Sign Out')).toBeInTheDocument();
  });

  it('shows Admin option for superusers', () => {
    const onAdminClick = jest.fn();
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        user: {
          id: '1',
          email: 'admin@example.com',
          display_name: 'Admin',
          is_active: true,
          is_verified: true,
          is_superuser: true,
          created_at: null,
          updated_at: null,
        },
      }),
      { onAdminClick }
    );
    fireEvent.click(screen.getByText('A'));
    expect(screen.getByText('Admin')).toBeInTheDocument();
  });

  it('does not show Admin for non-superusers', () => {
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        user: {
          id: '1',
          email: 'user@example.com',
          display_name: 'User',
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: null,
          updated_at: null,
        },
      }),
      { onAdminClick: jest.fn() }
    );
    fireEvent.click(screen.getByText('U'));
    expect(screen.queryByText('Admin')).not.toBeInTheDocument();
  });

  it('calls logout on Sign Out click', () => {
    const logout = jest.fn();
    renderWithAuth(
      mockAuthValue({
        isAuthenticated: true,
        logout,
        user: {
          id: '1',
          email: 'alice@example.com',
          display_name: 'Alice',
          is_active: true,
          is_verified: true,
          is_superuser: false,
          created_at: null,
          updated_at: null,
        },
      })
    );
    fireEvent.click(screen.getByText('A'));
    fireEvent.click(screen.getByText('Sign Out'));
    expect(logout).toHaveBeenCalled();
  });
});
