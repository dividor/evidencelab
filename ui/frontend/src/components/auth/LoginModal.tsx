import React, { useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import OAuthButtons from './OAuthButtons';

interface LoginModalProps {
  onClose: () => void;
}

type TabMode = 'login' | 'register';

const LoginModal: React.FC<LoginModalProps> = ({ onClose }) => {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<TabMode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login({ username: email, password });
      onClose();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);
    try {
      await register({ email, password, display_name: displayName || undefined });
      setSuccess('Registration successful! Please check your email to verify your account.');
      setMode('login');
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      if (typeof detail === 'string') {
        setError(detail);
      } else if (detail?.reason) {
        setError(detail.reason);
      } else {
        setError('Registration failed');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content login-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="login-tabs">
            <button
              className={`login-tab ${mode === 'login' ? 'login-tab-active' : ''}`}
              onClick={() => { setMode('login'); setError(''); setSuccess(''); }}
            >
              Sign In
            </button>
            <button
              className={`login-tab ${mode === 'register' ? 'login-tab-active' : ''}`}
              onClick={() => { setMode('register'); setError(''); setSuccess(''); }}
            >
              Register
            </button>
          </div>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="modal-body">
          {error && <div className="auth-error">{error}</div>}
          {success && <div className="auth-success">{success}</div>}

          <OAuthButtons action={mode === 'login' ? 'Sign in' : 'Sign up'} />

          <div className="auth-divider">
            <span>or</span>
          </div>

          <form onSubmit={mode === 'login' ? handleLogin : handleRegister}>
            {mode === 'register' && (
              <div className="form-group">
                <label htmlFor="auth-display-name">Name</label>
                <input
                  id="auth-display-name"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Your name (optional)"
                  autoComplete="name"
                />
              </div>
            )}
            <div className="form-group">
              <label htmlFor="auth-email">Email</label>
              <input
                id="auth-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                autoComplete="email"
              />
            </div>
            <div className="form-group">
              <label htmlFor="auth-password">Password</label>
              <input
                id="auth-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                required
                minLength={8}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              />
            </div>
            <button type="submit" className="auth-submit" disabled={loading}>
              {loading ? 'Please wait...' : mode === 'login' ? 'Sign In' : 'Create Account'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default LoginModal;
