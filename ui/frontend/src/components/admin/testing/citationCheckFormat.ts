import type { BriefCitationCheckPassage, CitationVerdict } from '../../../types/testing';

// Labels and helpers shared by the brief citation check views.

export const VERDICT_ORDER: CitationVerdict[] = [
  'supported',
  'partially_supported',
  'unsupported',
  'cannot_assess',
];

export const VERDICT_LABEL: Record<CitationVerdict, string> = {
  supported: 'Supported',
  partially_supported: 'Partially supported',
  unsupported: 'Unsupported',
  cannot_assess: 'Cannot assess',
};

// Maps a verdict onto the harness's existing status colours.
export const VERDICT_TONE: Record<CitationVerdict, string> = {
  supported: 'completed',
  partially_supported: 'pending',
  unsupported: 'failed',
  cannot_assess: 'draft',
};

export interface PassageFilters {
  verdicts: Set<CitationVerdict>;
  flaggedOnly: boolean;
  quoteNotInSource: boolean;
  section: string;
  search: string;
}

export const EMPTY_FILTERS: PassageFilters = {
  verdicts: new Set(),
  flaggedOnly: false,
  quoteNotInSource: false,
  section: '',
  search: '',
};

const matchesSearch = (p: BriefCitationCheckPassage, needle: string): boolean => {
  const hay = [p.passage, p.documents, p.explanation, ...p.problems].join(' ').toLowerCase();
  return hay.includes(needle);
};

export const filterPassages = (
  passages: BriefCitationCheckPassage[],
  filters: PassageFilters,
): BriefCitationCheckPassage[] => {
  const needle = filters.search.trim().toLowerCase();
  return passages.filter(
    (p) =>
      (filters.verdicts.size === 0 || filters.verdicts.has(p.verdict)) &&
      (!filters.flaggedOnly || p.flagged) &&
      (!filters.quoteNotInSource || p.quote_not_in_source) &&
      (!filters.section || p.brief_section === filters.section) &&
      (!needle || matchesSearch(p, needle)),
  );
};

export const formatConfidence = (value?: number | null): string =>
  value === null || value === undefined ? '—' : value.toFixed(2);

// Plain-language explanations shown on hover, for readers who did not build
// the check. Keys match the summary tiles and the passages table columns.
export const VERDICT_HELP: Record<CitationVerdict, string> = {
  supported: 'Every factual element of the passage is stated in, or directly follows from, the cited excerpts.',
  partially_supported:
    'The core statement is in the excerpts, but at least one element is missing, overstated or altered.',
  unsupported: 'The cited excerpts do not back the core statement, or they contradict it.',
  cannot_assess:
    'The passage could not be judged: no source is stored for the citation number, the excerpts are empty, or the judge gave an unusable answer.',
};

export const SUMMARY_HELP: Record<string, string> = {
  passages: 'Sentences in the brief that carry a [n] citation. Each one is checked on its own.',
  flagged:
    'Passages with any verdict other than Supported. These are the ones to review by hand.',
  quote_not_in_source:
    'Passages where the judge backed its verdict with a quote that cannot be found in the cited excerpt. Treat those verdicts with extra care.',
  duration: 'Wall-clock time of the check.',
  tokens: 'Model tokens used by the judge across all passages.',
  cost: 'Estimated cost of the judge calls at the configured model rates.',
};

export const COLUMN_HELP: Record<string, string> = {
  passage_id: 'Position of the passage in the brief, counting cited sentences from the top.',
  section: 'The brief section the passage belongs to.',
  passage: 'The sentence from the brief, with its [n] markers removed.',
  cites:
    'The citation numbers the sentence carries. Click one to open that passage of the source document in Evidence Lab; hover it for the document title.',
  verdict:
    "The judge's conclusion after reading the passage and only the excerpts it cites. Hover a verdict for its definition.",
  confidence:
    'How sure the judge says it is, from 0 to 1. Low confidence on a Supported verdict is worth a second look.',
  quotes_verified:
    'Found / given: how many of the quotes the judge relied on could be located in the cited excerpt. "near" means the same words with small extraction differences.',
};

export const QUOTES_HELP =
  'The judge was asked to copy, word for word, the parts of the cited excerpts it relied on. ' +
  'Each quote was then searched for in the excerpt it names: "verbatim" means it was found exactly, ' +
  '"near" means the same words with small differences from PDF extraction, and "missing" means it ' +
  'could not be found, so that part of the reasoning may be invented. The quotes come from the ' +
  'check, not from the brief.';
