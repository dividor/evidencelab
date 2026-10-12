import React from 'react';

interface ReprocessSummaryChoiceProps {
  doc: { title?: string; summary_updated_by?: string } | null;
  /** true replaces the summary, false keeps it, null cancels the reprocess. */
  onChoose: (replaceSummary: boolean | null) => void;
}

/** Reprocessing a document whose summary was written or edited in the app. */
export const ReprocessSummaryChoice: React.FC<ReprocessSummaryChoiceProps> = ({ doc, onChoose }) => {
  if (!doc) return null;
  return (
    <div className="preview-overlay" onClick={() => onChoose(null)}>
      <div
        className="modal-panel doc-summary-choice"
        role="dialog"
        aria-label="Reprocess document"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2>Reprocess “{doc.title || 'Untitled'}”</h2>
        </div>
        <div className="modal-body">
          <p>
            Its summary was written or edited in the app
            {doc.summary_updated_by ? ` by ${doc.summary_updated_by}` : ''}. Reprocessing keeps that summary unless
            you choose to replace it with a new one from the pipeline.
          </p>
          <div className="doc-summary-actions">
            <button type="button" className="btn-sm" onClick={() => onChoose(null)}>
              Cancel
            </button>
            <button type="button" className="btn-sm" onClick={() => onChoose(true)}>
              Reprocess and replace the summary
            </button>
            <button type="button" className="btn-sm btn-primary" onClick={() => onChoose(false)}>
              Reprocess and keep the summary
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
