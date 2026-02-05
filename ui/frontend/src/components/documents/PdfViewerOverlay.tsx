import React from 'react';
import { PDFViewer } from '../PDFViewer';
import { SummaryModelConfig } from '../../types/api';

interface PdfViewerOverlayProps {
  isOpen: boolean;
  onClose: () => void;
  docId: string;
  chunkId: string;
  pageNum: number;
  title: string;
  bbox: any[];
  metadata: any;
  semanticHighlightModelConfig?: SummaryModelConfig | null;
}

export const PdfViewerOverlay: React.FC<PdfViewerOverlayProps> = ({
  isOpen,
  onClose,
  docId,
  chunkId,
  pageNum,
  title,
  bbox,
  metadata,
  semanticHighlightModelConfig,
}) => {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="preview-panel" onClick={(event) => event.stopPropagation()}>
        <PDFViewer
          docId={docId}
          chunkId={chunkId}
          pageNum={pageNum}
          onClose={onClose}
          title={title}
          initialBBox={bbox}
          metadata={metadata}
          semanticHighlightModelConfig={semanticHighlightModelConfig}
        />
      </div>
    </div>
  );
};
