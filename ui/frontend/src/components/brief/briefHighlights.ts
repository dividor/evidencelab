import { SourceReference, SummaryModelConfig } from '../../types/api';
import { findSemanticMatches } from '../../utils/textHighlighting';
import {
  extractCitedNumbers,
  normalizeClaimText,
  parseSectionBreadcrumb,
} from '../citations/CitedContent';

/**
 * LLM-highlighted citation excerpts for the Brief tab.
 *
 * After a section's research completes (references validated), each cited
 * source's excerpt is run through the existing semantic-highlighting LLM with
 * the claim it supports — the sentence(s) carrying that `[n]` marker — so the
 * hover card can emphasise exactly the part of the excerpt backing the claim.
 * When the LLM returns nothing the excerpt simply renders in full, unmarked.
 */

// Sentences end at ./!/? followed by whitespace; markdown headings and list
// items break sentences too. Good enough for claim extraction — the claim only
// steers the highlighter, it is never shown to the user.
const SENTENCE_SPLIT_RE = /(?<=[.!?])\s+|\n+/;

// A source is often cited from several sentences; each claim is highlighted
// separately so every hover card is specific to the sentence it belongs to.
// There is no cap — a brief should have highlights everywhere it cites.
// Matches shorter than this are fragments ("er > Education --") that mislead
// more than they help — drop them.
const MIN_MATCH_CHARS = 30;

// Excerpts highlighted at once. Each is one LLM call taking ~10-15s, so a
// serial pass over a heavily-cited section took minutes; a small pool keeps
// the section usable quickly without flooding the highlight endpoint.
// Kept below the browser's ~6 connections per origin so a hover-triggered
// call, plus the brief's own saves, always have a socket free.
const HIGHLIGHT_CONCURRENCY = 3;

// A hover on an un-highlighted citation must be served at once. Background
// workers park between calls while any on-demand request is outstanding, and
// the smaller pool above leaves browser connections free for it — otherwise
// the hover queues behind a section's worth of calls and takes minutes.
let priorityInFlight = 0;
// Bounded: a slow (or stuck) hover request must not stall the whole backfill,
// so workers yield for at most this long before carrying on regardless.
const PRIORITY_YIELD_MS = 15000;
const waitForPriority = async (): Promise<void> => {
  const until = Date.now() + PRIORITY_YIELD_MS;
  while (priorityInFlight > 0 && Date.now() < until) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
};

// Completed excerpts to collect before publishing them to the UI, so cards
// fill in batches instead of one re-render per source.
const HIGHLIGHT_BATCH = 3;

/**
 * Every sentence of the section that cites source `n`, individually — cleaned
 * of markers/markdown for the LLM but keyed by `normalizeClaimText` so the
 * renderer can find the entry for the sentence being hovered.
 */
export const extractClaimsForCitation = (
  markdown: string,
  n: number,
): Array<{ key: string; prose: string }> => {
  const marker = new RegExp(`\\[(?:\\d+,\\s*)*${n}(?:,\\s*\\d+)*\\]`);
  const sentences = markdown
    .split(SENTENCE_SPLIT_RE)
    .map((s) => s.trim())
    .filter(Boolean);
  const out: Array<{ key: string; prose: string }> = [];
  const seen = new Set<string>();
  for (const s of sentences) {
    if (!marker.test(s)) continue;
    const key = normalizeClaimText(s);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push({ key, prose: key });
  }
  return out;
};

export interface HighlightSectionArgs {
  content: string;
  sources: SourceReference[];
  threshold: number;
  modelConfig?: SummaryModelConfig | null;
  // Abort check — polled between sources so a stale run stops early.
  isStale?: () => boolean;
  // Called after each source resolves with the full source list (enriched so
  // far + untouched rest), so the UI can show snippets as they arrive instead
  // of waiting for the whole section.
  onPartial?: (sources: SourceReference[]) => void;
}

/**
 * Compute LLM highlight matches for every cited source's excerpt, serially
 * (matching the app's post-search highlighting pattern). Match offsets are
 * relative to the excerpt *body* (after the heading-breadcrumb line the hover
 * card splits off). Sources that fail or return nothing keep no matches — the
 * hover card falls back to the full excerpt.
 */
export const highlightSectionSources = async ({
  content,
  sources,
  threshold,
  modelConfig,
  isStale,
  onPartial,
}: HighlightSectionArgs): Promise<SourceReference[]> => {
  const cited = new Set(extractCitedNumbers(content));
  const out = sources.slice();
  // Which sources still need a pass: cited, has text, never attempted.
  const queue = sources
    .map((source, at) => ({ source, at }))
    .filter(
      ({ source }) =>
        source.index != null &&
        cited.has(source.index) &&
        !!source.text &&
        source.claimMatches === undefined,
    );

  // Run several at a time. Serially, a section citing 50 sources took ~10
  // minutes at ~12s per LLM call, so highlights effectively never showed up
  // for the section the user had just researched.
  let next = 0;
  let sinceFlush = 0;
  const flush = (): void => {
    if (!sinceFlush) return;
    sinceFlush = 0;
    onPartial?.(out.slice());
  };
  const worker = async (): Promise<void> => {
    for (;;) {
      await waitForPriority();
      const slot = next++;
      if (slot >= queue.length || isStale?.()) return;
      const { source, at } = queue[slot];
      out[at] = await enrichSource(source, content, threshold, modelConfig, isStale);
      if (out[at].claimMatches?.length) sinceFlush += 1;
      // Publish a batch at a time rather than per source: the hover cards fill
      // in visibly as the pool completes waves, without a re-render each call.
      if (sinceFlush >= HIGHLIGHT_BATCH) flush();
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(HIGHLIGHT_CONCURRENCY, queue.length) }, worker),
  );
  flush();
  return out;
};

/**
 * Highlight a single source on demand — used when a hover card opens on a
 * citation whose excerpt has not been enriched yet, so the card can fill in
 * while it is open rather than waiting for the background pass to reach it.
 */
export const highlightOneSource = async (args: {
  source: SourceReference;
  content: string;
  threshold: number;
  modelConfig?: SummaryModelConfig | null;
  // Called as each claim resolves, so an open card shows its first highlight
  // after one round-trip instead of waiting for every claim in the source.
  onProgress?: (partial: SourceReference) => void;
}): Promise<SourceReference> => {
  // Registered as priority work: background workers pause until this returns.
  priorityInFlight += 1;
  try {
    return await enrichSource(
      args.source,
      args.content,
      args.threshold,
      args.modelConfig,
      undefined,
      args.onProgress,
    );
  } finally {
    priorityInFlight = Math.max(0, priorityInFlight - 1);
  }
};

/**
 * Highlight one source's excerpt against each sentence citing it. Returns the
 * source unchanged when nothing matched or the LLM failed — the full excerpt
 * remains the hover-card fallback.
 */
const enrichSource = async (
  source: SourceReference,
  content: string,
  threshold: number,
  modelConfig: SummaryModelConfig | null | undefined,
  isStale?: () => boolean,
  onProgress?: (partial: SourceReference) => void,
): Promise<SourceReference> => {
  const claims = extractClaimsForCitation(content, source.index as number);
  const { body } = parseSectionBreadcrumb(source.text || '');
  const entries: NonNullable<SourceReference['claimMatches']> = [];
  try {
    // The claims are independent, so ask for them together: a source cited from
    // five sentences took five sequential LLM calls (~a minute) before the card
    // showed anything. One round of parallel calls resolves it in one call's
    // time. Order is preserved by index.
    const results = await Promise.all(
      claims.map(async ({ key, prose }) => {
        if (isStale?.()) return null;
        try {
          // null: brief citation highlighting is not tied to the results-tab
          // search — detach from the search usage context.
          const matches = (
            await findSemanticMatches(body, prose, threshold, modelConfig, null)
          ).filter((m) => m.end - m.start >= MIN_MATCH_CHARS);
          if (!matches.length) return null;
          const entry = { claim: key, matches };
          // Publish immediately: the open card gains this span now rather
          // than when the slowest claim of the source finishes.
          onProgress?.({ ...source, claimMatches: [...entries, entry] });
          entries.push(entry);
          return entry;
        } catch {
          return null;
        }
      }),
    );
    // entries was filled as each claim resolved (see onProgress above).
    void results;
  } catch {
    // Highlighting is an enhancement — keep whatever matched before the error.
  }
  // Always record the attempt (an empty list means "tried, nothing matched"),
  // so resuming an interrupted run only retries sources never attempted.
  return { ...source, claimMatches: entries };
};
