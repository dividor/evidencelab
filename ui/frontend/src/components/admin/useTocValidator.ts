import axios from 'axios';
import { useCallback, useEffect, useState } from 'react';
import API_BASE_URL from '../../config';
import type { TocValidationResult } from '../../types/api';

const PAGE_SIZE = 25;
/** Max page size the /documents endpoint allows — used when collecting all ids. */
const MAX_PAGE_SIZE = 100;

export const docKey = (doc: any): string => String(doc.doc_id || doc.id || '');

interface DocumentsResponse {
  documents?: any[];
  total?: number;
  total_pages?: number;
}

/**
 * Returns true when the two results differ in a way worth highlighting to the
 * user (a brand new result, or a changed verdict / excluded-section count).
 */
const hasChanged = (
  previous: TocValidationResult | undefined,
  next: TocValidationResult
): boolean => {
  if (!previous) return true;
  return (
    previous.status !== next.status ||
    previous.num_excluded !== next.num_excluded ||
    previous.excluded_section_types.join(',') !== next.excluded_section_types.join(',')
  );
};

/** State + actions for the admin TOC validator screen. */
export const useTocValidator = (dataSource: string) => {
  const [documents, setDocuments] = useState<any[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [results, setResults] = useState<Record<string, TocValidationResult>>({});
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [changedIds, setChangedIds] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (dataSource) params.set('data_source', dataSource);
      if (search.trim()) params.set('search', search.trim());
      const response = await axios.get<DocumentsResponse>(
        `${API_BASE_URL}/documents?${params.toString()}`
      );
      setDocuments(response.data.documents || []);
      setTotalPages(response.data.total_pages || 1);
      setTotal(response.data.total || 0);
    } catch (err) {
      setError('Could not load documents.');
    } finally {
      setLoading(false);
    }
  }, [dataSource, page, search]);

  const loadResults = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (dataSource) params.set('data_source', dataSource);
      const response = await axios.get<{ results: Record<string, TocValidationResult> }>(
        `${API_BASE_URL}/toc-validator/results?${params.toString()}`
      );
      setResults(response.data.results || {});
    } catch (err) {
      setError('Could not load previous validation results.');
    }
  }, [dataSource]);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    loadResults();
  }, [loadResults]);

  // A data source change invalidates any selection from the previous source.
  useEffect(() => {
    setSelectedIds(new Set());
    setChangedIds(new Set());
    setPage(1);
  }, [dataSource]);

  const toggle = useCallback((docId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) {
        next.delete(docId);
      } else {
        next.add(docId);
      }
      return next;
    });
  }, []);

  const togglePage = useCallback(() => {
    const pageIds = documents.map(docKey);
    const allSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      pageIds.forEach((id) => (allSelected ? next.delete(id) : next.add(id)));
      return next;
    });
  }, [documents, selectedIds]);

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  /** Select every document matching the current search, across all pages. */
  const selectAllMatching = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const ids: string[] = [];
      let current = 1;
      let pages = 1;
      do {
        const params = new URLSearchParams({
          page: String(current),
          page_size: String(MAX_PAGE_SIZE),
        });
        if (dataSource) params.set('data_source', dataSource);
        if (search.trim()) params.set('search', search.trim());
        const response = await axios.get<DocumentsResponse>(
          `${API_BASE_URL}/documents?${params.toString()}`
        );
        (response.data.documents || []).forEach((doc) => ids.push(docKey(doc)));
        pages = response.data.total_pages || 1;
        current += 1;
      } while (current <= pages);
      setSelectedIds(new Set(ids));
    } catch (err) {
      setError('Could not select all documents.');
    } finally {
      setLoading(false);
    }
  }, [dataSource, search]);

  const runValidation = useCallback(async () => {
    const docIds = Array.from(selectedIds);
    if (docIds.length === 0) return;
    setRunning(true);
    setError(null);
    try {
      const response = await axios.post<{ results: TocValidationResult[] }>(
        `${API_BASE_URL}/toc-validator/run`,
        { data_source: dataSource || null, doc_ids: docIds }
      );
      const returned = response.data.results || [];
      const changed = new Set<string>();
      setResults((prev) => {
        const next = { ...prev };
        returned.forEach((result) => {
          if (hasChanged(prev[result.doc_id], result)) changed.add(result.doc_id);
          next[result.doc_id] = result;
        });
        return next;
      });
      setChangedIds(changed);
    } catch (err) {
      setError('Validation run failed.');
    } finally {
      setRunning(false);
    }
  }, [dataSource, selectedIds]);

  /** Re-validate a single document (used after its classification is edited). */
  const revalidate = useCallback(
    async (docId: string) => {
      try {
        const response = await axios.post<{ results: TocValidationResult[] }>(
          `${API_BASE_URL}/toc-validator/run`,
          { data_source: dataSource || null, doc_ids: [docId] }
        );
        const result = (response.data.results || [])[0];
        if (result) {
          setResults((prev) => ({ ...prev, [result.doc_id]: result }));
          setChangedIds((prev) => new Set(prev).add(result.doc_id));
        }
      } catch (err) {
        setError('Could not re-validate document.');
      }
    },
    [dataSource]
  );

  return {
    documents,
    page,
    totalPages,
    total,
    search,
    loading,
    error,
    results,
    selectedIds,
    changedIds,
    running,
    setPage,
    setSearch,
    toggle,
    togglePage,
    clearSelection,
    selectAllMatching,
    runValidation,
    revalidate,
    reloadDocuments: loadDocuments,
  };
};

export default useTocValidator;
