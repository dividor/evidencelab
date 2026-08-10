import { SourceReference, SummaryModelConfig } from '../../types/api';
import { findSemanticMatches } from '../../utils/textHighlighting';
import { extractCitedNumbers, parseSectionBreadcrumb } from '../citations/CitedContent';

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

/** The sentence(s) of the section that cite source `n`, joined together. */
export const extractClaimForCitation = (markdown: string, n: number): string => {
  const marker = new RegExp(`\\[(?:\\d+,\\s*)*${n}(?:,\\s*\\d+)*\\]`);
  const sentences = markdown
    .split(SENTENCE_SPLIT_RE)
    .map((s) => s.trim())
    .filter(Boolean);
  const claims = sentences.filter((s) => marker.test(s));
  return claims
    .join(' ')
    // Strip citation markers and markdown decoration so the LLM sees prose.
    .replace(/\[(?:\d+,\s*)*\d+\]/g, '')
    .replace(/[#*_>`]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
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
      source.semanticMatches?.length
    ) {
      out.push(source);
      continue;
    }
    const claim = extractClaimForCitation(content, source.index);
    if (!claim) {
      out.push(source);
      continue;
    }
    const { body } = parseSectionBreadcrumb(source.text);
    try {
      const matches = await findSemanticMatches(body, claim, threshold, modelConfig);
      out.push(matches.length ? { ...source, semanticMatches: matches } : source);
      if (matches.length) onPartial?.(out.concat(sources.slice(out.length)));
    } catch {
      // Highlighting is an enhancement — the full excerpt remains the fallback.
      out.push(source);
    }
  }
  return out;
};
