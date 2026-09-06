// Locating a comment's anchor in a section's text.
//
// A comment stores the quoted passage plus a little context either side rather
// than character offsets, because a section is often re-researched after a
// comment is left and offsets would then point at unrelated prose. Finding the
// quote again is best-effort and deliberately conservative: when the passage
// has genuinely gone, the comment is reported as orphaned rather than being
// pinned to text that merely looks similar.

export interface AnchorInput {
  quote?: string | null;
  quotePrefix?: string | null;
  quoteSuffix?: string | null;
}

/** A captured anchor: the quoted text with the context either side. */
export interface Anchor {
  quote: string;
  quotePrefix: string;
  quoteSuffix: string;
}

export interface AnchorRange {
  start: number;
  end: number;
}

// Context kept either side of a quote. Long enough to disambiguate a repeated
// phrase, short enough to survive light editing around it.
export const ANCHOR_CONTEXT_CHARS = 40;

/** Capture an anchor from a selection within `text`. */
export const buildAnchor = (text: string, start: number, end: number): Anchor => ({
  quote: text.slice(start, end),
  quotePrefix: text.slice(Math.max(0, start - ANCHOR_CONTEXT_CHARS), start),
  quoteSuffix: text.slice(end, Math.min(text.length, end + ANCHOR_CONTEXT_CHARS)),
});

// Whitespace differences are not meaningful here: markdown re-wraps lines when
// a section is rewritten, so compare with runs of whitespace collapsed.
const normalize = (s: string): string => s.replace(/\s+/g, ' ').trim();

/**
 * Match `target` (already normalised) against `haystack` starting at `start`.
 * Returns the end offset in the original string, or -1 when it does not match.
 * A run of whitespace in the text matches a single space in the target.
 */
const matchFrom = (haystack: string, start: number, target: string): number => {
  let j = start;
  let matched = 0;
  while (j < haystack.length && matched < target.length) {
    const hc = haystack[j];
    const tc = target[matched];
    if (/\s/.test(hc)) {
      if (tc !== ' ') return -1;
      matched += 1;
      while (j < haystack.length && /\s/.test(haystack[j])) j += 1;
      continue;
    }
    if (hc !== tc) return -1;
    matched += 1;
    j += 1;
  }
  return matched === target.length ? j : -1;
};

/**
 * Every occurrence of `needle` in `haystack`, comparing on normalised
 * whitespace. Returns ranges in the *original* string's coordinates.
 */
const findOccurrences = (haystack: string, needle: string): AnchorRange[] => {
  const target = normalize(needle);
  if (!target) return [];
  const out: AnchorRange[] = [];
  for (let i = 0; i < haystack.length; i++) {
    const end = matchFrom(haystack, i, target);
    if (end >= 0) out.push({ start: i, end });
  }
  return out;
};

/** How much of the stored context still surrounds this occurrence. */
const contextScore = (
  text: string,
  hit: AnchorRange,
  prefix: string,
  suffix: string,
): number => {
  const window = ANCHOR_CONTEXT_CHARS * 2;
  const before = normalize(text.slice(Math.max(0, hit.start - window), hit.start));
  const after = normalize(text.slice(hit.end, hit.end + window));
  let score = 0;
  if (prefix && before.endsWith(prefix.slice(-20))) score += 2;
  if (suffix && after.startsWith(suffix.slice(0, 20))) score += 2;
  if (prefix && before.includes(prefix.slice(-10))) score += 1;
  if (suffix && after.includes(suffix.slice(0, 10))) score += 1;
  return score;
};

/**
 * Locate a comment's quote in `text`, or null when it can no longer be found.
 *
 * With several matches the surrounding context decides, so a comment on one
 * instance of a repeated phrase stays on that instance.
 */
export const locateAnchor = (text: string, anchor: AnchorInput): AnchorRange | null => {
  const quote = (anchor.quote || '').trim();
  if (!quote || !text) return null;
  const hits = findOccurrences(text, quote);
  if (hits.length <= 1) return hits[0] ?? null;

  const prefix = normalize(anchor.quotePrefix || '');
  const suffix = normalize(anchor.quoteSuffix || '');
  let best = hits[0];
  let bestScore = -1;
  for (const hit of hits) {
    const score = contextScore(text, hit, prefix, suffix);
    if (score > bestScore) {
      bestScore = score;
      best = hit;
    }
  }
  return best;
};

/** True when the quoted passage is no longer present in the section. */
export const isOrphaned = (text: string, anchor: AnchorInput): boolean =>
  !!(anchor.quote || '').trim() && locateAnchor(text, anchor) === null;
