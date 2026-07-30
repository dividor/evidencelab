import axios from 'axios';
import { useCallback, useEffect, useMemo, useState } from 'react';
import API_BASE_URL from '../../config';
import type { TocValidationResult } from '../../types/api';

const PAGE_SIZE = 25;
/** Max page size the /documents endpoint allows — used when loading every doc. */
const MAX_PAGE_SIZE = 100;

export const docKey = (doc: any): string => String(doc.doc_id || doc.id || '');

/** Column accessors — kept together so filtering and options stay consistent. */
export const docTitle = (doc: any): string => doc.map_title || doc.title || '';
export const docOrg = (doc: any): string =>
  doc.organization || doc.map_organization || '';
export const docStatus = (doc: any): string =>
  doc.status || doc.sys_status || 'downloaded';

/** The four filterable columns; drives header rendering and options. */
export type FilterColumn = 'title' | 'organization' | 'status' | 'review';

interface DocumentsResponse {
  documents?: any[];
  total_pages?: number;
}

const NONE_LABEL = '(none)';

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

const reviewOf = (
  doc: any,
  results: Record<string, TocValidationResult>
): string => results[docKey(doc)]?.status || 'untested';

/** A document passes a single column filter (comma-joined selected values). */
const passesColumn = (
  doc: any,
  column: FilterColumn,
  raw: string,
  results: Record<string, TocValidationResult>
): boolean => {
  if (!raw) return true;
  if (column === 'title') {
    return docTitle(doc).toLowerCase().includes(raw.toLowerCase());
  }
  const selected = new Set(raw.split(',').map((v) => v.trim()));
  if (column === 'organization') return selected.has(docOrg(doc) || NONE_LABEL);
  if (column === 'status') return selected.has(docStatus(doc));
  return selected.has(reviewOf(doc, results));
};

/** State + actions for the admin TOC validator screen. */
export const useTocValidator = (dataSource: string) => {
  const [allDocuments, setAllDocuments] = useState<any[]>([]);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({});
  const [activeFilterColumn, setActiveFilterColumn] = useState<FilterColumn | null>(null);
  const [filterPosition, setFilterPosition] = useState<{ top: number; left: number }>({
    top: 0,
    left: 0,
  });

  const [results, setResults] = useState<Record<string, TocValidationResult>>({});
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [changedIds, setChangedIds] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const collected: any[] = [];
      let current = 1;
      let pages = 1;
      do {
        const params = new URLSearchParams({
          page: String(current),
          page_size: String(MAX_PAGE_SIZE),
        });
        if (dataSource) params.set('data_source', dataSource);
        const response = await axios.get<DocumentsResponse>(
          `${API_BASE_URL}/documents?${params.toString()}`
        );
        (response.data.documents || []).forEach((doc) => collected.push(doc));
        pages = response.data.total_pages || 1;
        current += 1;
      } while (current <= pages);
      setAllDocuments(collected);
    } catch (err) {
      setError('Could not load documents.');
    } finally {
      setLoading(false);
    }
  }, [dataSource]);

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

  // A data source change invalidates selection and filters from the old source.
  useEffect(() => {
    setSelectedIds(new Set());
    setChangedIds(new Set());
    setColumnFilters({});
    setSearch('');
    setPage(1);
  }, [dataSource]);

  // Filtered set (search box + every active column filter), in load order.
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return allDocuments.filter((doc) => {
      if (query && !docTitle(doc).toLowerCase().includes(query)) return false;
      return (Object.keys(columnFilters) as FilterColumn[]).every((column) =>
        passesColumn(doc, column, columnFilters[column], results)
      );
    });
  }, [allDocuments, search, columnFilters, results]);

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const documents = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page]
  );

  // Keep the current page in range as filters shrink the result set.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  /** Distinct values for a categorical column's filter popover. */
  const getCategoricalOptions = useCallback(
    (column: FilterColumn): string[] => {
      if (column === 'review') return ['pass', 'fail', 'skipped', 'untested'];
      const accessor = column === 'organization' ? docOrg : docStatus;
      const values = new Set<string>();
      allDocuments.forEach((doc) => values.add(accessor(doc) || NONE_LABEL));
      return Array.from(values).sort();
    },
    [allDocuments]
  );

  const openFilter = useCallback(
    (column: FilterColumn, event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      if (activeFilterColumn === column) {
        setActiveFilterColumn(null);
        return;
      }
      const rect = event.currentTarget.getBoundingClientRect();
      setFilterPosition({
        top: rect.bottom + window.scrollY + 5,
        left: rect.left + window.scrollX - 150,
      });
      setActiveFilterColumn(column);
    },
    [activeFilterColumn]
  );

  const applyFilter = useCallback((column: FilterColumn, value: string) => {
    setColumnFilters((prev) => {
      const next = { ...prev };
      if (value) next[column] = value;
      else delete next[column];
      return next;
    });
    setPage(1);
    setActiveFilterColumn(null);
  }, []);

  const clearFilter = useCallback((column: FilterColumn) => applyFilter(column, ''), [
    applyFilter,
  ]);

  const hasActiveFilter = useCallback(
    (column: FilterColumn): boolean => Boolean(columnFilters[column]),
    [columnFilters]
  );

  const toggle = useCallback((docId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
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

  /** Select every document matching the current search + column filters. */
  const selectAllMatching = useCallback(() => {
    setSelectedIds(new Set(filtered.map(docKey)));
  }, [filtered]);

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
    columnFilters,
    activeFilterColumn,
    filterPosition,
    setPage,
    setSearch,
    openFilter,
    applyFilter,
    clearFilter,
    hasActiveFilter,
    getCategoricalOptions,
    closeFilter: () => setActiveFilterColumn(null),
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
