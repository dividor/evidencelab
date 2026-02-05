import React from 'react';
import QueueModal from '../QueueModal';
import LogsModal from '../LogsModal';
import TocModal from '../TocModal';
import { ChunksModal } from './ChunksModal';
import { PdfViewerOverlay } from './PdfViewerOverlay';
import { SummaryModal } from './SummaryModal';
import { MetadataModal } from './MetadataModal';
import { TimelineModal } from './TimelineModal';
import { TaxonomyModal } from './TaxonomyModal';
import { SummaryModelConfig } from '../../types/api';

interface DocumentsModalsProps {
  chunksModalOpen: boolean;
  onCloseChunksModal: () => void;
  chunks: any[];
  loadingChunks: boolean;
  expandedChunks: Set<number>;
  onToggleChunk: (index: number) => void;
  onOpenPdfWithChunk: (chunk: any) => void;
  pdfViewerOpen: boolean;
  onClosePdfViewer: () => void;
  pdfViewerDocId: string;
  pdfViewerChunkId: string;
  pdfViewerPageNum: number;
  pdfViewerTitle: string;
  pdfViewerBBox: any[];
  selectedDocMetadata: any;
  summaryModalOpen: boolean;
  onCloseSummaryModal: () => void;
  selectedSummary: string;
  selectedSummaryTitle: string;
  taxonomyModalOpen: boolean;
  onCloseTaxonomyModal: () => void;
  selectedTaxonomyValue: any;
  selectedTaxonomyDefinition: string;
  selectedTaxonomyName: string;
  metadataModalOpen: boolean;
  onCloseMetadataModal: () => void;
  selectedMetadataDoc: any;
  timelineModalOpen: boolean;
  onCloseTimelineModal: () => void;
  selectedTimelineDoc: any;
  queueModalOpen: boolean;
  onCloseQueueModal: () => void;
  dataSource: string;
  logsModalOpen: boolean;
  onCloseLogsModal: () => void;
  selectedLogsDocId: string;
  selectedLogsDocTitle: string;
  tocModalOpen: boolean;
  onCloseTocModal: () => void;
  toc: string;
  selectedTocDocId: string;
  selectedTocPdfUrl: string;
  onTocUpdated: (newToc: string) => void;
  selectedTocApproved: boolean;
  onTocApprovedChange: (approved: boolean) => void;
  selectedTocPageCount?: number | null;
  semanticHighlightModelConfig?: SummaryModelConfig | null;
}


export const DocumentsModals: React.FC<DocumentsModalsProps> = ({
  chunksModalOpen,
  onCloseChunksModal,
  chunks,
  loadingChunks,
  expandedChunks,
  onToggleChunk,
  onOpenPdfWithChunk,
  pdfViewerOpen,
  onClosePdfViewer,
  pdfViewerDocId,
  pdfViewerChunkId,
  pdfViewerPageNum,
  pdfViewerTitle,
  pdfViewerBBox,
  selectedDocMetadata,
  summaryModalOpen,
  onCloseSummaryModal,
  selectedSummary,
  selectedSummaryTitle,
  taxonomyModalOpen,
  onCloseTaxonomyModal,
  selectedTaxonomyValue,
  selectedTaxonomyDefinition,
  selectedTaxonomyName,
  metadataModalOpen,
  onCloseMetadataModal,
  selectedMetadataDoc,
  timelineModalOpen,
  onCloseTimelineModal,
  selectedTimelineDoc,
  queueModalOpen,
  onCloseQueueModal,
  dataSource,
  logsModalOpen,
  onCloseLogsModal,
  selectedLogsDocId,
  selectedLogsDocTitle,
  tocModalOpen,
  onCloseTocModal,
  toc,
  selectedTocDocId,
  selectedTocPdfUrl,
  onTocUpdated,
  selectedTocApproved,
  onTocApprovedChange,
  selectedTocPageCount,
  semanticHighlightModelConfig,
}) => (
  <>
    <ChunksModal
      isOpen={chunksModalOpen}
      onClose={onCloseChunksModal}
      chunks={chunks}
      loading={loadingChunks}
      expandedChunks={expandedChunks}
      onToggleChunk={onToggleChunk}
      onOpenPdfWithChunk={onOpenPdfWithChunk}
    />
    <PdfViewerOverlay
      isOpen={pdfViewerOpen}
      onClose={onClosePdfViewer}
      docId={pdfViewerDocId}
      chunkId={pdfViewerChunkId}
      pageNum={pdfViewerPageNum}
      title={pdfViewerTitle}
      bbox={pdfViewerBBox}
      metadata={selectedDocMetadata || {}}
      semanticHighlightModelConfig={semanticHighlightModelConfig}
    />
    <SummaryModal
      isOpen={summaryModalOpen}
      onClose={onCloseSummaryModal}
      summary={selectedSummary}
      title={selectedSummaryTitle}
    />
    <TaxonomyModal
      isOpen={taxonomyModalOpen}
      onClose={onCloseTaxonomyModal}
      taxonomyValue={selectedTaxonomyValue}
      definition={selectedTaxonomyDefinition}
      taxonomyName={selectedTaxonomyName}
    />
    <MetadataModal
      isOpen={metadataModalOpen}
      onClose={onCloseMetadataModal}
      metadataDoc={selectedMetadataDoc}
    />
    <TimelineModal
      isOpen={timelineModalOpen}
      onClose={onCloseTimelineModal}
      timelineDoc={selectedTimelineDoc}
    />
    <QueueModal isOpen={queueModalOpen} onClose={onCloseQueueModal} dataSource={dataSource} />
    <LogsModal
      isOpen={logsModalOpen}
      onClose={onCloseLogsModal}
      docId={selectedLogsDocId}
      docTitle={selectedLogsDocTitle}
      dataSource={dataSource}
    />
    <TocModal
      isOpen={tocModalOpen}
      onClose={onCloseTocModal}
      toc={toc}
      docId={selectedTocDocId}
      dataSource={dataSource}
      loading={false}
      pdfUrl={selectedTocPdfUrl}
      onTocUpdated={onTocUpdated}
      tocApproved={selectedTocApproved}
      onTocApprovedChange={onTocApprovedChange}
      pageCount={selectedTocPageCount}
    />
  </>
);
