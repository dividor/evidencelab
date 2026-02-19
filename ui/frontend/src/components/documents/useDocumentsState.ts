import { useCallback, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../config';
import { Facets } from '../../types/api';
import { StatsData } from '../../types/documents';
import {
  ChartView,
  buildDocumentsParams,
  extractTitleFacets,
  getCategoricalOptions,
  getInitialChartView,
  getInitialFilterText,
  getInitialPage,
  sortDocuments,
  useDebouncedFilterText,
  useDocumentsInitialLoad,
  useDocumentsReload,
  useFilterPopoverClose,
  useSyncDocumentsUrlParams,
} from './documentsUtils';
import {
  applyColumnFilter,
  clearColumnFilter,
  isFilterActive,
  openChunksModal,
  openPdfViewerWithChunk,
  reprocessDocument,
  toggleFilterPopover,
  updateSelectedCategory,
  updateSortState,
  updateTocApprovalState,
} from './documentsActions';

export const useDocumentsState = (dataSource: string, dataSourceConfig?: any) => {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chartView, setChartView] = useState<ChartView>(getInitialChartView);
  const [hoveredBar, setHoveredBar] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [allDocuments, setAllDocuments] = useState<any[]>([]);
  const [sortField, setSortField] = useState<string>('last_updated');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [filterText, setFilterText] = useState<string>(getInitialFilterText);
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({
    title: '',
    organization: '',
    document_type: '',
    published_year: '',
    language: '',
    file_format: '',
    status: '',
    error_message: '',
    sdg: '',
  });
  const [tempColumnFilters, setTempColumnFilters] = useState<Record<string, string>>({
    title: '',
    error_message: '',
    sdg: '',
  });
  const [activeFilterColumn, setActiveFilterColumn] = useState<string | null>(null);
  const [filterPopoverPosition, setFilterPopoverPosition] = useState<{ top: number; left: number }>({
    top: 0,
    left: 0,
  });

  const tableContainerRef = useRef<HTMLDivElement>(null);
  const [chunksModalOpen, setChunksModalOpen] = useState(false);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [selectedDocTitle, setSelectedDocTitle] = useState<string | null>(null);
  const [selectedDocMetadata, setSelectedDocMetadata] = useState<any>(null);
  const [chunks, setChunks] = useState<any[]>([]);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [expandedChunks, setExpandedChunks] = useState<Set<number>>(new Set());
  const [summaryModalOpen, setSummaryModalOpen] = useState(false);
  const [selectedSummary, setSelectedSummary] = useState<string>('');
  const [selectedSummaryTitle, setSelectedSummaryTitle] = useState<string>('');
  const [selectedTocPdfUrl, setSelectedTocPdfUrl] = useState<string>('');
  const [selectedTocDocId, setSelectedTocDocId] = useState<string>('');
  const [selectedTocApproved, setSelectedTocApproved] = useState(false);
  const [selectedTocPageCount, setSelectedTocPageCount] = useState<number | null>(null);
  const [tocModalOpen, setTocModalOpen] = useState(false);
  const [metadataModalOpen, setMetadataModalOpen] = useState(false);
  const [selectedMetadataDoc, setSelectedMetadataDoc] = useState<any>(null);
  const [timelineModalOpen, setTimelineModalOpen] = useState(false);
  const [taxonomyModalOpen, setTaxonomyModalOpen] = useState(false);
  const [selectedTaxonomyValue, setSelectedTaxonomyValue] = useState<any>(null);
  const [selectedTaxonomyDefinition, setSelectedTaxonomyDefinition] = useState<string>('');
  const [selectedTaxonomyName, setSelectedTaxonomyName] = useState<string>('');
  const [selectedTimelineDoc, setSelectedTimelineDoc] = useState<any>(null);
  const [logsModalOpen, setLogsModalOpen] = useState(false);
  const [selectedLogsDocId, setSelectedLogsDocId] = useState<string>('');
  const [selectedLogsDocTitle, setSelectedLogsDocTitle] = useState<string>('');
  const [reprocessingDocId, setReprocessingDocId] = useState<string | null>(null);
  const [queueModalOpen, setQueueModalOpen] = useState(false);
  const [pdfViewerOpen, setPdfViewerOpen] = useState(false);
  const [pdfViewerDocId, setPdfViewerDocId] = useState<string>('');
  const [pdfViewerChunkId, setPdfViewerChunkId] = useState<string>('');
  const [pdfViewerPageNum, setPdfViewerPageNum] = useState<number>(1);
  const [pdfViewerTitle, setPdfViewerTitle] = useState<string>('');
  const [pdfViewerBBox, setPdfViewerBBox] = useState<any[]>([]);
  const [currentPage, setCurrentPage] = useState<number>(getInitialPage);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [pageSize] = useState<number>(20);
  const [loadingTable, setLoadingTable] = useState<boolean>(true);
  const [titleFacets, setTitleFacets] = useState<Array<{ value: string; count: number }>>([]);

  const loadDocuments = useCallback(async () => {
    try {
      setLoadingTable(true);
      const params = buildDocumentsParams({
        currentPage,
        pageSize,
        dataSource,
        filterText,
        selectedCategory,
        chartView,
        columnFilters,
        sortField,
        sortDirection,
      });
      const response = await axios.get(`${API_BASE_URL}/documents?${params}`);
      const data = response.data as {
        documents?: any[];
        total_pages?: number;
        total?: number;
      };
      setAllDocuments(data.documents || []);
      setTotalPages(data.total_pages || 0);
      setTotalCount(data.total || 0);
    } catch (err) {
      console.error('Error loading documents:', err);
    } finally {
      setLoadingTable(false);
    }
  }, [chartView, columnFilters, currentPage, dataSource, filterText, pageSize, selectedCategory, sortField, sortDirection]);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const statsResponse = await axios.get<StatsData>(
        `${API_BASE_URL}/stats?data_source=${dataSource}`
      );
      setStats(statsResponse.data);
      setError(null);
      // loadDocuments() is handled by useDocumentsReload or separate effect
    } catch (err) {
      console.error('Error loading stats:', err);
      setError('Failed to load statistics. Make sure the backend is running.');
    } finally {
      setLoading(false);
    }
  }, [dataSource]);

  const loadTitleFacets = useCallback(async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/facets?data_source=${dataSource}`);
      const data = response.data as Facets;
      setTitleFacets(extractTitleFacets(data));
    } catch (err) {
      console.error('Error loading title facets:', err);
    }
  }, [dataSource]);

  const handleBarClick = (category: string) => {
    updateSelectedCategory({
      currentCategory: selectedCategory,
      nextCategory: category,
      setSelectedCategory,
      setCurrentPage,
    });
  };

  const handleSort = (field: string) => {
    updateSortState({
      sortField,
      sortDirection,
      field,
      setSortField,
      setSortDirection,
    });
  };

  const handleFilterClick = (column: string, event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    toggleFilterPopover({
      column,
      currentColumn: activeFilterColumn,
      rect,
      setActiveFilterColumn,
      setFilterPopoverPosition,
    });
  };

  const getCategoricalOptionsForColumn = (column: string): string[] =>
    getCategoricalOptions(stats, titleFacets, column, dataSourceConfig);

  const applyFilter = (column: string, value: string) => {
    applyColumnFilter({
      column,
      value,
      columnFilters,
      tempColumnFilters,
      setColumnFilters,
      setTempColumnFilters,
      setCurrentPage,
      setActiveFilterColumn,
    });
  };

  const clearFilter = (column: string) => {
    clearColumnFilter({
      column,
      columnFilters,
      tempColumnFilters,
      setColumnFilters,
      setTempColumnFilters,
      setCurrentPage,
      setActiveFilterColumn,
    });
  };

  const hasActiveFilter = (column: string): boolean => isFilterActive(columnFilters, column);

  const handleViewChunks = async (doc: any) => {
    await openChunksModal({
      doc,
      dataSource,
      setSelectedDocId,
      setSelectedDocTitle,
      setSelectedDocMetadata,
      setChunksModalOpen,
      setLoadingChunks,
      setChunks,
      setExpandedChunks,
    });
  };

  const handleOpenPDFWithChunk = (chunk: any) => {
    pdfOpenedFromChunksRef.current = true;
    openPdfViewerWithChunk({
      chunk,
      selectedDocId,
      selectedDocTitle,
      setChunksModalOpen,
      setPdfViewerDocId,
      setPdfViewerChunkId,
      setPdfViewerPageNum,
      setPdfViewerTitle,
      setPdfViewerBBox,
      setPdfViewerOpen,
    });
  };

  const pdfOpenedFromChunksRef = useRef(false);

  const handleClosePDFViewer = () => {
    setPdfViewerOpen(false);
    if (pdfOpenedFromChunksRef.current) {
      setChunksModalOpen(true);
    }
    pdfOpenedFromChunksRef.current = false;
  };

  const handleOpenPdfPreview = (doc: any) => {
    const docId = doc.doc_id || doc.id;
    if (!docId) return;
    pdfOpenedFromChunksRef.current = false;
    setSelectedDocMetadata(doc);
    setPdfViewerDocId(docId);
    setPdfViewerChunkId('');
    setPdfViewerPageNum(1);
    setPdfViewerTitle(doc.title || 'Untitled');
    setPdfViewerBBox([]);
    setPdfViewerOpen(true);
  };

  const toggleChunk = (index: number) => {
    const newExpanded = new Set(expandedChunks);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedChunks(newExpanded);
  };

  const closeChunksModal = () => {
    setChunksModalOpen(false);
    setSelectedDocId(null);
    setSelectedDocTitle(null);
    setSelectedDocMetadata(null);
    setChunks([]);
    setExpandedChunks(new Set());
  };

  const handleReprocess = async (doc: any) => {
    await reprocessDocument({
      doc,
      dataSource,
      reprocessingDocId,
      setReprocessingDocId,
      onRefresh: loadDocuments,
    });
  };

  const handleTocUpdated = (newToc: string) => {
    setSelectedSummary(newToc);
    loadDocuments();
  };

  const handleTocApprovedChange = (approved: boolean) => {
    setSelectedTocApproved(approved);
    updateTocApprovalState({
      approved,
      selectedTocDocId,
      setAllDocuments,
    });
  };

  const fetchTocPdfUrl = useCallback(async (docId: string) => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/document/${docId}`,
        { params: { data_source: dataSource } }
      );
      const data = response.data as {
        pdf_url?: string;
      };
      const pdfUrl = data.pdf_url || '';
      if (!pdfUrl) {
        console.warn('No PDF link is available for this document.');
        return;
      }
      setSelectedTocPdfUrl(pdfUrl);
    } catch (error) {
      console.error('Error fetching PDF link for TOC:', error);
      alert('Failed to load PDF link for this TOC.');
    }
  }, [dataSource]);

  const fetchToc = useCallback(async (docId: string) => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/document/${docId}`,
        { params: { data_source: dataSource } }
      );
      const data = response.data as {
        toc_classified?: string;
        sys_toc_classified?: string;
        page_count?: number;
        sys_page_count?: number;
      };
      const tocValue = data.toc_classified || data.sys_toc_classified;
      if (!tocValue) {
        throw new Error('No classified TOC found for this document.');
      }
      setSelectedSummary(tocValue);
      setSelectedTocPageCount(data.page_count ?? data.sys_page_count ?? null);
    } catch (error) {
      console.error('Error fetching TOC:', error);
      alert('Failed to load classified TOC for this document.');
    }
  }, [dataSource]);

  const handleOpenToc = (doc: any) => {
    const tocToDisplay = doc.toc_classified || doc.sys_toc_classified || '';
    setSelectedSummary(tocToDisplay);
    setSelectedTocPdfUrl(doc.pdf_url || '');
    setSelectedTocDocId(doc.id || '');
    setSelectedTocApproved(doc.toc_approved || false);
    setSelectedTocPageCount(doc.page_count ?? doc.sys_page_count ?? null);
    setTocModalOpen(true);
    if (doc.id) {
      fetchToc(doc.id);
      if (!doc.pdf_url) {
        fetchTocPdfUrl(doc.id);
      }
    }
  };

  const handleOpenMetadata = (doc: any) => {
    setSelectedMetadataDoc(doc);
    setMetadataModalOpen(true);
  };

  const handleOpenTimeline = (doc: any) => {
    setSelectedTimelineDoc(doc);
    setTimelineModalOpen(true);
  };

  const handleOpenLogs = (doc: any) => {
    setSelectedLogsDocId(doc.id || '');
    setSelectedLogsDocTitle(doc.title || 'Untitled');
    setLogsModalOpen(true);
  };

  const handleOpenQueue = () => {
    setQueueModalOpen(true);
  };

  const handleOpenSummary = (summary: string, docTitle: string) => {
    setSelectedSummary(summary);
    setSelectedSummaryTitle(docTitle);
    setSummaryModalOpen(true);
  };

  const handleOpenTaxonomyModal = (value: any, definition: string, taxonomyName: string) => {
    setSelectedTaxonomyValue(value);
    setSelectedTaxonomyDefinition(definition);
    setSelectedTaxonomyName(taxonomyName);
    setTaxonomyModalOpen(true);
  };

  const closeTaxonomyModal = () => {
    setTaxonomyModalOpen(false);
  };

  const handleClearCategory = () => {
    setSelectedCategory(null);
    setCurrentPage(1);
  };

  const handleRefreshTable = () => {
    setCurrentPage(1);
    loadDocuments();
  };

  const handleTempFilterChange = (column: string, value: string) => {
    setTempColumnFilters({ ...tempColumnFilters, [column]: value });
  };

  const handleCloseFilterPopover = () => {
    setActiveFilterColumn(null);
  };

  const handleFilterTextChange = (value: string) => {
    setFilterText(value);
  };

  const closeSummaryModal = () => setSummaryModalOpen(false);
  const closeMetadataModal = () => setMetadataModalOpen(false);
  const closeTimelineModal = () => setTimelineModalOpen(false);
  const closeQueueModal = () => setQueueModalOpen(false);
  const closeLogsModal = () => setLogsModalOpen(false);
  const closeTocModal = () => setTocModalOpen(false);

  const getSortedAndFilteredDocuments = () => allDocuments;

  useDocumentsInitialLoad(dataSource, loadData, loadTitleFacets);
  useDocumentsReload(currentPage, selectedCategory, columnFilters, loadDocuments);
  useFilterPopoverClose(activeFilterColumn, handleCloseFilterPopover);
  const handleDebouncedFilterChange = useCallback(() => {
    setCurrentPage(1);
    loadDocuments();
  }, [loadDocuments]);

  useDebouncedFilterText(filterText, loading, handleDebouncedFilterChange);
  useSyncDocumentsUrlParams(currentPage, filterText, chartView);

  return {
    stats,
    loading,
    error,
    chartView,
    setChartView,
    hoveredBar,
    setHoveredBar,
    tooltipPos,
    setTooltipPos,
    selectedCategory,
    handleBarClick,
    allDocuments,
    sortField,
    sortDirection,
    handleSort,
    filterText,
    handleFilterTextChange,
    columnFilters,
    tempColumnFilters,
    activeFilterColumn,
    filterPopoverPosition,
    handleFilterClick,
    getCategoricalOptionsForColumn,
    applyFilter,
    clearFilter,
    hasActiveFilter,
    handleViewChunks,
    handleOpenPDFWithChunk,
    handleOpenPdfPreview,
    handleClosePDFViewer,
    toggleChunk,
    closeChunksModal,
    handleReprocess,
    handleTocUpdated,
    handleTocApprovedChange,
    handleOpenToc,
    handleOpenMetadata,
    handleOpenTimeline,
    handleOpenLogs,
    handleOpenQueue,
    handleOpenSummary,
    handleClearCategory,
    handleRefreshTable,
    handleTempFilterChange,
    handleCloseFilterPopover,
    getSortedAndFilteredDocuments,
    reprocessingDocId,
    chunksModalOpen,
    chunks,
    loadingChunks,
    expandedChunks,
    pdfViewerOpen,
    pdfViewerDocId,
    pdfViewerChunkId,
    pdfViewerPageNum,
    pdfViewerTitle,
    pdfViewerBBox,
    selectedDocMetadata,
    summaryModalOpen,
    selectedSummary,
    selectedSummaryTitle,
    closeSummaryModal,
    taxonomyModalOpen,
    selectedTaxonomyValue,
    selectedTaxonomyDefinition,
    selectedTaxonomyName,
    handleOpenTaxonomyModal,
    closeTaxonomyModal,
    metadataModalOpen,
    selectedMetadataDoc,
    closeMetadataModal,
    timelineModalOpen,
    selectedTimelineDoc,
    closeTimelineModal,
    queueModalOpen,
    closeQueueModal,
    logsModalOpen,
    selectedLogsDocId,
    selectedLogsDocTitle,
    closeLogsModal,
    tocModalOpen,
    selectedTocDocId,
    selectedTocPdfUrl,
    selectedTocApproved,
    selectedTocPageCount,
    closeTocModal,
    currentPage,
    totalPages,
    totalCount,
    pageSize,
    loadingTable,
    tableContainerRef,
    setCurrentPage,
  };
};
