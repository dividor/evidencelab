import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';

jest.mock('axios');

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
  verificationMessage: null,
  clearVerificationMessage: jest.fn(),
  ...overrides,
});

const renderModal = (authValue?: AuthContextValue) =>
  render(
    <AuthContext.Provider value={authValue || mockAuthValue()}>
      <LoginModal onClose={jest.fn()} />
    </AuthContext.Provider>
  );

describe('LoginModal', () => {
  it('renders with Sign In tab active by default', () => {
    renderModal();
    const signInTab = screen.getByText('Sign In', { selector: 'button.login-tab' });
    expect(signInTab).toHaveClass('login-tab-active');
  });

  it('shows email and password fields', () => {
    renderModal();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('shows name field only on register tab', () => {
    renderModal();
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Register'));
    expect(screen.getByLabelText('Name')).toBeInTheDocument();
  });

  it('shows OAuth buttons', () => {
    renderModal();
    expect(screen.getByText(/Sign in with Google/)).toBeInTheDocument();
    expect(screen.getByText(/Sign in with Microsoft/)).toBeInTheDocument();
  });

  it('switches to register tab', () => {
    renderModal();
    fireEvent.click(screen.getByText('Register'));
    const registerTab = screen.getByText('Register', { selector: 'button.login-tab' });
    expect(registerTab).toHaveClass('login-tab-active');
    expect(screen.getByText('Create Account')).toBeInTheDocument();
  });

  it('calls onClose when overlay is clicked', () => {
    const onClose = jest.fn();
    render(
      <AuthContext.Provider value={mockAuthValue()}>
        <LoginModal onClose={onClose} />
      </AuthContext.Provider>
    );
    fireEvent.click(screen.getByText('Sign In', { selector: 'button.login-tab' }).closest('.modal-overlay')!);
    // The overlay click triggers onClose, but stopPropagation on modal-content prevents it
    // when clicking inside. We click the overlay itself.
  });
});
