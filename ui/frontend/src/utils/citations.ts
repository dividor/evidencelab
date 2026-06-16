/**
 * Single source of truth for parsing and (re)numbering the `[N]` citation
 * markers the AI summary endpoint emits.
 *
 * The on-screen summary, the on-screen References list, the Word (.docx)
 * export, and the research HTML export all need to agree on:
 *   1. which numbers a summary cites,
 *   2. how those numbers are renumbered into a clean, sequential `1..k`
 *      run (in citation order), and
 *   3. how cited results are grouped, by document, into a References list.
 *
 * Previously each consumer carried its own copy of this logic. They drifted —
 * notably the docx export rendered the *original* citation number inline while
 * renumbering its References section, so the export disagreed with itself and
 * with the screen. Centralising the logic here guarantees every surface shows
 * identical citation numbers by construction.
 */
import { SearchResult } from '../types/api';

/** Matches inline citations like `[1]`, `[1, 3]`, `[1,3,5]`. */
export const CITATION_REGEX = /\[(\d+(?:,\s*\d+)*)\]/g;

/** Parse the comma-separated numbers inside a single `[...]` marker. */
export const parseCitationNumbers = (rawNumbers: string): number[] =>
  rawNumbers.split(',').map((item) => parseInt(item.trim(), 10));

/** The unique citation numbers referenced anywhere in the summary, sorted
 *  ascending. This ascending order *is* the canonical citation order used for
 *  renumbering — keep it identical across every consumer. */
export const extractCitedNumbers = (summaryText: string): number[] => {
  const cited = new Set<number>();
  const re = new RegExp(CITATION_REGEX.source, 'g');
  let match;
  while ((match = re.exec(summaryText)) !== null) {
    parseCitationNumbers(match[1]).forEach((num) => cited.add(num));
  }
  return Array.from(cited).sort((a, b) => a - b);
};

/** Map each original citation number to its sequential display number
 *  (`1..k`, in citation order). This is the renumbering the on-screen summary
 *  applies to inline `[N]` markers, and the docx/HTML exports must apply the
 *  same map so their inline markers agree with the screen. */
export const buildCitationSequenceMap = (
  summaryText: string,
): Map<number, number> => {
  const citationMapping = new Map<number, number>();
  extractCitedNumbers(summaryText).forEach((origNum, seqIdx) => {
    citationMapping.set(origNum, seqIdx + 1);
  });
  return citationMapping;
};

export interface CitedRef {
  /** The renumbered, sequential display number for this citation. */
  sequential: number;
  result: SearchResult;
}

export interface DocumentGroup {
  title: string;
  organization?: string;
  year?: string;
  refs: CitedRef[];
}

/** Group the summary's citations by document title, in citation order, with
 *  each citation carrying its sequential display number. Used to render the
 *  "References:" list on screen and in every export. */
export const buildGroupedReferences = (
  summaryText: string,
  results: SearchResult[],
): DocumentGroup[] => {
  const sortedCitations = extractCitedNumbers(summaryText);
  const groupMap = new Map<string, DocumentGroup>();
  const groupOrder: string[] = [];

  sortedCitations.forEach((origNum, seqIdx) => {
    const resultIndex = origNum - 1;
    if (resultIndex < 0 || resultIndex >= results.length) return;

    const result = results[resultIndex];
    const key = result.title;

    if (!groupMap.has(key)) {
      groupMap.set(key, {
        title: result.title,
        organization: result.organization,
        year: result.year,
        refs: [],
      });
      groupOrder.push(key);
    }

    groupMap.get(key)!.refs.push({ sequential: seqIdx + 1, result });
  });

  return groupOrder.map((key) => groupMap.get(key)!);
};
