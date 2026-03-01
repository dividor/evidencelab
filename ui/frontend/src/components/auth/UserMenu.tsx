import React, { useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import LoginModal from './LoginModal';
import ProfileModal from './ProfileModal';

interface UserMenuProps {
  onAdminClick?: () => void;
}

const UserMenu: React.FC<UserMenuProps> = ({ onAdminClick }) => {
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [showLogin, setShowLogin] = useState(false);
  const [showProfile, setShowProfile] = useState(false);

  if (isLoading) return null;

  const initials = user?.display_name
    ? user.display_name
        .split(' ')
        .map((n) => n[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : user?.email?.charAt(0).toUpperCase() || '?';

  const handleBlur = () => {
    // Delay to allow click events on dropdown items
    setTimeout(() => setMenuOpen(false), 200);
  };

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
        {showLogin && <LoginModal onClose={() => setShowLogin(false)} />}
      </>
    );
  }

  return (
    <>
      <div className="dropdown-container">
        <button
          className="user-menu-trigger"
          onClick={() => setMenuOpen(!menuOpen)}
          onBlur={handleBlur}
          title={user?.email || 'User menu'}
        >
          {initials}
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
      {showProfile && <ProfileModal onClose={() => setShowProfile(false)} />}
    </>
  );
};

export default UserMenu;
