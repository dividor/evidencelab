import '@testing-library/jest-dom';
import { randomUUID } from 'crypto';
import { TextEncoder, TextDecoder } from 'util';

// Polyfill TextEncoder/TextDecoder for jsdom (required by html2pdf.js / jspdf)
if (!global.TextEncoder) {
  global.TextEncoder = TextEncoder;
}
if (!global.TextDecoder) {
  global.TextDecoder = TextDecoder as typeof global.TextDecoder;
}

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
