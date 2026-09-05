import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import { installClickDiagnostics } from './utils/clickDiagnostics';

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
// Record what happens on every mouse press so a console screenshot can
// explain a click that did nothing (see utils/clickDiagnostics.ts).
installClickDiagnostics();

// Hide static crawler-only footer once React takes over
document.getElementById('static-footer')?.remove();

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
