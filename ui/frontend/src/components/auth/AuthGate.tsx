import React, { useEffect, useRef } from 'react';
import { USER_MODULE_MODE } from '../../config';
import { useAuth } from '../../hooks/useAuth';
import { autoSignInPaused } from '../../utils/oauthSignIn';
import LoginModal from './LoginModal';

/**
 * When USER_MODULE_MODE is "on_active", blocks all content behind a
 * non-dismissable login modal until the user authenticates.
 *
 * If the session expired (401 or inactivity timeout), the modal shows an
 * informational banner so the user understands why they need to sign in again.
 *
 * When the deployment offers only one way to sign in, the modal goes straight
 * to that provider's sign-in page — but not after a session times out (an
 * unattended tab would otherwise be signed back in over and over), nor after
 * someone signs out or a trip to the provider came back still signed out in
 * this tab (see pauseAutoSignIn). The button shows in those cases.
 *
 * Where sign-in is required, nothing is shown until the session check has
 * answered, so the app never flashes up before the sign-in page.
 *
 * MCP OAuth flow: when the URL contains ?mcp_auth=<pending_id>, the gate
 * always shows the login modal regardless of USER_MODULE_MODE.  Once the
 * user authenticates, it redirects the browser to /mcp/complete?pending=...
 * to finalise the OAuth handshake with the MCP client.
 */
export const AuthGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, isLoading, sessionExpired } = useAuth();
  const redirectedRef = useRef(false);

  // Detect MCP OAuth flow from URL params
  const params = new URLSearchParams(window.location.search);
  const mcpAuth = params.get('mcp_auth');

  // After login completes during an MCP auth flow, redirect to /mcp/complete
  useEffect(() => {
    if (mcpAuth && user && !redirectedRef.current) {
      redirectedRef.current = true;
      window.location.href = `/mcp/complete?pending=${encodeURIComponent(mcpAuth)}`;
    }
  }, [mcpAuth, user]);

  if ((mcpAuth || USER_MODULE_MODE === 'on_active') && isLoading) {
    return null;
  }

  // MCP auth flow: always show login modal until authenticated
  if (mcpAuth && !user) {
    return (
      <LoginModal onClose={() => {}} required sessionExpired={false} autoSignIn={!autoSignInPaused()} />
    );
  }

  // MCP auth flow: show loading state while redirecting
  if (mcpAuth && user) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', fontFamily: 'sans-serif', color: '#5B8FA8' }}>
        Completing authorization...
      </div>
    );
  }

  if (USER_MODULE_MODE === 'on_active' && !user) {
    return (
      <LoginModal
        onClose={() => {}}
        required
        sessionExpired={sessionExpired}
        autoSignIn={!sessionExpired && !autoSignInPaused()}
      />
    );
  }

  return <>{children}</>;
};
