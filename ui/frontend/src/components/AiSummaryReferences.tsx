import React from 'react';
import { SearchResult } from '../types/api';
import { buildCitationSequenceMap, extractCitedNumbers } from '../utils/citations';

interface AiSummaryReferencesProps {
  summaryText: string;
  results: SearchResult[];
  onResultClick: (result: SearchResult) => void;
}

interface CitedRef {
  sequential: number;
  result: SearchResult;
}

export interface DocumentGroup {
  title: string;
  organization?: string;
  year?: string;
  refs: CitedRef[];
}

export const buildGroupedReferences = (
  summaryText: string,
  results: SearchResult[]
): DocumentGroup[] => {
  const sortedCitations = extractCitedNumbers(summaryText);
  const sequenceMap = buildCitationSequenceMap(summaryText);
  const groupMap = new Map<string, DocumentGroup>();
  const groupOrder: string[] = [];

  sortedCitations.forEach((origNum) => {
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
      sequential: sequenceMap.get(origNum)!,
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
          {' | '}
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
