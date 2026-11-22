import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import OAuthButtons from './OAuthButtons';

describe('OAuthButtons', () => {
  const originalLocation = window.location;
  let assignedHref = '';

  beforeEach(() => {
    assignedHref = '';

    // jsdom's window.location is non-configurable; replace with a stub that
    // captures href assignments without triggering navigation.
    delete (window as unknown as { location?: Location }).location;
    (window as unknown as { location: Partial<Location> }).location = {
      pathname: '/',
      search: '',
      get href() {
        return assignedHref;
      },
      set href(value: string) {
        assignedHref = value;
      },
    } as Location;

    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ authorization_url: 'https://accounts.google.com/o/oauth2/v2/auth?client_id=test-client' }),
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    (window as unknown as { location: Location }).location = originalLocation;
    jest.restoreAllMocks();
  });

  const setLocation = (pathname: string, search: string) => {
    (window.location as unknown as { pathname: string }).pathname = pathname;
    (window.location as unknown as { search: string }).search = search;
  };

  test('passes current path+query as return_to when starting Google OAuth', async () => {
    setLocation('/', '?q=impact+of+climate+change&rerank=false&dataset=WFP');
    render(<OAuthButtons onError={jest.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /Sign in with Google/i }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;

    expect(calledUrl).toContain('/auth/google/authorize');
    expect(calledUrl).toContain(
      'return_to=' +
        encodeURIComponent('/?q=impact+of+climate+change&rerank=false&dataset=WFP'),
    );
  });

  test('passes current path+query as return_to when starting Microsoft OAuth', async () => {
    setLocation('/admin', '?page=2');
    render(<OAuthButtons onError={jest.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /Sign in with Microsoft/i }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;

    expect(calledUrl).toContain('/auth/microsoft/authorize');
    expect(calledUrl).toContain('return_to=' + encodeURIComponent('/admin?page=2'));
  });

  test('sends return_to=%2F when on bare app root', async () => {
    setLocation('/', '');
    render(<OAuthButtons microsoftEnabled={false} onError={jest.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /Sign in with Google/i }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;

    expect(calledUrl).toContain('return_to=' + encodeURIComponent('/'));
  });

  test('navigates to the authorization_url returned by the backend', async () => {
    setLocation('/', '?q=foo');
    render(<OAuthButtons microsoftEnabled={false} onError={jest.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /Sign in with Google/i }));

    await waitFor(() => expect(assignedHref).toBe('https://accounts.google.com/o/oauth2/v2/auth?client_id=test-client'));
  });

  test('reports a sign-in that cannot start instead of doing nothing', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: () => Promise.resolve({}),
    }) as unknown as typeof fetch;
    const onError = jest.fn();
    render(<OAuthButtons googleEnabled={false} onError={onError} />);

    fireEvent.click(screen.getByRole('button', { name: /Sign in with Microsoft/i }));

    await waitFor(() =>
      expect(onError).toHaveBeenCalledWith(
        'Could not start Microsoft sign-in (HTTP 502). Please try again.',
      ),
    );
    expect(assignedHref).toBe('');
  });
});
