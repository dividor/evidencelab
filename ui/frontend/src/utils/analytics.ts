/**
 * Web analytics behind one small interface.
 *
 * Analytics is optional. Nothing loads unless a provider is configured at
 * build time (`REACT_APP_GA_MEASUREMENT_ID` for Google Analytics) AND the
 * visitor has accepted analytics cookies. The vendor script is injected from
 * here, not from `public/index.html`, so swapping or removing a provider is a
 * change to this file only and the page's Content-Security-Policy needs no
 * inline-script hash.
 *
 * To add another provider, implement `AnalyticsProvider` and return it from
 * `createAnalyticsProvider()`.
 */
import { GA_MEASUREMENT_ID } from '../config';

export type AnalyticsConsent = 'granted' | 'denied';

// The key predates this module; keeping it means visitors who already made a
// choice are not asked again.
const CONSENT_KEY = 'ga-consent';

export interface AnalyticsProvider {
  readonly name: string;
  /** Inject the vendor script and start collecting. Safe to call twice. */
  load(): void;
  /** Stop collecting for the rest of this page view. */
  disable(): void;
}

type GtagWindow = Window & {
  dataLayer?: unknown[];
  gtag?: (...args: unknown[]) => void;
  [key: string]: unknown;
};

export class GoogleAnalyticsProvider implements AnalyticsProvider {
  readonly name = 'google-analytics';

  constructor(private readonly measurementId: string) {}

  private get disableFlag(): string {
    return `ga-disable-${this.measurementId}`;
  }

  load(): void {
    const w = window as unknown as GtagWindow;
    w[this.disableFlag] = false;
    if (document.querySelector(`script[data-analytics="${this.name}"]`)) return;

    const script = document.createElement('script');
    script.async = true;
    script.crossOrigin = 'anonymous';
    script.dataset.analytics = this.name;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(this.measurementId)}`;
    document.head.appendChild(script);

    w.dataLayer = w.dataLayer || [];
    // gtag.js only processes `arguments` objects on the data layer, not
    // arrays, so this must stay a plain function that pushes `arguments`.
    w.gtag = function gtag() {
      w.dataLayer!.push(arguments);
    };
    w.gtag('js', new Date());
    w.gtag('config', this.measurementId);
  }

  disable(): void {
    (window as unknown as GtagWindow)[this.disableFlag] = true;
  }
}

/** The provider this build is configured for, or null when analytics is off. */
export const createAnalyticsProvider = (
  measurementId: string | undefined = GA_MEASUREMENT_ID
): AnalyticsProvider | null =>
  measurementId && measurementId.startsWith('G-')
    ? new GoogleAnalyticsProvider(measurementId)
    : null;

export const isAnalyticsConfigured = (): boolean => createAnalyticsProvider() !== null;

export const getAnalyticsConsent = (): AnalyticsConsent | null =>
  localStorage.getItem(CONSENT_KEY) as AnalyticsConsent | null;

export const setAnalyticsConsent = (value: AnalyticsConsent): void => {
  localStorage.setItem(CONSENT_KEY, value);
};

/**
 * Load analytics when a provider is configured and consent was granted.
 * Called once at startup and again when the visitor accepts the banner.
 * Returns true when the provider was loaded.
 */
export const initAnalytics = (
  provider: AnalyticsProvider | null = createAnalyticsProvider()
): boolean => {
  if (!provider || getAnalyticsConsent() !== 'granted') return false;
  provider.load();
  return true;
};

export const grantAnalyticsConsent = (
  provider: AnalyticsProvider | null = createAnalyticsProvider()
): void => {
  setAnalyticsConsent('granted');
  initAnalytics(provider);
};

export const revokeAnalyticsConsent = (
  provider: AnalyticsProvider | null = createAnalyticsProvider()
): void => {
  setAnalyticsConsent('denied');
  provider?.disable();
};
