import React, { memo, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { SearchResult } from '../types/api';
import { LANGUAGES } from '../constants';
import { RainbowText } from './RainbowText';
import { SearchResultElements } from './SearchResultElements';
import { buildOrderedElements, shouldShowSnippetText } from './searchResultCardUtils';
import {
    highlightTextWithAPI,
    renderHighlightedText,
    renderMarkdownText,
    formatLinesWithIndentation
} from '../utils/textHighlighting';

interface SearchResultCardProps {
    result: SearchResult;
    query: string;
    isSelected: boolean;
    onClick: (result: SearchResult) => void;
    onOpenMetadata: (result: SearchResult) => void;
    onLanguageChange: (result: SearchResult, newLang: string) => void;
    onRequestHighlight?: (chunkId: string, text: string) => void;
    hidePageNumber?: boolean;
}

const ResultTitleRow = ({
    result,
    onClick,
    hidePageNumber
}: {
    result: SearchResult;
    onClick: (result: SearchResult) => void;
    hidePageNumber?: boolean;
}) => (
    <div className="result-title-row">
        <h3
            className="result-title result-title-link"
            onClick={() => onClick(result)}
            role="button"
            tabIndex={0}
            onKeyPress={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    onClick(result);
                }
            }}
        >
            {result.translated_title || result.title}
        </h3>
        {!hidePageNumber && result.page_num && <span className="result-page-badge">Page {result.page_num}</span>}
    </div>
);

const ResultSubtitleRow = ({ result }: { result: SearchResult }) => (
    <div
        className="result-subtitle"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
    >
        <div>
            {(result.organization || result.year) && (
                <>
                    {result.organization && <span>{result.organization}</span>}
                    {result.organization && result.year && <span> • </span>}
                    {result.year && <span>{result.year}</span>}
                </>
            )}
        </div>
    </div>
);

const ResultHeadings = ({ result }: { result: SearchResult }) => {
    if (!result.headings || result.headings.length === 0) {
        return null;
    }

    return (
        <div className="result-headings">
            {result.translated_headings_display || result.headings.join(' > ')}
        </div>
    );
};

const TranslatedSnippet = ({
    result,
    query
}: {
    result: SearchResult;
    query: string;
}) => {
    if (!result.translated_snippet) {
        return null;
    }

    const translatedResult = {
        ...result,
        semanticMatches: result.translatedSemanticMatches
    };
    const highlightedParts = renderHighlightedText(
        result.translated_snippet,
        query,
        translatedResult
    );

    return (
        <div className="result-snippet user-content">
            {formatLinesWithIndentation(highlightedParts, { lastType: 'none', level: 0 })}
        </div>
    );
};

const ResultBadges = ({
    result,
    onOpenMetadata,
    onLanguageChange
}: {
    result: SearchResult;
    onOpenMetadata: (result: SearchResult) => void;
    onLanguageChange: (result: SearchResult, newLang: string) => void;
}) => (
    <div className="result-badges">
        <button
            className="metadata-link"
            onClick={(e: React.MouseEvent) => {
                e.stopPropagation();
                onOpenMetadata(result);
            }}
        >
            Metadata
        </button>
        <div
            className="result-language-selector"
            onClick={(e) => e.stopPropagation()}
            style={{ position: 'relative', display: 'inline-block', marginLeft: 'auto' }}
        >
            {result.is_translating && (
                <div
                    className="rainbow-overlay translating-dropdown"
                    style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: 'white',
                        pointerEvents: 'none',
                        fontSize: '0.8rem',
                        borderRadius: '4px',
                        zIndex: 1
                    }}
                >
                    <RainbowText text={LANGUAGES[result.translated_language || 'en'] || '...'} />
                </div>
            )}
            <select
                value={result.translated_language || result.language || result.metadata?.language || 'en'}
                onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                    onLanguageChange(result, e.target.value)
                }
                style={{
                    fontSize: '0.8rem',
                    padding: '2px 4px',
                    border: 'none',
                    borderRadius: '4px',
                    backgroundColor: 'transparent',
                    color: '#6b7280',
                    cursor: 'pointer',
                    visibility: result.is_translating ? 'hidden' : 'visible'
                }}
            >
                {Object.entries(LANGUAGES).map(([code, name]) => (
                    <option key={code} value={code}>
                        {name}
                    </option>
                ))}
            </select>
        </div>
    </div>
);

const SearchResultCard = memo(({
    result,
    query,
    isSelected,
    onClick,
    onOpenMetadata,
    onLanguageChange,
    onRequestHighlight,
    hidePageNumber
}: SearchResultCardProps) => {
    const cardRef = useRef<HTMLDivElement>(null);

    // IntersectionObserver to trigger highlighting when scrolled into view
    useEffect(() => {
        // If it's already highlighted or no highlighter offered, skip
        if (result.highlightedText || !onRequestHighlight) return;

        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0].isIntersecting) {
                    onRequestHighlight(result.chunk_id, result.text);
                    observer.disconnect();
                }
            },
            { threshold: 0.1 } // Trigger when 10% visible
        );

        if (cardRef.current) {
            observer.observe(cardRef.current);
        }

        return () => {
            observer.disconnect();
        };
    }, [result.chunk_id, result.highlightedText, onRequestHighlight]);

    // Convert single newlines to double newlines for proper paragraph breaks in markdown
    const snippetText = result.text.replace(/\n/g, '\n\n');

    const showText = shouldShowSnippetText(result, snippetText);
    const orderedElements = buildOrderedElements(result);

    return (
        <div
            ref={cardRef}
            className={`result-card ${isSelected ? 'result-card-selected' : ''}`}
            data-doc-id={result.doc_id}
            data-page={result.page_num}
        >
            <ResultTitleRow result={result} onClick={onClick} hidePageNumber={hidePageNumber} />
            <ResultSubtitleRow result={result} />

            <div className="result-snippet-container">
                <ResultHeadings result={result} />
                <TranslatedSnippet result={result} query={query} />
                <SearchResultElements
                    result={result}
                    orderedElements={orderedElements}
                    query={query}
                    onResultClick={onClick}
                />
            </div>

            <ResultBadges
                result={result}
                onOpenMetadata={onOpenMetadata}
                onLanguageChange={onLanguageChange}
            />

        </div>
    );
});

SearchResultCard.displayName = 'SearchResultCard';

export default SearchResultCard;
