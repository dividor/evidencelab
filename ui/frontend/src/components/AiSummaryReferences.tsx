import React from 'react';
import { SearchResult } from '../types/api';

interface AiSummaryReferencesProps {
  summaryText: string;
  results: SearchResult[];
  onResultClick: (result: SearchResult) => void;
}

const CITATION_REGEX = /\[(\d+(?:,\s*\d+)*)\]/g;

const parseCitationNumbers = (rawNumbers: string): number[] =>
  rawNumbers.split(',').map((item) => parseInt(item.trim(), 10));

const extractCitationNumbers = (summaryText: string): number[] => {
  const citedNumbers = new Set<number>();
  let match;

  while ((match = CITATION_REGEX.exec(summaryText)) !== null) {
    const numbers = parseCitationNumbers(match[1]);
    numbers.forEach((num) => citedNumbers.add(num));
  }

  return Array.from(citedNumbers).sort((a, b) => a - b);
};

interface CitedRef {
  sequential: number;
  result: SearchResult;
}

interface DocumentGroup {
  title: string;
  organization?: string;
  year?: string;
  refs: CitedRef[];
}

const buildGroupedReferences = (
  summaryText: string,
  results: SearchResult[]
): DocumentGroup[] => {
  const sortedCitations = extractCitationNumbers(summaryText);
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

    groupMap.get(key)!.refs.push({
      sequential: seqIdx + 1,
      result,
    });
  });

  return groupOrder.map((key) => groupMap.get(key)!);
};

export const AiSummaryReferences: React.FC<AiSummaryReferencesProps> = ({
  summaryText,
  results,
  onResultClick,
}) => {
  const groups = buildGroupedReferences(summaryText, results);

  if (groups.length === 0) {
    return null;
  }

  return (
    <div className="ai-summary-references">
      <h4>References:</h4>
      {groups.map((group) => (
        <div key={group.title} className="ai-summary-ref-group">
          {group.title}
          {group.organization && `, ${group.organization}`}
          {group.year && `, ${group.year}`}
          {' : '}
          {group.refs.map(({ sequential, result }, idx) => (
            <React.Fragment key={sequential}>
              {idx > 0 && ' '}
              <a
                href="#"
                className="ai-summary-ref-link"
                onClick={(event: React.MouseEvent) => {
                  event.preventDefault();
                  onResultClick(result);
                }}
              >
                <span className="citation-doc-group">
                  <span className="ai-summary-citation">{sequential}</span>
                </span>
                {result.page_num ? ` p.${result.page_num}` : ''}
              </a>
            </React.Fragment>
          ))}
        </div>
      ))}
    </div>
  );
};
