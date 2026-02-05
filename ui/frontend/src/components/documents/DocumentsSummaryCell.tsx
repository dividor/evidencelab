import React from 'react';
import ReactMarkdown from 'react-markdown';
import { buildSummaryDisplayText } from './documentsModalUtils';

interface DocumentsSummaryCellProps {
  summary: string;
  docTitle: string;
  onOpenSummary: (summary: string, docTitle: string) => void;
}

export const DocumentsSummaryCell: React.FC<DocumentsSummaryCellProps> = ({
  summary,
  docTitle,
  onOpenSummary,
}) => {
  if (!summary) {
    return <>-</>;
  }

  const displaySummary = buildSummaryDisplayText(summary);

  const shouldTruncate = displaySummary.length > 200;
  const displayText = shouldTruncate ? `${displaySummary.substring(0, 200)}...` : displaySummary;

  return (
    <div className="markdown-summary-cell">
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
              onOpenSummary(summary, docTitle);
            }}
            aria-label="See more"
          >
            See more
          </a>
        </>
      )}
    </div>
  );
};
