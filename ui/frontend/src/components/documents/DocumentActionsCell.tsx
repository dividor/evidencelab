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
