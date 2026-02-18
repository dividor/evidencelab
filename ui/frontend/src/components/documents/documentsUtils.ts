import { useEffect, useRef } from 'react';
import { Facets } from '../../types/api';
import { StatsData } from '../../types/documents';
import { getLastUpdatedTimestamp } from './documentsModalUtils';

export type ChartView = 'type' | 'agency' | 'year' | 'language' | 'status' | 'format' | 'country';

const CHART_VIEWS: ChartView[] = ['year', 'type', 'agency', 'language', 'status', 'format', 'country'];

const CHART_VIEW_PARAM_MAP: Record<ChartView, string> = {
  type: 'document_type',
  agency: 'organization',
  year: 'published_year',
  language: 'language',
  status: 'status',
  format: 'file_format',
  country: 'country',
};

const COLUMN_FILTER_PARAM_MAP: Record<string, string> = {
  title: 'title',
  organization: 'organization',
  document_type: 'document_type',
  published_year: 'published_year',
  language: 'language',
  file_format: 'file_format',
  status: 'status',
  sdg: 'sdg',
  cross_cutting_theme: 'cross_cutting_theme',
};

export const getInitialChartView = (): ChartView => {
  const params = new URLSearchParams(window.location.search);
  const view = params.get('graph') || params.get('view');
  if (view && CHART_VIEWS.includes(view as ChartView)) {
    return view as ChartView;
  }
  return 'year';
};

export const getInitialFilterText = (): string => {
  const params = new URLSearchParams(window.location.search);
  return params.get('search') || '';
};

export const getInitialPage = (): number => {
  const params = new URLSearchParams(window.location.search);
  const page = params.get('page');
  return page ? parseInt(page, 10) : 1;
};

const appendColumnFilters = (
  params: URLSearchParams,
  columnFilters: Record<string, string>
): void => {
  Object.entries(columnFilters).forEach(([column, filterValue]) => {
    if (!filterValue || !filterValue.trim()) {
      return;
    }
    const apiParam = COLUMN_FILTER_PARAM_MAP[column];
    if (apiParam) {
      params.append(apiParam, filterValue.trim());
    }
  });
};

export const buildDocumentsParams = ({
  currentPage,
  pageSize,
  dataSource,
  filterText,
  selectedCategory,
  chartView,
  columnFilters,
  sortField,
  sortDirection,
}: {
  currentPage: number;
  pageSize: number;
  dataSource: string;
  filterText: string;
  selectedCategory: string | null;
  chartView: ChartView;
  columnFilters: Record<string, string>;
  sortField: string;
  sortDirection: 'asc' | 'desc';
}): URLSearchParams => {
  const params = new URLSearchParams();
  params.append('page', currentPage.toString());
  params.append('page_size', pageSize.toString());
  params.append('data_source', dataSource);

  // Map frontend sort fields to backend
  let backendSortField = sortField;
  if (sortField === 'published_year') {
    backendSortField = 'year';
  }

  params.append('sort_by', backendSortField);
  params.append('order', sortDirection);

  if (filterText) {
    params.append('search', filterText);
  }

  if (selectedCategory) {
    const filterKey = CHART_VIEW_PARAM_MAP[chartView];
    if (filterKey) {
      params.append(filterKey, selectedCategory);
    }
  }

  appendColumnFilters(params, columnFilters);
  return params;
};

export const getCategoricalOptions = (
  stats: StatsData | null,
  titleFacets: Array<{ value: string; count: number }>,
  column: string,
  dataSourceConfig?: any
): string[] => {
  if (!stats) {
    return [];
  }

  // Check if this column is a taxonomy defined in config
  const taxonomies = dataSourceConfig?.pipeline?.tag?.taxonomies || {};
  if (column in taxonomies) {
    // Return taxonomy codes from config (e.g., "sdg1", "sdg2", not "SDG 1", "SDG 2")
    const taxonomyValues = taxonomies[column]?.values || {};
    return Object.keys(taxonomyValues).sort();
  }

  // Otherwise use stats-based options
  switch (column) {
    case 'title':
      return titleFacets.map((facet) => facet.value);
    case 'organization':
      return Object.keys(stats.agency_breakdown).sort();
    case 'document_type':
      return Object.keys(stats.type_breakdown).sort();
    case 'published_year':
      return Object.keys(stats.year_breakdown).sort();
    case 'language':
      return Object.keys(stats.language_breakdown || {}).sort();
    case 'file_format':
      return Object.keys(stats.format_breakdown || {}).sort();
    case 'status':
      return Object.keys(stats.status_breakdown).sort();
    default:
      return [];
  }
};

const compareAny = (a: any, b: any): number => {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
};

const getSortValue = (doc: any, sortField: string): any => {
  if (sortField === 'last_updated') {
    const ts = getLastUpdatedTimestamp(doc.stages || {});
    return ts ? Date.parse(ts) : Number.NEGATIVE_INFINITY;
  }
  return doc[sortField] || '';
};

export const sortDocuments = (
  documents: any[],
  sortField: string,
  sortDirection: 'asc' | 'desc'
): any[] => {
  return [...documents].sort((a, b) => {
    const comparison = compareAny(getSortValue(a, sortField), getSortValue(b, sortField));
    return sortDirection === 'asc' ? comparison : -comparison;
  });
};

export const formatChunkBBox = (chunk: any): Array<{ page: number; bbox: any; text: string; semanticMatches: any[] }> => {
  return (chunk.bbox || [])
    .map((item: any) => {
      if (Array.isArray(item) && item.length === 2 && typeof item[0] === 'number' && Array.isArray(item[1])) {
        return {
          page: item[0],
          bbox: { l: item[1][0], b: item[1][1], r: item[1][2], t: item[1][3] },
          text: chunk.text || '',
          semanticMatches: [],
        };
      }
      if (Array.isArray(item) && item.length === 4) {
        return {
          page: chunk.page_num,
          bbox: { l: item[0], b: item[1], r: item[2], t: item[3] },
          text: chunk.text || '',
          semanticMatches: [],
        };
      }
      return null;
    })
    .filter((item: any) => item !== null);
};

export const useDocumentsInitialLoad = (
  dataSource: string,
  loadData: () => void,
  loadTitleFacets: () => void
): void => {
  const lastDataSourceRef = useRef<string | null>(null);

  useEffect(() => {
    if (lastDataSourceRef.current === dataSource) {
      return;
    }
    lastDataSourceRef.current = dataSource;
    loadData();
    loadTitleFacets();
  }, [dataSource, loadData, loadTitleFacets]);
};

export const useDocumentsReload = (
  currentPage: number,
  selectedCategory: string | null,
  columnFilters: Record<string, string>,
  loadDocuments: () => void
): void => {
  useEffect(() => {
    loadDocuments();
  }, [currentPage, selectedCategory, columnFilters, loadDocuments]);
};

export const useFilterPopoverClose = (
  activeFilterColumn: string | null,
  onClose: () => void
): void => {
  useEffect(() => {
    if (!activeFilterColumn) {
      return;
    }
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (!target.closest('.filter-popover') && !target.closest('.filter-icon-button')) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [activeFilterColumn, onClose]);
};

export const useDebouncedFilterText = (
  filterText: string,
  loading: boolean,
  onDebouncedChange: () => void
): void => {
  const onDebouncedChangeRef = useRef(onDebouncedChange);

  useEffect(() => {
    onDebouncedChangeRef.current = onDebouncedChange;
  }, [onDebouncedChange]);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (!loading) {
        onDebouncedChangeRef.current();
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [filterText, loading]);
};

export const useSyncDocumentsUrlParams = (
  currentPage: number,
  filterText: string,
  chartView: ChartView
): void => {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);

    if (currentPage > 1) {
      params.set('page', currentPage.toString());
    } else {
      params.delete('page');
    }

    if (filterText) {
      params.set('search', filterText);
    } else {
      params.delete('search');
    }

    if (chartView !== 'year') {
      params.set('graph', chartView);
    } else {
      params.delete('graph');
    }
    if (params.has('view')) {
      params.delete('view');
    }

    const newUrl = `${window.location.pathname}?${params.toString()}`;
    window.history.replaceState({}, '', newUrl);
  }, [currentPage, filterText, chartView]);
};

export const extractTitleFacets = (data: Facets): Array<{ value: string; count: number }> => {
  const facets = data.facets;
  if (facets && facets.title) {
    return facets.title;
  }
  return [];
};
