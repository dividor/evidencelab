import React from 'react';

interface ChunksModalProps {
  isOpen: boolean;
  onClose: () => void;
  chunks: any[];
  loading: boolean;
  expandedChunks: Set<number>;
  onToggleChunk: (index: number) => void;
  onOpenPdfWithChunk: (chunk: any) => void;
}

export const ChunksModal: React.FC<ChunksModalProps> = ({
  isOpen,
  onClose,
  chunks,
  loading,
  expandedChunks,
  onToggleChunk,
  onOpenPdfWithChunk,
}) => {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="chunks-modal-overlay" onClick={onClose}>
      <div className="chunks-modal" onClick={(event) => event.stopPropagation()}>
        <div className="chunks-modal-header">
          <h3>Document Chunks</h3>
          <button className="chunks-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <ChunksModalBody
          loading={loading}
          chunks={chunks}
          expandedChunks={expandedChunks}
          onToggleChunk={onToggleChunk}
          onOpenPdfWithChunk={onOpenPdfWithChunk}
        />
      </div>
    </div>
  );
};

const ChunksModalBody: React.FC<{
  loading: boolean;
  chunks: any[];
  expandedChunks: Set<number>;
  onToggleChunk: (index: number) => void;
  onOpenPdfWithChunk: (chunk: any) => void;
}> = ({ loading, chunks, expandedChunks, onToggleChunk, onOpenPdfWithChunk }) => {
  if (loading) {
    return (
      <div className="chunks-modal-content">
        <div className="chunks-loading">Loading chunks...</div>
      </div>
    );
  }

  if (chunks.length === 0) {
    return (
      <div className="chunks-modal-content">
        <div className="chunks-empty">No chunks found for this document.</div>
      </div>
    );
  }

  return (
    <div className="chunks-modal-content">
      <div className="chunks-list">
        {chunks.map((chunk, index) => (
          <ChunkItem
            key={index}
            chunk={chunk}
            index={index}
            expanded={expandedChunks.has(index)}
            onToggle={() => onToggleChunk(index)}
            onOpenPdf={() => onOpenPdfWithChunk(chunk)}
          />
        ))}
      </div>
    </div>
  );
};

const ChunkItem: React.FC<{
  chunk: any;
  index: number;
  expanded: boolean;
  onToggle: () => void;
  onOpenPdf: () => void;
}> = ({ chunk, index, expanded, onToggle, onOpenPdf }) => (
  <div className="chunk-item">
    <div className="chunk-header" onClick={onToggle}>
      <span className="chunk-toggle">{expanded ? '▼' : '▶'}</span>
      <div className="chunk-header-content">
        <div className="chunk-header-row1">
          <span className="chunk-title">
            Chunk {index + 1} - Page {chunk.page_num || 'N/A'}
            {chunk.page_num && (
              <>
                {' '}
                <a
                  href="#"
                  className="chunk-pdf-link"
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    onOpenPdf();
                  }}
                >
                  [View in PDF]
                </a>
              </>
            )}
          </span>
          <span className="chunk-length">{chunk.text?.length || 0} chars</span>
        </div>
        {(chunk.headings?.length > 0 || chunk.section_type) && (
          <div className="chunk-header-row2">
            <span className="chunk-heading">
              {chunk.headings && chunk.headings.length > 0
                ? chunk.headings[chunk.headings.length - 1]
                : ''}
            </span>
            <span className="chunk-tags">
              {chunk.section_type && (
                <span className={`chunk-section-tag section-tag-${chunk.section_type}`}>
                  {chunk.section_type.replace(/_/g, ' ')}
                </span>
              )}
            </span>
          </div>
        )}
      </div>
    </div>
    {expanded && (
      <div className="chunk-content">
        <div className="chunk-text">{chunk.text || 'No text available'}</div>
        {chunk.headings && chunk.headings.length > 0 && (
          <div className="chunk-metadata">
            <strong>Headings:</strong> {chunk.headings.join(' > ')}
          </div>
        )}
      </div>
    )}
  </div>
);
