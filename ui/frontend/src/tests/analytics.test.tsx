import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import {
  AnalyticsProvider,
  GoogleAnalyticsProvider,
  createAnalyticsProvider,
  getAnalyticsConsent,
  grantAnalyticsConsent,
  initAnalytics,
  isAnalyticsConfigured,
  revokeAnalyticsConsent,
} from '../utils/analytics';
import { CookieConsent } from '../components/CookieConsent';

jest.mock('../config', () => ({ GA_MEASUREMENT_ID: 'G-TEST123' }));

const TEST_ID = 'G-TEST123';
const CONSENT_KEY = 'ga-consent';
const scriptSelector = 'script[data-analytics="google-analytics"]';
const anyWindow = window as unknown as Record<string, unknown>;

class FakeProvider implements AnalyticsProvider {
  readonly name = 'fake';
  loads = 0;
  disables = 0;
  load() {
    this.loads += 1;
  }
  disable() {
    this.disables += 1;
  }
}

beforeEach(() => {
  localStorage.clear();
  document.head.querySelectorAll(scriptSelector).forEach((el) => el.remove());
  delete anyWindow.dataLayer;
  delete anyWindow.gtag;
  delete anyWindow[`ga-disable-${TEST_ID}`];
});

describe('createAnalyticsProvider', () => {
  test('returns null when no measurement id is configured', () => {
    expect(createAnalyticsProvider('')).toBeNull();
  });

  test('returns null for an id that is not a GA4 measurement id', () => {
    expect(createAnalyticsProvider('UA-12345')).toBeNull();
  });

  test('returns a Google Analytics provider for a G- id', () => {
    const provider = createAnalyticsProvider('G-ABC');
    expect(provider).toBeInstanceOf(GoogleAnalyticsProvider);
    expect(provider?.name).toBe('google-analytics');
  });

  test('reads the build-time id by default', () => {
    expect(isAnalyticsConfigured()).toBe(true);
  });
});

describe('GoogleAnalyticsProvider', () => {
  test('load injects the gtag script once and primes the data layer', () => {
    const provider = new GoogleAnalyticsProvider('G-ABC');

    provider.load();
    provider.load();

    const scripts = document.head.querySelectorAll(scriptSelector);
    expect(scripts).toHaveLength(1);
    const script = scripts[0] as HTMLScriptElement;
    expect(script.src).toBe('https://www.googletagmanager.com/gtag/js?id=G-ABC');
    expect(script.async).toBe(true);
    expect(script.crossOrigin).toBe('anonymous');

    // gtag.js only acts on `arguments` objects, so the entries must not be
    // plain arrays.
    const dataLayer = anyWindow.dataLayer as IArguments[];
    expect(Array.isArray(dataLayer[0])).toBe(false);
    expect(Array.from(dataLayer[0])[0]).toBe('js');
    expect(Array.from(dataLayer[1])).toEqual(['config', 'G-ABC']);
    expect(anyWindow['ga-disable-G-ABC']).toBe(false);
  });

  test('disable sets the gtag opt-out flag for this id', () => {
    const provider = new GoogleAnalyticsProvider('G-ABC');
    provider.disable();
    expect(anyWindow['ga-disable-G-ABC']).toBe(true);
  });
});

describe('consent and initialisation', () => {
  test('nothing loads without consent', () => {
    const provider = new FakeProvider();
    expect(initAnalytics(provider)).toBe(false);
    expect(provider.loads).toBe(0);
  });

  test('nothing loads when no provider is configured, even with consent', () => {
    localStorage.setItem(CONSENT_KEY, 'granted');
    expect(initAnalytics(null)).toBe(false);
  });

  test('loads when consent was granted earlier', () => {
    localStorage.setItem(CONSENT_KEY, 'granted');
    const provider = new FakeProvider();
    expect(initAnalytics(provider)).toBe(true);
    expect(provider.loads).toBe(1);
  });

  test('granting consent persists it and loads the provider', () => {
    const provider = new FakeProvider();
    grantAnalyticsConsent(provider);
    expect(getAnalyticsConsent()).toBe('granted');
    expect(provider.loads).toBe(1);
  });

  test('revoking consent persists it and disables the provider', () => {
    const provider = new FakeProvider();
    revokeAnalyticsConsent(provider);
    expect(getAnalyticsConsent()).toBe('denied');
    expect(provider.disables).toBe(1);
  });

  test('revoking with no provider configured still records the choice', () => {
    revokeAnalyticsConsent(null);
    expect(getAnalyticsConsent()).toBe('denied');
  });
});

describe('CookieConsent banner', () => {
  test('is shown only while no choice has been made', () => {
    localStorage.setItem(CONSENT_KEY, 'denied');
    const { container } = render(<CookieConsent />);
    expect(container).toBeEmptyDOMElement();
  });

  test('accepting loads analytics in place without a page reload', () => {
    render(<CookieConsent />);

    fireEvent.click(screen.getByRole('button', { name: 'Accept all' }));

    expect(getAnalyticsConsent()).toBe('granted');
    expect(document.head.querySelector(scriptSelector)).not.toBeNull();
    expect(screen.queryByRole('button', { name: 'Accept all' })).toBeNull();
  });

  test('rejecting records the choice and loads nothing', () => {
    render(<CookieConsent />);

    fireEvent.click(screen.getByRole('button', { name: 'Reject all' }));

    expect(getAnalyticsConsent()).toBe('denied');
    expect(document.head.querySelector(scriptSelector)).toBeNull();
  });
});
