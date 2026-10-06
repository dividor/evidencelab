import React, { useState } from 'react';
import { DocumentsTable } from './documents/DocumentsTable';
import { DocumentsModals } from './documents/DocumentsModals';
import { useDocumentsState } from './documents/useDocumentsState';
import { BulkSummaryModal } from './documents/summary/BulkSummaryModal';
import { ReprocessSummaryChoice } from './documents/summary/ReprocessSummaryChoice';
import { SummaryBulkBar } from './documents/summary/SummaryBulkBar';
import { useDocumentSelection } from './documents/summary/useDocumentSelection';
import { useSummaryAdmin } from './documents/summary/useSummaryAdmin';
import './documents/summary/documentSummary.css';
import type { SummaryModelConfig } from '../types/api';
import type { DocumentSummaryDefaults } from '../types/auth';

interface DocumentsProps {
  dataSource?: string;
  semanticHighlightModelConfig?: SummaryModelConfig | null;
  dataSourceConfig?: import('../App').DataSourceConfigItem;
  /** The summarization model of the selected model combo (used to regenerate summaries). */
  summaryModelConfig?: SummaryModelConfig | null;
  /** The team's defaults for summaries generated here. */
  summaryGroupDefaults?: DocumentSummaryDefaults | null;
}

export const Documents: React.FC<DocumentsProps> = ({
  dataSource = '',
  semanticHighlightModelConfig,
  dataSourceConfig,
  summaryModelConfig,
  summaryGroupDefaults,
}) => {
  const state = useDocumentsState(dataSource, dataSourceConfig);
  const metadataPanelFields = dataSourceConfig?.metadata_panel_fields
    || dataSourceConfig?.filter_fields
    || {};
  // Administrators can edit and regenerate summaries, one or many at a time.
  const { admin: summaryAdmin, error: summaryAdminError } = useSummaryAdmin({
    enabled: state.canModerate,
    dataSource,
    groupDefaults: summaryGroupDefaults,
    model: summaryModelConfig,
    onSaved: state.applySavedSummary,
  });
  const selection = useDocumentSelection();
  const [bulkOpen, setBulkOpen] = useState(false);
  const pageDocuments = state.getSortedAndFilteredDocuments();

  return (
    <div className="statistics-container">
      <div className="statistics-content">
        <h2 className="statistics-title">Documents Library</h2>
        {summaryAdminError && <p className="doc-summary-error" role="alert">{summaryAdminError}</p>}
        {summaryAdmin && (
          <SummaryBulkBar selection={selection} pageDocuments={pageDocuments} onRegenerate={() => setBulkOpen(true)} />
        )}
        <DocumentsTable
          documents={pageDocuments}
          selection={summaryAdmin ? selection : null}
          sortField={state.sortField}
          sortDirection={state.sortDirection}
          onSort={state.handleSort}
          onFilterClick={state.handleFilterClick}
          hasActiveFilter={state.hasActiveFilter}
          onOpenSummary={state.handleOpenSummary}
          onOpenTaxonomyModal={state.handleOpenTaxonomyModal}
          onOpenToc={state.handleOpenToc}
          onOpenMetadata={state.handleOpenMetadata}
          onOpenTimeline={state.handleOpenTimeline}
          onOpenLogs={state.handleOpenLogs}
          onViewChunks={state.handleViewChunks}
          onReprocess={state.handleReprocess}
          onOpenQueue={state.handleOpenQueue}
          canModerate={state.canModerate}
          moderatingDocId={state.moderatingDocId}
          onToggleHidden={state.handleToggleHidden}
          onOpenPdfPreview={state.handleOpenPdfPreview}
          reprocessingDocId={state.reprocessingDocId}
          filterText={state.filterText}
          onFilterTextChange={state.handleFilterTextChange}
          selectedCategory={state.selectedCategory}
          chartView={state.chartView}
          currentPage={state.currentPage}
          totalPages={state.totalPages}
          totalCount={state.totalCount}
          pageSize={state.pageSize}
          loadingTable={state.loadingTable}
          onRefresh={state.handleRefreshTable}
          onClearCategory={state.handleClearCategory}
          tableContainerRef={state.tableContainerRef}
          filterPopoverPosition={state.filterPopoverPosition}
          activeFilterColumn={state.activeFilterColumn}
          tempColumnFilters={state.tempColumnFilters}
          columnFilters={state.columnFilters}
          onTempFilterChange={state.handleTempFilterChange}
          onApplyFilter={state.applyFilter}
          onClearFilter={state.clearFilter}
          getCategoricalOptions={state.getCategoricalOptionsForColumn}
          onCloseFilterPopover={state.handleCloseFilterPopover}
          onPageChange={state.setCurrentPage}
          dataSourceConfig={dataSourceConfig}
          dataSource={dataSource}
        />

      </div>

      <DocumentsModals
        chunksModalOpen={state.chunksModalOpen}
        onCloseChunksModal={state.closeChunksModal}
        chunks={state.chunks}
        loadingChunks={state.loadingChunks}
        expandedChunks={state.expandedChunks}
        onToggleChunk={state.toggleChunk}
        onOpenPdfWithChunk={state.handleOpenPDFWithChunk}
        pdfViewerOpen={state.pdfViewerOpen}
        onClosePdfViewer={state.handleClosePDFViewer}
        pdfViewerDocId={state.pdfViewerDocId}
        pdfViewerChunkId={state.pdfViewerChunkId}
        pdfViewerPageNum={state.pdfViewerPageNum}
        pdfViewerTitle={state.pdfViewerTitle}
        pdfViewerBBox={state.pdfViewerBBox}
        selectedDocMetadata={state.selectedDocMetadata}
        onOpenMetadata={state.handleOpenMetadata}
        summaryModalOpen={state.summaryModalOpen}
        onCloseSummaryModal={state.closeSummaryModal}
        selectedSummary={state.selectedSummary}
        selectedSummaryTitle={state.selectedSummaryTitle}
        selectedSummaryDocId={state.selectedSummaryDocId}
        taxonomyModalOpen={state.taxonomyModalOpen}
        onCloseTaxonomyModal={state.closeTaxonomyModal}
        selectedTaxonomyValue={state.selectedTaxonomyValue}
        selectedTaxonomyDefinition={state.selectedTaxonomyDefinition}
        selectedTaxonomyName={state.selectedTaxonomyName}
        selectedTaxonomyDocId={state.selectedTaxonomyDocId}
        selectedTaxonomyDocTitle={state.selectedTaxonomyDocTitle}
        selectedTaxonomyDocSummary={state.selectedTaxonomyDocSummary}
        metadataModalOpen={state.metadataModalOpen}
        onCloseMetadataModal={state.closeMetadataModal}
        selectedMetadataDoc={state.selectedMetadataDoc}
        timelineModalOpen={state.timelineModalOpen}
        onCloseTimelineModal={state.closeTimelineModal}
        selectedTimelineDoc={state.selectedTimelineDoc}
        queueModalOpen={state.queueModalOpen}
        onCloseQueueModal={state.closeQueueModal}
        dataSource={dataSource}
        logsModalOpen={state.logsModalOpen}
        onCloseLogsModal={state.closeLogsModal}
        selectedLogsDocId={state.selectedLogsDocId}
        selectedLogsDocTitle={state.selectedLogsDocTitle}
        tocModalOpen={state.tocModalOpen}
        onCloseTocModal={state.closeTocModal}
        toc={state.selectedSummary}
        selectedTocDocId={state.selectedTocDocId}
        selectedTocPdfUrl={state.selectedTocPdfUrl}
        onTocUpdated={state.handleTocUpdated}
        selectedTocApproved={state.selectedTocApproved}
        onTocApprovedChange={state.handleTocApprovedChange}
        selectedTocPageCount={state.selectedTocPageCount}
        semanticHighlightModelConfig={semanticHighlightModelConfig}
        metadataPanelFields={metadataPanelFields}
        onOpenSummaryFromMetadata={state.handleOpenSummary}
        onOpenTocFromMetadata={state.handleOpenToc}
        summaryAdmin={summaryAdmin}
        summaryProvenance={state.selectedSummaryProvenance}
      />
      {summaryAdmin && bulkOpen && (
        <BulkSummaryModal
          isOpen={bulkOpen}
          onClose={() => setBulkOpen(false)}
          admin={summaryAdmin}
          documents={selection.documents}
          onFinished={selection.clear}
        />
      )}
      <ReprocessSummaryChoice doc={state.reprocessChoiceDoc} onChoose={state.handleReprocessChoice} />
    </div >
  );
};
