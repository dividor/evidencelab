import axios from 'axios';
import API_BASE_URL from '../../config';
import { formatChunkBBox } from './documentsUtils';

export const updateSelectedCategory = ({
  currentCategory,
  nextCategory,
  setSelectedCategory,
  setCurrentPage,
}: {
  currentCategory: string | null;
  nextCategory: string;
  setSelectedCategory: (value: string | null) => void;
  setCurrentPage: (value: number) => void;
}): void => {
  setSelectedCategory(currentCategory === nextCategory ? null : nextCategory);
  setCurrentPage(1);
};

export const updateSortState = ({
  sortField,
  sortDirection,
  field,
  setSortField,
  setSortDirection,
}: {
  sortField: string;
  sortDirection: 'asc' | 'desc';
  field: string;
  setSortField: (value: string) => void;
  setSortDirection: (value: 'asc' | 'desc') => void;
}): void => {
  if (sortField === field) {
    setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    return;
  }
  setSortField(field);
  setSortDirection('asc');
};

export const toggleFilterPopover = ({
  column,
  currentColumn,
  rect,
  setActiveFilterColumn,
  setFilterPopoverPosition,
}: {
  column: string;
  currentColumn: string | null;
  rect: DOMRect;
  setActiveFilterColumn: (value: string | null) => void;
  setFilterPopoverPosition: (value: { top: number; left: number }) => void;
}): void => {
  if (currentColumn === column) {
    setActiveFilterColumn(null);
    return;
  }
  setActiveFilterColumn(column);
  setFilterPopoverPosition({
    top: rect.bottom + window.scrollY + 5,
    left: rect.left + window.scrollX - 150,
  });
};

export const applyColumnFilter = ({
  column,
  value,
  columnFilters,
  tempColumnFilters,
  setColumnFilters,
  setTempColumnFilters,
  setCurrentPage,
  setActiveFilterColumn,
}: {
  column: string;
  value: string;
  columnFilters: Record<string, string>;
  tempColumnFilters: Record<string, string>;
  setColumnFilters: (value: Record<string, string>) => void;
  setTempColumnFilters: (value: Record<string, string>) => void;
  setCurrentPage: (value: number) => void;
  setActiveFilterColumn: (value: string | null) => void;
}): void => {
  setColumnFilters({ ...columnFilters, [column]: value });
  setTempColumnFilters({ ...tempColumnFilters, [column]: value });
  setCurrentPage(1);
  setActiveFilterColumn(null);
};

export const clearColumnFilter = ({
  column,
  columnFilters,
  tempColumnFilters,
  setColumnFilters,
  setTempColumnFilters,
  setCurrentPage,
  setActiveFilterColumn,
}: {
  column: string;
  columnFilters: Record<string, string>;
  tempColumnFilters: Record<string, string>;
  setColumnFilters: (value: Record<string, string>) => void;
  setTempColumnFilters: (value: Record<string, string>) => void;
  setCurrentPage: (value: number) => void;
  setActiveFilterColumn: (value: string | null) => void;
}): void => {
  setColumnFilters({ ...columnFilters, [column]: '' });
  setTempColumnFilters({ ...tempColumnFilters, [column]: '' });
  setCurrentPage(1);
  setActiveFilterColumn(null);
};

export const isFilterActive = (columnFilters: Record<string, string>, column: string): boolean => {
  return Boolean(columnFilters[column] && columnFilters[column].trim());
};

export const fetchDocumentChunks = async ({
  docId,
  dataSource,
}: {
  docId: string;
  dataSource: string;
}): Promise<any[]> => {
  const response = await axios.get(
    `${API_BASE_URL}/documents/${docId}/chunks?data_source=${dataSource}`
  );
  const data = response.data as { chunks?: any[] };
  return (data.chunks || []).sort((a: any, b: any) => {
    const pageA = a.page_num ?? Infinity;
    const pageB = b.page_num ?? Infinity;
    return pageA - pageB;
  });
};

export const buildPdfViewerState = ({
  chunk,
  selectedDocId,
  selectedDocTitle,
}: {
  chunk: any;
  selectedDocId: string | null;
  selectedDocTitle: string | null;
}) => {
  if (!selectedDocId) {
    return null;
  }
  return {
    docId: selectedDocId,
    chunkId: chunk.chunk_id || '',
    pageNum: chunk.page_num || 1,
    title: selectedDocTitle || 'Document',
    bbox: formatChunkBBox(chunk),
  };
};

export const openChunksModal = async ({
  doc,
  dataSource,
  setSelectedDocId,
  setSelectedDocTitle,
  setSelectedDocMetadata,
  setChunksModalOpen,
  setLoadingChunks,
  setChunks,
  setExpandedChunks,
}: {
  doc: any;
  dataSource: string;
  setSelectedDocId: (value: string | null) => void;
  setSelectedDocTitle: (value: string | null) => void;
  setSelectedDocMetadata: (value: any) => void;
  setChunksModalOpen: (value: boolean) => void;
  setLoadingChunks: (value: boolean) => void;
  setChunks: (value: any[]) => void;
  setExpandedChunks: (value: Set<number>) => void;
}): Promise<void> => {
  setSelectedDocId(doc.id);
  setSelectedDocTitle(doc.title || null);
  setSelectedDocMetadata(doc);
  setChunksModalOpen(true);
  setLoadingChunks(true);
  setChunks([]);
  setExpandedChunks(new Set());

  try {
    const sortedChunks = await fetchDocumentChunks({ docId: doc.id, dataSource });
    setChunks(sortedChunks);
  } catch (err) {
    console.error('Error loading chunks:', err);
    setChunks([]);
  } finally {
    setLoadingChunks(false);
  }
};

export const openPdfViewerWithChunk = ({
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
}: {
  chunk: any;
  selectedDocId: string | null;
  selectedDocTitle: string | null;
  setChunksModalOpen: (value: boolean) => void;
  setPdfViewerDocId: (value: string) => void;
  setPdfViewerChunkId: (value: string) => void;
  setPdfViewerPageNum: (value: number) => void;
  setPdfViewerTitle: (value: string) => void;
  setPdfViewerBBox: (value: any[]) => void;
  setPdfViewerOpen: (value: boolean) => void;
}): void => {
  const viewerState = buildPdfViewerState({ chunk, selectedDocId, selectedDocTitle });
  if (!viewerState) {
    return;
  }
  setChunksModalOpen(false);
  setPdfViewerDocId(viewerState.docId);
  setPdfViewerChunkId(viewerState.chunkId);
  setPdfViewerPageNum(viewerState.pageNum);
  setPdfViewerTitle(viewerState.title);
  setPdfViewerBBox(viewerState.bbox);
  setPdfViewerOpen(true);
};

export const reprocessDocument = async ({
  doc,
  dataSource,
  reprocessingDocId,
  setReprocessingDocId,
  onRefresh,
}: {
  doc: any;
  dataSource: string;
  reprocessingDocId: string | null;
  setReprocessingDocId: (value: string | null) => void;
  onRefresh: () => void;
}): Promise<void> => {
  if (!doc.id || reprocessingDocId) {
    return;
  }
  setReprocessingDocId(doc.id);
  try {
    await axios.post(`${API_BASE_URL}/documents/${doc.id}/reprocess?data_source=${dataSource}`);
    onRefresh();
  } catch (err) {
    console.error('Error reprocessing document:', err);
  } finally {
    setReprocessingDocId(null);
  }
};

export const updateTocApprovalState = ({
  approved,
  selectedTocDocId,
  setAllDocuments,
}: {
  approved: boolean;
  selectedTocDocId: string;
  setAllDocuments: (value: any[] | ((prev: any[]) => any[])) => void;
}): void => {
  if (!selectedTocDocId) {
    return;
  }
  setAllDocuments((prev: any[]) =>
    prev.map((doc) => (doc.id === selectedTocDocId ? { ...doc, toc_approved: approved } : doc))
  );
};
