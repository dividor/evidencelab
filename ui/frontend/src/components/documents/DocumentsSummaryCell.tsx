import React from 'react';
import ReactMarkdown from 'react-markdown';
import { buildSummaryDisplayText } from './documentsModalUtils';
import { SummaryProvenance, formatProvenance } from './summary/summaryProvenance';

interface DocumentsSummaryCellProps {
  summary: string;
  docTitle: string;
  onOpenSummary: (summary: string, docTitle: string) => void;
  /** Administrators can open an empty summary to write or generate one. */
  canEdit?: boolean;
  /** How, when and by whom the summary was made. */
  provenance?: SummaryProvenance | null;
}

export const DocumentsSummaryCell: React.FC<DocumentsSummaryCellProps> = ({
  summary,
  docTitle,
  onOpenSummary,
  canEdit = false,
  provenance = null,
}) => {
  const open = () => onOpenSummary(summary || '', docTitle);

  if (!summary) {
    return canEdit ? (
      <button type="button" className="doc-summary-add-link" onClick={open}>
        Add summary
      </button>
    ) : (
      <>-</>
    );
  }

  const displaySummary = buildSummaryDisplayText(summary);

  const shouldTruncate = displaySummary.length > 200;
  const displayText = shouldTruncate ? `${displaySummary.substring(0, 200)}...` : displaySummary;

  return (
    <div
      className="markdown-summary-cell markdown-summary-cell-clickable"
      role="button"
      tabIndex={0}
      title="Open the summary"
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          open();
        }
      }}
    >
      <ReactMarkdown
        components={{
          p: ({ node, ...props }) => <span {...props} />,
          ul: ({ node, ...props }) => <ul style={{ margin: '0', paddingLeft: '1.2em' }} {...props} />,
          ol: ({ node, ...props }) => <ol style={{ margin: '0', paddingLeft: '1.2em' }} {...props} />,
          li: ({ node, ...props }) => <li style={{ margin: '0' }} {...props} />,
          h1: ({ node, ...props }) => <strong style={{ display: 'block', margin: '0.5em 0 0.2em' }} {...props} />,
          h2: ({ node, ...props }) => <strong style={{ display: 'block', margin: '0.5em 0 0.2em' }} {...props} />,
          h3: ({ node, ...props }) => <strong style={{ display: 'block', margin: '0.4em 0 0.2em' }} {...props} />,
          h4: ({ node, ...props }) => <strong style={{ display: 'block', margin: '0.4em 0 0.2em' }} {...props} />,
          h5: ({ node, ...props }) => <strong {...props} />,
          h6: ({ node, ...props }) => <strong {...props} />,
        }}
      >
        {displayText}
      </ReactMarkdown>
      {shouldTruncate && (
        <>
          <br />
          <a
            className="see-more-link"
            href="#"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              open();
            }}
            aria-label="See more"
          >
            See more
          </a>
        </>
      )}
      {provenance && <div className="doc-summary-provenance">{formatProvenance(provenance)}</div>}
    </div>
  );
};
