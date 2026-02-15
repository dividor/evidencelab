import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import API_BASE_URL from '../config';
import { ChunkElement, SearchResult } from '../types/api';
import {
  parseAndRenderSuperscripts,
  renderTextWithInlineReferences,
  renderHighlightedText,
  formatLinesWithIndentation,
  parseSuperscripts
} from '../utils/textHighlighting';

type FootnoteGroup = { items: ChunkElement[] };

interface SearchResultElementsProps {
  result: SearchResult;
  orderedElements: Array<ChunkElement & { key: string }>;
  query: string;
  onResultClick: (result: SearchResult) => void;
}

const isReferenceElement = (element: ChunkElement) => {
  const textContent = element.text;
  const isPotentialRef =
    element.element_type !== 'image' && element.element_type !== 'table';
  return (
    isPotentialRef &&
    (element.is_reference || (textContent ? /^\^\d+/.test(textContent) : false))
  );
};

const groupFootnotes = (elements: ChunkElement[]) => {
  const contentItems: ChunkElement[] = [];
  const footnoteGroups: FootnoteGroup[] = [];
  let refBuffer: ChunkElement[] = [];

  elements.forEach((element) => {
    if (isReferenceElement(element)) {
      refBuffer.push(element);
      return;
    }

    if (refBuffer.length > 0) {
      footnoteGroups.push({ items: [...refBuffer] });
      refBuffer = [];
    }
    contentItems.push(element);
  });

  if (refBuffer.length > 0) {
    footnoteGroups.push({ items: [...refBuffer] });
  }

  return { contentItems, footnoteGroups };
};

const renderCaption = (textContent: string, indentContext: any) => (
  <div
    className="result-snippet result-snippet-caption"
    style={{ marginBottom: '0.5em', fontStyle: 'italic' }}
  >
    {parseAndRenderSuperscripts(textContent, indentContext)}
  </div>
);

const renderInlineRefs = (
  textContent: string,
  query: string,
  inlineRefs: any[],
  result: SearchResult,
  indentContext: any
) => (
  <div className="result-snippet" style={{ marginBottom: '0.5em' }}>
    {renderTextWithInlineReferences(
      textContent,
      query,
      inlineRefs,
      result.semanticMatches,
      indentContext
    )}
  </div>
);

const renderHighlightedTextBlock = (
  textContent: string,
  query: string,
  result: SearchResult,
  indentContext: any
) => {
  const highlightedParts = renderHighlightedText(textContent, query, result);
  const processedParts = highlightedParts
    .map((part) => {
      if (typeof part === 'string') {
        return parseSuperscripts(part);
      }
      if (React.isValidElement(part) && part.type === 'mark') {
        const partElement = part as React.ReactElement<{ children?: string }>;
        return React.cloneElement(
          partElement,
          {},
          parseSuperscripts((partElement.props.children || '') as string)
        );
      }
      return part;
    })
    .flat();

  return (
    <div className="result-snippet" style={{ marginBottom: '0.5em' }}>
      {formatLinesWithIndentation(processedParts, indentContext)}
    </div>
  );
};

const renderTextElement = (
  element: ChunkElement,
  result: SearchResult,
  query: string,
  indentContext: any
) => {
  const isCaption = element.label === 'caption';
  const textContent = element.text || '';
  const inlineRefs = element.inline_references;

  if (isCaption && textContent) {
    return renderCaption(textContent, indentContext);
  }

  if (inlineRefs && inlineRefs.length > 0) {
    return renderInlineRefs(textContent, query, inlineRefs, result, indentContext);
  }

  return renderHighlightedTextBlock(textContent, query, result, indentContext);
};

const renderImageElement = (
  element: ChunkElement,
  onResultClick: (result: SearchResult) => void,
  result: SearchResult
) => {
  const imagePath = element.path?.startsWith('/') ? element.path.slice(1) : element.path;
  return (
    <div className="result-figure-block">
      <div className="images-container">
        <img
          src={`${API_BASE_URL}/file/${imagePath}`}
          alt="Figure"
          className="table-image-thumbnail-clickable"
          onClick={() => onResultClick(result)}
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = 'none';
          }}
        />
      </div>
    </div>
  );
};

const renderTableElement = (
  element: ChunkElement,
  onResultClick: (result: SearchResult) => void,
  result: SearchResult
) => {
  const rawTablePath = element.image_path || element.path;
  const tablePath = rawTablePath?.startsWith('/') ? rawTablePath.slice(1) : rawTablePath;

  if (tablePath) {
    return (
      <div className="result-figure-block">
        <div className="images-container">
          <img
            src={`${API_BASE_URL}/file/${tablePath}`}
            alt="Table"
            className="table-image-thumbnail-clickable"
            onClick={() => onResultClick(result)}
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
        </div>
      </div>
    );
  }

  if (result.text) {
    return (
      <p className="result-snippet" style={{ marginBottom: '0.5em' }}>
        {result.text}
      </p>
    );
  }

  return null;
};

const renderFootnoteText = (element: ChunkElement) => {
  const textContent = element.text || '';
  if (element.is_reference && textContent) {
    const refRegex = /^(\d+)\s+(.+)$/;
    const match = refRegex.exec(textContent);
    if (match) {
      return (
        <>
          <sup className="reference-number">{match[1]}</sup>{' '}
          {parseAndRenderSuperscripts(match[2])}
        </>
      );
    }
  }
  return parseAndRenderSuperscripts(textContent);
};

const renderFootnoteGroups = (groups: FootnoteGroup[]) => (
  <div
    className="result-footnotes"
    style={{
      marginTop: '1em',
      paddingTop: '0.5em',
      borderTop: '1px solid var(--border-color, #eee)'
    }}
  >
    {groups.map((group, groupIdx) => (
      <div
        key={`ref-group-${groupIdx}`}
        className="result-snippet result-snippet-reference"
        style={{ marginBottom: '0.5em', display: 'flex', flexDirection: 'column', gap: '0.25em' }}
      >
        {group.items.map((element, subIdx) => (
          <div key={`sub-${subIdx}`}>{renderFootnoteText(element)}</div>
        ))}
      </div>
    ))}
  </div>
);

export const SearchResultElements = ({
  result,
  orderedElements,
  query,
  onResultClick
}: SearchResultElementsProps) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const { contentItems, footnoteGroups } = groupFootnotes(orderedElements);
  const indentContext: { lastType: 'none' | 'number' | 'bullet' | 'letter'; level: number } = {
    lastType: 'none',
    level: 0
  };

  // If no query, show full summary with markdown
  const hasNoQuery = !query || query.trim() === '' || query === 'No query';
  if (hasNoQuery) {
    const summary = result.sys_full_summary || result.metadata?.sys_full_summary || result.text;
    if (summary) {
      // Smart truncation: show first heading + first paragraph, then "Show more" for rest
      const paragraphs = summary.split(/\n\n+/); // Split by double newlines (paragraphs)
      const shouldTruncate = paragraphs.length > 2;

      // Show first 2 paragraphs (usually heading + first paragraph)
      const displaySummary = isExpanded || !shouldTruncate
        ? summary
        : paragraphs.slice(0, 2).join('\n\n');

      return (
        <div className="result-snippet result-full-summary">
          <em className="result-summary-ai-badge">AI-generated (Experimental)</em>
          <ReactMarkdown>{displaySummary}</ReactMarkdown>
          {shouldTruncate && (
            <button
              className="show-more-button"
              onClick={(e) => {
                e.stopPropagation();
                setIsExpanded(!isExpanded);
              }}
              style={{
                marginTop: '0.5rem',
                padding: '0.25rem 0.75rem',
                fontSize: '0.85rem',
                color: 'var(--brand-primary)',
                background: 'transparent',
                border: '1px solid var(--brand-primary)',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              {isExpanded ? 'Show less' : 'Show more'}
            </button>
          )}
        </div>
      );
    }
  }

  return (
    <>
      {contentItems.map((element, idx) => {
        const elType = element.element_type;
        const itemKey = element.key || `content-${idx}`;

        if (result.translated_snippet && elType !== 'image' && elType !== 'table') {
          return null;
        }

        if (elType === 'text' || element.label === 'text') {
          return (
            <div key={itemKey}>
              {renderTextElement(element, result, query, indentContext)}
            </div>
          );
        }

        if (elType === 'image') {
          return (
            <div key={itemKey}>
              {renderImageElement(element, onResultClick, result)}
            </div>
          );
        }

        if (elType === 'table') {
          return (
            <div key={itemKey}>
              {renderTableElement(element, onResultClick, result)}
            </div>
          );
        }

        return null;
      })}

      {footnoteGroups.length > 0 && !result.translated_snippet
        ? renderFootnoteGroups(footnoteGroups)
        : null}
    </>
  );
};
