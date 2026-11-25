import { useEffect, useRef, useState } from 'react';
import {
  accountPickRequested,
  AuthStatus,
  OAuthProvider,
  onlyOAuthProvider,
  pauseAutoSignIn,
  startOAuthSignIn,
} from '../utils/oauthSignIn';

/**
 * When ENABLED and STATUS offers only one way to sign in, send the browser
 * straight to that provider's sign-in page instead of showing its button.
 * Returns the provider while that is under way, otherwise null.
 *
 * After a sign-out or a timeout in this tab (pickAccountNextTime), the trip
 * asks the provider for its account picker, so it does not sign the person
 * straight back in.
 *
 * It goes once per sign-in screen. If the trip cannot start, ON_ERROR gets the
 * message and the button shows. Coming back with the browser's Back button
 * can restore the page exactly as it was left; the button shows then too.
 */
export function useAutoSignIn(
  status: AuthStatus | null,
  enabled: boolean,
  onError: (message: string) => void,
): OAuthProvider | null {
  const [stopped, setStopped] = useState(false);
  const startedRef = useRef(false);
  const provider = status ? onlyOAuthProvider(status) : null;
  const going = enabled && !stopped && provider !== null;

  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) setStopped(true);
    };
    window.addEventListener('pageshow', onPageShow);
    return () => window.removeEventListener('pageshow', onPageShow);
  }, []);

  useEffect(() => {
    if (!going || provider === null || startedRef.current) return;
    startedRef.current = true;
    const pickAccount = accountPickRequested();
    pauseAutoSignIn();
    startOAuthSignIn(provider, { pickAccount }).catch((err: Error) => {
      setStopped(true);
      onError(err.message);
    });
  }, [going, provider, onError]);

  return going ? provider : null;
}
