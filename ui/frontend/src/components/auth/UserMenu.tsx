import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useCloseOnOutsideClick } from '../../hooks/useCloseOnOutsideClick';
import type { AuthUser } from '../../types/auth';
import EnvironmentalImpactModal from './EnvironmentalImpactModal';
import LoginModal from './LoginModal';
import ProfileModal from './ProfileModal';
import SavedResearchModal from '../SavedResearchModal';

interface UserMenuProps {
  personalImpactEnabled?: boolean;
  onAdminClick?: () => void;
  onLoadResearch?: (id: string) => void;
}

function userInitials(user: AuthUser | null): string {
  if (user?.first_name || user?.last_name) {
    return [user.first_name?.[0], user.last_name?.[0]]
      .filter(Boolean)
      .join('')
      .toUpperCase()
      .slice(0, 2);
  }
  return user?.email?.charAt(0).toUpperCase() || '?';
}

const UserMenu: React.FC<UserMenuProps> = ({ onAdminClick, onLoadResearch, personalImpactEnabled }) => {
  const {
    user, isAuthenticated, isLoading, logout,
    verificationMessage, resetPasswordToken, clearResetPasswordToken,
  } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [showLogin, setShowLogin] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [impactUserId, setImpactUserId] = useState<string>();
  const [showSavedResearch, setShowSavedResearch] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  const triggerRef = useRef<HTMLButtonElement>(null);
  useCloseOnOutsideClick(containerRef, menuOpen, closeMenu);

  // Auto-open the login modal when a verification message arrives
  useEffect(() => {
    if (verificationMessage && !isAuthenticated) {
      setShowLogin(true);
    }
  }, [verificationMessage, isAuthenticated]);

  // Auto-open the login modal in reset-password mode
  useEffect(() => {
    if (resetPasswordToken) {
      setShowLogin(true);
    }
  }, [resetPasswordToken]);

  if (isLoading) return null;

  if (!isAuthenticated) {
    return (
      <>
        <button
          className="user-menu-trigger user-menu-trigger-anonymous"
          onClick={() => setShowLogin(true)}
          title="Sign in"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        </button>
        {showLogin && (
          <LoginModal
            onClose={() => { setShowLogin(false); clearResetPasswordToken(); }}
            resetToken={resetPasswordToken}
            autoSignIn
          />
        )}
      </>
    );
  }

  return (
    <>
      <div className="dropdown-container" ref={containerRef}>
        <button
          className="user-menu-trigger"
          ref={triggerRef}
          onClick={() => setMenuOpen(!menuOpen)}
          title={user?.email || 'User menu'}
        >
          {userInitials(user)}
        </button>
        {menuOpen && (
          <div className="dropdown-menu user-menu-dropdown">
            <div className="user-menu-header">
              <strong>{user?.display_name || user?.email}</strong>
              {user?.display_name && (
                <span className="user-menu-email">{user?.email}</span>
              )}
            </div>
            <button
              className="dropdown-item"
              onClick={() => { setShowProfile(true); setMenuOpen(false); }}
            >
              Profile
            </button>
            {personalImpactEnabled && user && (
              <button
                className="dropdown-item"
                onClick={() => { setImpactUserId(user.id); closeMenu(); }}
              >
                Environmental impact
              </button>
            )}
            {onLoadResearch && (
              <button
                className="dropdown-item"
                onClick={() => { setShowSavedResearch(true); setMenuOpen(false); }}
              >
                Saved Research
              </button>
            )}
            {user?.is_superuser && onAdminClick && (
              <button
                className="dropdown-item"
                onClick={() => { onAdminClick(); setMenuOpen(false); }}
              >
                Admin
              </button>
            )}
            <button
              className="dropdown-item user-menu-logout"
              onClick={() => { logout(); setMenuOpen(false); }}
            >
              Sign Out
            </button>
          </div>
        )}
      </div>
      {showProfile && (
        <ProfileModal onClose={() => setShowProfile(false)} />
      )}
      {personalImpactEnabled && user && impactUserId === user.id && (
        <EnvironmentalImpactModal onClose={() => {
          setImpactUserId(undefined);
          requestAnimationFrame(() => triggerRef.current?.focus());
        }} />
      )}
      {showSavedResearch && onLoadResearch && (
        <SavedResearchModal
          onClose={() => setShowSavedResearch(false)}
          onLoadResearch={(id: string) => {
            setShowSavedResearch(false);
            onLoadResearch(id);
          }}
        />
      )}
    </>
  );
};

export default UserMenu;
