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
}: SearchBoxProps) => {
  if (!isActive) {
    return null;
  }

  return (
    <div
      className={`search-container ${
        !hasSearched ? 'search-container-landing' : 'search-container-results'
      }`}
    >
      <form onSubmit={onSubmit} className="search-form">
        <input
          type="text"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search documents"
          className="search-input"
        />
        {!hasSearched && onShowFilters && (
          <button type="button" className="search-filters-btn" onClick={onShowFilters}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M1 3h14M4 8h8M6 13h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
            Filters
          </button>
        )}
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
      {searchError && <div className="search-error">⚠️ {searchError}</div>}
    </div>
  );
};
