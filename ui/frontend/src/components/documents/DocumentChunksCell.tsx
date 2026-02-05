import React from 'react';

interface DocumentChunksCellProps {
  doc: any;
  onViewChunks: (doc: any) => void;
}

export const DocumentChunksCell: React.FC<DocumentChunksCellProps> = ({ doc, onViewChunks }) => (
  <td>
    {doc.status === 'indexed' && doc.id && (
      <a
        onClick={(event) => {
          event.preventDefault();
          onViewChunks(doc);
        }}
        href="#"
        className="doc-link"
      >
        Chunks
      </a>
    )}
  </td>
);
