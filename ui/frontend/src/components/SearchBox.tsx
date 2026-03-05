import React from 'react';

interface SearchBoxProps {
  isActive: boolean;
  hasSearched: boolean;
  query: string;
  loading: boolean;
  searchError: string | null;
  onQueryChange: (value: string) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  onShowFilters?: () => void;
  datasetName?: string;
  documentCount?: number;
  exampleQueries?: string[];
  onExampleQueryClick?: (query: string) => void;
  filterLabels?: Record<string, string>;
}

export const SearchBox = ({
  isActive,
  hasSearched,
  query,
  loading,
  searchError,
  onQueryChange,
  onSubmit,
  onShowFilters,
  datasetName,
  documentCount,
  exampleQueries,
  onExampleQueryClick,
  filterLabels,
}: SearchBoxProps) => {
  if (!isActive) {
    return null;
  }

  const isLanding = !hasSearched;

  return (
    <div
      className={`search-container ${
        isLanding ? 'search-container-landing' : 'search-container-results'
      }`}
    >
      {isLanding ? (
        <div className="search-landing-content">
          {datasetName && (
            <p className="search-tagline">
              Search {documentCount?.toLocaleString()} {datasetName}
            </p>
          )}
          <form onSubmit={onSubmit} className="search-form">
            <div className="search-input-wrapper">
              <input
                type="text"
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="Search documents"
                className="search-input"
              />
              {!query && (
                <span className="search-enter-hint">
                  Press Enter <kbd>↵</kbd>
                </span>
              )}
            </div>
            <button type="submit" disabled={loading} className="search-button">
              {loading ? (
                <>
                  {Array.from('Searching...').map((char, index) => (
                    <span
                      key={index}
                      className="wave-char"
                      style={{ animationDelay: `${index * 0.1}s` }}
                    >
                      {char}
                    </span>
                  ))}
                </>
              ) : (
                'Search'
              )}
            </button>
          </form>
          {exampleQueries && exampleQueries.length > 0 && (
            <div className="search-examples">
              <span className="search-examples-label">Try:</span>
              {exampleQueries.map((q) => (
                <button
                  key={q}
                  type="button"
                  className="search-example-chip"
                  onClick={() => onExampleQueryClick?.(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          )}
          {onShowFilters && filterLabels && (
            <div className="search-landing-filters">
              <span className="search-landing-filters-label">Filter by:</span>
              {['published_year', 'country', 'organization']
                .filter((k) => filterLabels[k])
                .map((key) => (
                  <button
                    key={key}
                    type="button"
                    className="search-filter-chip"
                    onClick={onShowFilters}
                  >
                    {filterLabels[key]}
                  </button>
                ))}
            </div>
          )}
        </div>
      ) : (
        <form onSubmit={onSubmit} className="search-form">
          <input
            type="text"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search documents"
            className="search-input"
          />
          <button type="submit" disabled={loading} className="search-button">
            {loading ? (
              <>
                {Array.from('Searching...').map((char, index) => (
                  <span
                    key={index}
                    className="wave-char"
                    style={{ animationDelay: `${index * 0.1}s` }}
                  >
                    {char}
                  </span>
                ))}
              </>
            ) : (
              'Search'
            )}
          </button>
        </form>
      )}
      {searchError && <div className="search-error">⚠️ {searchError}</div>}
    </div>
  );
};
