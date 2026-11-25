import React from 'react';
import ReactDOM from 'react-dom/client';
// The app's typefaces, served from this site (see App.css): the same weights
// the Google Fonts link used to load, so pages look the same.
import '@fontsource/poppins/400.css';
import '@fontsource/poppins/600.css';
import '@fontsource/poppins/700.css';
import '@fontsource/open-sans/400.css';
import '@fontsource/open-sans/600.css';
import './index.css';
import App from './App';
import { installClickDiagnostics } from './utils/clickDiagnostics';
import { initAnalytics } from './utils/analytics';

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
// Record what happens on every mouse press so a console screenshot can
// explain a click that did nothing (see utils/clickDiagnostics.ts).
installClickDiagnostics();

// Hide static crawler-only footer once React takes over
document.getElementById('static-footer')?.remove();

// Optional analytics: loads only when a provider is configured at build time
// and the visitor has accepted analytics cookies (see utils/analytics.ts).
initAnalytics();

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
