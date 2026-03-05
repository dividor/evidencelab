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
}: SearchBoxProps) => {
  if (!isActive) {
    return null;
  }

  const isLanding = !hasSearched;
  const placeholder = datasetName && documentCount
    ? `Search ${documentCount.toLocaleString()} ${datasetName}`
    : 'Search documents';

  return (
    <div
      className={`search-container ${
        isLanding ? 'search-container-landing' : 'search-container-results'
      }`}
    >
      {isLanding ? (
        <div className="search-landing-content">
          <form onSubmit={onSubmit} className="search-form">
            <div className="search-input-column">
              <div className="search-input-wrapper">
                <input
                  type="text"
                  value={query}
                  onChange={(event) => onQueryChange(event.target.value)}
                  placeholder={placeholder}
                  className="search-input"
                />
                {onShowFilters && (
                  <button type="button" className="search-input-filters" onClick={onShowFilters}>
                    <svg width="20" height="20" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M1 3h14M4 8h8M6 13h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                    </svg>
                    Filters
                  </button>
                )}
              </div>
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
        </div>
      ) : (
        <form onSubmit={onSubmit} className="search-form">
          <input
            type="text"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={placeholder}
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
