import React, { useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { useAuth } from '../../hooks/useAuth';
import OAuthButtons from './OAuthButtons';

interface LoginModalProps {
  onClose: () => void;
  /** When set, open straight into reset-password mode with this token. */
  resetToken?: string | null;
  /** When true, the modal cannot be dismissed (no close button, no overlay click). */
  required?: boolean;
  /** When true, show an info banner indicating the session has expired. */
  sessionExpired?: boolean;
}

type TabMode = 'login' | 'register' | 'forgot' | 'reset';

/** Map raw error codes from fastapi-users to user-friendly messages. */
const ERROR_MESSAGES: Record<string, string> = {
  REGISTER_USER_ALREADY_EXISTS: 'An account with this email address already exists. Try signing in instead.',
  LOGIN_BAD_CREDENTIALS: 'Incorrect email or password. Please try again.',
  LOGIN_USER_NOT_VERIFIED: 'Please verify your email address before signing in. Check your inbox for the verification link.',
  RESET_PASSWORD_BAD_TOKEN: 'This reset link has expired or is invalid. Please request a new one.', // pragma: allowlist secret
  VERIFY_USER_BAD_TOKEN: 'This verification link has expired or is invalid. Please request a new one.',
  VERIFY_USER_ALREADY_VERIFIED: 'Your email has already been verified. You can sign in.',
  OAUTH_EXCHANGE_ERROR: 'Sign-in failed — could not complete the authentication. Please try again.',
  OAUTH_NOT_AVAILABLE_EMAIL: 'Your account provider did not share an email address. Please use a different sign-in method.',
  OAUTH_USER_ALREADY_EXISTS: 'An account with this email already exists. Try signing in with your email and password instead.',
};

/** Extract a human-readable message from fastapi-users error responses. */
function parseErrorDetail(err: any, fallback: string): string {
  const detail = err.response?.data?.detail;
  if (typeof detail === 'string') return ERROR_MESSAGES[detail] || detail;
  if (detail?.reason) return detail.reason;
  return fallback;
}

/* ------------------------------------------------------------------ */
/*  Sub-form: Forgot password                                         */
/* ------------------------------------------------------------------ */

interface ForgotFormProps {
  email: string;
  setEmail: (v: string) => void;
  loading: boolean;
  onSubmit: (e: React.FormEvent) => void;
  onBack: () => void;
}

const ForgotPasswordForm: React.FC<ForgotFormProps> = ({
  email, setEmail, loading, onSubmit, onBack,
}) => (
  <>
    <p className="auth-callout">
      Enter your email address and we&apos;ll send you a link to reset your password.
    </p>
    <form onSubmit={onSubmit}>
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
      <button type="submit" className="auth-submit" disabled={loading}>
        {loading ? 'Sending...' : 'Send Reset Link'}
      </button>
    </form>
    <p className="auth-forgot-back">
      <button type="button" className="auth-link-button" onClick={onBack}>
        Back to Sign In
      </button>
    </p>
  </>
);

/* ------------------------------------------------------------------ */
/*  Sub-form: Reset password (from email link)                        */
/* ------------------------------------------------------------------ */

interface ResetFormProps {
  password: string;
  setPassword: (v: string) => void;
  confirmPassword: string;
  setConfirmPassword: (v: string) => void;
  loading: boolean;
  onSubmit: (e: React.FormEvent) => void;
}

const ResetPasswordForm: React.FC<ResetFormProps> = ({
  password, setPassword, confirmPassword, setConfirmPassword, loading, onSubmit,
}) => (
  <>
    <p className="auth-callout">
      Choose a new password for your account.
    </p>
    <form onSubmit={onSubmit}>
      <div className="form-group">
        <label htmlFor="auth-password">New Password</label>
        <input
          id="auth-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="New password"
          required
          minLength={12}
          autoComplete="new-password"
        />
      </div>
      <div className="form-group">
        <label htmlFor="auth-confirm-password">Confirm Password</label>
        <input
          id="auth-confirm-password"
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          placeholder="Confirm new password"
          required
          minLength={12}
          autoComplete="new-password"
        />
      </div>
      <button type="submit" className="auth-submit" disabled={loading}>
        {loading ? 'Resetting...' : 'Reset Password'}
      </button>
    </form>
  </>
);

/* ------------------------------------------------------------------ */
/*  Sub-form: Login / Register                                        */
/* ------------------------------------------------------------------ */

interface MainAuthFormProps {
  mode: 'login' | 'register';
  email: string;
  setEmail: (v: string) => void;
  password: string;
  setPassword: (v: string) => void;
  firstName: string;
  setFirstName: (v: string) => void;
  lastName: string;
  setLastName: (v: string) => void;
  loading: boolean;
  displaySuccess: string | null;
  onSubmit: (e: React.FormEvent) => void;
  onForgot: () => void;
}

const MainAuthForm: React.FC<MainAuthFormProps> = ({
  mode, email, setEmail, password, setPassword,
  firstName, setFirstName, lastName, setLastName,
  loading, displaySuccess,
  onSubmit, onForgot,
}) => (
  <>
    {mode === 'register' && !displaySuccess && (
      <p className="auth-callout">
        Registering for a free account allows you to access more features.
      </p>
    )}

    <OAuthButtons action={mode === 'login' ? 'Sign in' : 'Sign up'} />

    <div className="auth-divider"><span>or</span></div>

    <form onSubmit={onSubmit}>
      {mode === 'register' && (
        <div className="form-group-row">
          <div className="form-group">
            <label htmlFor="auth-first-name">First name</label>
            <input
              id="auth-first-name"
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              placeholder="First name (optional)"
              autoComplete="given-name"
            />
          </div>
          <div className="form-group">
            <label htmlFor="auth-last-name">Last name</label>
            <input
              id="auth-last-name"
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              placeholder="Last name (optional)"
              autoComplete="family-name"
            />
          </div>
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
          minLength={12}
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
        />
      </div>
      {mode === 'login' && (
        <p className="auth-forgot-link">
          <button type="button" className="auth-link-button" onClick={onForgot}>
            Forgot password?
          </button>
        </p>
      )}
      {mode === 'register' && (
        <p className="auth-legal-text">
          By creating an account, you agree to our{' '}
          <a href="/privacy" target="_blank" rel="noopener noreferrer">
            Privacy Policy
          </a>{' '}and{' '}
          <a href="/terms" target="_blank" rel="noopener noreferrer">
            Terms of Service
          </a>.
        </p>
      )}
      <button type="submit" className="auth-submit" disabled={loading}>
        {loading ? 'Please wait...' : mode === 'login' ? 'Sign In' : 'Create Account'}
      </button>
    </form>
  </>
);

/* ------------------------------------------------------------------ */
/*  Main modal                                                        */
/* ------------------------------------------------------------------ */

const LoginModal: React.FC<LoginModalProps> = ({ onClose, resetToken, required, sessionExpired }) => {
  const { login, register, verificationMessage, clearVerificationMessage } = useAuth();
  const [mode, setMode] = useState<TabMode>(resetToken ? 'reset' : 'login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleClose = () => {
    clearVerificationMessage();
    onClose();
  };

  const switchMode = (next: TabMode) => {
    setMode(next);
    setError('');
    setSuccess('');
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login({ username: email, password });
      clearVerificationMessage();
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
      await register({
        email,
        password,
        first_name: firstName || undefined,
        last_name: lastName || undefined,
      });
      setSuccess('Registration successful! Please check your email to verify your account.');
      setMode('login');
    } catch (err: any) {
      setError(parseErrorDetail(err, 'Registration failed'));
    } finally {
      setLoading(false);
    }
  };

  const handleForgotPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/auth/forgot-password`, { email });
      setSuccess('If an account exists for that email, a password reset link has been sent.');
    } catch {
      // Always show success to avoid email enumeration
      setSuccess('If an account exists for that email, a password reset link has been sent.');
    } finally {
      setLoading(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/auth/reset-password`, {
        token: resetToken,
        password,
      });
      setSuccess('Your password has been reset. You can now sign in.');
      setMode('login');
    } catch (err: any) {
      const msg = parseErrorDetail(err, 'Password reset failed. The link may have expired.');
      const isExpired = msg.includes('RESET_PASSWORD_BAD_TOKEN');
      setError(isExpired ? 'This reset link has expired or is invalid. Please request a new one.' : msg);
    } finally {
      setLoading(false);
    }
  };

  const displaySuccess = verificationMessage || success;
  const isMainTab = mode === 'login' || mode === 'register';

  return (
    <div className="modal-overlay login-overlay" onClick={required ? undefined : handleClose}>
      <div className="modal-content login-modal" onClick={(e) => e.stopPropagation()}>
        <div className="login-branding">
          <img src="/logo.png" alt="Evidence Lab" className="login-logo" />
          <span className="login-brand-name">Evidence Lab</span>
        </div>
        <div className="modal-header">
          <div className="login-tabs">
            <button
              className={`login-tab ${mode === 'login' ? 'login-tab-active' : ''}`}
              onClick={() => switchMode('login')}
            >
              Sign In
            </button>
            <button
              className={`login-tab ${mode === 'register' ? 'login-tab-active' : ''}`}
              onClick={() => switchMode('register')}
            >
              Register
            </button>
          </div>
          {!required && <button className="modal-close" onClick={handleClose}>&times;</button>}
        </div>

        <div className="modal-body">
          {sessionExpired && !error && !displaySuccess && (
            <div className="auth-info">Your session has expired. Please sign in again to continue.</div>
          )}
          {error && <div className="auth-error">{error}</div>}
          {displaySuccess && <div className="auth-success">{displaySuccess}</div>}

          {mode === 'forgot' && (
            <ForgotPasswordForm
              email={email}
              setEmail={setEmail}
              loading={loading}
              onSubmit={handleForgotPassword}
              onBack={() => switchMode('login')}
            />
          )}

          {mode === 'reset' && !success && (
            <ResetPasswordForm
              password={password}
              setPassword={setPassword}
              confirmPassword={confirmPassword}
              setConfirmPassword={setConfirmPassword}
              loading={loading}
              onSubmit={handleResetPassword}
            />
          )}

          {isMainTab && (
            <MainAuthForm
              mode={mode as 'login' | 'register'}
              email={email}
              setEmail={setEmail}
              password={password}
              setPassword={setPassword}
              firstName={firstName}
              setFirstName={setFirstName}
              lastName={lastName}
              setLastName={setLastName}
              loading={loading}
              displaySuccess={displaySuccess}
              onSubmit={mode === 'login' ? handleLogin : handleRegister}
              onForgot={() => switchMode('forgot')}
            />
          )}
        </div>
      </div>
    </div>
  );
};

export default LoginModal;
