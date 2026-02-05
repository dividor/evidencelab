import React from 'react';

interface DocumentStatusCellProps {
  doc: any;
  onOpenTimeline: (doc: any) => void;
  onOpenLogs: (doc: any) => void;
}

export const DocumentStatusCell: React.FC<DocumentStatusCellProps> = ({
  doc,
  onOpenTimeline,
  onOpenLogs,
}) => (
  <td>
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignItems: 'flex-start' }}>
      <span
        className={`status-badge status-${doc.status || 'downloaded'} ${
          doc.status === 'indexed' ? 'status-badge-success' : ''
        }`}
      >
        {doc.status || 'downloaded'}
      </span>
      <div style={{ display: 'flex', gap: '8px' }}>
        {doc.stages && (
          <a
            href="#"
            className="timeline-link"
            onClick={(event) => {
              event.preventDefault();
              onOpenTimeline(doc);
            }}
          >
            Timeline
          </a>
        )}
        {doc.id && doc.status && doc.status !== 'downloaded' && (
          <a
            href="#"
            className="timeline-link"
            onClick={(event) => {
              event.preventDefault();
              onOpenLogs(doc);
            }}
          >
            Logs
          </a>
        )}
      </div>
    </div>
  </td>
);
