import React from 'react';
import type { SearchResult } from '../types/api';

interface DocumentResultGroupProps {
  /** Excerpts from one document, best match first. */
  results: SearchResult[];
  /** Cover image for the document, or null when none can be built. */
  thumbnailUrl: string | null;
  expanded: boolean;
  onToggle: () => void;
  /** Renders one excerpt card; shared with the flat list so cards look identical. */
  renderResult: (result: SearchResult) => React.ReactNode;
}

const documentSource = (result: SearchResult): string =>
  result.organization || result.metadata?.organization || '';
const documentYear = (result: SearchResult): string =>
  String(result.year || result.metadata?.year || '');

/**
 * One collapsible row per document on the Search screen ("Group by document").
 * The header shows the cover thumbnail, title, source and year, and how many
 * excerpts matched; expanding it shows the same excerpt cards as the flat list.
 */
export const DocumentResultGroup: React.FC<DocumentResultGroupProps> = ({
  results,
  thumbnailUrl,
  expanded,
  onToggle,
  renderResult,
}) => {
  const first = results[0];
  const count = results.length;
  const source = documentSource(first);
  const year = documentYear(first);
  const label = `${count} ${count === 1 ? 'excerpt' : 'excerpts'}`;
  return (
    <section className={`result-group${expanded ? ' result-group-expanded' : ''}`}>
      <button
        type="button"
        className="result-group-header"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span className={`result-group-chevron${expanded ? ' result-group-chevron-open' : ''}`} aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </span>
        <span className="result-group-thumb" aria-hidden="true">
          {thumbnailUrl && (
            <img
              src={thumbnailUrl}
              alt=""
              className="result-group-thumb-img"
              onError={(event) => {
                (event.target as HTMLImageElement).style.display = 'none';
              }}
            />
          )}
        </span>
        <span className="result-group-text">
          <span className="result-group-title">{first.translated_title || first.title}</span>
          {(source || year) && (
            <span className="result-group-meta">
              {source && <span className="result-group-source">{source}</span>}
              {source && year && ' \u00b7 '}
              {year && <span className="result-group-year">{year}</span>}
            </span>
          )}
        </span>
        <span className="result-group-count">{label}</span>
      </button>
      {expanded && <div className="result-group-body">{results.map(renderResult)}</div>}
    </section>
  );
};
