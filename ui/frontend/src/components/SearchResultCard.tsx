import React, { memo, useRef, useEffect, useState, useCallback } from 'react';
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
import StarRating from './ratings/StarRating';
import RatingModal from './ratings/RatingModal';

interface SearchResultCardProps {
    result: SearchResult;
    query: string;
    isSelected: boolean;
    onClick: (result: SearchResult) => void;
    onOpenMetadata: (result: SearchResult) => void;
    onLanguageChange: (result: SearchResult, newLang: string) => void;
    onRequestHighlight?: (chunkId: string, text: string) => void;
    hidePageNumber?: boolean;
    /** UUID search ID for rating reference */
    searchId?: string;
    /** Whether user is authenticated (controls rating visibility) */
    isAuthenticated?: boolean;
    /** Callback to submit a rating */
    onSubmitRating?: (params: {
        ratingType: string;
        referenceId: string;
        itemId?: string;
        score: number;
        comment?: string;
        context?: Record<string, any>;
    }) => Promise<any>;
    /** Existing rating score for this item (0 = no rating) */
    existingRatingScore?: number;
    /** Existing rating comment */
    existingRatingComment?: string;
    /** Existing rating id (for deletion) */
    existingRatingId?: string;
    /** Delete a rating */
    onDeleteRating?: (ratingId: string) => Promise<void>;
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

const CountryDisplay = ({ raw }: { raw: string }) => {
    const [expanded, setExpanded] = useState(false);
    const countries = raw.includes('; ')
        ? raw.split('; ').map(s => s.trim()).filter(Boolean)
        : raw.includes(',')
          ? raw.split(',').map(s => s.trim()).filter(Boolean)
          : [raw];
    if (countries.length <= 3) return <span>{countries.join(', ')}</span>;
    const visible = expanded ? countries : countries.slice(0, 3);
    return (
        <span>
            {visible.join(', ')}
            {!expanded && (
                <button className="see-more-link" onClick={e => { e.stopPropagation(); setExpanded(true); }}>
                    +{countries.length - 3} more
                </button>
            )}
        </span>
    );
};

/** Renders organization, year, and country parts separated by bullets */
const MetadataSubtitle = ({ result }: { result: SearchResult }) => {
    const country = result.metadata?.map_country || result.metadata?.country || '';
    const parts: React.ReactNode[] = [];
    if (result.organization) parts.push(<span key="org">{result.organization}</span>);
    if (result.year) parts.push(<span key="year">{result.year}</span>);
    if (country) parts.push(<CountryDisplay key="country" raw={country} />);
    if (parts.length === 0) return null;
    return (
        <>
            {parts.map((part, i) => (
                <React.Fragment key={i}>
                    {i > 0 && <span> • </span>}
                    {part}
                </React.Fragment>
            ))}
        </>
    );
};

const ResultSubtitleRow = ({
    result,
    onLanguageChange
}: {
    result: SearchResult;
    onLanguageChange: (result: SearchResult, newLang: string) => void;
}) => {
    return (
        <div
            className="result-subtitle"
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        >
            <div>
                <MetadataSubtitle result={result} />
            </div>
            <div
                className="result-language-selector"
                onClick={(e) => e.stopPropagation()}
                style={{ position: 'relative', display: 'inline-block', flexShrink: 0 }}
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
};

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
}: {
    result: SearchResult;
    onOpenMetadata: (result: SearchResult) => void;
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
    hidePageNumber,
    searchId,
    isAuthenticated,
    onSubmitRating,
    existingRatingScore = 0,
    existingRatingComment = '',
    existingRatingId,
    onDeleteRating,
}: SearchResultCardProps) => {
    const cardRef = useRef<HTMLDivElement>(null);
    const [ratingModalOpen, setRatingModalOpen] = useState(false);
    const [modalInitialScore, setModalInitialScore] = useState(0);

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

    const handleRatingSubmit = useCallback((score: number, comment: string) => {
        if (!onSubmitRating || !searchId) return;
        onSubmitRating({
            ratingType: 'search_result',
            referenceId: searchId,
            itemId: result.chunk_id,
            score,
            comment,
            context: {
                query,
                doc_id: result.doc_id,
                title: result.title,
                chunk_id: result.chunk_id,
                page_num: result.page_num || null,
                relevance_score: result.score,
                chunk_text: result.text || '',
                link: window.location.href,
            },
        });
    }, [onSubmitRating, searchId, result.chunk_id, result.doc_id, result.title, result.score, result.page_num, result.text, query]);

    const handleDeleteRating = useCallback(() => {
        if (existingRatingId && onDeleteRating) {
            onDeleteRating(existingRatingId);
        }
    }, [existingRatingId, onDeleteRating]);

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
            <ResultSubtitleRow result={result} onLanguageChange={onLanguageChange} />

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

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 'var(--spacing-sm)' }}>
                <ResultBadges
                    result={result}
                    onOpenMetadata={onOpenMetadata}
                />
                {isAuthenticated && searchId && (
                    <StarRating
                        score={existingRatingScore}
                        onRequestModal={(selectedScore) => {
                            setModalInitialScore(existingRatingScore || selectedScore);
                            setRatingModalOpen(true);
                        }}
                        size={14}
                        className="result-card-star-rating"
                    />
                )}
            </div>

            {ratingModalOpen && (
                <RatingModal
                    isOpen={ratingModalOpen}
                    onClose={() => setRatingModalOpen(false)}
                    title="Rate this search result"
                    initialScore={modalInitialScore}
                    initialComment={existingRatingComment}
                    onSubmit={handleRatingSubmit}
                    onDelete={existingRatingId ? handleDeleteRating : undefined}
                />
            )}
        </div>
    );
});

SearchResultCard.displayName = 'SearchResultCard';

export default SearchResultCard;
