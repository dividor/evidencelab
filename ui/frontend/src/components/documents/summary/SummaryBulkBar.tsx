import React from 'react';
import type { DocumentSelection, SelectableDoc } from './useDocumentSelection';

interface SummaryBulkBarProps {
  selection: DocumentSelection;
  /** The documents on the current page. */
  pageDocuments: SelectableDoc[];
  onRegenerate: () => void;
}

/** Select documents and start a bulk summary run (administrators). */
export const SummaryBulkBar: React.FC<SummaryBulkBarProps> = ({ selection, pageDocuments, onRegenerate }) => {
  const pageSelected = pageDocuments.length > 0 && pageDocuments.every((doc) => selection.isSelected(doc));
  return (
    <div className="doc-summary-bulk-bar">
      <label className="doc-summary-option">
        <input
          type="checkbox"
          checked={pageSelected}
          disabled={!pageDocuments.length}
          onChange={() => selection.setPage(pageDocuments, !pageSelected)}
        />
        <span>Select all on this page</span>
      </label>
      <span className="doc-summary-bulk-count">{selection.count} selected</span>
      <button type="button" className="btn-sm btn-primary" disabled={!selection.count} onClick={onRegenerate}>
        Regenerate summaries{selection.count ? ` (${selection.count})` : ''}
      </button>
      {selection.count > 0 && (
        <button type="button" className="btn-sm" onClick={selection.clear}>
          Clear selection
        </button>
      )}
    </div>
  );
};
