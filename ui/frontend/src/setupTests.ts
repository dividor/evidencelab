import '@testing-library/jest-dom';

// Polyfill ResizeObserver for jsdom test environment
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};
