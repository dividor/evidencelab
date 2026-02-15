import React from 'react';
import { DocumentsFilterPopover } from './DocumentsFilterPopover';
import { DocumentsPagination } from './DocumentsPagination';
import { DocumentsTableControls } from './DocumentsTableControls';
import { DocumentsTableRow } from './DocumentsTableRow';
import { SortableHeader } from './SortableHeader';

type SortDirection = 'asc' | 'desc';

interface DocumentsTableProps {
  documents: any[];
  sortField: string;
  sortDirection: SortDirection;
  onSort: (field: string) => void;
  onFilterClick: (column: string, event: React.MouseEvent<HTMLButtonElement>) => void;
  hasActiveFilter: (column: string) => boolean;
  onOpenSummary: (summary: string, docTitle: string) => void;
  onOpenTaxonomyModal?: (value: any, definition: string, taxonomyName: string) => void;
  onOpenToc: (doc: any) => void;
  onOpenMetadata: (doc: any) => void;
  onOpenTimeline: (doc: any) => void;
  onOpenLogs: (doc: any) => void;
  onViewChunks: (doc: any) => void;
  onReprocess: (doc: any) => void;
  onOpenQueue: () => void;
  reprocessingDocId: string | null;
  filterText: string;
  onFilterTextChange: (value: string) => void;
  selectedCategory: string | null;
  chartView: string;
  currentPage: number;
  totalPages: number;
  totalCount: number;
  pageSize: number;
  loadingTable: boolean;
  onRefresh: () => void;
  onClearCategory: () => void;
  tableContainerRef: React.RefObject<HTMLDivElement | null>;
  filterPopoverPosition: { top: number; left: number };
  activeFilterColumn: string | null;
  tempColumnFilters: Record<string, string>;
  columnFilters: Record<string, string>;
  onTempFilterChange: (column: string, value: string) => void;
  onApplyFilter: (column: string, value: string) => void;
  onClearFilter: (column: string) => void;
  getCategoricalOptions: (column: string) => string[];
  onCloseFilterPopover: () => void;
  onPageChange: (page: number) => void;
  dataSourceConfig?: import('../../App').DataSourceConfigItem;
  dataSource?: string;
}

// Generate sortable headers dynamically based on config
const generateSortableHeaders = (dataSourceConfig?: import('../../App').DataSourceConfigItem) => {
  const baseHeaders: Array<{
    key: string;
    label: string;
    filterable?: boolean;
  }> = [
    { key: 'title', label: 'Title', filterable: true },
    { key: 'organization', label: 'Organization', filterable: true },
    { key: 'status', label: 'Status', filterable: true },
    { key: 'document_type', label: 'Type', filterable: true },
    { key: 'published_year', label: 'Year', filterable: true },
    { key: 'language', label: 'Language', filterable: true },
  ];

  // Add taxonomy headers dynamically
  const taxonomies = dataSourceConfig?.pipeline?.tag?.taxonomies || {};
  const taxonomyHeaders = Object.keys(taxonomies).map((taxonomyKey) => ({
    key: taxonomyKey,
    label: `${taxonomies[taxonomyKey].name}\n(AI-generated : Experimental)`,
    filterable: true,
  }));

  const endHeaders: Array<{
    key: string;
    label: string;
    filterable?: boolean;
  }> = [
    { key: 'file_format', label: 'Format', filterable: true },
    { key: 'page_count', label: 'Pages' },
    { key: 'file_size_mb', label: 'Size (MB)' },
    { key: 'error_message', label: 'Error', filterable: true },
    { key: 'last_updated', label: 'Last updated' },
  ];

  return [...baseHeaders, ...taxonomyHeaders, ...endHeaders];
};

const TopScrollbar: React.FC<{ tableContainer: HTMLDivElement | null }> = ({ tableContainer }) => {
  const [topScrollEl, setTopScrollEl] = React.useState<HTMLDivElement | null>(null);
  const [tableScrollWidth, setTableScrollWidth] = React.useState(0);
  const [containerWidth, setContainerWidth] = React.useState(0);

  // Measure dimensions and watch for resize
  React.useEffect(() => {
    if (!tableContainer) return;

    const updateDimensions = () => {
      setTableScrollWidth(tableContainer.scrollWidth);
      setContainerWidth(tableContainer.clientWidth);
    };

    updateDimensions();

    const observer = new ResizeObserver(updateDimensions);
    observer.observe(tableContainer);
    const tableElement = tableContainer.querySelector('table');
    if (tableElement) observer.observe(tableElement);

    return () => {
      observer.disconnect();
    };
  }, [tableContainer]);

  // Sync scroll between top scrollbar and table container
  React.useEffect(() => {
    if (!tableContainer || !topScrollEl) return;

    const syncScroll = (source: HTMLElement, target: HTMLElement) => {
      if (Math.abs(source.scrollLeft - target.scrollLeft) > 1) {
        target.scrollLeft = source.scrollLeft;
      }
    };

    const handleTopScroll = () => syncScroll(topScrollEl, tableContainer);
    const handleTableScroll = () => syncScroll(tableContainer, topScrollEl);

    topScrollEl.addEventListener('scroll', handleTopScroll);
    tableContainer.addEventListener('scroll', handleTableScroll);

    return () => {
      topScrollEl.removeEventListener('scroll', handleTopScroll);
      tableContainer.removeEventListener('scroll', handleTableScroll);
    };
  }, [tableContainer, topScrollEl]);

  // Only show if there's overflow
  if (tableScrollWidth <= containerWidth) return null;

  return (
    <div
      ref={setTopScrollEl}
      style={{
        overflowX: 'auto',
        overflowY: 'hidden',
        width: '100%',
        marginBottom: '0px',
        height: '12px'
      }}
      className="top-scrollbar"
    >
      <div style={{ width: `${tableScrollWidth}px`, height: '1px' }} />
    </div>
  );
};

export const DocumentsTable: React.FC<DocumentsTableProps> = ({
  documents,
  sortField,
  sortDirection,
  onSort,
  onFilterClick,
  hasActiveFilter,
  onOpenSummary,
  onOpenTaxonomyModal,
  onOpenToc,
  onOpenMetadata,
  onOpenTimeline,
  onOpenLogs,
  onViewChunks,
  onReprocess,
  onOpenQueue,
  reprocessingDocId,
  filterText,
  onFilterTextChange,
  selectedCategory,
  chartView,
  currentPage,
  totalPages,
  totalCount,
  pageSize,
  loadingTable,
  onRefresh,
  onClearCategory,
  tableContainerRef,
  filterPopoverPosition,
  activeFilterColumn,
  tempColumnFilters,
  columnFilters,
  onTempFilterChange,
  onApplyFilter,
  onClearFilter,
  getCategoricalOptions,
  onCloseFilterPopover,
  onPageChange,
  dataSourceConfig,
  dataSource,
}) => {
  const [tableContainer, setTableContainer] = React.useState<HTMLDivElement | null>(null);

  // Generate headers dynamically based on config
  const SORTABLE_HEADERS = React.useMemo(
    () => generateSortableHeaders(dataSourceConfig),
    [dataSourceConfig]
  );

  // Get taxonomy keys for rendering dynamic columns
  const taxonomyKeys = React.useMemo(
    () => Object.keys(dataSourceConfig?.pipeline?.tag?.taxonomies || {}),
    [dataSourceConfig]
  );

  const setRef = React.useCallback(
    (node: HTMLDivElement | null) => {
      setTableContainer(node);
      // Forward external ref
      if (tableContainerRef) {
        if (typeof tableContainerRef === 'function') {
          // @ts-ignore
          tableContainerRef(node);
        } else {
          (tableContainerRef as React.MutableRefObject<HTMLDivElement | null>).current = node;
        }
      }
    },
    [tableContainerRef]
  );

  return (
    <div className="chart-section">
      <DocumentsTableControls
        filterText={filterText}
        onFilterTextChange={onFilterTextChange}
        selectedCategory={selectedCategory}
        chartView={chartView}
        currentPage={currentPage}
        pageSize={pageSize}
        totalCount={totalCount}
        loadingTable={loadingTable}
        onRefresh={onRefresh}
        onClearCategory={onClearCategory}
      />

      {/* Top Scrollbar */}
      <TopScrollbar tableContainer={tableContainer} />

      <div className="documents-table-container" ref={setRef} style={{ position: 'relative' }}>
        {loadingTable && (
          <div className="table-loading-overlay">
            <div className="table-loading-spinner">Loading...</div>
          </div>
        )}
        <table
          className="documents-table"
          style={{ opacity: loadingTable ? 0.5 : 1, transition: 'opacity 0.15s' }}
        >
          <colgroup>
            <col className="col-title" />
            <col className="col-links" />
            <col className="col-summary" />
            <col className="col-metadata" />
            <col className="col-organization" />
            <col className="col-status" />
            <col className="col-type" />
            <col className="col-year" />
            <col className="col-language" />
            {taxonomyKeys.map((key) => (
              <col key={key} className={`col-taxonomy-${key}`} />
            ))}
            <col className="col-format" />
            <col className="col-pages" />
            <col className="col-size" />
            <col className="col-error" />
            <col className="col-updated" />
            <col className="col-chunks" />
            <col className="col-actions" />
          </colgroup>
          <thead>
            <tr>
              {SORTABLE_HEADERS.slice(0, 1).map((column) => (
                <SortableHeader
                  key={column.key}
                  columnKey={column.key}
                  label={column.label}
                  filterable={column.filterable}
                  sortField={sortField}
                  sortDirection={sortDirection}
                  onSort={onSort}
                  onFilterClick={onFilterClick}
                  hasActiveFilter={hasActiveFilter}
                />
              ))}
              <th>Links</th>
              <th className="summary-column">Summary<em className="header-label-subtitle">(AI-generated : Experimental)</em></th>
              <th>Metadata</th>
              {SORTABLE_HEADERS.slice(1).map((column) => (
                <SortableHeader
                  key={column.key}
                  columnKey={column.key}
                  label={column.label}
                  filterable={column.filterable}
                  sortField={sortField}
                  sortDirection={sortDirection}
                  onSort={onSort}
                  onFilterClick={onFilterClick}
                  hasActiveFilter={hasActiveFilter}
                />
              ))}
              <th>Chunks</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((doc, index) => (
              <DocumentsTableRow
                key={doc.id || index}
                doc={doc}
                index={index}
                onOpenSummary={onOpenSummary}
                onOpenTaxonomyModal={onOpenTaxonomyModal}
                onOpenToc={onOpenToc}
                onOpenMetadata={onOpenMetadata}
                onOpenTimeline={onOpenTimeline}
                onOpenLogs={onOpenLogs}
                onViewChunks={onViewChunks}
                onReprocess={onReprocess}
                onOpenQueue={onOpenQueue}
                reprocessingDocId={reprocessingDocId}
                dataSourceConfig={dataSourceConfig}
                dataSource={dataSource}
              />
            ))}
          </tbody>
        </table>
      </div>
      {activeFilterColumn && (
        <DocumentsFilterPopover
          activeFilterColumn={activeFilterColumn}
          filterPopoverPosition={filterPopoverPosition}
          tempColumnFilters={tempColumnFilters}
          columnFilters={columnFilters}
          onTempFilterChange={onTempFilterChange}
          onApplyFilter={onApplyFilter}
          onClearFilter={onClearFilter}
          hasActiveFilter={hasActiveFilter}
          getCategoricalOptions={getCategoricalOptions}
          onClose={onCloseFilterPopover}
          dataSourceConfig={dataSourceConfig}
        />
      )}
      {!loadingTable && totalPages > 1 && (
        <DocumentsPagination currentPage={currentPage} totalPages={totalPages} onPageChange={onPageChange} />
      )}
    </div>
  );
};
