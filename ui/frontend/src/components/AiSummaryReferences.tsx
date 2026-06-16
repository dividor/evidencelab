import React from 'react';
import { SearchResult } from '../types/api';
import { buildGroupedReferences } from '../utils/citations';

interface AiSummaryReferencesProps {
  summaryText: string;
  results: SearchResult[];
  onResultClick: (result: SearchResult) => void;
}

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
