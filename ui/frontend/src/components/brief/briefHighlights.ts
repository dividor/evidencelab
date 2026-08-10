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

// A source is often cited from several sentences; highlighting each claim
// separately keeps every hover card specific. Cap the per-source claim count
// so one heavily-cited source can't monopolise the (serial) LLM budget.
const MAX_CLAIMS_PER_SOURCE = 4;

// Matches shorter than this are fragments ("er > Education --") that mislead
// more than they help — drop them.
const MIN_MATCH_CHARS = 30;

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
    if (out.length >= MAX_CLAIMS_PER_SOURCE) break;
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
  const out: SourceReference[] = [];
  for (const source of sources) {
    if (isStale?.()) return out.concat(sources.slice(out.length));
    if (
      source.index == null ||
      !cited.has(source.index) ||
      !source.text ||
      source.claimMatches?.length
    ) {
      out.push(source);
      continue;
    }
    const enriched = await enrichSource(source, content, threshold, modelConfig, isStale);
    out.push(enriched);
    if (enriched !== source) onPartial?.(out.concat(sources.slice(out.length)));
  }
  return out;
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
): Promise<SourceReference> => {
  const claims = extractClaimsForCitation(content, source.index as number);
  const { body } = parseSectionBreadcrumb(source.text || '');
  const entries: NonNullable<SourceReference['claimMatches']> = [];
  try {
    for (const { key, prose } of claims) {
      if (isStale?.()) break;
      const matches = (await findSemanticMatches(body, prose, threshold, modelConfig)).filter(
        (m) => m.end - m.start >= MIN_MATCH_CHARS,
      );
      if (matches.length) entries.push({ claim: key, matches });
    }
  } catch {
    // Highlighting is an enhancement — keep whatever matched before the error.
  }
  return entries.length ? { ...source, claimMatches: entries } : source;
};
