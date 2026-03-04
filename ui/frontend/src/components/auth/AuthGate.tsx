import React from 'react';
import { USER_MODULE_MODE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import LoginModal from './LoginModal';

/**
 * When USER_MODULE_MODE is "on_active", blocks all content behind a
 * non-dismissable login modal until the user authenticates.
 *
 * If the session expired (401 or inactivity timeout), the modal shows an
 * informational banner so the user understands why they need to sign in again.
 */
export const AuthGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, isLoading, sessionExpired } = useAuth();

  if (USER_MODULE_MODE === 'on_active' && !isLoading && !user) {
    return <LoginModal onClose={() => {}} required sessionExpired={sessionExpired} />;
  }

  return <>{children}</>;
};
