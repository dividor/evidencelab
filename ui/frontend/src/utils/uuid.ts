/**
 * Generate a UUID v4.
 *
 * Prefers `crypto.randomUUID()` when available (secure contexts), but falls
 * back to `crypto.getRandomValues()` which works in all modern browsers
 * regardless of the security context.  This is necessary because the
 * integration-test environment accesses the UI over plain HTTP with a
 * non-localhost hostname, where `crypto.randomUUID` is undefined.
 */
export function generateUUID(): string {
  // Fast path — available in secure contexts (HTTPS / localhost)
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  // Fallback using crypto.getRandomValues (works in all contexts)
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);

  // Set version (4) and variant (RFC 4122)
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10

  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
