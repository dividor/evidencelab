import React from 'react';
import type { SearchCoverage } from '../types/api';
import { approximateExtraDocuments, plural } from '../utils/resultsCoverage';

interface CoverageNoticeProps {
  /** Server-computed coverage for the current results page (null until a
   *  query search has run — the empty-query scroll path returns none). */
  coverage: SearchCoverage | null;
  /** True while the per-document cap ("broaden results" mode) is active. */
  broadenActive: boolean;
  /** True once the user dismissed the alert for this session. */
  dismissed: boolean;
  /** Re-run the search with a per-document cap so more documents appear. */
  onBroaden: () => void;
  /** Leave broaden mode: back to the uncapped ranking, where the top
   *  excerpts concentrate in the few best-matching documents. */
  onShowTopDocuments: () => void;
  /** Hide the alert for the rest of the session. */
  onDismiss: () => void;
}

/**
 * Contextual strip above the search results that appears only when the
 * server flagged the page as concentrated: the top-scoring excerpts come
 * from a handful of documents although many more documents matched the
 * query (typical for very broad terms). Offers a one-click "broaden"
 * action; while broaden mode is active it flips to a confirmation strip
 * with the way back.
 *
 * Deliberately NOT a static banner — it renders nothing in the common case
 * so the UI stays uncluttered (see docs/using-evidence-lab/search.md).
 */
export const CoverageNotice: React.FC<CoverageNoticeProps> = ({
  coverage,
  broadenActive,
  dismissed,
  onBroaden,
  onShowTopDocuments,
  onDismiss,
}) => {
  if (!coverage) return null;

  if (broadenActive) {
    return (
      <div className="coverage-notice" role="status" aria-live="polite">
        <span className="coverage-notice-text">
          Showing the top excerpts from{' '}
          <strong>{plural(coverage.documents_in_results, 'document')}</strong>.
        </span>
        <button
          type="button"
          className="coverage-notice-action"
          onClick={onShowTopDocuments}
        >
          Show only top documents
        </button>
      </div>
    );
  }

  if (!coverage.concentrated || dismissed) return null;

  const extraDocuments = approximateExtraDocuments(coverage);
  return (
    <div className="coverage-notice" role="status" aria-live="polite">
      <span className="coverage-notice-text">
        Only <strong>{plural(coverage.documents_in_results, 'document')}</strong>{' '}
        {coverage.documents_in_results === 1 ? 'contains' : 'contain'} the
        top-matching excerpts
        {extraDocuments > 0 && (
          <>
            {' '}
            — about <strong>{extraDocuments} more</strong> matched with lower
            relevance
          </>
        )}
        .
      </span>
      <button type="button" className="coverage-notice-action" onClick={onBroaden}>
        Show more documents
      </button>
      <button
        type="button"
        className="coverage-notice-dismiss"
        aria-label="Dismiss this notice"
        onClick={onDismiss}
      >
        &times;
      </button>
    </div>
  );
};
