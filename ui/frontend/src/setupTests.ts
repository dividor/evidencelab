import '@testing-library/jest-dom';
import { randomUUID } from 'crypto';
import { TextDecoder, TextEncoder } from 'util';

// Polyfill ResizeObserver for jsdom test environment
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Polyfill IntersectionObserver for jsdom. jsdom has no layout, so the real
// observer would never fire. This mock collects every constructed instance
// on `MockIntersectionObserver.instances` so tests can drive visibility
// changes manually (e.g. instances[0].fireEntries([{ target, isIntersecting: true }])).
class MockIntersectionObserver implements IntersectionObserver {
  static instances: MockIntersectionObserver[] = [];
  static reset(): void {
    MockIntersectionObserver.instances = [];
  }

  readonly root: Element | Document | null = null;
  readonly rootMargin: string = '';
  readonly thresholds: ReadonlyArray<number> = [];
  observed = new Set<Element>();
  callback: IntersectionObserverCallback;
  options?: IntersectionObserverInit;

  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.callback = callback;
    this.options = options;
    MockIntersectionObserver.instances.push(this);
  }

  observe(target: Element): void {
    this.observed.add(target);
  }

  unobserve(target: Element): void {
    this.observed.delete(target);
  }

  disconnect(): void {
    this.observed.clear();
  }

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }

  // Test helper — synthesise IntersectionObserverEntry-like records and
  // invoke the callback with them. Real entries have many more fields; for
  // the purposes of our code we only read `target` and `isIntersecting`.
  fireEntries(records: { target: Element; isIntersecting: boolean }[]): void {
    const entries = records.map(({ target, isIntersecting }) => ({
      target,
      isIntersecting,
      intersectionRatio: isIntersecting ? 1 : 0,
      boundingClientRect: target.getBoundingClientRect(),
      intersectionRect: target.getBoundingClientRect(),
      rootBounds: null,
      time: Date.now()
    } as IntersectionObserverEntry));
    this.callback(entries, this);
  }
}

(global as any).IntersectionObserver = MockIntersectionObserver;
(global as any).MockIntersectionObserver = MockIntersectionObserver;

// Polyfill crypto.randomUUID for jsdom test environment
if (!global.crypto) {
  (global as any).crypto = {};
}
if (!(global.crypto as any).randomUUID) {
  (global.crypto as any).randomUUID = randomUUID;
}

// jsdom does not expose TextEncoder/TextDecoder, but the `docx` package
// used by the Word-export utility needs them to pack a Document into a Blob.
// Polyfill from Node's built-in `util` module.
if (typeof (globalThis as any).TextEncoder === 'undefined') {
  (globalThis as any).TextEncoder = TextEncoder;
}
if (typeof (globalThis as any).TextDecoder === 'undefined') {
  (globalThis as any).TextDecoder = TextDecoder;
}

// jsdom 16 ships a Blob without .arrayBuffer() — polyfill via FileReader so
// JSZip (and any other binary consumer) can read docx Blobs in tests.
if (typeof Blob !== 'undefined' && typeof Blob.prototype.arrayBuffer !== 'function') {
  (Blob.prototype as any).arrayBuffer = function arrayBuffer(this: Blob): Promise<ArrayBuffer> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(this);
    });
  };
}
