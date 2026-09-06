import React from 'react';
import type { SearchResult } from '../types/api';

interface DocumentResultGroupProps {
  /** Excerpts from one document, best match first. */
  results: SearchResult[];
  expanded: boolean;
  onToggle: () => void;
  /** Renders one excerpt card; shared with the flat list so cards look identical. */
  renderResult: (result: SearchResult) => React.ReactNode;
}

const documentMeta = (result: SearchResult): string => {
  const organization = result.organization || result.metadata?.organization || '';
  const year = result.year || result.metadata?.year || '';
  return [organization, year].filter(Boolean).join(' \u00b7 ');
};

/**
 * One collapsible row per document on the Search screen ("Group by document").
 * The header shows the title, organization and year, and how many excerpts
 * matched; expanding it shows the same excerpt cards as the flat list.
 */
export const DocumentResultGroup: React.FC<DocumentResultGroupProps> = ({
  results,
  expanded,
  onToggle,
  renderResult,
}) => {
  const first = results[0];
  const count = results.length;
  const meta = documentMeta(first);
  const label = `${count} ${count === 1 ? 'excerpt' : 'excerpts'}`;
  return (
    <section className={`result-group${expanded ? ' result-group-expanded' : ''}`}>
      <button
        type="button"
        className="result-group-header"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span className="result-group-chevron" aria-hidden="true">{expanded ? '\u25be' : '\u25b8'}</span>
        <span className="result-group-title">{first.translated_title || first.title}</span>
        {meta && <span className="result-group-meta">{meta}</span>}
        <span className="result-group-count">{label}</span>
      </button>
      {expanded && <div className="result-group-body">{results.map(renderResult)}</div>}
    </section>
  );
};
