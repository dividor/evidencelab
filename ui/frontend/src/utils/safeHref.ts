/**
 * Return *value* as a link target only if a browser would treat it as a
 * normal link: http, https or mailto, or a path on this site. Anything else
 * (javascript:, data:, file:, vbscript:, //other-host paths, junk) gives
 * undefined, so the caller renders plain text instead of a link.
 *
 * Used wherever a link comes from stored data rather than from the app's own
 * code: document metadata, and what visitors send in ratings and activity.
 */
const SAFE_PROTOCOLS = new Set(['http:', 'https:', 'mailto:']);

export const safeHref = (value: string | null | undefined): string | undefined => {
  if (!value) return undefined;
  const trimmed = value.trim();
  if (trimmed.startsWith('/') && !trimmed.startsWith('//') && !trimmed.startsWith('/\\')) {
    return trimmed;
  }
  try {
    const url = new URL(trimmed);
    return SAFE_PROTOCOLS.has(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
};
