import React from 'react';

interface DocumentActionsCellProps {
  doc: any;
  reprocessingDocId: string | null;
  onReprocess: (doc: any) => void;
  onOpenQueue: () => void;
}

export const DocumentActionsCell: React.FC<DocumentActionsCellProps> = ({
  doc,
  reprocessingDocId,
  onReprocess,
  onOpenQueue,
}) => (
  <td>
    {doc.id && (
      <div
        className="reprocess-actions"
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}
      >
        <button
          onClick={() => onReprocess(doc)}
          className="reprocess-btn"
          disabled={reprocessingDocId === doc.id}
          title="Reprocess document through full pipeline"
        >
          {reprocessingDocId === doc.id ? 'Processing...' : 'Reprocess'}
        </button>
        <a
          href="#"
          className="queue-link"
          style={{ fontSize: '11px', color: '#666', textDecoration: 'underline' }}
          onClick={(event) => {
            event.preventDefault();
            onOpenQueue();
          }}
        >
          View Queue
        </a>
      </div>
    )}
  </td>
);

interface DocumentModerationCellProps {
  doc: any;
  /** Doc id whose hide/restore request is in flight, if any */
  moderatingDocId: string | null;
  onToggleHidden: (doc: any) => void;
}

/**
 * Hide a document from every user-facing path (search, listings, assistant,
 * MCP/A2A) or restore it. Shown only to superusers; see the Content policy in
 * the Terms and docs/admin/user-administration.md.
 */
export const DocumentModerationCell: React.FC<DocumentModerationCellProps> = ({
  doc,
  moderatingDocId,
  onToggleHidden,
}) => (
  <td>
    {doc.id && (
      <button
        onClick={() => onToggleHidden(doc)}
        className="reprocess-btn"
        disabled={moderatingDocId === doc.id}
        title={doc.hidden
          ? 'Restore this document to search and listings'
          : 'Hide this document from all users (content policy)'}
      >
        {moderatingDocId === doc.id ? 'Saving...' : doc.hidden ? 'Restore' : 'Hide'}
      </button>
    )}
  </td>
);
