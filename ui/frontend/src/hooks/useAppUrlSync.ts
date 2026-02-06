import { useEffect } from 'react';
import { DEFAULT_SECTION_TYPES, getSearchStateFromURL } from '../utils/searchUrl';

interface UseAppUrlSyncArgs {
  availableDomains: string[];
  loadingConfig: boolean;
  selectedDomain: string;
  setSelectedDomain: (value: string) => void;
  setActiveTab: (value: any) => void;
  setQuery: (value: string) => void;
  setFilters: (value: any) => void;
  setSelectedFilters: (value: Record<string, string[]>) => void;
  setSearchDenseWeight: (value: number) => void;
  setRerankEnabled: (value: boolean) => void;
  setSectionTypes: (value: string[]) => void;
  setMinChunkSize: (value: number) => void;
  setSemanticHighlighting: (value: boolean) => void;
  setSearchModel: (value: string | null) => void;
  coreFilterFields: string[];
  getTabFromPath: () => any;
}

export const useAppUrlSync = ({
  availableDomains,
  loadingConfig,
  selectedDomain,
  setSelectedDomain,
  setActiveTab,
  setQuery,
  setFilters,
  setSelectedFilters,
  setSearchDenseWeight,
  setRerankEnabled,
  setSectionTypes,
  setMinChunkSize,
  setSemanticHighlighting,
  setSearchModel,
  coreFilterFields,
  getTabFromPath,
}: UseAppUrlSyncArgs) => {
  useEffect(() => {
    const handlePopState = () => {
      setActiveTab(getTabFromPath());
      const searchState = getSearchStateFromURL(coreFilterFields, DEFAULT_SECTION_TYPES);
      setQuery(searchState.query);
      setFilters(searchState.filters);
      setSelectedFilters(searchState.selectedFilters);
      setSearchDenseWeight(searchState.denseWeight);
      setRerankEnabled(searchState.rerank);
      setSectionTypes(searchState.sectionTypes);
      setMinChunkSize(searchState.minChunkSize);
      setSemanticHighlighting(searchState.semanticHighlighting);
      setSearchModel(searchState.model);
      if (searchState.dataset && availableDomains.includes(searchState.dataset)) {
        setSelectedDomain(searchState.dataset);
      }
    };

    const checkURLForDataset = () => {
      const searchState = getSearchStateFromURL(coreFilterFields, DEFAULT_SECTION_TYPES);
      if (searchState.dataset && availableDomains.includes(searchState.dataset) && selectedDomain !== searchState.dataset) {
        setSelectedDomain(searchState.dataset);
      }
    };

    window.addEventListener('popstate', handlePopState);
    if (!loadingConfig && availableDomains.length > 0) {
      checkURLForDataset();
    }

    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, [
    availableDomains,
    loadingConfig,
    selectedDomain,
    setActiveTab,
    setFilters,
    setMinChunkSize,
    setQuery,
    setRerankEnabled,
    setSearchDenseWeight,
    setSearchModel,
    setSectionTypes,
    setSelectedDomain,
    setSelectedFilters,
    setSemanticHighlighting,
    coreFilterFields,
    getTabFromPath,
  ]);
};
