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

const buildCitedResults = (
  summaryText: string,
  results: SearchResult[]
): Array<{ sequential: number; result: SearchResult }> => {
  const sortedCitations = extractCitationNumbers(summaryText);
  const citedResultsList: Array<{ sequential: number; result: SearchResult }> = [];

  sortedCitations.forEach((origNum, seqIdx) => {
    const resultIndex = origNum - 1;
    if (resultIndex >= 0 && resultIndex < results.length) {
      citedResultsList.push({
        sequential: seqIdx + 1,
        result: results[resultIndex],
      });
    }
  });

  return citedResultsList;
};

export const AiSummaryReferences: React.FC<AiSummaryReferencesProps> = ({
  summaryText,
  results,
  onResultClick,
}) => {
  const citedResultsList = buildCitedResults(summaryText, results);

  if (citedResultsList.length === 0) {
    return null;
  }

  return (
    <div className="ai-summary-references">
      <h4>References:</h4>
      <ul>
        {citedResultsList.map(({ sequential, result }) => (
          <li key={sequential}>
            <a
              href="#"
              onClick={(event: React.MouseEvent) => {
                event.preventDefault();
                onResultClick(result);
              }}
            >
              <span className="ai-summary-ref-number">[{sequential}]</span> {result.title}
              {result.page_num && `, page ${result.page_num}`}
              {result.organization && ` (${result.organization}`}
              {result.year && `${result.organization ? ', ' : '('}${result.year}`}
              {(result.organization || result.year) && ')'}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
};
