// The excerpt shown in a citation hover card. Chunk text is tidied, then laid
// out by the same renderer Search uses for result snippets (superscripts,
// bullet/number indentation) with the LLM-selected span(s) supporting the
// hovered claim highlighted in place.

import React from 'react';
import { renderTextWithInlineReferences } from '../../utils/textHighlighting';

/**
 * Tidy a raw chunk for reading: PDF extraction leaves runs of spaces
 * mid-sentence and inline footnote markers ("[^56]"), and lines arrive hard-
 * wrapped with stray leading whitespace. Line and paragraph breaks are kept so
 * the formatter can indent lists.
 */
export const formatExcerpt = (text: string): string =>
  text
    .replace(/\[\^\d+\]/g, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/[ \t]+([.,;:!?])/g, '$1')
    .split('\n')
    .map((line) => line.trim())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

export const CitationExcerpt: React.FC<{
  text: string;
  // The claim being supported; used as the highlighter's query context.
  claim?: string;
  // Spans the LLM picked out for that claim. Search's renderer re-finds them
  // by text, so formatting shifting the original offsets does not matter.
  matches?: Array<{ start: number; end: number; matchedText?: string }>;
}> = ({ text, claim, matches }) => {
  const spans = (matches || []).filter((m) => m.matchedText);
  return (
    <div className="citation-hover-body">
      {renderTextWithInlineReferences(
        formatExcerpt(text),
        // renderHighlightedText short-circuits on an empty query; the claim is
        // the meaningful context here and semantic matches take precedence.
        claim || 'excerpt',
        undefined,
        spans.length
          ? (spans as Array<{ start: number; end: number; matchedText: string }>)
          : undefined,
      )}
    </div>
  );
};
