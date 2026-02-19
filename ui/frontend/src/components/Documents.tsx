import React from 'react';
import { DocumentsChart } from './documents/DocumentsChart';
import { DocumentsTable } from './documents/DocumentsTable';
import { DocumentsModals } from './documents/DocumentsModals';
import { useDocumentsState } from './documents/useDocumentsState';

interface DocumentsProps {
  dataSource?: string;
  semanticHighlightModelConfig?: import('../types/api').SummaryModelConfig | null;
  dataSourceConfig?: import('../App').DataSourceConfigItem;
}

export const Documents: React.FC<DocumentsProps> = ({
  dataSource = 'uneg',
  semanticHighlightModelConfig,
  dataSourceConfig,
}) => {
  const state = useDocumentsState(dataSource, dataSourceConfig);

  return (
    <div className="statistics-container">
      <div className="statistics-content">
        <h2 className="statistics-title">Documents Library</h2>
        <DocumentsTable
          documents={state.getSortedAndFilteredDocuments()}
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
        taxonomyModalOpen={state.taxonomyModalOpen}
        onCloseTaxonomyModal={state.closeTaxonomyModal}
        selectedTaxonomyValue={state.selectedTaxonomyValue}
        selectedTaxonomyDefinition={state.selectedTaxonomyDefinition}
        selectedTaxonomyName={state.selectedTaxonomyName}
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
      />
    </div >
  );
};
