import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import './App.css';
import API_BASE_URL, {
  AI_SUMMARY_ON,
  SEARCH_SEMANTIC_HIGHLIGHTS,
  SEMANTIC_HIGHLIGHT_THRESHOLD,
  SEARCH_RESULTS_PAGE_SIZE,
  APP_BASE_PATH
} from './config';

import {
  SearchResponse,
  Facets,
  FacetValue,
  SearchFilters,
  SearchResult,
  ModelComboConfig,
  SummaryModelConfig
} from './types/api';
import { Documents } from './components/Documents';
import { Stats } from './components/Stats';
import { Pipeline, Processing } from './components/Pipeline';
import TocModal from './components/TocModal';
import { MetadataModal } from './components/documents/MetadataModal';
import { TopBar } from './components/layout/TopBar';
import { NavTabs } from './components/layout/NavTabs';
import { SearchBox } from './components/SearchBox';
import { PdfPreviewOverlay } from './components/app/PdfPreviewOverlay';
import { SearchTabContent } from './components/app/SearchTabContent';
import { HeatmapTabContent } from './components/app/HeatmapTabContent';
import { TabContent } from './components/app/TabContent';
import { DEFAULT_SECTION_TYPES, buildSearchURL, getSearchStateFromURL } from './utils/searchUrl';
import { streamAiSummary } from './utils/aiSummaryStream';
import {
  highlightTextWithAPI,
  findSemanticMatches,
  TextMatch
} from './utils/textHighlighting';
// datasource config is now fetched dynamically
// import datasourcesConfig from './datasources.config.json';

// Configure API key header for all axios requests
const API_KEY = process.env.REACT_APP_API_KEY;
if (API_KEY) {
  if (!axios.defaults) {
    axios.defaults = {} as typeof axios.defaults;
  }
  if (!axios.defaults.headers) {
    axios.defaults.headers = {
      common: {},
      post: {},
      put: {},
      patch: {}
    };
  }
  if (!axios.defaults.headers.common) {
    axios.defaults.headers.common = {};
  }
  axios.defaults.headers.common['X-API-Key'] = API_KEY;
}

// Type for datasource configuration
interface FieldMapping {
  [coreField: string]: string; // core field name -> source field name
}

interface FilterFields {
  [coreField: string]: string; // core field name -> display label
}

export type DataSourceConfig = {
  [key: string]: DataSourceConfigItem;
};

export interface DataSourceConfigItem {
  data_subdir: string;
  field_mapping: FieldMapping;
  filter_fields: FilterFields;
  pipeline?: any; // Add pipeline to access taxonomies
}

type DataSourcesConfig = DataSourceConfig;

type DatasetTotals = Record<string, number | undefined>;

// Valid tab names for URL routing
const VALID_TABS = ['search', 'heatmap', 'documents', 'pipeline', 'processing', 'help', 'tech', 'data', 'privacy', 'stats'] as const;
type TabName = typeof VALID_TABS[number];

const isGatewayError = (error: any): boolean => {
  const status = error?.response?.status;
  return status === 502 || status === 503 || status === 504;
};

const isServerError = (error: any): boolean => error?.response?.status === 500;

const isNetworkError = (error: any): boolean =>
  error?.code === 'ERR_NETWORK' || error?.message?.includes('Network Error');

const withBasePath = (path: string): string => {
  if (!APP_BASE_PATH) return path;
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${APP_BASE_PATH}${normalized}`;
};

const stripBasePath = (pathname: string): string => {
  if (!APP_BASE_PATH) return pathname;
  if (!pathname.startsWith(APP_BASE_PATH)) return pathname;
  const stripped = pathname.slice(APP_BASE_PATH.length);
  return stripped || '/';
};

const buildSearchErrorMessage = (error: any): string => {
  if (isGatewayError(error)) {
    return 'Backend server is unreachable (502 Bad Gateway). Please check if the backend service is running.';
  }
  if (isServerError(error)) {
    return 'Backend server error (500). Please try again later.';
  }
  if (isNetworkError(error)) {
    return 'Network error. Please check your connection and ensure the backend is accessible.';
  }
  return 'Search failed. Make sure the backend is running.';
};

const translateViaApi = async (text: string, targetLanguage: string): Promise<string | null> => {
  try {
    const resp = await fetch(`${API_BASE_URL}/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(API_KEY ? { 'X-API-Key': API_KEY } : {}) },
      body: JSON.stringify({ text, target_language: targetLanguage })
    });
    if (resp.ok) {
      const data = await resp.json();
      return data.translated_text;
    }
  } catch (e) {
    console.error('Translation failed', e);
  }
  return null;
};

const buildChunkTextForTranslation = (result: SearchResult): string => {
  if (result.chunk_elements && result.chunk_elements.length > 0) {
    return result.chunk_elements
      .filter(el => el.element_type === 'text')
      .map(el => el.text)
      .join('\n\n');
  }
  return result.text;
};

const translateHeadings = async (
  headings: string[],
  targetLanguage: string
): Promise<string | undefined> => {
  if (!headings.length) {
    return undefined;
  }
  const translated = await translateViaApi(headings.join(' > '), targetLanguage);
  return translated ?? undefined;
};

const updateResultsForChunk = (
  setResults: React.Dispatch<React.SetStateAction<SearchResult[]>>,
  chunkId: string,
  updater: (result: SearchResult) => SearchResult
) => {
  setResults((prev: SearchResult[]) =>
    prev.map((r) => (r.chunk_id === chunkId ? updater(r) : r))
  );
};

const resetTranslationState = (
  setResults: React.Dispatch<React.SetStateAction<SearchResult[]>>,
  chunkId: string
) => {
  updateResultsForChunk(setResults, chunkId, (r) => ({
    ...r,
    translated_snippet: undefined,
    translated_title: undefined,
    translated_headings_display: undefined,
    translated_language: undefined,
    highlightedText: undefined
  }));
};

const setTranslationInProgress = (
  setResults: React.Dispatch<React.SetStateAction<SearchResult[]>>,
  chunkId: string,
  newLang: string
) => {
  updateResultsForChunk(setResults, chunkId, (r) => ({
    ...r,
    translated_language: newLang,
    is_translating: true
  }));
};

const applyTranslationError = (
  setResults: React.Dispatch<React.SetStateAction<SearchResult[]>>,
  chunkId: string
) => {
  updateResultsForChunk(setResults, chunkId, (r) => ({
    ...r,
    translated_language: undefined,
    is_translating: false
  }));
};

const applyTranslationResult = (
  setResults: React.Dispatch<React.SetStateAction<SearchResult[]>>,
  result: SearchResult,
  newLang: string,
  translatedTitle: string | null,
  translatedText: string | null,
  translatedHeadings: string | undefined,
  translatedSemanticMatches: TextMatch[] | undefined
) => {
  updateResultsForChunk(setResults, result.chunk_id, (r) => ({
    ...r,
    translated_title: translatedTitle ?? result.title,
    translated_snippet: translatedText ?? result.text,
    translated_headings_display: translatedHeadings,
    translated_language: newLang,
    translatedSemanticMatches,
    is_translating: false
  }));
};

const computeTranslatedSemanticMatches = async ({
  translatedText,
  translatedQuery,
  originalText,
  originalQuery,
  semanticHighlightModelConfig,
}: {
  translatedText: string | null;
  translatedQuery: string | null;
  originalText: string;
  originalQuery: string;
  semanticHighlightModelConfig: SummaryModelConfig | null;
}): Promise<TextMatch[] | undefined> => {
  if (!SEARCH_SEMANTIC_HIGHLIGHTS) {
    return undefined;
  }
  const textForHighlight = translatedText ?? originalText;
  if (!textForHighlight) {
    return undefined;
  }
  try {
    return await findSemanticMatches(
      textForHighlight,
      translatedQuery ?? originalQuery,
      SEMANTIC_HIGHLIGHT_THRESHOLD,
      semanticHighlightModelConfig
    );
  } catch (err) {
    console.error('Failed to highlight translated text', err);
    return undefined;
  }
};

const resolveRequestHighlightHandler = (
  featureEnabled: boolean,
  semanticHighlighting: boolean,
  handler: (chunkId: string, text: string) => void
): ((chunkId: string, text: string) => void) | undefined => {
  if (!featureEnabled || !semanticHighlighting) {
    return undefined;
  }
  return handler;
};

const buildSearchParams = ({
  query,
  filters,
  searchDenseWeight,
  rerankEnabled,
  recencyBoostEnabled,
  recencyWeight,
  recencyScaleDays,
  sectionTypes,
  keywordBoostShortQueries,
  minChunkSize,
  rerankModel,
  searchModel,
  dataSource,
  autoMinScore,
}: {
  query: string;
  filters: SearchFilters;
  searchDenseWeight: number;
  rerankEnabled: boolean;
  recencyBoostEnabled: boolean;
  recencyWeight: number;
  recencyScaleDays: number;
  sectionTypes: string[];
  keywordBoostShortQueries: boolean;
  minChunkSize: number;
  rerankModel: string | null;
  searchModel: string | null;
  dataSource: string;
  autoMinScore: boolean;
}): URLSearchParams => {
  const params = new URLSearchParams({ q: query, limit: SEARCH_RESULTS_PAGE_SIZE });
  for (const [field, value] of Object.entries(filters)) {
    if (value) {
      params.append(field, value);
    }
  }
  params.append('dense_weight', searchDenseWeight.toString());
  params.append('rerank', rerankEnabled.toString());
  params.append('recency_boost', recencyBoostEnabled.toString());
  params.append('recency_weight', recencyWeight.toString());
  params.append('recency_scale_days', recencyScaleDays.toString());
  if (sectionTypes.length > 0) {
    params.append('section_types', sectionTypes.join(','));
  }
  params.append('keyword_boost_short_queries', keywordBoostShortQueries.toString());
  if (minChunkSize > 0) {
    params.append('min_chunk_size', minChunkSize.toString());
  }
  if (rerankModel) {
    params.append('rerank_model', rerankModel);
  }
  if (searchModel) {
    params.append('model', searchModel);
  }
  if (autoMinScore) {
    params.append('auto_min_score', 'true');
  }
  params.append('data_source', dataSource);
  return params;
};

type ModelCombos = Record<string, ModelComboConfig>;

const fetchModelCombos = async (
  apiBaseUrl: string,
  setModelCombos: React.Dispatch<React.SetStateAction<ModelCombos>>,
  setLoading: React.Dispatch<React.SetStateAction<boolean>>
): Promise<void> => {
  try {
    const response = await axios.get<ModelCombos>(`${apiBaseUrl}/config/model-combos`);
    const data = response.data as ModelCombos;
    setModelCombos(data);
  } catch (error: any) {
    console.error('Error fetching model combos:', error);
    if (isGatewayError(error)) {
      console.warn(
        'Backend server is unreachable (502 Bad Gateway). Model selection will not be available until the backend is running.'
      );
    }
  } finally {
    setLoading(false);
  }
};

// Get initial tab from URL path
const getTabFromPath = (): TabName => {
  const params = new URLSearchParams(window.location.search);
  const tabParam = params.get('tab');
  if (tabParam && VALID_TABS.includes(tabParam as TabName)) {
    return tabParam as TabName;
  }
  if (params.get('search') || params.get('view') || params.get('page')) {
    return 'documents';
  }
  const path = stripBasePath(window.location.pathname).replace('/', '').toLowerCase();
  return VALID_TABS.includes(path as TabName) ? (path as TabName) : 'search';
};

// Core field names used in URL and API (order matters for display)
const CORE_FILTER_FIELDS = ['organization', 'title', 'published_year', 'document_type', 'country', 'language'];
const DEFAULT_PUBLISHED_YEARS = ['2020', '2021', '2022', '2023', '2024', '2025'];

function App() {
  // Initialize search state from URL parameters
  const initialSearchState = getSearchStateFromURL(
    CORE_FILTER_FIELDS,
    DEFAULT_SECTION_TYPES
  );
  const initialQueryFromUrlRef = useRef(Boolean(initialSearchState.query.trim()));
  // Capture doc_id/chunk_id from URL so we can auto-open the PDF modal after search completes
  const initialDocFromUrl = useRef<{ doc_id: string; chunk_id: string } | null>(
    (() => {
      const params = new URLSearchParams(window.location.search);
      const docId = params.get('doc_id');
      const chunkId = params.get('chunk_id');
      return docId && chunkId ? { doc_id: docId, chunk_id: chunkId } : null;
    })()
  );
  const [activeTab, setActiveTab] = useState<TabName>(getTabFromPath);

  // Config state
  const [datasourcesConfig, setDatasourcesConfig] = useState<DataSourcesConfig>({});
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [datasetTotals, setDatasetTotals] = useState<DatasetTotals>({});

  // Model Selection State
  const [modelCombos, setModelCombos] = useState<ModelCombos>({});
  const [modelCombosLoading, setModelCombosLoading] = useState(true);
  const [selectedModelCombo, setSelectedModelCombo] = useState<string | null>(
    initialSearchState.modelCombo
  );
  const [searchModel, setSearchModel] = useState<string | null>(initialSearchState.model);
  const [summaryModelConfig, setSummaryModelConfig] = useState<SummaryModelConfig | null>(null);
  const [semanticHighlightModelConfig, setSemanticHighlightModelConfig] =
    useState<SummaryModelConfig | null>(null);
  const [rerankModel, setRerankModel] = useState<string | null>(null);

  // Fetch datasources config on mount
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const response = await axios.get<DataSourcesConfig>(`${API_BASE_URL}/config/datasources`);
        setDatasourcesConfig(response.data);
      } catch (err) {
        console.error('Failed to fetch datasources config:', err);
      } finally {
        setLoadingConfig(false);
      }
    };
    fetchConfig();
  }, []);

  // Fetch model combos config on mount
  useEffect(() => {
    fetchModelCombos(API_BASE_URL, setModelCombos, setModelCombosLoading);
  }, []);

  useEffect(() => {
    if (loadingConfig) {
      return;
    }
    const domains = Object.entries(datasourcesConfig);
    if (domains.length === 0) {
      setDatasetTotals({});
      return;
    }
    let isMounted = true;
    const fetchTotals = async () => {
      const totals = await Promise.all(domains.map(async ([domainName, cfg]) => {
        const config = cfg as DataSourceConfigItem;
        if (!config.data_subdir) {
          console.error(`Missing data_subdir for dataset: ${domainName}`);
          return null;
        }
        try {
          const response = await axios.get<{ total_documents?: number }>(
            `${API_BASE_URL}/stats?data_source=${config.data_subdir}`
          );
          return {
            domainName,
            total: response.data?.total_documents,
          };
        } catch (error) {
          // Silently handle missing or unavailable data sources
          // (e.g., WorldBank may be configured but not yet populated)
          return null;
        }
      }));
      if (!isMounted) {
        return;
      }
      const nextTotals: DatasetTotals = {};
      totals.forEach((entry) => {
        if (!entry) {
          return;
        }
        if (entry.total === undefined || Number.isNaN(entry.total)) {
          return;
        }
        nextTotals[entry.domainName] = entry.total;
      });
      setDatasetTotals(nextTotals);
    };
    fetchTotals();
    return () => {
      isMounted = false;
    };
  }, [datasourcesConfig, loadingConfig]);

  // Get available domains from config
  const availableDomains = Object.keys(datasourcesConfig);

  const availableModelCombos = Object.keys(modelCombos);
  const defaultModelCombo = availableModelCombos[0] || '';
  const resolvedModelCombo = (
    selectedModelCombo && availableModelCombos.includes(selectedModelCombo)
  )
    ? selectedModelCombo
    : (defaultModelCombo || 'Models');

  const [selectedDomain, setSelectedDomain] = useState<string>(() => {
    // Initial state setup needs to handle empty config initially,
    // but we can default to dataset param if present, or wait for config load?
    // For now, let's just initialize with what we have from URL
    if (initialSearchState.dataset) {
      return initialSearchState.dataset;
    }
    return 'UN Humanitarian Evaluation';  // Fallback default
  });

  // Update selected domain when config loads if needed, or ensure it's valid
  useEffect(() => {
    if (!loadingConfig && availableDomains.length > 0) {
      // If URL has a dataset parameter, use it if it's valid
      if (initialSearchState.dataset && availableDomains.includes(initialSearchState.dataset)) {
        // Set it if it's different - this ensures dataSource is recalculated when config loads
        if (selectedDomain !== initialSearchState.dataset) {
          setSelectedDomain(initialSearchState.dataset);
        }
      } else if (!availableDomains.includes(selectedDomain)) {
        // Only override if current selection is invalid and no valid dataset in URL
        setSelectedDomain(availableDomains[0]);
      }
    }
  }, [loadingConfig, availableDomains, selectedDomain, initialSearchState.dataset]);

  // Update selected model combo when config loads if needed, or ensure it's valid
  useEffect(() => {
    if (modelCombosLoading || availableModelCombos.length === 0) {
      return;
    }
    if (
      initialSearchState.modelCombo
      && availableModelCombos.includes(initialSearchState.modelCombo)
    ) {
      if (selectedModelCombo !== initialSearchState.modelCombo) {
        setSelectedModelCombo(initialSearchState.modelCombo);
      }
      return;
    }
    if (!selectedModelCombo || !availableModelCombos.includes(selectedModelCombo)) {
      setSelectedModelCombo(availableModelCombos[0]);
    }
  }, [
    modelCombosLoading,
    availableModelCombos,
    selectedModelCombo,
    initialSearchState.modelCombo,
  ]);

  useEffect(() => {
    if (!selectedModelCombo) {
      return;
    }
    const combo = modelCombos[selectedModelCombo];
    if (!combo) {
      return;
    }
    setSearchModel(combo.embedding_model);
    setSummaryModelConfig(combo.summarization_model);
    setSemanticHighlightModelConfig(combo.semantic_highlighting_model);
    setRerankModel(combo.reranker_model);
  }, [selectedModelCombo, modelCombos]);


  const [domainDropdownOpen, setDomainDropdownOpen] = useState(false);
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [helpDropdownOpen, setHelpDropdownOpen] = useState(false);
  const [showDomainTooltip, setShowDomainTooltip] = useState(false);
  const [aboutContent, setAboutContent] = useState('');
  const [techContent, setTechContent] = useState('');
  const [dataContent, setDataContent] = useState('');
  const [privacyContent, setPrivacyContent] = useState('');
  const tooltipTimeoutRef = React.useRef<number | null>(null);

  const handleToggleDomainDropdown = useCallback(() => {
    setDomainDropdownOpen(!domainDropdownOpen);
    setModelDropdownOpen(false);
    setHelpDropdownOpen(false);
    setShowDomainTooltip(false);
    if (tooltipTimeoutRef.current) {
      clearTimeout(tooltipTimeoutRef.current);
      tooltipTimeoutRef.current = null;
    }
  }, [domainDropdownOpen]);

  const handleToggleModelDropdown = useCallback(() => {
    setModelDropdownOpen(!modelDropdownOpen);
    setDomainDropdownOpen(false);
    setHelpDropdownOpen(false);
  }, [modelDropdownOpen]);

  const handleDomainMouseEnter = useCallback(() => {
    tooltipTimeoutRef.current = window.setTimeout(() => {
      if (!domainDropdownOpen) {
        setShowDomainTooltip(true);
      }
    }, 2000);
  }, [domainDropdownOpen]);

  const handleDomainMouseLeave = useCallback(() => {
    if (tooltipTimeoutRef.current) {
      clearTimeout(tooltipTimeoutRef.current);
      tooltipTimeoutRef.current = null;
    }
    setShowDomainTooltip(false);
  }, []);

  const handleDomainBlur = useCallback(() => {
    setTimeout(() => setDomainDropdownOpen(false), 200);
  }, []);

  const handleModelBlur = useCallback(() => {
    setTimeout(() => setModelDropdownOpen(false), 200);
  }, []);

  const handleSelectDomain = useCallback((domainName: string) => {
    setSelectedDomain(domainName);
    const url = new URL(window.location.href);
    url.searchParams.set('dataset', domainName);
    window.history.replaceState(null, '', url.toString());
    setDomainDropdownOpen(false);
  }, []);

  const handleSelectModelCombo = useCallback((comboName: string) => {
    setSelectedModelCombo(comboName);
    setInitialSearchDone(false);
    const url = new URL(window.location.href);
    url.searchParams.set('model_combo', comboName);
    window.history.replaceState(null, '', url.toString());
    setModelDropdownOpen(false);
  }, []);

  const handleToggleHelpDropdown = useCallback(() => {
    setHelpDropdownOpen(!helpDropdownOpen);
    setDomainDropdownOpen(false);
    setModelDropdownOpen(false);
  }, [helpDropdownOpen]);

  const handleHelpBlur = useCallback(() => {
    setTimeout(() => setHelpDropdownOpen(false), 200);
  }, []);

  // Get current datasource config
  const currentDataSourceConfig = datasourcesConfig[selectedDomain] || {};

  // Get data source for API calls (from datasource config)
  // Ensure dataSource updates when config loads and selectedDomain is available
  const dataSource = React.useMemo(() => {
    // If we have a selectedDomain and config is loaded, get the data_subdir
    if (!loadingConfig && selectedDomain && datasourcesConfig[selectedDomain]) {
      return datasourcesConfig[selectedDomain].data_subdir || 'uneg';
    }
    // If config is still loading but we have a dataset in URL, we need to wait
    // Return 'uneg' as fallback, but it will update when config loads
    return currentDataSourceConfig?.data_subdir || 'uneg';
  }, [loadingConfig, selectedDomain, datasourcesConfig, currentDataSourceConfig]);

  const fieldMapping = currentDataSourceConfig?.field_mapping || {};
  const filterFields = currentDataSourceConfig?.filter_fields || {};


  // Initialize search state from URL parameters - MOVED TO TOP
  const [query, setQuery] = useState(initialSearchState.query);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [allFacets, setAllFacets] = useState<Facets | null>(null);
  const [facetsDataSource, setFacetsDataSource] = useState<string | null>(null);
  const [allFacetsDataSource, setAllFacetsDataSource] = useState<string | null>(null);
  const [filters, setFilters] = useState<SearchFilters>(initialSearchState.filters);
  const [initialSearchDone, setInitialSearchDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<SearchResult | null>(null);
  const [expandedCards, setExpandedCards] = useState<Set<string>>(new Set());
  // TOC modal state for search results
  const [tocModalOpen, setTocModalOpen] = useState(false);
  const [selectedTocDocId, setSelectedTocDocId] = useState<string>('');
  const [selectedToc, setSelectedToc] = useState<string>('');
  const [selectedTocPdfUrl, setSelectedTocPdfUrl] = useState<string>('');
  const [selectedTocPageCount, setSelectedTocPageCount] = useState<number | null>(null);
  const [loadingToc, setLoadingToc] = useState(false);
  const [metadataModalOpen, setMetadataModalOpen] = useState(false);
  const [metadataModalDoc, setMetadataModalDoc] = useState<Record<string, any> | null>(null);
  const fetchTocPdfUrl = useCallback(async (docId: string) => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/document/${docId}`,
        { params: { data_source: dataSource } }
      );
      const doc = response.data as {
        pdf_url?: string;
      };
      const pdfUrl = doc.pdf_url || '';
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

  const [minScore, setMinScore] = useState<number>(0.0);
  const [maxScore, setMaxScore] = useState<number>(1.0);
  const [autoMinScore, setAutoMinScore] = useState<boolean>(initialSearchState.autoMinScore);
  const [searchDenseWeight, setSearchDenseWeight] = useState<number>(initialSearchState.denseWeight); // Default from .env or URL
  const [rerankEnabled, setRerankEnabled] = useState<boolean>(initialSearchState.rerank); // Reranker toggle from URL
  // Recency boost state
  const [recencyBoostEnabled, setRecencyBoostEnabled] = useState<boolean>(initialSearchState.recencyBoost);
  const [recencyWeight, setRecencyWeight] = useState<number>(initialSearchState.recencyWeight);
  const [recencyScaleDays, setRecencyScaleDays] = useState<number>(initialSearchState.recencyScaleDays);
  // Keyword boost for short queries
  const [keywordBoostShortQueries, setKeywordBoostShortQueries] = useState<boolean>(initialSearchState.keywordBoostShortQueries);
  // Semantic Highlighting state
  const [semanticHighlighting, setSemanticHighlighting] = useState<boolean>(initialSearchState.semanticHighlighting);
  // Content settings
  const [sectionTypes, setSectionTypes] = useState<string[]>(initialSearchState.sectionTypes);
  const [minChunkSize, setMinChunkSize] = useState<number>(initialSearchState.minChunkSize);
  const [aiSummary, setAiSummary] = useState<string>('');
  const [aiSummaryLoading, setAiSummaryLoading] = useState<boolean>(false);
  const [aiPrompt, setAiPrompt] = useState<string>('');
  const [showPromptModal, setShowPromptModal] = useState<boolean>(false);
  const [aiSummaryCollapsed, setAiSummaryCollapsed] = useState<boolean>(false);
  const [aiSummaryExpanded, setAiSummaryExpanded] = useState<boolean>(false);

  const [aiSummaryBuffer, setAiSummaryBuffer] = useState<string>(''); // Buffer for character animation

  // Debug: Log semantic threshold on startup
  useEffect(() => {
    console.log(`[Config] Semantic Highlight Threshold: ${SEMANTIC_HIGHLIGHT_THRESHOLD}`);
    console.log(`[Config] Semantic Highlighting Enabled: ${SEARCH_SEMANTIC_HIGHLIGHTS}`);
  }, []);

  // Update URL when tab changes
  const handleTabChange = useCallback((tab: TabName) => {
    setActiveTab(tab);
    let newPath = tab === 'search' ? '/' : `/${tab}`;
    newPath = withBasePath(newPath);

    // Preserve dataset/model in URL when switching tabs
    const params = new URLSearchParams();
    if (selectedDomain) {
      params.set('dataset', selectedDomain);
    }
    if (searchModel) {
      params.set('model', searchModel);
    }
    if (selectedModelCombo) {
      params.set('model_combo', selectedModelCombo);
    }
    if (tab !== 'search') {
      params.set('tab', tab);
    }

    const queryString = params.toString();
    if (queryString) {
      newPath += `?${queryString}`;
    }

    window.history.pushState(null, '', newPath);
  }, [selectedDomain, searchModel, selectedModelCombo]);

  const handleAboutClick = useCallback(() => {
    handleTabChange('help');
    setHelpDropdownOpen(false);
  }, [handleTabChange]);

  const handleTechClick = useCallback(() => {
    handleTabChange('tech');
    setHelpDropdownOpen(false);
  }, [handleTabChange]);

  const handleDataClick = useCallback(() => {
    handleTabChange('data');
    setHelpDropdownOpen(false);
  }, [handleTabChange]);

  const handlePrivacyClick = useCallback(() => {
    handleTabChange('privacy');
    setHelpDropdownOpen(false);
  }, [handleTabChange]);


  // Listen for browser back/forward navigation and URL changes
  useEffect(() => {
    const handlePopState = () => {
      setActiveTab(getTabFromPath());
      // Also restore search state from URL
      const searchState = getSearchStateFromURL(
        CORE_FILTER_FIELDS,
        DEFAULT_SECTION_TYPES
      );
      setQuery(searchState.query);
      setFilters(searchState.filters);
      // Restore selected filter arrays (dynamic)
      setSelectedFilters(searchState.selectedFilters);
      // Restore search mode settings
      setSearchDenseWeight(searchState.denseWeight);
      setRerankEnabled(searchState.rerank);
      // Restore content settings
      setSectionTypes(searchState.sectionTypes);
      // Restore min chunk size
      setMinChunkSize(searchState.minChunkSize);
      // Restore semantic highlighting
      setSemanticHighlighting(searchState.semanticHighlighting);
      setSearchModel(searchState.model);
      setSelectedModelCombo(searchState.modelCombo);

      // Restore dataset if valid
      if (searchState.dataset && availableDomains.includes(searchState.dataset)) {
        setSelectedDomain(searchState.dataset);
      }
    };

    // Also check URL on mount and when availableDomains changes (for direct navigation)
    const checkURLForDataset = () => {
      const searchState = getSearchStateFromURL(
        CORE_FILTER_FIELDS,
        DEFAULT_SECTION_TYPES
      );
      if (searchState.dataset && availableDomains.includes(searchState.dataset) && selectedDomain !== searchState.dataset) {
        setSelectedDomain(searchState.dataset);
      }
    };

    window.addEventListener('popstate', handlePopState);
    // Check URL when domains are available (handles direct navigation to URLs with dataset param)
    if (!loadingConfig && availableDomains.length > 0) {
      checkURLForDataset();
    }

    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, [availableDomains, loadingConfig, selectedDomain]);


  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const toggleFiltersExpanded = useCallback(() => {
    setFiltersExpanded((prev) => !prev);
  }, []);

  const buildEmptySelectedFilters = () => {
    const cleared: Record<string, string[]> = {};
    for (const field of CORE_FILTER_FIELDS) {
      cleared[field] = [];
    }
    return cleared;
  };

  const defaultYearFiltersAppliedRef = useRef(false);

  // Multi-select filters (dynamic by core field name) - initialize from URL
  const [selectedFilters, setSelectedFilters] = useState<Record<string, string[]>>(initialSearchState.selectedFilters);
  const [heatmapFilters, setHeatmapFilters] = useState<SearchFilters>({});
  const [heatmapSelectedFilters, setHeatmapSelectedFilters] = useState<Record<string, string[]>>(
    buildEmptySelectedFilters()
  );

  const buildHeatmapFacetFilters = useCallback(() => {
    const nextFilters = { ...heatmapFilters };
    delete nextFilters.published_year;
    return nextFilters;
  }, [heatmapFilters]);

  // Collapsed filters state (all collapsed by default) - use core field names
  const [collapsedFilters, setCollapsedFilters] = useState<Set<string>>(() => {
    const defaultCollapsed = new Set(CORE_FILTER_FIELDS);
    defaultCollapsed.add('search_settings');
    defaultCollapsed.add('content_settings');
    return defaultCollapsed;
  });
  const [heatmapCollapsedFilters, setHeatmapCollapsedFilters] = useState<Set<string>>(() => {
    const defaultCollapsed = new Set(CORE_FILTER_FIELDS);
    defaultCollapsed.add('search_settings');
    defaultCollapsed.add('content_settings');
    return defaultCollapsed;
  });

  // Track which filter lists are expanded to show all items (default shows 5)
  const [expandedFilterLists, setExpandedFilterLists] = useState<Set<string>>(new Set());
  const [heatmapExpandedFilterLists, setHeatmapExpandedFilterLists] = useState<Set<string>>(new Set());

  // Search terms for each filter (dynamic by core field name)
  const [filterSearchTerms, setFilterSearchTerms] = useState<Record<string, string>>({});

  // Collapsed headings state for search results (all collapsed by default)
  const [collapsedHeadings, setCollapsedHeadings] = useState<Set<number>>(new Set());

  // Title search state
  const [titleSearchResults, setTitleSearchResults] = useState<FacetValue[]>([]);
  const [isSearchingTitles, setIsSearchingTitles] = useState(false);
  const titleSearchTimeoutRef = useRef<any>(null);

  const handleFilterChange = (key: string, value: string) => {
    setFilters(prev => ({ ...prev, [key]: value || undefined }));
  };

  const handleHeatmapFilterChange = (key: string, value: string) => {
    setHeatmapFilters(prev => ({ ...prev, [key]: value || undefined }));
  };

  const buildFilterValue = (values: string[]) =>
    values.length > 0 ? values.join(',') : '';

  const handleRemoveFilter = useCallback(
    (coreField: string, value: string) => {
      const selectedValues = selectedFilters[coreField] || [];
      const newValues = selectedValues.filter((item) => item !== value);
      setSelectedFilters((prev: Record<string, string[]>) => ({
        ...prev,
        [coreField]: newValues,
      }));
      handleFilterChange(coreField, buildFilterValue(newValues));
    },
    [buildFilterValue, handleFilterChange, selectedFilters]
  );

  const handleFilterValuesChange = useCallback(
    (coreField: string, nextValues: string[]) => {
      setSelectedFilters((prev: Record<string, string[]>) => ({
        ...prev,
        [coreField]: nextValues,
      }));
      handleFilterChange(coreField, buildFilterValue(nextValues));
    },
    [buildFilterValue, handleFilterChange]
  );

  const handleHeatmapRemoveFilter = useCallback(
    (coreField: string, value: string) => {
      const selectedValues = heatmapSelectedFilters[coreField] || [];
      const newValues = selectedValues.filter((item) => item !== value);
      setHeatmapSelectedFilters((prev: Record<string, string[]>) => ({
        ...prev,
        [coreField]: newValues,
      }));
      handleHeatmapFilterChange(coreField, buildFilterValue(newValues));
    },
    [buildFilterValue, handleHeatmapFilterChange, heatmapSelectedFilters]
  );

  const handleHeatmapFilterValuesChange = useCallback(
    (coreField: string, nextValues: string[]) => {
      setHeatmapSelectedFilters((prev: Record<string, string[]>) => ({
        ...prev,
        [coreField]: nextValues,
      }));
      handleHeatmapFilterChange(coreField, buildFilterValue(nextValues));
    },
    [buildFilterValue, handleHeatmapFilterChange]
  );

  // Auto-collapse all filter fields (including taxonomy fields) when facets first load
  useEffect(() => {
    if (facets?.filter_fields) {
      setCollapsedFilters(prev => {
        const newSet = new Set(prev);
        Object.keys(facets.filter_fields).forEach(field => {
          newSet.add(field);
        });
        return newSet;
      });
    }
  }, [facets?.filter_fields]);

  // Auto-collapse all filter fields in heatmap tab when facets load
  useEffect(() => {
    if (allFacets?.filter_fields) {
      setHeatmapCollapsedFilters(prev => {
        const newSet = new Set(prev);
        Object.keys(allFacets.filter_fields).forEach(field => {
          newSet.add(field);
        });
        return newSet;
      });
    }
  }, [allFacets?.filter_fields]);

  // Perform title search when title filter input changes
  useEffect(() => {
    const titleQuery = filterSearchTerms['title'];

    // clear previous timeout
    if (titleSearchTimeoutRef.current) {
      clearTimeout(titleSearchTimeoutRef.current);
    }

    if (!titleQuery || titleQuery.trim().length < 2) {
      setTitleSearchResults([]);
      setIsSearchingTitles(false);
      return;
    }

    // Debounce search
    titleSearchTimeoutRef.current = setTimeout(async () => {
      setIsSearchingTitles(true);
      try {
        const params = new URLSearchParams();
        params.append('q', titleQuery.trim());
        params.append('limit', '50');
        params.append('data_source', dataSource);

        if (searchModel) params.append('model', searchModel);

        const response = await axios.get<any[]>(`${API_BASE_URL}/search/titles?${params}`);
        const data = response.data as any[];

        // Map response to FacetValue format
        const facets: FacetValue[] = data.map((item: any) => ({
          value: item.title,
          count: 1, // Count is less relevant for direct search, but needed for interface
          organization: item.organization,
          published_year: item.year ? String(item.year) : undefined
        }));

        setTitleSearchResults(facets);
      } catch (error) {
        console.error('Title search failed:', error);
      } finally {
        setIsSearchingTitles(false);
      }
    }, 300); // 300ms debounce

    return () => {
      if (titleSearchTimeoutRef.current) {
        clearTimeout(titleSearchTimeoutRef.current);
      }
    };
  }, [filterSearchTerms['title'], dataSource, searchDenseWeight, searchModel]);

  // General Facet Value Search State
  // Map of field -> list of FacetValues found via search
  const [facetSearchResults, setFacetSearchResults] = useState<Record<string, FacetValue[]>>({});
  const facetSearchTimeoutRef = useRef<any>(null);

  // Perform generic facet value search when filter input changes (for fields other than title)
  useEffect(() => {
    // We only care about fields that have search terms AND are not title
    Object.entries(filterSearchTerms).forEach(([field, query]) => {
      if (field === 'title') return; // Handled by separate effect

      // Clear specific searches if query is empty
      if (!query || query.trim().length < 2) {
        setFacetSearchResults(prev => {
          const next = { ...prev };
          delete next[field];
          return next;
        });
      }
    });

    // Better Approach: Iterate and find which one triggered? No, simpler:
    // This effect runs on `filterSearchTerms`.
    // We can just debounce the API call for ANY field that has a value.
    // However, if we have "Uni" in Org and "20" in Year, we don't want to re-search Org when typing Year.
    // So we should track 'prevFilterSearchTerms' or similar.
    // OR just use a separate generic handler.

    // Simplest Robust Implementation:
    // Just handle the search in the `onChange` handler directly (debounced there) instead of a global effect?
    // But `filterSearchTerms` is state.
    // Let's stick to the Effect but use a ref to track which one changed?
    // No, let's just use a ref for the timeout.

    // We will initiate a search for the changed field.
    // Actually, we can reuse the `titleSearchTimeoutRef` pattern but generalized.
    // But since we can't easily know *which* key changed in a massive object dependency,
    // we'll implement a `performFacetSearch` function and call it from the `onChange` event in the JSX.
    // That avoids this complex Effect logic.

  }, [filterSearchTerms]); // We will actually remove this generic effect and move logic to specific handler.

  const performFacetSearch = (field: string, query: string) => {
    if (facetSearchTimeoutRef.current) clearTimeout(facetSearchTimeoutRef.current);

    if (!query || query.trim().length < 2) {
      setFacetSearchResults(prev => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
      return;
    }

    facetSearchTimeoutRef.current = setTimeout(async () => {
      try {
        const params = new URLSearchParams();
        params.append('field', field);
        params.append('q', query.trim());
        params.append('limit', '100');
        params.append('data_source', dataSource);

        const response = await axios.get<any[]>(`${API_BASE_URL}/search/facet-values?${params}`);
        const data = response.data as any[];

        // Map response
        const facets: FacetValue[] = data.map((item: any) => ({
          value: item.value,
          count: item.count
        }));

        setFacetSearchResults(prev => ({
          ...prev,
          [field]: facets
        }));

      } catch (e) {
        console.error(`Facet search failed for ${field}:`, e);
      }
    }, 300);
  };

  const handleFilterSearchTermChange = useCallback(
    (coreField: string, value: string) => {
      setFilterSearchTerms((prev) => ({ ...prev, [coreField]: value }));
      if (coreField !== 'title') {
        performFacetSearch(coreField, value);
      }
    },
    [performFacetSearch]
  );


  const toggleFilter = (filterName: string) => {
    setCollapsedFilters(prev => {
      const newSet = new Set(prev);
      if (newSet.has(filterName)) {
        newSet.delete(filterName);
      } else {
        newSet.add(filterName);
      }
      return newSet;
    });
  };

  const toggleHeatmapFilter = (filterName: string) => {
    setHeatmapCollapsedFilters(prev => {
      const newSet = new Set(prev);
      if (newSet.has(filterName)) {
        newSet.delete(filterName);
      } else {
        newSet.add(filterName);
      }
      return newSet;
    });
  };

  const toggleFilterListExpansion = (filterKey: string) => {
    setExpandedFilterLists(prev => {
      const newSet = new Set(prev);
      if (newSet.has(filterKey)) {
        newSet.delete(filterKey);
      } else {
        newSet.add(filterKey);
      }
      return newSet;
    });
  };

  const toggleHeatmapFilterListExpansion = (filterKey: string) => {
    setHeatmapExpandedFilterLists(prev => {
      const newSet = new Set(prev);
      if (newSet.has(filterKey)) {
        newSet.delete(filterKey);
      } else {
        newSet.add(filterKey);
      }
      return newSet;
    });
  };

  const toggleHeadings = (resultIndex: number) => {
    setCollapsedHeadings(prev => {
      const newSet = new Set(prev);
      if (newSet.has(resultIndex)) {
        newSet.delete(resultIndex);
      } else {
        newSet.add(resultIndex);
      }
      return newSet;
    });
  };

  const loadFacets = useCallback(async (options?: { includeQuery?: boolean; filtersOverride?: SearchFilters }) => {
    try {
      if (loadingConfig && initialSearchState.dataset) {
        return;
      }
      const includeQuery = options?.includeQuery ?? true;
      const filtersToUse = options?.filtersOverride ?? filters;
      const params = new URLSearchParams();
      // Add all filter values using core field names
      for (const [field, value] of Object.entries(filtersToUse)) {
        if (value) {
          params.append(field, value);
        }
      }
      params.append('data_source', dataSource);
      if (includeQuery && query && query.trim()) {
        params.append('q', query.trim());
      }

      const url = `${API_BASE_URL}/facets?${params}`;
      const response = await axios.get<Facets>(url);
      const data = response.data as Facets;

      // Always update facets
      setFacets(data);
      setFacetsDataSource(dataSource);
    } catch (error: any) {
      console.error('Error loading facets:', error);
      if (error?.response?.status === 502 || error?.response?.status === 503 || error?.response?.status === 504) {
        console.warn('Backend server is unreachable (502 Bad Gateway). Facets will not be available until the backend is running.');
      }
    }
  }, [loadingConfig, initialSearchState.dataset, filters, dataSource, query]);

  const loadAllFacets = useCallback(async () => {
    try {
      if (loadingConfig && initialSearchState.dataset) {
        return;
      }
      const params = new URLSearchParams();
      params.append('data_source', dataSource);
      const url = `${API_BASE_URL}/facets?${params}`;
      const response = await axios.get<Facets>(url);
      const data = response.data as Facets;
      setAllFacets(data);
      setAllFacetsDataSource(dataSource);
    } catch (error) {
      console.error('Error loading all facets:', error);
    }
  }, [loadingConfig, initialSearchState.dataset, dataSource]);

  // Load about/tech/data/privacy content when help tabs are active
  useEffect(() => {
    if (activeTab === 'help') {
      // Add timestamp to prevent caching during development
      fetch(`${withBasePath('/docs/about.md')}?t=${Date.now()}`)
        .then(response => response.text())
        .then(text => setAboutContent(text))
        .catch(err => console.error('Failed to load about content:', err));
    }
    if (activeTab === 'tech') {
      // Add timestamp to prevent caching during development
      fetch(`${withBasePath('/docs/tech.md')}?t=${Date.now()}`)
        .then(response => response.text())
        .then(text => setTechContent(text))
        .catch(err => console.error('Failed to load tech content:', err));
    }
    if (activeTab === 'data') {
      // Add timestamp to prevent caching during development
      fetch(`${withBasePath('/docs/data.md')}?t=${Date.now()}`)
        .then(response => response.text())
        .then(text => setDataContent(text))
        .catch(err => console.error('Failed to load data content:', err));
    }
    if (activeTab === 'privacy') {
      // Add timestamp to prevent caching during development
      fetch(`${withBasePath('/docs/privacy.md')}?t=${Date.now()}`)
        .then(response => response.text())
        .then(text => setPrivacyContent(text))
        .catch(err => console.error('Failed to load privacy content:', err));
    }
  }, [activeTab]);

  // Load facets on mount, when filters change, or when data source changes
  // Heatmap uses full dataset facets by default, even if a query is present.
  useEffect(() => {
    if (activeTab === 'heatmap') {
      loadFacets({ includeQuery: false, filtersOverride: buildHeatmapFacetFilters() });
    } else {
      loadFacets();
    }
  }, [filters, heatmapFilters, dataSource, activeTab, loadFacets, buildHeatmapFacetFilters]);

  useEffect(() => {
    loadAllFacets();
  }, [dataSource, loadAllFacets]);

  useEffect(() => {
    defaultYearFiltersAppliedRef.current = false;
  }, [dataSource]);

  useEffect(() => {
    if (activeTab !== 'heatmap') {
      return;
    }
    if (defaultYearFiltersAppliedRef.current) {
      return;
    }
    if (heatmapFilters.published_year || (heatmapSelectedFilters.published_year || []).length > 0) {
      defaultYearFiltersAppliedRef.current = true;
      return;
    }
    const yearFacets = facets?.facets?.published_year || [];
    if (yearFacets.length === 0) {
      return;
    }
    const availableYears = new Set(yearFacets.map((item) => item.value));
    const nextYears = DEFAULT_PUBLISHED_YEARS.filter((year) => availableYears.has(year));
    defaultYearFiltersAppliedRef.current = true;
    if (nextYears.length === 0) {
      return;
    }
    setHeatmapSelectedFilters((prev) => ({ ...prev, published_year: nextYears }));
    setHeatmapFilters((prev) => ({ ...prev, published_year: nextYears.join(',') }));
  }, [
    activeTab,
    facets,
    heatmapFilters.published_year,
    heatmapSelectedFilters.published_year,
  ]);



  // Track if we've done initial search to avoid double-searching on load
  // Update URL when search state changes (after results are loaded)
  useEffect(() => {
    if (activeTab !== 'search') {
      return;
    }
    if (results.length > 0 && query.trim()) {
      const searchParams = buildSearchURL(
        query,
        filters,
        searchDenseWeight,
        rerankEnabled,
        recencyBoostEnabled,
        recencyWeight,
        recencyScaleDays,
        sectionTypes,
        keywordBoostShortQueries,
        minChunkSize,
        semanticHighlighting,
        autoMinScore,
        searchModel,
        selectedModelCombo,
        selectedDomain
      );
      // Build URLSearchParams from the base search params
      const params = new URLSearchParams(searchParams || '');
      // Append or remove doc_id/chunk_id depending on whether a document is selected
      if (selectedDoc) {
        params.set('doc_id', selectedDoc.doc_id);
        params.set('chunk_id', selectedDoc.chunk_id);
      } else {
        params.delete('doc_id');
        params.delete('chunk_id');
      }
      const finalParams = params.toString();
      const searchString = finalParams ? `?${finalParams}` : '';
      const newURL = withBasePath(finalParams ? `/?${finalParams}` : '/');
      if (window.location.search !== searchString) {
        window.history.replaceState(null, '', newURL);
      }
    }
  }, [
    activeTab,
    results,
    query,
    filters,
    searchDenseWeight,
    rerankEnabled,
    recencyBoostEnabled,
    recencyWeight,
    recencyScaleDays,
    sectionTypes,
    keywordBoostShortQueries,
    semanticHighlighting,
    autoMinScore,
    searchModel,
    selectedModelCombo,
    selectedDoc,
  ]);

  // Auto-open PDF modal if URL contained doc_id/chunk_id when page loaded
  useEffect(() => {
    if (!initialDocFromUrl.current || results.length === 0) return;
    const { doc_id, chunk_id } = initialDocFromUrl.current;
    const match = results.find(r => r.doc_id === doc_id && r.chunk_id === chunk_id);
    if (match) {
      setSelectedDoc(match);
      initialDocFromUrl.current = null; // Only do this once
    }
  }, [results]);

  const processingHighlightsRef = useRef<Set<string>>(new Set());
  const isSearchingRef = useRef(false);

  // Callback to perform highlighting for a single result
  const handleRequestHighlight = useCallback(async (chunkId: string, text: string) => {
    if (processingHighlightsRef.current.has(chunkId)) return;

    // Check if result already has highlighting
    // Since we don't depend on "results", we need to check this logic in context or assume caller checked.
    // The caller (SearchResultCard) checks !result.highlightedText before calling.
    // But we should double check if another request race finished?
    // We rely on processingHighlightsRef for in-flight dedupe.

    processingHighlightsRef.current.add(chunkId);
    console.log(`[Highlight] Starting semantic highlighting for ${chunkId}`);

    try {
      // Call unified highlight API which returns HTML with <em> tags

      // Use the improved findSemanticMatches utility which handles alignment and offsets correctly
      // This avoids the issue where "safety" highlights every instance of "safety" in the document.
      const semanticMatches = await findSemanticMatches(
        text,
        query,
        SEMANTIC_HIGHLIGHT_THRESHOLD,
        semanticHighlightModelConfig
      );

      // Update state
      setResults((prev: SearchResult[]) => prev.map((r: SearchResult) => {
        if (r.chunk_id === chunkId) {
          // Add similarity: 1.0 as a default for these matches since we don't get per-match scores from this flow easily
          // (The backend simply returns <em> tags).
          const matchesWithScore = semanticMatches.map(m => ({
            ...m,
            similarity: 1.0
          }));

          return {
            ...r,
            highlightedText: r.text, // Trigger re-render with highlighting enabled
            semanticMatches: matchesWithScore
          };
        }
        return r;
      }));
    } catch (error) {
      console.error(`[Highlight] Error for ${chunkId}:`, error);
    } finally {
      processingHighlightsRef.current.delete(chunkId);
    }
  }, [query, semanticHighlightModelConfig]);

  const handleAiSummaryForResults = useCallback((data: SearchResponse) => {
    if (!AI_SUMMARY_ON || data.results.length === 0) {
      setAiSummary('');
      setAiPrompt('');
      return;
    }
    if (!summaryModelConfig) {
      console.error('AI summary model config is missing.');
      setAiSummary('AI summary unavailable: no summary model configured.');
      setAiSummaryLoading(false);
      return;
    }

    setAiSummaryLoading(true);
    setAiSummary('');
    setAiSummaryBuffer('');
    setAiPrompt('');

    streamAiSummary({
      apiBaseUrl: API_BASE_URL,
      apiKey: API_KEY || undefined,
      dataSource,
      query,
      results: data.results.slice(0, 20),
      summaryModelConfig,
      handlers: {
        onPrompt: setAiPrompt,
        onToken: setAiSummary,
        onDone: () => setAiSummaryLoading(false),
        onError: (message: string) => {
          console.error('AI summary streaming error:', message);
          setAiSummary('Uh oh. Something went wrong asking the AI.');
          setAiSummaryLoading(false);
        },
      },
    }).catch((error) => {
      console.error('AI summary streaming failed:', error);
      setAiSummary('Uh oh. Something went wrong asking the AI.');
      setAiSummaryLoading(false);
    });
  }, [dataSource, query, summaryModelConfig]);

  const handlePostSearchResults = useCallback((data: SearchResponse) => {
    if (data.results.length > 0) {
      const calculatedMaxScore = Math.max(...data.results.map(r => r.score || 0));
      const roundedMaxScore = Math.ceil(calculatedMaxScore * 2) / 2;
      setMaxScore(roundedMaxScore);

      console.log('SEARCH_SEMANTIC_HIGHLIGHTS flag:', SEARCH_SEMANTIC_HIGHLIGHTS, 'User Setting:', semanticHighlighting);
      if (SEARCH_SEMANTIC_HIGHLIGHTS && semanticHighlighting) {
        const maxResults = Math.min(10, data.results.length);
        console.log('Starting explicit semantic highlighting for top', maxResults);

        const processResult = async (idx: number) => {
          if (idx >= maxResults) return;
          const res = data.results[idx];
          await handleRequestHighlight(res.chunk_id, res.text);
          processResult(idx + 1);
        };

        processResult(0);
      }
    } else {
      setMaxScore(3.0);
    }
  }, [semanticHighlighting, handleRequestHighlight]);

  // Auto min_score is now handled server-side - no client calculation needed

  const handleSearchError = useCallback((error: any) => {
    console.error('Error searching:', error);
    setSearchError(buildSearchErrorMessage(error));
  }, []);

  const performSearch = useCallback(async () => {
    if (!query.trim() || isSearchingRef.current) {
      if (isSearchingRef.current) {
        console.warn("Search already in progress, skipping double call.");
      }
      return;
    }

    setLoading(true);
    setSearchError(null);
    processingHighlightsRef.current.clear(); // Clear highlight locks
    isSearchingRef.current = true;

    try {
      const params = buildSearchParams({
        query,
        filters,
        searchDenseWeight,
        rerankEnabled,
        recencyBoostEnabled,
        recencyWeight,
        recencyScaleDays,
        sectionTypes,
        keywordBoostShortQueries,
        minChunkSize,
        rerankModel,
        searchModel,
        dataSource,
        autoMinScore,
      });

      const searchStartTime = performance.now();
      console.log(`[Perf] Starting search request at ${new Date().toISOString()}`);
      console.time('Total Search API Time');

      const response = await axios.get<SearchResponse>(`${API_BASE_URL}/search?${params}`);
      const data = response.data as SearchResponse;

      console.timeEnd('Total Search API Time');
      const searchEndTime = performance.now();
      console.log(`[Perf] Search API took ${(searchEndTime - searchStartTime).toFixed(2)}ms`);
      console.log(`[Perf] Results count: ${data.results.length}`);
      setResults(data.results);
      // Initialize all headings as collapsed by default
      setCollapsedHeadings(new Set(data.results.map((_, index) => index)));

      // Reload facets to reflect search result distribution
      loadFacets();

      handleAiSummaryForResults(data);
      handlePostSearchResults(data);
    } catch (error: any) {
      handleSearchError(error);
    } finally {
      setLoading(false);
      isSearchingRef.current = false;
    }
  }, [
    query,
    filters,
    searchDenseWeight,
    rerankEnabled,
    recencyBoostEnabled,
    recencyWeight,
    recencyScaleDays,
    sectionTypes,
    dataSource,
    keywordBoostShortQueries,
    semanticHighlighting,
    handleRequestHighlight,
    handleAiSummaryForResults,
    handlePostSearchResults,
    handleSearchError,
    minChunkSize,
    rerankModel,
    searchModel,
    loadFacets,
  ]);

  // Track if we've done initial search to avoid double-searching on load
  const hasSearchedRef = React.useRef(false);

  // REMOVED: Auto-search on filter changes - user must explicitly click Search or press Enter
  // Search only triggers via:
  // 1. Form submit (handleSearch)
  // 2. Initial page load with URL query params (below)

  // Trigger initial search only when a URL query was present on initial load.
  useEffect(() => {
    const modelsReady = !modelCombosLoading && (
      !availableModelCombos.length
      || (searchModel && summaryModelConfig && semanticHighlightModelConfig)
    );
    if (!initialSearchDone && initialQueryFromUrlRef.current && query.trim() && modelsReady) {
      setInitialSearchDone(true);
      hasSearchedRef.current = true;
      performSearch();
    }
  }, [
    availableModelCombos.length,
    initialSearchDone,
    modelCombosLoading,
    performSearch,
    query,
    searchModel,
  ]);

  // Handler for toggling auto min score mode
  const handleAutoMinScoreToggle = useCallback((enabled: boolean) => {
    setAutoMinScore(enabled);
    if (enabled) {
      // Reset to 0 when enabling auto mode - will be calculated after search
      setMinScore(0);
    }
  }, []);

  // Handler for manual min score changes - disables auto mode
  const handleMinScoreChange = useCallback((value: number) => {
    setMinScore(value);
    // Disable auto mode when user manually adjusts the slider
    if (autoMinScore) {
      setAutoMinScore(false);
    }
  }, [autoMinScore]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    // When form is submitted (Enter key), search immediately
    hasSearchedRef.current = true;
    performSearch();
    // Update URL with pushState for browser history
    if (query.trim()) {
      const searchParams = buildSearchURL(
        query,
        filters,
        searchDenseWeight,
        rerankEnabled,
        recencyBoostEnabled,
        recencyWeight,
        recencyScaleDays,
        sectionTypes,
        keywordBoostShortQueries,
        minChunkSize,
        semanticHighlighting,
        autoMinScore,
        searchModel,
        selectedModelCombo,
        selectedDomain
      );
      const newURL = withBasePath(searchParams ? `/?${searchParams}` : '/');
      window.history.pushState(null, '', newURL);
    }
  };

  const handleClearFilters = () => {
    setFilters({});
    // Clear all selected filters dynamically
    setSelectedFilters(buildEmptySelectedFilters());
    setMinScore(0.0);
    // Update URL to remove filter params (keep search mode settings)
    if (query.trim()) {
      const searchParams = buildSearchURL(
        query,
        {},
        searchDenseWeight,
        rerankEnabled,
        recencyBoostEnabled,
        recencyWeight,
        recencyScaleDays,
        sectionTypes,
        keywordBoostShortQueries,
        minChunkSize,
        semanticHighlighting,
        autoMinScore,
        searchModel,
        selectedModelCombo,
        selectedDomain
      );
      const newURL = withBasePath(searchParams ? `/?${searchParams}` : '/');
      window.history.replaceState(null, '', newURL);
    }
  };

  const handleClearHeatmapFilters = () => {
    setHeatmapFilters({});
    setHeatmapSelectedFilters(buildEmptySelectedFilters());
  };

  const handleResultClick = (result: SearchResult) => {
    setSelectedDoc(result);
  };

  const handleClosePreview = () => {
    setSelectedDoc(null);
  };

  const toggleCardExpansion = (chunkId: string, e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent card click from firing
    setExpandedCards(prev => {
      const newSet = new Set(prev);
      if (newSet.has(chunkId)) {
        newSet.delete(chunkId);
      } else {
        newSet.add(chunkId);
      }
      return newSet;
    });
  };

  const buildSearchMetadataDoc = useCallback((result: SearchResult) => {
    const metadata = result.metadata || {};
    return {
      doc_id: metadata.doc_id ?? result.doc_id,
      ...metadata,
      organization: metadata.organization ?? result.organization,
      published_year: metadata.published_year ?? result.year,
      title: metadata.title ?? result.title,
    };
  }, []);

  const handleOpenMetadata = useCallback((metadataDoc: Record<string, any>) => {
    setMetadataModalDoc(metadataDoc);
    setMetadataModalOpen(true);
  }, []);

  const handleOpenSearchMetadata = useCallback(
    (result: SearchResult) => {
      handleOpenMetadata(buildSearchMetadataDoc(result));
    },
    [buildSearchMetadataDoc, handleOpenMetadata]
  );

  const handleCloseMetadataModal = () => {
    setMetadataModalOpen(false);
  };

  const handleResultLanguageChange = async (result: SearchResult, newLang: string) => {
    const originalLanguage = result.language || result.metadata?.language || 'en';
    if (newLang === originalLanguage) {
      resetTranslationState(setResults, result.chunk_id);
      return;
    }

    if (result.translated_language === newLang) {
      return;
    }

    setTranslationInProgress(setResults, result.chunk_id, newLang);

    try {
      const textToTranslate = buildChunkTextForTranslation(result);
      const [translatedTitle, translatedText, translatedQuery, translatedHeadings] =
        await Promise.all([
          translateViaApi(result.title, newLang),
          translateViaApi(textToTranslate, newLang),
          query.trim() ? translateViaApi(query, newLang) : Promise.resolve(null),
          translateHeadings(result.headings ?? [], newLang)
        ]);

      const translatedSemanticMatches = await computeTranslatedSemanticMatches({
        translatedText,
        translatedQuery,
        originalText: result.text,
        originalQuery: query,
        semanticHighlightModelConfig,
      });

      applyTranslationResult(
        setResults,
        result,
        newLang,
        translatedTitle,
        translatedText,
        translatedHeadings,
        translatedSemanticMatches
      );
    } catch (error) {
      console.error("Translation error", error);
      applyTranslationError(setResults, result.chunk_id);
    }
  };

  // Fetch TOC data for a document
  const fetchTocData = async (docId: string) => {
    setLoadingToc(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/document/${docId}?data_source=${dataSource}`);
      const doc = response.data as {
        toc_classified?: string;
        toc?: string;
        page_count?: number;
        sys_page_count?: number;
      };
      // Use toc_classified if available, otherwise fall back to toc
      const toc = doc.toc_classified || doc.toc || '';
      setSelectedToc(toc);
      setSelectedTocPageCount(doc.page_count ?? doc.sys_page_count ?? null);
    } catch (error) {
      console.error('Error fetching TOC:', error);
      setSelectedToc('');
    } finally {
      setLoadingToc(false);
    }
  };

  const handleOpenToc = useCallback(
    (docId: string, toc: string, pdfUrl?: string, pageCount?: number | null) => {
      setSelectedTocDocId(docId);
      setSelectedToc(toc);
      setSelectedTocPdfUrl(pdfUrl || '');
      setSelectedTocPageCount(pageCount ?? null);
      if (!pdfUrl) {
        fetchTocPdfUrl(docId);
      }
      setTocModalOpen(true);
    },
    [fetchTocPdfUrl]
  );

  const handleTocUpdated = (newToc: string) => {
    setSelectedToc(newToc);
  };

  // renderMetadata removed - now in SearchResultCard component


  // Track whether user has performed a search (to keep layout in results mode permanently)
  // Once the user has searched, the layout stays in results mode even when clearing the search box
  const hasSearched = results.length > 0 || initialSearchDone || hasSearchedRef.current;

  const dataSourceLoading = Boolean(
    loadingConfig && initialSearchState.dataset && !datasourcesConfig[selectedDomain]
  );

  const dataSourceLoadingContent = (
    <div className="main-content">
      <div style={{ padding: '2rem', textAlign: 'center' }}></div>
    </div>
  );

  const pipelineLoadingContent = (
    <div className="main-content">
      <div style={{ padding: '2rem', textAlign: 'center' }}>Loading processing stats ...</div>
    </div>
  );

  const documentsTab = dataSourceLoading ? (
    dataSourceLoadingContent
  ) : (
    <Documents
      key={`documents-${dataSource}`}
      dataSource={dataSource}
      semanticHighlightModelConfig={semanticHighlightModelConfig}
      dataSourceConfig={currentDataSourceConfig}
    />
  );

  const pipelineTab = dataSourceLoading ? (
    pipelineLoadingContent
  ) : (
    <Pipeline key={`pipeline-${dataSource}`} dataSource={dataSource} />
  );

  const processingTab = dataSourceLoading ? (
    pipelineLoadingContent
  ) : (
    <Processing key={`processing-${dataSource}`} dataSource={dataSource} />
  );

  const handleNavigateToDocuments = (filter: { category: string; value: string }) => {
    // Switch to documents tab
    handleTabChange('documents');

    // Update URL with filter
    const url = new URL(window.location.href);
    url.searchParams.set('tab', 'documents');
    url.searchParams.set(filter.category, filter.value);

    // We change the history. State update in Documents component (via useDocumentsState)
    // will pick this up if it initializes from URL or listens to changes.
    // Since we are unmounting Stats and mounting Documents, Documents will read initialization from URL.
    // However, if we are already "alive" (unlikely given conditional rendering in TabContent), we might need to force update.
    // Pushing state:
    window.history.pushState({}, '', url.toString());

    // Note: useDocumentsState uses useSyncDocumentsUrlParams which updates URL on state change.
    // It also initializes from URL on mount.
    // So ensuring URL is correct before Documents mounts is key.
  };

  const statsTab = dataSourceLoading ? (
    dataSourceLoadingContent
  ) : (
    <Stats
      key={`stats-${dataSource}`}
      dataSource={dataSource}
      onNavigateToDocuments={handleNavigateToDocuments}
    />
  );

  const activeFiltersCount = Object.keys(filters).length;
  const heatmapActiveFiltersCount = Object.keys(heatmapFilters).length;

  const displayFacets =
    allFacetsDataSource === dataSource && allFacets ? allFacets : facets;

  const requestHighlightHandler = resolveRequestHighlightHandler(
    SEARCH_SEMANTIC_HIGHLIGHTS,
    semanticHighlighting,
    handleRequestHighlight
  );

  const searchTab = (
    <SearchTabContent
      filtersExpanded={filtersExpanded}
      activeFiltersCount={activeFiltersCount}
      onToggleFiltersExpanded={toggleFiltersExpanded}
      onClearFilters={handleClearFilters}
      facets={displayFacets}
      selectedFilters={selectedFilters}
      collapsedFilters={collapsedFilters}
      expandedFilterLists={expandedFilterLists}
      filterSearchTerms={filterSearchTerms}
      titleSearchResults={titleSearchResults}
      facetSearchResults={facetSearchResults}
      onRemoveFilter={handleRemoveFilter}
      onToggleFilter={toggleFilter}
      onFilterSearchTermChange={handleFilterSearchTermChange}
      onToggleFilterListExpansion={toggleFilterListExpansion}
      onFilterValuesChange={handleFilterValuesChange}
      searchDenseWeight={searchDenseWeight}
      onSearchDenseWeightChange={setSearchDenseWeight}
      keywordBoostShortQueries={keywordBoostShortQueries}
      onKeywordBoostChange={setKeywordBoostShortQueries}
      semanticHighlighting={semanticHighlighting}
      onSemanticHighlightingChange={setSemanticHighlighting}
      minScore={minScore}
      maxScore={maxScore}
      onMinScoreChange={handleMinScoreChange}
      autoMinScore={autoMinScore}
      onAutoMinScoreToggle={handleAutoMinScoreToggle}
      rerankEnabled={rerankEnabled}
      onRerankToggle={setRerankEnabled}
      recencyBoostEnabled={recencyBoostEnabled}
      onRecencyBoostToggle={setRecencyBoostEnabled}
      recencyWeight={recencyWeight}
      onRecencyWeightChange={setRecencyWeight}
      recencyScaleDays={recencyScaleDays}
      onRecencyScaleDaysChange={setRecencyScaleDays}
      minChunkSize={minChunkSize}
      onMinChunkSizeChange={setMinChunkSize}
      sectionTypes={sectionTypes}
      onSectionTypesChange={setSectionTypes}
      aiSummaryEnabled={AI_SUMMARY_ON}
      aiSummaryCollapsed={aiSummaryCollapsed}
      aiSummaryExpanded={aiSummaryExpanded}
      aiSummaryLoading={aiSummaryLoading}
      aiSummary={aiSummary}
      aiPrompt={aiPrompt}
      showPromptModal={showPromptModal}
      results={results}
      loading={loading}
      query={query}
      selectedDoc={selectedDoc}
      onResultClick={handleResultClick}
      onOpenPrompt={() => setShowPromptModal(true)}
      onClosePrompt={() => setShowPromptModal(false)}
      onToggleCollapsed={() => setAiSummaryCollapsed(!aiSummaryCollapsed)}
      onToggleExpanded={() => setAiSummaryExpanded(!aiSummaryExpanded)}
      onOpenMetadata={handleOpenSearchMetadata}
      onLanguageChange={handleResultLanguageChange}
      onRequestHighlight={requestHighlightHandler}
    />
  );

  const heatmapTab = (
    <HeatmapTabContent
      selectedDomain={selectedDomain}
      loadingConfig={loadingConfig}
      facetsDataSource={facetsDataSource}
      filtersExpanded={filtersExpanded}
      activeFiltersCount={heatmapActiveFiltersCount}
      onToggleFiltersExpanded={toggleFiltersExpanded}
      onClearFilters={handleClearHeatmapFilters}
      facets={facets}
      filters={heatmapFilters}
      selectedFilters={heatmapSelectedFilters}
      collapsedFilters={heatmapCollapsedFilters}
      expandedFilterLists={heatmapExpandedFilterLists}
      filterSearchTerms={filterSearchTerms}
      titleSearchResults={titleSearchResults}
      facetSearchResults={facetSearchResults}
      onRemoveFilter={handleHeatmapRemoveFilter}
      onToggleFilter={toggleHeatmapFilter}
      onFilterSearchTermChange={handleFilterSearchTermChange}
      onToggleFilterListExpansion={toggleHeatmapFilterListExpansion}
      onFilterValuesChange={handleHeatmapFilterValuesChange}
      searchModel={searchModel}
      searchDenseWeight={searchDenseWeight}
      onSearchDenseWeightChange={setSearchDenseWeight}
      keywordBoostShortQueries={keywordBoostShortQueries}
      onKeywordBoostChange={setKeywordBoostShortQueries}
      semanticHighlighting={semanticHighlighting}
      onSemanticHighlightingChange={setSemanticHighlighting}
      minScore={minScore}
      maxScore={maxScore}
      onMinScoreChange={handleMinScoreChange}
      autoMinScore={autoMinScore}
      onAutoMinScoreToggle={handleAutoMinScoreToggle}
      rerankEnabled={rerankEnabled}
      onRerankToggle={setRerankEnabled}
      recencyBoostEnabled={recencyBoostEnabled}
      onRecencyBoostToggle={setRecencyBoostEnabled}
      recencyWeight={recencyWeight}
      onRecencyWeightChange={setRecencyWeight}
      recencyScaleDays={recencyScaleDays}
      onRecencyScaleDaysChange={setRecencyScaleDays}
      minChunkSize={minChunkSize}
      onMinChunkSizeChange={setMinChunkSize}
      sectionTypes={sectionTypes}
      onSectionTypesChange={setSectionTypes}
      rerankModel={rerankModel}
      semanticHighlightModelConfig={semanticHighlightModelConfig}
      dataSource={dataSource}
      selectedDoc={selectedDoc}
      onResultClick={handleResultClick}
      onOpenMetadata={handleOpenSearchMetadata}
      onLanguageChange={handleResultLanguageChange}
      onRequestHighlight={requestHighlightHandler}
    />
  );

  return (
    <div className="app">
      <TopBar
        selectedDomain={selectedDomain}
        availableDomains={availableDomains}
        datasetTotals={datasetTotals}
        selectedModelCombo={resolvedModelCombo}
        availableModelCombos={availableModelCombos}
        modelCombos={modelCombos}
        domainDropdownOpen={domainDropdownOpen}
        modelDropdownOpen={modelDropdownOpen}
        helpDropdownOpen={helpDropdownOpen}
        showDomainTooltip={showDomainTooltip}
        onToggleDomainDropdown={handleToggleDomainDropdown}
        onToggleModelDropdown={handleToggleModelDropdown}
        onDomainMouseEnter={handleDomainMouseEnter}
        onDomainMouseLeave={handleDomainMouseLeave}
        onDomainBlur={handleDomainBlur}
        onModelBlur={handleModelBlur}
        onSelectDomain={handleSelectDomain}
        onSelectModelCombo={handleSelectModelCombo}
        onToggleHelpDropdown={handleToggleHelpDropdown}
        onHelpBlur={handleHelpBlur}
        onAboutClick={handleAboutClick}
        onTechClick={handleTechClick}
        onDataClick={handleDataClick}
        navTabs={<NavTabs activeTab={activeTab} onTabChange={handleTabChange} />}
      />

      <SearchBox
        isActive={activeTab === 'search'}
        hasSearched={hasSearched}
        query={query}
        loading={loading}
        searchError={searchError}
        onQueryChange={setQuery}
        onSubmit={handleSearch}
      />

      <TabContent
        activeTab={activeTab}
        hasSearched={hasSearched}
        searchTab={searchTab}
        heatmapTab={heatmapTab}
        documentsTab={documentsTab}
        statsTab={statsTab}
        pipelineTab={pipelineTab}
        processingTab={processingTab}
        aboutContent={aboutContent}
        techContent={techContent}
        dataContent={dataContent}
        privacyContent={privacyContent}
      />

      <footer className="app-footer">
        <button
          type="button"
          className="app-footer-link"
          onClick={handleAboutClick}
        >
          About
        </button>
        <span className="app-footer-divider">•</span>
        <button
          type="button"
          className="app-footer-link"
          onClick={handleDataClick}
        >
          Data & Attribution
        </button>
        <span className="app-footer-divider">•</span>
        <button
          type="button"
          className="app-footer-link"
          onClick={handlePrivacyClick}
        >
          Privacy
        </button>
        <span className="app-footer-divider">•</span>
        <a href="https://github.com/dividor/evidencelab-ai" target="_blank" rel="noreferrer">
          GitHub
        </a>
        <span className="app-footer-divider">•</span>
        <a href="mailto:evidence-lab@astrobagel.com">Contact</a>
      </footer>

      <PdfPreviewOverlay
        selectedDoc={selectedDoc}
        query={query}
        dataSource={dataSource}
        semanticHighlightModelConfig={semanticHighlightModelConfig}
        onClose={handleClosePreview}
        onOpenMetadata={handleOpenMetadata}
        searchDenseWeight={searchDenseWeight}
        rerankEnabled={rerankEnabled}
        recencyBoostEnabled={recencyBoostEnabled}
        recencyWeight={recencyWeight}
        recencyScaleDays={recencyScaleDays}
        sectionTypes={sectionTypes}
        keywordBoostShortQueries={keywordBoostShortQueries}
        minChunkSize={minChunkSize}
        minScore={minScore}
        rerankModel={rerankModel}
        searchModel={searchModel}
      />

      {/* TOC Modal for Search Results */}
      {/* TOC Modal */}
      <TocModal
        isOpen={tocModalOpen}
        onClose={() => setTocModalOpen(false)}
        toc={selectedToc}
        docId={selectedTocDocId}
        dataSource={dataSource}
        loading={loadingToc}
        pdfUrl={selectedTocPdfUrl}
        onTocUpdated={handleTocUpdated}
        pageCount={selectedTocPageCount}
      />

      <MetadataModal
        isOpen={metadataModalOpen}
        onClose={handleCloseMetadataModal}
        metadataDoc={metadataModalDoc}
      />
    </div >
  );
}

export default App;
