import React from 'react';

interface SearchBoxProps {
  isActive: boolean;
  hasSearched: boolean;
  query: string;
  loading: boolean;
  searchError: string | null;
  onQueryChange: (value: string) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}

export const SearchBox = ({
  isActive,
  hasSearched,
  query,
  loading,
  searchError,
  onQueryChange,
  onSubmit,
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
