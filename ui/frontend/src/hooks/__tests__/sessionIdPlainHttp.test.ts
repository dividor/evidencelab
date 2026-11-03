/**
 * Browsers only provide crypto.randomUUID on secure pages (HTTPS or
 * localhost). On a site served over plain HTTP it is undefined, and calling it
 * broke every search with "Search failed" (seen on the AWS demo deployment).
 * The anonymous session ID must still be created there.
 */
import { webcrypto } from 'crypto';
import { getSessionId } from '../useActivityLogging';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('getSessionId on a plain-HTTP page', () => {
  const realRandomUUID = crypto.randomUUID;

  beforeEach(() => {
    localStorage.clear();
    // A plain-HTTP page has getRandomValues but not randomUUID. jsdom has
    // neither, so supply the real getRandomValues from Node.
    Object.defineProperty(crypto, 'getRandomValues', {
      value: webcrypto.getRandomValues.bind(webcrypto),
      configurable: true,
    });
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
  });

  afterEach(() => {
    Object.defineProperty(crypto, 'randomUUID', { value: realRandomUUID, configurable: true });
  });

  test('creates and stores a UUID without crypto.randomUUID', () => {
    const id = getSessionId();
    expect(id).toMatch(UUID);
    expect(localStorage.getItem('evidencelab_session_id')).toBe(id);
  });

  test('returns the same ID on later calls', () => {
    expect(getSessionId()).toBe(getSessionId());
  });
});
