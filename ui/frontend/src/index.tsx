import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
// Hide static crawler-only footer once React takes over
document.getElementById('static-footer')?.remove();

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
