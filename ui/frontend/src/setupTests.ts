import '@testing-library/jest-dom';
import { randomUUID } from 'crypto';

// Polyfill ResizeObserver for jsdom test environment
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Polyfill crypto.randomUUID for jsdom test environment
if (!global.crypto) {
  (global as any).crypto = {};
}
if (!(global.crypto as any).randomUUID) {
  (global.crypto as any).randomUUID = randomUUID;
}
