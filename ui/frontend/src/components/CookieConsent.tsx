import React, { useState } from 'react';
import { GA_MEASUREMENT_ID } from '../config';

const GA_CONSENT_KEY = 'ga-consent';

export const getGaConsent = (): string | null => localStorage.getItem(GA_CONSENT_KEY);

export const setGaConsent = (value: 'granted' | 'denied') => {
  localStorage.setItem(GA_CONSENT_KEY, value);
};

export const CookieConsent: React.FC = () => {
  const [visible, setVisible] = useState(
    () => !!GA_MEASUREMENT_ID && getGaConsent() === null
  );

  if (!visible) return null;

  const handleAccept = () => {
    setGaConsent('granted');
    setVisible(false);
    window.location.reload();
  };

  const handleDecline = () => {
    setGaConsent('denied');
    setVisible(false);
  };

  return (
    <div style={{
      position: 'fixed',
      bottom: 0,
      left: 0,
      right: 0,
      background: '#fff',
      borderTop: '1px solid var(--gray-200)',
      padding: '1.25rem 1.5rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '1.5rem',
      flexWrap: 'wrap',
      zIndex: 10000,
      boxShadow: '0 -2px 12px rgba(0,0,0,0.1)',
    }}>
      <p style={{ color: 'var(--gray-700)', fontSize: '0.9rem', lineHeight: 1.5, margin: 0, maxWidth: '600px' }}>
        This site uses cookies and Google Analytics to help us understand usage and improve the platform.
        No data is used for advertising.
      </p>
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexShrink: 0 }}>
        <button
          onClick={handleDecline}
          style={{
            background: 'transparent',
            color: 'var(--gray-600)',
            border: '1px solid var(--gray-300)',
            borderRadius: '4px',
            padding: '0.5rem 1.25rem',
            cursor: 'pointer',
            fontSize: '0.85rem',
          }}
        >
          Reject all
        </button>
        <button
          onClick={handleAccept}
          style={{
            background: 'var(--primary-blue)',
            color: '#fff',
            border: 'none',
            borderRadius: '4px',
            padding: '0.5rem 1.25rem',
            cursor: 'pointer',
            fontSize: '0.85rem',
            fontWeight: 600,
          }}
        >
          Accept all
        </button>
        <a
          href="/privacy"
          onClick={(e) => { e.preventDefault(); handleDecline(); window.location.href = '/privacy'; }}
          style={{ color: 'var(--primary-blue)', fontSize: '0.85rem', whiteSpace: 'nowrap' }}
        >
          Privacy policy
        </a>
      </div>
    </div>
  );
};
